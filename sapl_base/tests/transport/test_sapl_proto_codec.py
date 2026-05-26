from __future__ import annotations

import pytest

from sapl_base.transport.codec.sapl_proto_codec import (
    decode_decision,
    decode_identifiable_decision,
    decode_multi_decision,
    encode_multi_subscription,
    encode_subscription,
)
from sapl_base.transport.codec import sapl_types_pb2 as types
from sapl_base.types import (
    RESOURCE_ABSENT,
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationSubscription,
)


class TestEncodeSubscription:
    def test_roundtrip_simple_string_fields(self) -> None:
        original = AuthorizationSubscription(
            subject="alice", action="read", resource="doc-1"
        )
        wire = encode_subscription(original)
        message = types.AuthorizationSubscription()
        message.ParseFromString(wire)
        assert message.subject.text_value == "alice"
        assert message.action.text_value == "read"
        assert message.resource.text_value == "doc-1"

    def test_encodes_nested_dict_as_object_value(self) -> None:
        subscription = AuthorizationSubscription(
            subject={"id": "alice", "roles": ["admin", "auditor"]}
        )
        wire = encode_subscription(subscription)
        message = types.AuthorizationSubscription()
        message.ParseFromString(wire)
        fields = message.subject.object_value.fields
        assert fields["id"].text_value == "alice"
        assert [e.text_value for e in fields["roles"].array_value.elements] == [
            "admin",
            "auditor",
        ]

    def test_encodes_bool_as_bool_value_not_number(self) -> None:
        subscription = AuthorizationSubscription(action=True)
        wire = encode_subscription(subscription)
        message = types.AuthorizationSubscription()
        message.ParseFromString(wire)
        assert message.action.WhichOneof("kind") == "bool_value"
        assert message.action.bool_value is True

    def test_omits_none_action_field(self) -> None:
        subscription = AuthorizationSubscription(subject="alice")
        wire = encode_subscription(subscription)
        message = types.AuthorizationSubscription()
        message.ParseFromString(wire)
        assert not message.HasField("action")


class TestDecodeDecision:
    def test_decodes_each_decision_verb(self) -> None:
        for verb_enum, expected in [
            (types.Decision.PERMIT, Decision.PERMIT),
            (types.Decision.DENY, Decision.DENY),
            (types.Decision.INDETERMINATE, Decision.INDETERMINATE),
            (types.Decision.NOT_APPLICABLE, Decision.NOT_APPLICABLE),
            (types.Decision.SUSPEND, Decision.SUSPEND),
        ]:
            message = types.AuthorizationDecision()
            message.decision = verb_enum
            decision = decode_decision(message.SerializeToString())
            assert decision.decision == expected

    def test_decodes_obligations_array(self) -> None:
        message = types.AuthorizationDecision()
        message.decision = types.Decision.PERMIT
        first = message.obligations.elements.add()
        first.object_value.fields["type"].text_value = "log"
        decision = decode_decision(message.SerializeToString())
        assert decision.obligations == ({"type": "log"},)

    def test_resource_absent_when_field_unset(self) -> None:
        message = types.AuthorizationDecision()
        message.decision = types.Decision.PERMIT
        decision = decode_decision(message.SerializeToString())
        assert decision.resource is RESOURCE_ABSENT

    def test_resource_present_when_field_set(self) -> None:
        message = types.AuthorizationDecision()
        message.decision = types.Decision.PERMIT
        message.resource.text_value = "redacted"
        decision = decode_decision(message.SerializeToString())
        assert decision.resource == "redacted"

    def test_garbage_bytes_return_indeterminate(self) -> None:
        decision = decode_decision(b"not-protobuf-bytes")
        assert decision.decision == Decision.INDETERMINATE


class TestMulti:
    def test_encode_multi_uses_flat_id_to_subscription(self) -> None:
        subscription = MultiAuthorizationSubscription(
            subscriptions={
                "a": AuthorizationSubscription(action="read"),
                "b": AuthorizationSubscription(action="write"),
            }
        )
        wire = encode_multi_subscription(subscription)
        message = types.MultiAuthorizationSubscription()
        message.ParseFromString(wire)
        by_id = {entry.subscription_id: entry for entry in message.subscriptions}
        assert by_id["a"].subscription.action.text_value == "read"
        assert by_id["b"].subscription.action.text_value == "write"

    def test_decode_multi_returns_id_to_decision_map(self) -> None:
        message = types.MultiAuthorizationDecision()
        message.decisions["a"].decision = types.Decision.PERMIT
        message.decisions["b"].decision = types.Decision.DENY
        result = decode_multi_decision(message.SerializeToString())
        assert result.decisions["a"].decision == Decision.PERMIT
        assert result.decisions["b"].decision == Decision.DENY

    def test_decode_identifiable_returns_none_when_id_missing(self) -> None:
        message = types.IdentifiableAuthorizationDecision()
        message.decision.decision = types.Decision.PERMIT
        result = decode_identifiable_decision(message.SerializeToString())
        assert result is None

    def test_decode_identifiable_returns_decision_when_id_present(self) -> None:
        message = types.IdentifiableAuthorizationDecision()
        message.subscription_id = "sub-1"
        message.decision.decision = types.Decision.PERMIT
        result = decode_identifiable_decision(message.SerializeToString())
        assert result is not None
        assert result.subscription_id == "sub-1"
        assert result.decision.decision == Decision.PERMIT


class TestValueCoercion:
    @pytest.mark.parametrize(
        "py_value, accessor",
        [
            (None, "null_value"),
            (True, "bool_value"),
            (42, "number_value"),
            (1.5, "number_value"),
            ("hello", "text_value"),
            ([1, 2, 3], "array_value"),
            ({"k": "v"}, "object_value"),
        ],
    )
    def test_python_value_maps_to_expected_proto_kind(
        self, py_value: object, accessor: str
    ) -> None:
        subscription = AuthorizationSubscription(subject=py_value)
        wire = encode_subscription(subscription)
        message = types.AuthorizationSubscription()
        message.ParseFromString(wire)
        assert message.subject.WhichOneof("kind") == accessor
