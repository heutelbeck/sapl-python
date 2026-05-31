"""One-shot enforcement helpers: `pre_enforce` and `post_enforce`.

Both functions take a method, the PDP client, the planner, the
subscription, and the method's args / kwargs. They run the
required signal sequence around the method invocation and return
the post-enforcement result. Strict fail-closed: decision-scoped
or output-scoped obligation failure raises `AccessDeniedError`.

Framework wrappers compose these into decorators that handle the
framework-specific request extraction and response wrapping.

This module owns the one-shot signal taxonomy: `DECISION`,
`INPUT`, `OUTPUT`, `ERROR`, and the corresponding signal
dataclasses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.plan import ABSENT
from sapl_base.pep.planner import EnforcementPlanner
from sapl_base.pep.request_context import reset_current_plan, set_current_plan
from sapl_base.pep.signal import SignalKind
from sapl_base.transport.pdp_client import PdpClient
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision

logger = structlog.get_logger(__name__)


DECISION = SignalKind("decision", data_carrying=False)
INPUT = SignalKind("input", data_carrying=True)
OUTPUT = SignalKind("output", data_carrying=True)
ERROR = SignalKind("error", data_carrying=True)


PRE_ENFORCE_SUPPORTED: frozenset[SignalKind] = frozenset(
    {DECISION, INPUT, OUTPUT, ERROR}
)
POST_ENFORCE_SUPPORTED: frozenset[SignalKind] = frozenset({DECISION, OUTPUT, ERROR})


@dataclass(frozen=True, slots=True)
class DecisionSignal:
    """Fires once per PDP decision. Self-contained; carries the decision."""

    decision: AuthorizationDecision = AuthorizationDecision()
    kind: SignalKind = DECISION


@dataclass(frozen=True, slots=True)
class InputSignal:
    """Fires before method invocation; carries the call arguments."""

    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    kind: SignalKind = INPUT


@dataclass(frozen=True, slots=True)
class OutputSignal:
    """Fires on method return (or per item in streaming) with the value."""

    value: Any
    kind: SignalKind = OUTPUT


@dataclass(frozen=True, slots=True)
class ErrorSignal:
    """Fires when the protected method raises; carries the exception."""

    error: BaseException
    kind: SignalKind = ERROR


async def pre_enforce(
    method: Callable[..., Awaitable[Any]],
    *,
    pdp_client: PdpClient,
    planner: EnforcementPlanner,
    subscription: AuthorizationSubscription,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Authorize, transform inputs, invoke, transform output."""
    kwargs = dict(kwargs or {})
    decision = await pdp_client.decide_once(subscription)
    plan = planner.plan(decision, PRE_ENFORCE_SUPPORTED)

    decision_result = plan.execute(DecisionSignal(decision=decision))
    if decision_result.failure_state or decision.decision is not Decision.PERMIT:
        raise AccessDeniedError(
            "Access denied",
            decision=decision,
            reason=_reason_for(decision, decision_result.failure_state),
        )

    if plan.has_entries(INPUT):
        input_result = plan.execute(InputSignal(args=args, kwargs=kwargs))
        if input_result.failure_state:
            raise AccessDeniedError(
                "Access denied", decision=decision, reason="INPUT_FAILURE"
            )
        transformed = input_result.value
        if transformed is not ABSENT and isinstance(transformed, tuple) and len(transformed) == 2:
            args, kwargs = transformed[0], transformed[1]

    token = set_current_plan(plan)
    try:
        result = await method(*args, **kwargs)
    except Exception as error:
        if plan.has_entries(ERROR):
            plan.execute(ErrorSignal(error=error))
        raise
    finally:
        reset_current_plan(token)

    if decision.has_resource:
        result = decision.resource

    if plan.has_entries(OUTPUT):
        output_result = plan.execute(OutputSignal(value=result))
        if output_result.failure_state:
            raise AccessDeniedError(
                "Access denied", decision=decision, reason="OUTPUT_FAILURE"
            )
        if output_result.value is not ABSENT:
            return output_result.value
    return result


async def post_enforce(
    method: Callable[..., Awaitable[Any]],
    *,
    pdp_client: PdpClient,
    planner: EnforcementPlanner,
    subscription_builder: Callable[[Any], AuthorizationSubscription],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Invoke first, then authorize against a subscription built from the return value."""
    kwargs = dict(kwargs or {})
    try:
        result = await method(*args, **kwargs)
    except Exception:
        raise

    subscription = subscription_builder(result)
    decision = await pdp_client.decide_once(subscription)
    plan = planner.plan(decision, POST_ENFORCE_SUPPORTED)

    decision_result = plan.execute(DecisionSignal(decision=decision))
    if decision_result.failure_state or decision.decision is not Decision.PERMIT:
        raise AccessDeniedError(
            "Access denied",
            decision=decision,
            reason=_reason_for(decision, decision_result.failure_state),
        )

    if decision.has_resource:
        result = decision.resource

    if plan.has_entries(OUTPUT):
        output_result = plan.execute(OutputSignal(value=result))
        if output_result.failure_state:
            raise AccessDeniedError(
                "Access denied", decision=decision, reason="OUTPUT_FAILURE"
            )
        if output_result.value is not ABSENT:
            return output_result.value
    return result


def _reason_for(decision: AuthorizationDecision, failure: bool) -> str:
    if failure:
        return "OBLIGATION_FAILURE"
    return f"VERB_{decision.decision.value}"
