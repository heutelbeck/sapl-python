"""Streaming PEP Mealy machine.

Pure data: states, events, emissions, and a total `step` function.
No I/O. No async. The driver (`pipeline.py`) feeds events in and
renders emissions out.

State set:
    Pending             — initial; no decision received yet
    Permitting(plan)    — decisions PERMIT this stream; plan is active
    Suspended           — decisions SUSPEND this stream; items dropped
    Terminated          — absorbing; subscription is over

Event alphabet:
    PdpPermit(decision, plan)       PDP delivered PERMIT
    PdpSuspend(decision)            PDP delivered SUSPEND
    PdpDeny(decision, reason)       PDP delivered DENY / INDETERMINATE
                                    / NOT_APPLICABLE, or decision-scoped
                                    enforcement failed on PERMIT
    RapItem(value)                  RAP emitted a successfully enforced item
    RapEpsilon                      RAP item was dropped by a filter mapper
    RapObligationFailure            per-item obligation discharge failed
    RapComplete                     RAP stream ended normally
    Cancel                          subscriber unsubscribed

Emission alphabet:
    Emit(value)                     deliver value to subscriber
    EmitError(error)                terminal error (raises on subscriber)
    EmitTransition(reason)          non-terminal boundary signal
    EmitComplete                    normal completion

Invariants (paper §6):
    1. Totality and determinism: every (state, event) maps to one
       (new_state, emissions) pair.
    2. Absorbing termination: every event from Terminated self-loops
       with no emissions.
    3. Universal denial: PdpDeny drives any non-terminal state to
       Terminated, emitting EmitError(AccessDeniedError).
    4. Confidentiality: RapItem in Pending or Suspended emits
       nothing; values reach the subscriber only from Permitting.
    5. Universal discharge-failure termination: RapObligationFailure
       drives any non-terminal state to Terminated.
    6. Lifecycle terminator uniformity: RapComplete and Cancel
       drive any non-terminal state to Terminated, emitting
       EmitComplete and nothing respectively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sapl_base.pep.boundary_signals import AccessDeniedError

if TYPE_CHECKING:
    from sapl_base.pep.plan import EnforcementPlan
    from sapl_base.types import AuthorizationDecision


class _Singleton:
    _INSTANCE: Any | None = None

    def __new__(cls) -> Any:
        if cls._INSTANCE is None:
            cls._INSTANCE = super().__new__(cls)
        return cls._INSTANCE


class PendingState(_Singleton):
    __slots__ = ()

    def __repr__(self) -> str:
        return "Pending"


class SuspendedState(_Singleton):
    __slots__ = ()

    def __repr__(self) -> str:
        return "Suspended"


class TerminatedState(_Singleton):
    __slots__ = ()

    def __repr__(self) -> str:
        return "Terminated"


@dataclass(frozen=True, slots=True)
class PermittingState:
    plan: EnforcementPlan


State = PendingState | PermittingState | SuspendedState | TerminatedState


PENDING: PendingState = PendingState()
SUSPENDED: SuspendedState = SuspendedState()
TERMINATED: TerminatedState = TerminatedState()


@dataclass(frozen=True, slots=True)
class PdpPermit:
    decision: AuthorizationDecision
    plan: EnforcementPlan


@dataclass(frozen=True, slots=True)
class PdpSuspend:
    decision: AuthorizationDecision


@dataclass(frozen=True, slots=True)
class PdpDeny:
    decision: AuthorizationDecision
    reason: str = "DENIED"


@dataclass(frozen=True, slots=True)
class RapItem:
    value: Any


class RapEpsilon(_Singleton):
    __slots__ = ()

    def __repr__(self) -> str:
        return "RapEpsilon"


class RapObligationFailure(_Singleton):
    __slots__ = ()

    def __repr__(self) -> str:
        return "RapObligationFailure"


class RapComplete(_Singleton):
    __slots__ = ()

    def __repr__(self) -> str:
        return "RapComplete"


class Cancel(_Singleton):
    __slots__ = ()

    def __repr__(self) -> str:
        return "Cancel"


RAP_EPSILON: RapEpsilon = RapEpsilon()
RAP_OBLIGATION_FAILURE: RapObligationFailure = RapObligationFailure()
RAP_COMPLETE: RapComplete = RapComplete()
CANCEL: Cancel = Cancel()


Event = (
    PdpPermit
    | PdpSuspend
    | PdpDeny
    | RapItem
    | RapEpsilon
    | RapObligationFailure
    | RapComplete
    | Cancel
)


@dataclass(frozen=True, slots=True)
class GrantedReason:
    decision: AuthorizationDecision


@dataclass(frozen=True, slots=True)
class SuspendedReason:
    decision: AuthorizationDecision


TransitionReason = GrantedReason | SuspendedReason


@dataclass(frozen=True, slots=True)
class Emit:
    value: Any


@dataclass(frozen=True, slots=True)
class EmitError:
    error: BaseException


@dataclass(frozen=True, slots=True)
class EmitTransition:
    reason: TransitionReason


class EmitComplete(_Singleton):
    __slots__ = ()

    def __repr__(self) -> str:
        return "EmitComplete"


EMIT_COMPLETE: EmitComplete = EmitComplete()


Emission = Emit | EmitError | EmitTransition | EmitComplete


@dataclass(frozen=True, slots=True)
class Step:
    state: State
    emissions: tuple[Emission, ...]


def step(state: State, event: Event) -> Step:
    """Total transition function delta : S x Sigma -> S x Emissions.

    Implements the table in paper §6 verbatim. The Terminated state
    is absorbing: every event self-loops with no emissions.
    """
    if isinstance(state, TerminatedState):
        return Step(state=TERMINATED, emissions=())

    if isinstance(event, PdpPermit):
        return _on_pdp_permit(state, event)
    if isinstance(event, PdpSuspend):
        return _on_pdp_suspend(state, event)
    if isinstance(event, PdpDeny):
        return _on_pdp_deny(event)
    if isinstance(event, RapItem):
        return _on_rap_item(state, event)
    if isinstance(event, RapEpsilon):
        return Step(state=state, emissions=())
    if isinstance(event, RapObligationFailure):
        return _on_rap_obligation_failure()
    if isinstance(event, RapComplete):
        return Step(state=TERMINATED, emissions=(EMIT_COMPLETE,))
    if isinstance(event, Cancel):
        return Step(state=TERMINATED, emissions=())
    raise AssertionError(f"Unexpected event: {event!r}")


def _on_pdp_permit(state: State, event: PdpPermit) -> Step:
    if isinstance(state, PermittingState):
        return Step(state=PermittingState(plan=event.plan), emissions=())
    return Step(
        state=PermittingState(plan=event.plan),
        emissions=(EmitTransition(reason=GrantedReason(decision=event.decision)),),
    )


def _on_pdp_suspend(state: State, event: PdpSuspend) -> Step:
    if isinstance(state, SuspendedState):
        return Step(state=SUSPENDED, emissions=())
    return Step(
        state=SUSPENDED,
        emissions=(EmitTransition(reason=SuspendedReason(decision=event.decision)),),
    )


def _on_pdp_deny(event: PdpDeny) -> Step:
    error = AccessDeniedError(
        "Access denied",
        decision=event.decision,
        reason=event.reason,
    )
    return Step(state=TERMINATED, emissions=(EmitError(error=error),))


def _on_rap_item(state: State, event: RapItem) -> Step:
    if isinstance(state, PermittingState):
        return Step(state=state, emissions=(Emit(value=event.value),))
    return Step(state=state, emissions=())


def _on_rap_obligation_failure() -> Step:
    error = AccessDeniedError(
        "Obligation discharge failed",
        reason="OBLIGATION_FAILURE",
    )
    return Step(state=TERMINATED, emissions=(EmitError(error=error),))
