from __future__ import annotations

from typing import Any

import pytest

from sapl_base.pep import EnforcementPlan
from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.streaming.mealy import (
    CANCEL,
    EMIT_COMPLETE,
    PENDING,
    RAP_COMPLETE,
    RAP_EPSILON,
    RAP_OBLIGATION_FAILURE,
    SUSPENDED,
    TERMINATED,
    Cancel,
    Emit,
    EmitError,
    EmitTransition,
    GrantedReason,
    PdpDeny,
    PdpPermit,
    PdpSuspend,
    PermittingState,
    RapComplete,
    RapItem,
    State,
    SuspendedReason,
    step,
)
from sapl_base.types import AuthorizationDecision, Decision


def _plan() -> EnforcementPlan:
    return EnforcementPlan({})


def _permit_decision() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT)


def _suspend_decision() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.SUSPEND)


def _deny_decision() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.DENY)


class TestTransitionFromPending:
    def test_permit_enters_permitting_and_emits_granted(self) -> None:
        decision = _permit_decision()
        plan = _plan()
        out = step(PENDING, PdpPermit(decision=decision, plan=plan))
        assert isinstance(out.state, PermittingState)
        assert out.state.plan is plan
        assert len(out.emissions) == 1
        assert isinstance(out.emissions[0], EmitTransition)
        assert isinstance(out.emissions[0].reason, GrantedReason)
        assert out.emissions[0].reason.decision is decision

    def test_suspend_enters_suspended_and_emits_suspended(self) -> None:
        out = step(PENDING, PdpSuspend(decision=_suspend_decision()))
        assert out.state is SUSPENDED
        assert len(out.emissions) == 1
        assert isinstance(out.emissions[0].reason, SuspendedReason)

    def test_deny_terminates_with_access_denied_error(self) -> None:
        out = step(PENDING, PdpDeny(decision=_deny_decision(), reason="POLICY_DENIED"))
        assert out.state is TERMINATED
        assert len(out.emissions) == 1
        emission = out.emissions[0]
        assert isinstance(emission, EmitError)
        assert isinstance(emission.error, AccessDeniedError)
        assert emission.error.reason == "POLICY_DENIED"

    def test_rap_item_in_pending_emits_nothing(self) -> None:
        out = step(PENDING, RapItem(value="x"))
        assert out.state is PENDING
        assert out.emissions == ()

    def test_epsilon_in_pending_is_inert(self) -> None:
        out = step(PENDING, RAP_EPSILON)
        assert out.state is PENDING
        assert out.emissions == ()

    def test_obligation_failure_in_pending_terminates(self) -> None:
        out = step(PENDING, RAP_OBLIGATION_FAILURE)
        assert out.state is TERMINATED
        assert isinstance(out.emissions[0], EmitError)
        assert out.emissions[0].error.reason == "OBLIGATION_FAILURE"

    def test_complete_in_pending_terminates_with_complete(self) -> None:
        out = step(PENDING, RAP_COMPLETE)
        assert out.state is TERMINATED
        assert out.emissions == (EMIT_COMPLETE,)

    def test_cancel_in_pending_terminates_silently(self) -> None:
        out = step(PENDING, CANCEL)
        assert out.state is TERMINATED
        assert out.emissions == ()


class TestTransitionFromPermitting:
    def _permitting(self) -> PermittingState:
        return PermittingState(plan=_plan())

    def test_permit_in_permitting_replaces_plan_silently(self) -> None:
        plan_b = _plan()
        out = step(self._permitting(), PdpPermit(decision=_permit_decision(), plan=plan_b))
        assert isinstance(out.state, PermittingState)
        assert out.state.plan is plan_b
        assert out.emissions == ()

    def test_suspend_in_permitting_emits_suspended(self) -> None:
        out = step(self._permitting(), PdpSuspend(decision=_suspend_decision()))
        assert out.state is SUSPENDED
        assert isinstance(out.emissions[0].reason, SuspendedReason)

    def test_deny_in_permitting_terminates(self) -> None:
        out = step(self._permitting(), PdpDeny(decision=_deny_decision()))
        assert out.state is TERMINATED
        assert isinstance(out.emissions[0], EmitError)

    def test_rap_item_in_permitting_forwards_value(self) -> None:
        out = step(self._permitting(), RapItem(value=42))
        assert isinstance(out.state, PermittingState)
        assert out.emissions == (Emit(value=42),)

    def test_obligation_failure_in_permitting_terminates(self) -> None:
        out = step(self._permitting(), RAP_OBLIGATION_FAILURE)
        assert out.state is TERMINATED
        assert out.emissions[0].error.reason == "OBLIGATION_FAILURE"

    def test_complete_in_permitting_terminates_with_complete(self) -> None:
        out = step(self._permitting(), RAP_COMPLETE)
        assert out.state is TERMINATED
        assert out.emissions == (EMIT_COMPLETE,)

    def test_cancel_in_permitting_terminates_silently(self) -> None:
        out = step(self._permitting(), CANCEL)
        assert out.state is TERMINATED
        assert out.emissions == ()


class TestTransitionFromSuspended:
    def test_permit_in_suspended_enters_permitting_and_emits_granted(self) -> None:
        out = step(SUSPENDED, PdpPermit(decision=_permit_decision(), plan=_plan()))
        assert isinstance(out.state, PermittingState)
        assert isinstance(out.emissions[0].reason, GrantedReason)

    def test_suspend_in_suspended_is_idempotent_no_emission(self) -> None:
        out = step(SUSPENDED, PdpSuspend(decision=_suspend_decision()))
        assert out.state is SUSPENDED
        assert out.emissions == ()

    def test_deny_in_suspended_terminates(self) -> None:
        out = step(SUSPENDED, PdpDeny(decision=_deny_decision()))
        assert out.state is TERMINATED
        assert isinstance(out.emissions[0], EmitError)

    def test_rap_item_in_suspended_is_dropped(self) -> None:
        out = step(SUSPENDED, RapItem(value="leak-attempt"))
        assert out.state is SUSPENDED
        assert out.emissions == ()

    def test_obligation_failure_in_suspended_terminates(self) -> None:
        out = step(SUSPENDED, RAP_OBLIGATION_FAILURE)
        assert out.state is TERMINATED

    def test_complete_in_suspended_terminates_with_complete(self) -> None:
        out = step(SUSPENDED, RAP_COMPLETE)
        assert out.state is TERMINATED
        assert out.emissions == (EMIT_COMPLETE,)

    def test_cancel_in_suspended_terminates_silently(self) -> None:
        out = step(SUSPENDED, CANCEL)
        assert out.state is TERMINATED
        assert out.emissions == ()


class TestAbsorbingTermination:
    @pytest.mark.parametrize(
        "event",
        [
            PdpPermit(decision=AuthorizationDecision(decision=Decision.PERMIT), plan=EnforcementPlan({})),
            PdpSuspend(decision=AuthorizationDecision(decision=Decision.SUSPEND)),
            PdpDeny(decision=AuthorizationDecision(decision=Decision.DENY)),
            RapItem(value=1),
            RAP_EPSILON,
            RAP_OBLIGATION_FAILURE,
            RAP_COMPLETE,
            CANCEL,
        ],
    )
    def test_every_event_from_terminated_self_loops_silently(self, event: Any) -> None:
        out = step(TERMINATED, event)
        assert out.state is TERMINATED
        assert out.emissions == ()
