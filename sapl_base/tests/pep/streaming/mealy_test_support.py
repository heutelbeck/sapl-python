"""Shared fixtures and translation helpers for the Mealy machine test suites.

Used by:
  * test_mealy_cell.py        -- content checks of one row of delta
  * test_mealy_invariant.py   -- Lean theorems witnessed at the test layer

Alphabet factoring (paper Section 6 footnote / `notes/`):
The canonical `mealy-table.csv` is written against the Java/TypeScript
alphabet:
  * One `RapItem` event with an outcome discriminator
    {Present, Absent, Failed}.
  * Transport-layer events `PdpError` and `RapError` as first-class
    FSM inputs.

Python's alphabet factors this differently:
  * Three separate event types  RapItem(value), RapEpsilon,
    RapObligationFailure  for the three outcomes.
  * No transport-error events; errors are handled at the
    async-iterator boundary outside the FSM.

The `eventByName` translator below applies the bijection at row-load
time. Rows whose event is `PdpError` or `RapError` are out of Python's
delta and the cell loader filters them out.
"""

from __future__ import annotations

from typing import Any

from sapl_base.pep import EnforcementPlan
from sapl_base.pep.streaming.mealy import (
    CANCEL,
    PENDING,
    RAP_COMPLETE,
    RAP_EPSILON,
    RAP_OBLIGATION_FAILURE,
    SUSPENDED,
    TERMINATED,
    Emission,
    Emit,
    EmitComplete,
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
)
from sapl_base.types import AuthorizationDecision, Decision

EMIT_VALUE = "EMIT_VALUE"
EMIT_ERROR = "EMIT_ERROR"
EMIT_COMPLETE = "EMIT_COMPLETE"
EMIT_TRANSITION_GRANTED = "EMIT_TRANSITION_GRANTED"
EMIT_TRANSITION_SUSPENDED = "EMIT_TRANSITION_SUSPENDED"

PERMIT_DECISION = AuthorizationDecision(decision=Decision.PERMIT)
SUSPEND_DECISION = AuthorizationDecision(decision=Decision.SUSPEND)
DENY_DECISION = AuthorizationDecision(decision=Decision.DENY)


def plan() -> EnforcementPlan:
    return EnforcementPlan({})


def permitting() -> PermittingState:
    return PermittingState(plan=plan())


def pdp_permit() -> PdpPermit:
    return PdpPermit(decision=PERMIT_DECISION, plan=plan())


def pdp_suspend() -> PdpSuspend:
    return PdpSuspend(decision=SUSPEND_DECISION)


def pdp_deny() -> PdpDeny:
    return PdpDeny(decision=DENY_DECISION, reason="POLICY_DENIED")


def rap_item(value: Any = "payload") -> RapItem:
    return RapItem(value=value)


# Event-type-level events that are not in Python's delta. Used by the
# cell-test loader to skip rows whose event column is one of these.
EVENTS_NOT_IN_PYTHON_ALPHABET = frozenset({"PdpError", "RapError"})


def state_by_name(name: str) -> State:
    """Translate a CSV state name to the corresponding Python State value."""
    if name == "Pending":
        return PENDING
    if name == "Permitting":
        return permitting()
    if name == "Suspended":
        return SUSPENDED
    if name == "Terminated":
        return TERMINATED
    raise ValueError(f"Unknown state: {name}")


def event_by_name(name: str, outcome: str) -> Event:
    """Translate a CSV (event, outcome) pair to a Python Event.

    Applies the alphabet bijection for `RapItem`:
      * Present -> RapItem(value)
      * Absent  -> RapEpsilon
      * Failed  -> RapObligationFailure
    """
    if name == "PdpPermit":
        return pdp_permit()
    if name == "PdpSuspend":
        return pdp_suspend()
    if name == "PdpDeny":
        return pdp_deny()
    if name == "RapComplete":
        return RAP_COMPLETE
    if name == "Cancel":
        return CANCEL
    if name == "RapItem":
        return _rap_item_by_outcome(outcome)
    raise ValueError(f"Unknown event for Python alphabet: {name}")


def emission_kind(emission: Emission) -> str:
    """Map an Emission instance to a CSV-symbolic kind string."""
    if isinstance(emission, Emit):
        return EMIT_VALUE
    if isinstance(emission, EmitError):
        return EMIT_ERROR
    if isinstance(emission, EmitComplete):
        return EMIT_COMPLETE
    if isinstance(emission, EmitTransition):
        if isinstance(emission.reason, GrantedReason):
            return EMIT_TRANSITION_GRANTED
        if isinstance(emission.reason, SuspendedReason):
            return EMIT_TRANSITION_SUSPENDED
    raise ValueError(f"Unrecognised emission: {emission!r}")


# Subset providers consumed via @pytest.mark.parametrize.

NON_TERMINATED_STATES: list[tuple[str, State]] = [
    ("Pending", PENDING),
    ("Permitting", permitting()),
    ("Suspended", SUSPENDED),
]

# Python's lifecycle terminator set. Java/TS additionally include
# `RapError` and `PdpError`; Python handles those outside the FSM, so
# this set is smaller.
LIFECYCLE_TERMINATORS: list[tuple[str, Event]] = [
    ("Cancel", CANCEL),
    ("RapComplete", RAP_COMPLETE),
]

# All Python events. Used to witness the absorbing-Terminated invariant.
ALL_EVENTS: list[tuple[str, Event]] = [
    ("PdpPermit", pdp_permit()),
    ("PdpSuspend", pdp_suspend()),
    ("PdpDeny", pdp_deny()),
    ("RapItem", rap_item()),
    ("RapEpsilon", RAP_EPSILON),
    ("RapObligationFailure", RAP_OBLIGATION_FAILURE),
    ("RapComplete", RAP_COMPLETE),
    ("Cancel", CANCEL),
]

# The three events that correspond to Java/TS's RapItem outcomes under
# the bijection. Used to witness `no_emit_in_*` invariants.
RAP_ITEM_ALL_OUTCOMES: list[tuple[str, Event]] = [
    ("Present", rap_item()),
    ("Absent", RAP_EPSILON),
    ("Failed", RAP_OBLIGATION_FAILURE),
]


def _rap_item_by_outcome(outcome: str) -> Event:
    if outcome == "Present":
        return rap_item()
    if outcome == "Absent":
        return RAP_EPSILON
    if outcome == "Failed":
        return RAP_OBLIGATION_FAILURE
    raise ValueError(f"Unknown RapItem outcome: {outcome}")
