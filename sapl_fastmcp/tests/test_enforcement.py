"""Tests for sapl_fastmcp.enforcement module (gate-level enforcement)."""

from unittest.mock import MagicMock

from sapl_base import AuthorizationDecision, Decision
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.constraint_types import Signal
from sapl_fastmcp.enforcement import enforce_decision_gate


def _make_decision(
    decision=Decision.PERMIT,
    obligations=(),
    advice=(),
    has_resource=False,
):
    d = MagicMock(spec=AuthorizationDecision)
    d.decision = decision
    d.obligations = list(obligations)
    d.advice = list(advice)
    d.has_resource = has_resource
    return d


def _make_provider(signal=Signal.ON_DECISION, responsible=True, handler=None):
    provider = MagicMock()
    provider.get_signal.return_value = signal
    provider.is_responsible.return_value = responsible
    provider.get_handler.return_value = handler or MagicMock()
    return provider


def _make_service(*providers):
    service = ConstraintEnforcementService()
    for provider in providers:
        service.register_runnable(provider)
    return service


class TestEnforceDecisionGate:
    """Tests for enforce_decision_gate (ON_DECISION handlers only)."""

    def test_permit_without_constraints(self):
        result = enforce_decision_gate(_make_service(), _make_decision())
        assert result is True

    def test_deny_without_constraints(self):
        result = enforce_decision_gate(_make_service(), _make_decision(decision=Decision.DENY))
        assert result is False

    def test_deny_when_resource_present(self):
        result = enforce_decision_gate(_make_service(), _make_decision(has_resource=True))
        assert result is False

    def test_deny_when_obligation_unhandled(self):
        provider = _make_provider(responsible=False)
        service = _make_service(provider)
        result = enforce_decision_gate(service, _make_decision(obligations=[{"type": "unknown"}]))
        assert result is False

    def test_permit_when_obligation_handled(self):
        handler = MagicMock()
        provider = _make_provider(handler=handler)
        service = _make_service(provider)

        result = enforce_decision_gate(service, _make_decision(obligations=[{"type": "logAccess"}]))

        assert result is True
        handler.assert_called_once()

    def test_deny_when_obligation_handler_raises(self):
        provider = _make_provider(handler=MagicMock(side_effect=RuntimeError("boom")))
        service = _make_service(provider)

        result = enforce_decision_gate(service, _make_decision(obligations=[{"type": "logAccess"}]))

        assert result is False

    def test_no_short_circuit_on_obligation_failure(self):
        failing = MagicMock(side_effect=RuntimeError("boom"))
        succeeding = MagicMock()
        p1 = _make_provider(handler=failing)
        p1.is_responsible.side_effect = lambda c: c.get("id") == 1
        p2 = _make_provider(handler=succeeding)
        p2.is_responsible.side_effect = lambda c: c.get("id") == 2

        service = _make_service(p1, p2)
        enforce_decision_gate(service, _make_decision(obligations=[{"id": 1}, {"id": 2}]))

        failing.assert_called_once()
        succeeding.assert_called_once()

    def test_mixed_handled_and_unhandled_obligations(self):
        handler = MagicMock()
        provider = _make_provider(handler=handler)
        provider.is_responsible.side_effect = lambda c: c.get("type") == "known"

        service = _make_service(provider)
        decision = _make_decision(obligations=[{"type": "known"}, {"type": "unknown"}])

        result = enforce_decision_gate(service, decision)

        assert result is False
        handler.assert_called_once()

    def test_multiple_providers_for_same_obligation(self):
        h1, h2 = MagicMock(), MagicMock()
        p1 = _make_provider(handler=h1)
        p2 = _make_provider(handler=h2)

        service = _make_service(p1, p2)
        enforce_decision_gate(service, _make_decision(obligations=[{"type": "logAccess"}]))

        h1.assert_called_once()
        h2.assert_called_once()

    def test_ignores_providers_with_wrong_signal(self):
        provider = _make_provider(signal=Signal.ON_COMPLETE)
        service = _make_service(provider)

        result = enforce_decision_gate(service, _make_decision(obligations=[{"type": "logAccess"}]))

        assert result is False

    def test_resource_plus_handler_failure_both_deny(self):
        provider = _make_provider(handler=MagicMock(side_effect=RuntimeError("boom")))
        service = _make_service(provider)
        decision = _make_decision(obligations=[{"type": "logAccess"}], has_resource=True)

        result = enforce_decision_gate(service, decision)

        assert result is False

    def test_advice_executed_after_obligations(self):
        call_order = []
        obl_handler = MagicMock(side_effect=lambda: call_order.append("obligation"))
        adv_handler = MagicMock(side_effect=lambda: call_order.append("advice"))

        obl_provider = _make_provider(handler=obl_handler)
        obl_provider.is_responsible.side_effect = lambda c: c.get("role") == "obl"
        adv_provider = _make_provider(handler=adv_handler)
        adv_provider.is_responsible.side_effect = lambda c: c.get("role") == "adv"

        service = _make_service(obl_provider, adv_provider)
        decision = _make_decision(obligations=[{"role": "obl"}], advice=[{"role": "adv"}])

        enforce_decision_gate(service, decision)

        assert call_order == ["obligation", "advice"]

    def test_advice_failure_does_not_affect_outcome(self):
        adv_provider = _make_provider(handler=MagicMock(side_effect=RuntimeError("boom")))
        service = _make_service(adv_provider)

        result = enforce_decision_gate(service, _make_decision(advice=[{"type": "logAccess"}]))

        assert result is True

    def test_unhandled_advice_ignored(self):
        provider = _make_provider(responsible=False)
        service = _make_service(provider)

        result = enforce_decision_gate(service, _make_decision(advice=[{"type": "unknown"}]))

        assert result is True

    def test_advice_ignores_wrong_signal(self):
        handler = MagicMock()
        provider = _make_provider(signal=Signal.ON_COMPLETE, handler=handler)
        service = _make_service(provider)

        enforce_decision_gate(service, _make_decision(advice=[{"type": "logAccess"}]))

        handler.assert_not_called()

    def test_deny_with_obligations_runs_handlers(self):
        handler = MagicMock()
        provider = _make_provider(handler=handler)
        service = _make_service(provider)
        decision = _make_decision(decision=Decision.DENY, obligations=[{"type": "logAccess"}])

        result = enforce_decision_gate(service, decision)

        assert result is False
        handler.assert_called_once()

    def test_obligation_handler_invoked_exactly_once_on_permit(self):
        handler = MagicMock()
        provider = _make_provider(handler=handler)
        service = _make_service(provider)
        decision = _make_decision(obligations=[{"type": "logAccess"}])

        enforce_decision_gate(service, decision)

        assert handler.call_count == 1

    def test_obligation_handler_invoked_exactly_once_on_deny(self):
        handler = MagicMock()
        provider = _make_provider(handler=handler)
        service = _make_service(provider)
        decision = _make_decision(decision=Decision.DENY, obligations=[{"type": "logAccess"}])

        enforce_decision_gate(service, decision)

        assert handler.call_count == 1

    def test_advice_handler_invoked_exactly_once(self):
        handler = MagicMock()
        provider = _make_provider(handler=handler)
        service = _make_service(provider)
        decision = _make_decision(advice=[{"type": "logAccess"}])

        enforce_decision_gate(service, decision)

        assert handler.call_count == 1

    def test_handlers_invoked_exactly_once_on_failed_obligation(self):
        failing = MagicMock(side_effect=RuntimeError("boom"))
        ok_handler = MagicMock()
        adv_handler = MagicMock()

        p1 = _make_provider(handler=failing)
        p1.is_responsible.side_effect = lambda c: c.get("id") == 1
        p2 = _make_provider(handler=ok_handler)
        p2.is_responsible.side_effect = lambda c: c.get("id") == 2
        p3 = _make_provider(handler=adv_handler)
        p3.is_responsible.side_effect = lambda c: c.get("id") == 3

        service = _make_service(p1, p2, p3)
        decision = _make_decision(
            obligations=[{"id": 1}, {"id": 2}],
            advice=[{"id": 3}],
        )

        enforce_decision_gate(service, decision)

        assert failing.call_count == 1
        assert ok_handler.call_count == 1
        assert adv_handler.call_count == 1
