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

import asyncio
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

import structlog

from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.plan import ABSENT
from sapl_base.pep.request_context import reset_current_plan, set_current_plan
from sapl_base.pep.shim_signals import shim_signals
from sapl_base.pep.signal import SignalKind
from sapl_base.pep.transaction import (
    SyncTransactionProvider,
    TransactionProvider,
    transaction_scope,
    transaction_scope_sync,
)
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sapl_base.pep.planner import EnforcementPlanner
    from sapl_base.transport.pdp_client import PdpClient

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

    decision: AuthorizationDecision = field(default_factory=AuthorizationDecision)
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
    transaction: TransactionProvider | None = None,
) -> Any:
    """Authorize, transform inputs, invoke, transform output.

    When ``transaction`` is supplied, the method call and the OUTPUT-obligation
    stage run inside that transaction scope, so an output-obligation failure (a
    post-write denial) rolls the transaction back instead of committing.
    """
    kwargs = dict(kwargs or {})
    decision = await pdp_client.decide_once(subscription)
    plan = planner.plan(decision, PRE_ENFORCE_SUPPORTED | shim_signals())

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

    async with transaction_scope(transaction):
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
                result = output_result.value
    return result


async def post_enforce(
    method: Callable[..., Awaitable[Any]],
    *,
    pdp_client: PdpClient,
    planner: EnforcementPlanner,
    subscription_builder: Callable[[Any], AuthorizationSubscription],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    transaction: TransactionProvider | None = None,
) -> Any:
    """Invoke first, then authorize against a subscription built from the return value.

    When ``transaction`` is supplied, the method call and the post-invocation
    authorization (decision + OUTPUT obligations) run inside that transaction
    scope, so a denial or output-obligation failure after the method has written
    rolls the transaction back instead of committing.
    """
    kwargs = dict(kwargs or {})
    async with transaction_scope(transaction):
        result = await method(*args, **kwargs)

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
                result = output_result.value
    return result


def pre_enforce_blocking(
    method: Callable[..., Any],
    *,
    pdp_client: PdpClient,
    planner: EnforcementPlanner,
    subscription: AuthorizationSubscription,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    transaction: SyncTransactionProvider | None = None,
) -> Any:
    """Blocking counterpart of `pre_enforce`.

    Runs the method synchronously, off any event loop, so synchronous ORM access
    (and its query-manipulation cut point) works. Only the PDP decision is bridged:
    an async client is driven to completion before the method runs, so the method
    executes with no running event loop. Plan execution and obligation handling are
    already synchronous.
    """
    kwargs = dict(kwargs or {})
    decision = _decide_blocking(pdp_client, subscription)
    plan = planner.plan(decision, PRE_ENFORCE_SUPPORTED | shim_signals())

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

    with transaction_scope_sync(transaction):
        token = set_current_plan(plan)
        try:
            result = method(*args, **kwargs)
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
                result = output_result.value
    return result


def post_enforce_blocking(
    method: Callable[..., Any],
    *,
    pdp_client: PdpClient,
    planner: EnforcementPlanner,
    subscription_builder: Callable[[Any], AuthorizationSubscription],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    transaction: SyncTransactionProvider | None = None,
) -> Any:
    """Blocking counterpart of `post_enforce`. Runs the method synchronously, then
    authorizes against a subscription built from its return value."""
    kwargs = dict(kwargs or {})
    with transaction_scope_sync(transaction):
        result = method(*args, **kwargs)

        subscription = subscription_builder(result)
        decision = _decide_blocking(pdp_client, subscription)
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
                result = output_result.value
    return result


def _decide_blocking(
    pdp_client: PdpClient, subscription: AuthorizationSubscription
) -> AuthorizationDecision:
    """Obtain a decision synchronously. An async `decide_once` is run to completion;
    a synchronous client's return value passes through unchanged."""
    outcome = pdp_client.decide_once(subscription)
    if isawaitable(outcome):
        return asyncio.run(outcome)
    return outcome


def _reason_for(decision: AuthorizationDecision, failure: bool) -> str:
    if failure:
        return "OBLIGATION_FAILURE"
    return f"VERB_{decision.decision.value}"
