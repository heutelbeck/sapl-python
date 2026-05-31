"""Driver that couples the Mealy FSM to PDP and RAP async iterators.

The pipeline is a single async generator: caller subscribes via
`async for`. Internally:

- A background task drains `pdp_client.decide(...)` and pushes a
  classified `Event` per decision into an `asyncio.Queue`.
- A second background task drains the RAP (the user's protected
  async iterator), pushing `RapItem` per yielded value.
- The driver loop consumes the queue, steps the FSM, renders
  emissions to the subscriber, and manages the RAP task lifecycle
  when `pause_rap_during_suspend` is set.

Strict fail-closed routing of PDP verbs:

- `PERMIT` runs decision-scoped enforcement; on obligation failure
  the decision is reclassified to a deny event.
- `SUSPEND` enters the Suspended state. Items are dropped.
- `DENY`, `INDETERMINATE`, `NOT_APPLICABLE` are all routed to
  `PdpDeny` so the subscription terminates.

This module owns the streaming signal taxonomy: `DECISION`,
`OUTPUT`, `ERROR`, `COMPLETE`, `CANCEL`, `TERMINATION`. The
DECISION / OUTPUT / ERROR signal dataclasses are reused from
`sapl_base.pep.enforce`; the lifecycle-only ones live here.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import structlog

from sapl_base.pep.boundary_signals import (
    AccessGrantedSignal,
    AccessSuspendedSignal,
)
from sapl_base.pep.enforce import (
    DECISION,
    ERROR,
    OUTPUT,
    DecisionSignal,
    OutputSignal,
)
from sapl_base.pep.plan import ABSENT
from sapl_base.pep.planner import EnforcementPlanner
from sapl_base.pep.signal import SignalKind
from sapl_base.pep.streaming.mealy import (
    EMIT_COMPLETE,
    PENDING,
    RAP_COMPLETE,
    RAP_EPSILON,
    RAP_OBLIGATION_FAILURE,
    Emit,
    EmitError,
    EmitTransition,
    Event,
    GrantedReason,
    PdpDeny,
    PdpPermit,
    PdpSuspend,
    PermittingState,
    RapItem,
    State,
    SuspendedReason,
    SuspendedState,
    TerminatedState,
    step,
)
from sapl_base.types import AuthorizationDecision, Decision

logger = structlog.get_logger(__name__)


COMPLETE = SignalKind("complete", data_carrying=False)
CANCEL_SIGNAL = SignalKind("cancel", data_carrying=False)
TERMINATION = SignalKind("termination", data_carrying=False)


STREAM_SUPPORTED: frozenset[SignalKind] = frozenset(
    {DECISION, OUTPUT, ERROR, COMPLETE, CANCEL_SIGNAL, TERMINATION}
)


@dataclass(frozen=True, slots=True)
class CompleteSignal:
    """Lifecycle marker fired when the RAP stream completes normally."""

    kind: SignalKind = COMPLETE


@dataclass(frozen=True, slots=True)
class CancelSignal:
    """Lifecycle marker fired when the subscriber cancels."""

    kind: SignalKind = CANCEL_SIGNAL


@dataclass(frozen=True, slots=True)
class TerminationSignal:
    """Lifecycle marker fired when the subscription terminates for any reason."""

    kind: SignalKind = TERMINATION


@dataclass(frozen=True, slots=True)
class _PdpEnd:
    pass


@dataclass(frozen=True, slots=True)
class _RapEnd:
    pass


@dataclass(frozen=True, slots=True)
class _RapError:
    error: BaseException


_PDP_END = _PdpEnd()
_RAP_END = _RapEnd()


def _classify(
    decision: AuthorizationDecision,
    planner: EnforcementPlanner,
) -> Event:
    """Translate a PDP decision into an FSM event.

    Strict fail-closed: any non-PERMIT, non-SUSPEND verb becomes
    `PdpDeny`. Obligation failure on the `decision` signal during
    PERMIT also produces `PdpDeny`.
    """
    plan = planner.plan(decision, STREAM_SUPPORTED)
    decision_result = plan.execute(DecisionSignal(decision=decision))

    verb = decision.decision
    if verb is Decision.PERMIT:
        if decision_result.failure_state:
            return PdpDeny(decision=decision, reason="OBLIGATION_FAILURE")
        return PdpPermit(decision=decision, plan=plan)
    if verb is Decision.SUSPEND:
        return PdpSuspend(decision=decision)
    return PdpDeny(decision=decision, reason=f"VERB_{verb.value}")


async def run_pipeline(
    *,
    decisions: AsyncIterator[AuthorizationDecision],
    planner: EnforcementPlanner,
    rap_factory: Callable[[], AsyncIterator[Any]],
    signal_transitions: bool = False,
    pause_rap_during_suspend: bool = False,
) -> AsyncIterator[Any]:
    """The driver. Yields rendered values, raises AccessDeniedError on terminal denial."""
    state: State = PENDING
    queue: asyncio.Queue[Any] = asyncio.Queue()

    pdp_task = asyncio.create_task(_pump_pdp(decisions, planner, queue))
    rap_task: asyncio.Task[None] | None = None

    def _ensure_rap_started() -> None:
        nonlocal rap_task
        if rap_task is None or rap_task.done():
            rap_task = asyncio.create_task(_pump_rap(rap_factory(), queue))

    def _stop_rap() -> None:
        nonlocal rap_task
        if rap_task is not None and not rap_task.done():
            rap_task.cancel()
        rap_task = None

    try:
        while True:
            item = await queue.get()

            if isinstance(item, _PdpEnd):
                continue
            if isinstance(item, _RapEnd):
                event: Event = RAP_COMPLETE
            elif isinstance(item, _RapError):
                event = RAP_OBLIGATION_FAILURE
            elif isinstance(item, RapItem):
                event = _enforce_per_item(state, item)
            else:
                event = item

            result = step(state, event)
            prior_state = state
            state = result.state

            for emission in result.emissions:
                if isinstance(emission, Emit):
                    yield emission.value
                elif isinstance(emission, EmitError):
                    raise emission.error
                elif isinstance(emission, EmitTransition):
                    boundary = _render_transition(emission)
                    if signal_transitions and boundary is not None:
                        yield boundary
                elif emission is EMIT_COMPLETE:
                    return

            if isinstance(state, TerminatedState):
                return

            _manage_rap(
                prior_state=prior_state,
                next_state=state,
                ensure=_ensure_rap_started,
                stop=_stop_rap,
                pause_rap_during_suspend=pause_rap_during_suspend,
            )
    finally:
        pdp_task.cancel()
        _stop_rap()


def _enforce_per_item(state: State, item: RapItem) -> Event:
    """Run output-signal enforcement when an item arrives in Permitting.

    Drops (DROP/ABSENT) become RAP_EPSILON. Obligation failure on
    the output signal becomes RAP_OBLIGATION_FAILURE.
    """
    if not isinstance(state, PermittingState):
        return RAP_EPSILON
    plan = state.plan
    output_result = plan.execute(OutputSignal(value=item.value))
    if output_result.failure_state:
        return RAP_OBLIGATION_FAILURE
    if output_result.value is ABSENT:
        return RAP_EPSILON
    return RapItem(value=output_result.value)


def _render_transition(
    emission: EmitTransition,
) -> AccessGrantedSignal | AccessSuspendedSignal | None:
    reason = emission.reason
    if isinstance(reason, GrantedReason):
        return AccessGrantedSignal(decision=reason.decision)
    if isinstance(reason, SuspendedReason):
        return AccessSuspendedSignal(decision=reason.decision)
    return None


def _manage_rap(
    *,
    prior_state: State,
    next_state: State,
    ensure: Callable[[], None],
    stop: Callable[[], None],
    pause_rap_during_suspend: bool,
) -> None:
    if isinstance(next_state, PermittingState):
        ensure()
        return
    if (
        pause_rap_during_suspend
        and isinstance(next_state, SuspendedState)
        and not isinstance(prior_state, SuspendedState)
    ):
        stop()


async def _pump_pdp(
    decisions: AsyncIterator[AuthorizationDecision],
    planner: EnforcementPlanner,
    queue: asyncio.Queue[Any],
) -> None:
    try:
        async for decision in decisions:
            await queue.put(_classify(decision, planner))
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001
        logger.warning("pdp_pump_failed", error=str(error))
        await queue.put(
            PdpDeny(
                decision=AuthorizationDecision(decision=Decision.INDETERMINATE),
                reason="PDP_PUMP_ERROR",
            )
        )
        return
    await queue.put(_PDP_END)


async def _pump_rap(
    rap: AsyncIterator[Any],
    queue: asyncio.Queue[Any],
) -> None:
    try:
        async for value in rap:
            await queue.put(RapItem(value=value))
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001
        logger.warning("rap_pump_failed", error=str(error))
        await queue.put(_RapError(error=error))
        return
    await queue.put(_RAP_END)
