from __future__ import annotations

import pytest

from sapl_base.pep import AccessDeniedError, AccessGrantedSignal, AccessSuspendedSignal
from sapl_base.types import AuthorizationDecision, Decision


def test_access_denied_error_is_an_exception() -> None:
    with pytest.raises(AccessDeniedError, match="Access denied"):
        raise AccessDeniedError()


def test_access_denied_error_carries_decision_and_reason() -> None:
    decision = AuthorizationDecision(decision=Decision.DENY)
    error = AccessDeniedError(
        "policy denial", decision=decision, reason="POLICY_DENIED"
    )
    assert error.decision is decision
    assert error.reason == "POLICY_DENIED"


def test_access_suspended_signal_is_non_terminal_sentinel() -> None:
    """A plain value yieldable on an async iterator."""
    decision = AuthorizationDecision(decision=Decision.SUSPEND)
    signal = AccessSuspendedSignal(decision=decision)
    assert isinstance(signal, AccessSuspendedSignal)
    assert not isinstance(signal, Exception)
    assert signal.decision is decision


def test_access_granted_signal_is_non_terminal_sentinel() -> None:
    decision = AuthorizationDecision(decision=Decision.PERMIT)
    signal = AccessGrantedSignal(decision=decision)
    assert isinstance(signal, AccessGrantedSignal)
    assert not isinstance(signal, Exception)
    assert signal.decision is decision


def test_signals_distinguishable_via_isinstance() -> None:
    """Subscribers must be able to tell the boundary types apart."""
    permit = AuthorizationDecision(decision=Decision.PERMIT)
    suspend = AuthorizationDecision(decision=Decision.SUSPEND)
    granted = AccessGrantedSignal(decision=permit)
    suspended = AccessSuspendedSignal(decision=suspend)
    assert not isinstance(granted, AccessSuspendedSignal)
    assert not isinstance(suspended, AccessGrantedSignal)
