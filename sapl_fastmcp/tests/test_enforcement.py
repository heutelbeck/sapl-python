"""Tests for sapl_fastmcp.enforcement (gate-level enforcement)."""

from typing import Any
from unittest.mock import MagicMock

from sapl_base import AuthorizationDecision, Decision
from sapl_base.pep import DECISION, OUTPUT, EnforcementPlanner, ScopedHandler
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


class _Provider:
    """Helper provider that emits a DECISION runner for matching constraints.

    ``match`` decides whether a constraint is claimed. The handler is
    invoked at the DECISION signal; if it raises, the planner records
    obligation failure.
    """

    def __init__(self, match=None, handler=None):
        self._match = match or (lambda c: True)
        self._handler = handler or MagicMock()

    def get_handlers(self, constraint: Any):
        if not self._match(constraint):
            return ()
        return (
            ScopedHandler(
                signal=DECISION, priority=0, shape="runner",
                handler=self._handler,
            ),
        )


def _planner(*providers):
    return EnforcementPlanner(providers=tuple(providers))


class TestEnforceDecisionGate:
    """Tests for enforce_decision_gate."""

    def test_permit_without_constraints(self):
        assert enforce_decision_gate(_planner(), _make_decision()) is True

    def test_deny_without_constraints(self):
        assert enforce_decision_gate(_planner(), _make_decision(decision=Decision.DENY)) is False

    def test_deny_when_resource_present(self):
        assert enforce_decision_gate(_planner(), _make_decision(has_resource=True)) is False

    def test_deny_when_obligation_unhandled(self):
        provider = _Provider(match=lambda c: False)
        assert enforce_decision_gate(
            _planner(provider), _make_decision(obligations=[{"type": "unknown"}])
        ) is False

    def test_permit_when_obligation_handled(self):
        handler = MagicMock()
        provider = _Provider(handler=handler)

        result = enforce_decision_gate(
            _planner(provider), _make_decision(obligations=[{"type": "logAccess"}])
        )

        assert result is True
        handler.assert_called_once()

    def test_deny_when_obligation_handler_raises(self):
        provider = _Provider(handler=MagicMock(side_effect=RuntimeError("boom")))

        result = enforce_decision_gate(
            _planner(provider), _make_decision(obligations=[{"type": "logAccess"}])
        )

        assert result is False

    def test_no_short_circuit_on_obligation_failure(self):
        failing = MagicMock(side_effect=RuntimeError("boom"))
        succeeding = MagicMock()
        p1 = _Provider(match=lambda c: c.get("id") == 1, handler=failing)
        p2 = _Provider(match=lambda c: c.get("id") == 2, handler=succeeding)

        enforce_decision_gate(
            _planner(p1, p2),
            _make_decision(obligations=[{"id": 1}, {"id": 2}]),
        )

        failing.assert_called_once()
        succeeding.assert_called_once()

    def test_mixed_handled_and_unhandled_obligations(self):
        handler = MagicMock()
        provider = _Provider(match=lambda c: c.get("type") == "known", handler=handler)

        result = enforce_decision_gate(
            _planner(provider),
            _make_decision(obligations=[{"type": "known"}, {"type": "unknown"}]),
        )

        assert result is False
        handler.assert_called_once()

    def test_ambiguous_claim_denies(self):
        """Two providers claiming the same constraint produce a synthetic failure."""
        h1, h2 = MagicMock(), MagicMock()
        p1 = _Provider(handler=h1)
        p2 = _Provider(handler=h2)

        result = enforce_decision_gate(
            _planner(p1, p2),
            _make_decision(obligations=[{"type": "logAccess"}]),
        )

        assert result is False

    def test_deny_when_only_output_handler_admissible_for_obligation(self):
        """An OUTPUT mapper for an obligation cannot satisfy the DECISION gate.

        The planner classifies the claim as inadmissible (OUTPUT not in the
        supported signal set for the gate), produces a synthetic failure
        runner at DECISION, and the gate denies.
        """
        class OutputOnlyProvider:
            def get_handlers(self, constraint):
                return (ScopedHandler(signal=OUTPUT, priority=0, shape="mapper",
                                      handler=lambda v: v),)

        result = enforce_decision_gate(
            _planner(OutputOnlyProvider()),
            _make_decision(obligations=[{"type": "redactFields"}]),
        )

        assert result is False

    def test_resource_plus_handler_failure_both_deny(self):
        provider = _Provider(handler=MagicMock(side_effect=RuntimeError("boom")))
        decision = _make_decision(obligations=[{"type": "logAccess"}], has_resource=True)

        assert enforce_decision_gate(_planner(provider), decision) is False

    def test_advice_executed_after_obligations(self):
        call_order = []
        obl_handler = MagicMock(side_effect=lambda: call_order.append("obligation"))
        adv_handler = MagicMock(side_effect=lambda: call_order.append("advice"))

        obl_provider = _Provider(match=lambda c: c.get("role") == "obl", handler=obl_handler)
        adv_provider = _Provider(match=lambda c: c.get("role") == "adv", handler=adv_handler)

        decision = _make_decision(obligations=[{"role": "obl"}], advice=[{"role": "adv"}])
        enforce_decision_gate(_planner(obl_provider, adv_provider), decision)

        assert call_order == ["obligation", "advice"]

    def test_advice_failure_does_not_affect_outcome(self):
        adv_provider = _Provider(handler=MagicMock(side_effect=RuntimeError("boom")))

        result = enforce_decision_gate(
            _planner(adv_provider), _make_decision(advice=[{"type": "logAccess"}])
        )

        assert result is True

    def test_unhandled_advice_ignored(self):
        provider = _Provider(match=lambda c: False)

        result = enforce_decision_gate(
            _planner(provider), _make_decision(advice=[{"type": "unknown"}])
        )

        assert result is True

    def test_deny_with_obligations_runs_handlers(self):
        handler = MagicMock()
        provider = _Provider(handler=handler)
        decision = _make_decision(decision=Decision.DENY, obligations=[{"type": "logAccess"}])

        result = enforce_decision_gate(_planner(provider), decision)

        assert result is False
        handler.assert_called_once()

    def test_obligation_handler_invoked_exactly_once_on_permit(self):
        handler = MagicMock()
        provider = _Provider(handler=handler)
        decision = _make_decision(obligations=[{"type": "logAccess"}])

        enforce_decision_gate(_planner(provider), decision)

        assert handler.call_count == 1

    def test_obligation_handler_invoked_exactly_once_on_deny(self):
        handler = MagicMock()
        provider = _Provider(handler=handler)
        decision = _make_decision(decision=Decision.DENY, obligations=[{"type": "logAccess"}])

        enforce_decision_gate(_planner(provider), decision)

        assert handler.call_count == 1

    def test_advice_handler_invoked_exactly_once(self):
        handler = MagicMock()
        provider = _Provider(handler=handler)
        decision = _make_decision(advice=[{"type": "logAccess"}])

        enforce_decision_gate(_planner(provider), decision)

        assert handler.call_count == 1

    def test_handlers_invoked_exactly_once_on_failed_obligation(self):
        failing = MagicMock(side_effect=RuntimeError("boom"))
        ok_handler = MagicMock()
        adv_handler = MagicMock()

        p1 = _Provider(match=lambda c: c.get("id") == 1, handler=failing)
        p2 = _Provider(match=lambda c: c.get("id") == 2, handler=ok_handler)
        p3 = _Provider(match=lambda c: c.get("id") == 3, handler=adv_handler)

        decision = _make_decision(
            obligations=[{"id": 1}, {"id": 2}],
            advice=[{"id": 3}],
        )

        enforce_decision_gate(_planner(p1, p2, p3), decision)

        assert failing.call_count == 1
        assert ok_handler.call_count == 1
        assert adv_handler.call_count == 1
