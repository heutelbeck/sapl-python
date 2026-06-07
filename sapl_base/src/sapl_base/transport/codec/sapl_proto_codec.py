"""Encode / decode wrappers over the generated protobuf classes.

`encode_*` accepts a typed dataclass and returns wire bytes.
`decode_*` accepts wire bytes and returns a typed dataclass.

The decoders are total: on malformed wire bytes they return
`INDETERMINATE` for `AuthorizationDecision`, `None` for the
identifiable variant, or an empty `MultiAuthorizationDecision`.

Number values are encoded as the SAPL `Value` `number_value` string
field (BigDecimal-compatible). On decode, integer-looking strings
are returned as `int`; anything else as `float`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from google.protobuf.message import DecodeError

from sapl_base.transport.codec import sapl_types_pb2 as types
from sapl_base.types import (
    RESOURCE_ABSENT,
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
)

if TYPE_CHECKING:
    from google.protobuf import message as _proto_message

_DECISION_FROM_PROTO = {
    types.Decision.INDETERMINATE: Decision.INDETERMINATE,
    types.Decision.PERMIT: Decision.PERMIT,
    types.Decision.DENY: Decision.DENY,
    types.Decision.NOT_APPLICABLE: Decision.NOT_APPLICABLE,
    types.Decision.SUSPEND: Decision.SUSPEND,
}



def encode_subscription(subscription: AuthorizationSubscription) -> bytes:
    """Serialize an `AuthorizationSubscription` to protobuf wire bytes."""
    message = types.AuthorizationSubscription()
    _set_optional_value(message, "subject", subscription.subject)
    _set_optional_value(message, "action", subscription.action)
    _set_optional_value(message, "resource", subscription.resource)
    _set_optional_value(message, "environment", subscription.environment)
    _set_optional_value(message, "secrets", subscription.secrets)
    return message.SerializeToString()


def encode_multi_subscription(
    subscription: MultiAuthorizationSubscription,
) -> bytes:
    """Serialize a multi-subscription bundle to protobuf wire bytes."""
    message = types.MultiAuthorizationSubscription()
    for subscription_id, single in subscription.subscriptions.items():
        entry = message.subscriptions.add()
        entry.subscription_id = subscription_id
        _set_optional_value(entry.subscription, "subject", single.subject)
        _set_optional_value(entry.subscription, "action", single.action)
        _set_optional_value(entry.subscription, "resource", single.resource)
        _set_optional_value(entry.subscription, "environment", single.environment)
        _set_optional_value(entry.subscription, "secrets", single.secrets)
    return message.SerializeToString()


def decode_decision(buffer: bytes) -> AuthorizationDecision:
    """Parse protobuf wire bytes into an `AuthorizationDecision`.

    Returns `INDETERMINATE` on parse failure (fail-closed).
    """
    message = types.AuthorizationDecision()
    try:
        message.ParseFromString(buffer)
    except DecodeError:
        return AuthorizationDecision.indeterminate()
    return _decision_from_proto(message)


def decode_identifiable_decision(
    buffer: bytes,
) -> IdentifiableAuthorizationDecision | None:
    """Parse a tagged single-subscription decision.

    Returns None on parse failure or when the wire payload carries no
    subscription_id.
    """
    message = types.IdentifiableAuthorizationDecision()
    try:
        message.ParseFromString(buffer)
    except DecodeError:
        return None
    if not message.subscription_id:
        return None
    return IdentifiableAuthorizationDecision(
        subscription_id=message.subscription_id,
        decision=_decision_from_proto(message.decision),
    )


def decode_multi_decision(buffer: bytes) -> MultiAuthorizationDecision:
    """Parse a multi-subscription decision snapshot.

    Returns an empty MultiAuthorizationDecision on parse failure.
    """
    message = types.MultiAuthorizationDecision()
    try:
        message.ParseFromString(buffer)
    except DecodeError:
        return MultiAuthorizationDecision()
    decisions = {
        subscription_id: _decision_from_proto(decision)
        for subscription_id, decision in message.decisions.items()
    }
    return MultiAuthorizationDecision(decisions=decisions)


def _decision_from_proto(message: Any) -> AuthorizationDecision:
    verb = _DECISION_FROM_PROTO.get(message.decision, Decision.INDETERMINATE)
    obligations = tuple(_value_to_python(v) for v in message.obligations.elements)
    advice = tuple(_value_to_python(v) for v in message.advice.elements)
    resource: Any = RESOURCE_ABSENT
    if message.HasField("resource"):
        resource = _value_to_python(message.resource)
    return AuthorizationDecision(
        decision=verb,
        obligations=obligations,
        advice=advice,
        resource=resource,
    )


def _set_optional_value(
    message: _proto_message.Message,
    field: str,
    python_value: Any,
) -> None:
    """Assign a Python value into a `Value` field, leaving it unset when None.

    SAPL semantics: a None subscription field means 'not provided'
    (absent on the wire), distinct from JSON null which we encode as
    `null_value`. Empty containers and explicit None are passed through
    as their respective `Value` kinds.
    """
    if python_value is None and field != "subject":
        return
    _python_to_value(python_value, getattr(message, field))


def _python_to_value(python_value: Any, target: Any) -> None:
    if python_value is None:
        target.null_value.SetInParent()
    elif isinstance(python_value, bool):
        target.bool_value = python_value
    elif isinstance(python_value, int):
        target.number_value = str(python_value)
    elif isinstance(python_value, float):
        target.number_value = repr(python_value)
    elif isinstance(python_value, Decimal):
        target.number_value = str(python_value)
    elif isinstance(python_value, str):
        target.text_value = python_value
    elif isinstance(python_value, (list, tuple)):
        for element in python_value:
            _python_to_value(element, target.array_value.elements.add())
    elif isinstance(python_value, dict):
        for key, value in python_value.items():
            _python_to_value(value, target.object_value.fields[str(key)])
    else:
        target.text_value = str(python_value)


def _value_to_python(value: Any) -> Any:
    kind = value.WhichOneof("kind")
    if kind is None or kind == "null_value":
        return None
    if kind == "bool_value":
        return value.bool_value
    if kind == "number_value":
        text = value.number_value
        if "." in text or "e" in text or "E" in text:
            return float(text)
        try:
            return int(text)
        except ValueError:
            return float(text)
    if kind == "text_value":
        return value.text_value
    if kind == "array_value":
        return [_value_to_python(element) for element in value.array_value.elements]
    if kind == "object_value":
        return {key: _value_to_python(v) for key, v in value.object_value.fields.items()}
    if kind == "undefined_value":
        return None
    if kind == "error_value":
        return {
            "_error_": value.error_value.message,
            "_arguments_": list(value.error_value.arguments),
        }
    return None
