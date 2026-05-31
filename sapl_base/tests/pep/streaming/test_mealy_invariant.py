"""Layer-2 invariants on `step(state, event)`.

Each test is the executable witness of a theorem proved on the formal
model in `stream-pep-lean/StreamPepFsm/Properties.lean`. Test names
mirror the Lean theorem names verbatim (Python snake_case == Lean
snake_case). The block comment carries the Lean statement; the test
body discharges it by computation, by enumeration over a finite
quantification domain, or by replaying a fixed event sequence --
whichever shape Lean uses.

The Lean module groups its theorems by section (per-cell invariants
first, sequence invariants last); the test ordering follows the same
order.

Python alphabet note: the Lean model is written against the Java/TS
alphabet (RapItem with an outcome discriminator; transport-error
events as first-class FSM inputs). Python factors the same routing
into separate event types. Each test below uses the Python event that
corresponds to the Lean event under the bijection documented in
`mealy_test_support`.
"""

from __future__ import annotations

import pytest

from sapl_base.pep.streaming.mealy import (
    PENDING,
    RAP_OBLIGATION_FAILURE,
    SUSPENDED,
    TERMINATED,
    Emit,
    EmitError,
    EmitTransition,
    Event,
    GrantedReason,
    PermittingState,
    State,
    SuspendedReason,
    SuspendedState,
    TerminatedState,
    step,
)

from .mealy_test_support import (
    ALL_EVENTS,
    LIFECYCLE_TERMINATORS,
    NON_TERMINATED_STATES,
    RAP_ITEM_ALL_OUTCOMES,
    pdp_deny,
    pdp_permit,
    pdp_suspend,
    permitting,
)


# Lean theorem: terminated_is_absorbing
#
#   forall (e : Event), step .Terminated e = (.Terminated, [])
@pytest.mark.parametrize(
    ("name", "event"), ALL_EVENTS, ids=[n for n, _ in ALL_EVENTS]
)
def test_terminated_is_absorbing(name: str, event: Event) -> None:
    result = step(TERMINATED, event)
    assert isinstance(result.state, TerminatedState)
    assert result.emissions == ()


# Lean theorem: deny_universally_terminates
#
#   forall (s : State), s != .Terminated ->
#     step s .PdpDeny = (.Terminated, [.EmitError])
@pytest.mark.parametrize(
    ("name", "source"), NON_TERMINATED_STATES, ids=[n for n, _ in NON_TERMINATED_STATES]
)
def test_deny_universally_terminates(name: str, source: State) -> None:
    result = step(source, pdp_deny())
    assert isinstance(result.state, TerminatedState)
    assert len(result.emissions) == 1
    assert isinstance(result.emissions[0], EmitError)


# Lean theorem: permit_universally_reaches_permitting
#
#   forall (s : State), s != .Terminated ->
#     (step s .PdpPermit).newState = .Permitting
@pytest.mark.parametrize(
    ("name", "source"), NON_TERMINATED_STATES, ids=[n for n, _ in NON_TERMINATED_STATES]
)
def test_permit_universally_reaches_permitting(name: str, source: State) -> None:
    result = step(source, pdp_permit())
    assert isinstance(result.state, PermittingState)


# Lean theorem: suspend_universally_reaches_suspended
#
#   forall (s : State), s != .Terminated ->
#     (step s .PdpSuspend).newState = .Suspended
@pytest.mark.parametrize(
    ("name", "source"), NON_TERMINATED_STATES, ids=[n for n, _ in NON_TERMINATED_STATES]
)
def test_suspend_universally_reaches_suspended(name: str, source: State) -> None:
    result = step(source, pdp_suspend())
    assert isinstance(result.state, SuspendedState)


# Lean theorem: lifecycle_terminators_reach_terminated
#
#   forall (s : State) (e : Event),
#     s != .Terminated ->
#     e = .Cancel or e = .RapComplete or e = .RapError or e = .PdpError ->
#     (step s e).newState = .Terminated
#
# Python alphabet: only Cancel and RapComplete are in the lifecycle-
# terminator subset; RapError and PdpError are not Python events
# (handled outside the FSM).
@pytest.mark.parametrize(
    ("source_name", "source"), NON_TERMINATED_STATES, ids=[n for n, _ in NON_TERMINATED_STATES]
)
@pytest.mark.parametrize(
    ("event_name", "event"), LIFECYCLE_TERMINATORS, ids=[n for n, _ in LIFECYCLE_TERMINATORS]
)
def test_lifecycle_terminators_reach_terminated(
    source_name: str, source: State, event_name: str, event: Event
) -> None:
    result = step(source, event)
    assert isinstance(result.state, TerminatedState)


# Lean theorem: no_emit_in_suspended
#
#   forall (o : ItemOutcome),
#     .Emit not-in (step .Suspended (.RapItem o)).emissions
@pytest.mark.parametrize(
    ("outcome", "event"), RAP_ITEM_ALL_OUTCOMES, ids=[n for n, _ in RAP_ITEM_ALL_OUTCOMES]
)
def test_no_emit_in_suspended(outcome: str, event: Event) -> None:
    result = step(SUSPENDED, event)
    assert not any(isinstance(e, Emit) for e in result.emissions)


# Lean theorem: no_emit_in_pending
#
#   forall (o : ItemOutcome),
#     .Emit not-in (step .Pending (.RapItem o)).emissions
@pytest.mark.parametrize(
    ("outcome", "event"), RAP_ITEM_ALL_OUTCOMES, ids=[n for n, _ in RAP_ITEM_ALL_OUTCOMES]
)
def test_no_emit_in_pending(outcome: str, event: Event) -> None:
    result = step(PENDING, event)
    assert not any(isinstance(e, Emit) for e in result.emissions)


# Lean theorem: item_failure_universally_terminates
#
#   forall (s : State), s != .Terminated ->
#     step s (.RapItem .Failed) = (.Terminated, [.EmitError])
#
# Paper Invariant 5: universal fulfillment-failure termination. Python's
# RapObligationFailure event corresponds to RapItem(.Failed) under the
# alphabet bijection.
@pytest.mark.parametrize(
    ("name", "source"), NON_TERMINATED_STATES, ids=[n for n, _ in NON_TERMINATED_STATES]
)
def test_item_failure_universally_terminates(name: str, source: State) -> None:
    result = step(source, RAP_OBLIGATION_FAILURE)
    assert isinstance(result.state, TerminatedState)
    assert len(result.emissions) == 1
    assert isinstance(result.emissions[0], EmitError)


# Lean theorem: replan_is_silent
#
#   (step .Permitting .PdpPermit).emissions = []
def test_replan_is_silent() -> None:
    result = step(permitting(), pdp_permit())
    assert result.emissions == ()


# Lean theorem: re_suspend_is_silent
#
#   (step .Suspended .PdpSuspend).emissions = []
def test_re_suspend_is_silent() -> None:
    result = step(SUSPENDED, pdp_suspend())
    assert result.emissions == ()


# Lean theorem: initial_permit_emits_boundary
#
#   (step .Pending .PdpPermit).emissions = [.EmitTransition]
def test_initial_permit_emits_boundary() -> None:
    result = step(PENDING, pdp_permit())
    assert len(result.emissions) == 1
    emission = result.emissions[0]
    assert isinstance(emission, EmitTransition)
    assert isinstance(emission.reason, GrantedReason)


# Lean theorem: resume_permit_emits_boundary
#
#   (step .Suspended .PdpPermit).emissions = [.EmitTransition]
def test_resume_permit_emits_boundary() -> None:
    result = step(SUSPENDED, pdp_permit())
    assert len(result.emissions) == 1
    emission = result.emissions[0]
    assert isinstance(emission, EmitTransition)
    assert isinstance(emission.reason, GrantedReason)


# Lean theorem: pending_to_suspended_emits_boundary
#
#   (step .Pending .PdpSuspend).emissions = [.EmitTransition]
def test_pending_to_suspended_emits_boundary() -> None:
    result = step(PENDING, pdp_suspend())
    assert len(result.emissions) == 1
    emission = result.emissions[0]
    assert isinstance(emission, EmitTransition)
    assert isinstance(emission.reason, SuspendedReason)


# Lean theorem: permitting_to_suspended_emits_boundary
#
#   (step .Permitting .PdpSuspend).emissions = [.EmitTransition]
def test_permitting_to_suspended_emits_boundary() -> None:
    result = step(permitting(), pdp_suspend())
    assert len(result.emissions) == 1
    emission = result.emissions[0]
    assert isinstance(emission, EmitTransition)
    assert isinstance(emission.reason, SuspendedReason)


# Lean theorem: permit_then_failed_item_terminates
#
#   (replay .Pending [.PdpPermit, .RapItem .Failed]).fst = .Terminated
def test_permit_then_failed_item_terminates() -> None:
    after_permit = step(PENDING, pdp_permit())
    after_item = step(after_permit.state, RAP_OBLIGATION_FAILURE)
    assert isinstance(after_item.state, TerminatedState)
