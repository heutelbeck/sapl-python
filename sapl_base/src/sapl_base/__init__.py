"""SAPL PEP core library for Python.

Two public namespaces:

- `sapl_base.pep`: the PEP layer (planner, plan, signal taxonomy,
  boundary signals, one-shot enforcement, streaming pipeline,
  built-in JSON filter providers).
- `sapl_base.transport`: the connector to the SAPL Node (HTTP and
  RSocket PDP clients, TLS config, OAuth2 token provider).

`sapl_base.types` carries the wire types (Decision enum,
AuthorizationSubscription, AuthorizationDecision, multi variants,
RESOURCE_ABSENT sentinel).

The legacy `sapl_base.pdp_client` and `sapl_base.sse_parser`
modules remain available as transitional entry points until the
framework wrappers migrate to the new transport package.
"""

from __future__ import annotations

from sapl_base.deduplication import deduplicate
from sapl_base.logging_utils import truncate
from sapl_base.pdp_client import PdpClient, PdpConfig
from sapl_base.pep import (
    AccessDeniedError,
    AccessGrantedSignal,
    AccessSuspendedSignal,
    ConstraintHandlerProvider,
    EnforcementPlan,
    EnforcementPlanner,
    ScopedHandler,
    SignalKind,
    SubscriptionContext,
)
from sapl_base.sse_parser import SseBufferOverflowError, parse_sse_stream
from sapl_base.types import (
    RESOURCE_ABSENT,
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
)
from sapl_base.validation import (
    parse_decision_from_json,
    parse_identifiable_decision_from_json,
    parse_multi_decision_from_json,
    validate_decision_response,
    validate_multi_decision_response,
)

__all__ = [
    "AccessDeniedError",
    "AccessGrantedSignal",
    "AccessSuspendedSignal",
    "AuthorizationDecision",
    "AuthorizationSubscription",
    "ConstraintHandlerProvider",
    "Decision",
    "EnforcementPlan",
    "EnforcementPlanner",
    "IdentifiableAuthorizationDecision",
    "MultiAuthorizationDecision",
    "MultiAuthorizationSubscription",
    "PdpClient",
    "PdpConfig",
    "RESOURCE_ABSENT",
    "ScopedHandler",
    "SignalKind",
    "SseBufferOverflowError",
    "SubscriptionContext",
    "deduplicate",
    "parse_decision_from_json",
    "parse_identifiable_decision_from_json",
    "parse_multi_decision_from_json",
    "parse_sse_stream",
    "truncate",
    "validate_decision_response",
    "validate_multi_decision_response",
]
