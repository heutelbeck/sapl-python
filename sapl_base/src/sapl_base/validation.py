from __future__ import annotations

import json
from typing import Any

import structlog

from sapl_base.types import (
    RESOURCE_ABSENT,
    AuthorizationDecision,
    Decision,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
)

logger = structlog.get_logger(__name__)

ERROR_DECISION_NOT_DICT = "Decision response is not a dictionary, returning INDETERMINATE"
ERROR_DECISION_FIELD_MISSING = "Decision response missing 'decision' field, returning INDETERMINATE"
ERROR_DECISION_VALUE_INVALID = "Decision response has invalid 'decision' value, returning INDETERMINATE"
ERROR_JSON_PARSE_FAILED = "Failed to parse JSON from SSE data, returning INDETERMINATE"
ERROR_MULTI_DECISION_NOT_DICT = "Multi-decision response is not a dictionary, returning empty"
ERROR_MULTI_DECISION_PARSE_FAILED = "Failed to parse multi-decision JSON, returning empty"
ERROR_OBLIGATIONS_NOT_LIST = "Obligations field is not a list, defaulting to empty"
ERROR_ADVICE_NOT_LIST = "Advice field is not a list, defaulting to empty"
ERROR_IDENTIFIABLE_MISSING_ID = "Identifiable decision missing 'authorizationSubscriptionId', skipping"
ERROR_IDENTIFIABLE_MISSING_DECISION = "Identifiable decision missing 'authorizationDecision', using INDETERMINATE"

_VALID_DECISIONS = frozenset({d.value for d in Decision})


def validate_decision_response(data: Any) -> AuthorizationDecision:
    """Validate and parse a raw decision response into an AuthorizationDecision.

    REQ-FAILCLOSE-1: Any validation failure results in INDETERMINATE.
    Only recognized fields (decision, obligations, advice, resource) are kept.
    """
    if not isinstance(data, dict):
        logger.error(ERROR_DECISION_NOT_DICT, data_type=type(data).__name__)
        return AuthorizationDecision.indeterminate()

    raw_decision = data.get("decision")
    if raw_decision is None:
        logger.error(ERROR_DECISION_FIELD_MISSING)
        return AuthorizationDecision.indeterminate()

    if not isinstance(raw_decision, str) or raw_decision not in _VALID_DECISIONS:
        logger.error(ERROR_DECISION_VALUE_INVALID, raw_decision=raw_decision)
        return AuthorizationDecision.indeterminate()

    decision = Decision(raw_decision)

    obligations = _validate_collection(data, "obligations", ERROR_OBLIGATIONS_NOT_LIST)
    advice = _validate_collection(data, "advice", ERROR_ADVICE_NOT_LIST)
    resource = _extract_resource(data)

    return AuthorizationDecision(
        decision=decision,
        obligations=obligations,
        advice=advice,
        resource=resource,
    )


def parse_decision_from_json(raw_json: str) -> AuthorizationDecision:
    """Parse a JSON string into a validated AuthorizationDecision."""
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(ERROR_JSON_PARSE_FAILED, error=str(exc))
        return AuthorizationDecision.indeterminate()
    return validate_decision_response(data)


def parse_multi_decision_from_json(raw_json: str) -> MultiAuthorizationDecision:
    """Parse a JSON string into a validated MultiAuthorizationDecision."""
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(ERROR_MULTI_DECISION_PARSE_FAILED, error=str(exc))
        return MultiAuthorizationDecision()

    return validate_multi_decision_response(data)


def validate_multi_decision_response(data: Any) -> MultiAuthorizationDecision:
    """Validate and parse a raw multi-decision response."""
    if not isinstance(data, dict):
        logger.error(ERROR_MULTI_DECISION_NOT_DICT, data_type=type(data).__name__)
        return MultiAuthorizationDecision()

    decisions: dict[str, AuthorizationDecision] = {}
    for subscription_id, raw_decision in data.items():
        decisions[subscription_id] = validate_decision_response(raw_decision)

    return MultiAuthorizationDecision(decisions=decisions)


def parse_identifiable_decision_from_json(raw_json: str) -> IdentifiableAuthorizationDecision | None:
    """Parse a JSON string into a validated IdentifiableAuthorizationDecision.

    Returns None if the subscription ID is missing (cannot be associated).
    """
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(ERROR_JSON_PARSE_FAILED, error=str(exc))
        return None

    if not isinstance(data, dict):
        logger.error(ERROR_DECISION_NOT_DICT, data_type=type(data).__name__)
        return None

    subscription_id = data.get("authorizationSubscriptionId")
    if subscription_id is None:
        logger.error(ERROR_IDENTIFIABLE_MISSING_ID)
        return None

    raw_decision = data.get("authorizationDecision")
    if raw_decision is None:
        logger.warning(ERROR_IDENTIFIABLE_MISSING_DECISION, subscription_id=subscription_id)
        decision = AuthorizationDecision.indeterminate()
    else:
        decision = validate_decision_response(raw_decision)

    return IdentifiableAuthorizationDecision(
        subscription_id=str(subscription_id),
        decision=decision,
    )


def _validate_collection(data: dict[str, Any], key: str, error_message: str) -> tuple[Any, ...]:
    raw = data.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        logger.warning(error_message, raw_type=type(raw).__name__)
        return ()
    return tuple(raw)


def _extract_resource(data: dict[str, Any]) -> Any:
    if "resource" in data:
        return data["resource"]
    return RESOURCE_ABSENT
