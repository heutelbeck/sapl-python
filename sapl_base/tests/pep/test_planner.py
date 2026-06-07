from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sapl_base.pep import (
    DECISION,
    OUTPUT,
    DecisionSignal,
    EnforcementPlanner,
    OutputSignal,
    ScopedHandler,
)
from sapl_base.pep.streaming import STREAM_SUPPORTED
from sapl_base.types import AuthorizationDecision, Decision

if TYPE_CHECKING:
    from collections.abc import Sequence

_STREAM_SIGNALS = STREAM_SUPPORTED


class _StaticProvider:
    """Test double: claims constraints with type matching `accepted_type`
    by returning a fixed sequence of scoped handlers."""

    def __init__(self, accepted_type: str, handlers: Sequence[ScopedHandler]) -> None:
        self._accepted_type = accepted_type
        self._handlers = tuple(handlers)

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != self._accepted_type:
            return ()
        return self._handlers


def _decision(*, obligations: list[Any] | None = None, advice: list[Any] | None = None) -> AuthorizationDecision:
    return AuthorizationDecision(
        decision=Decision.PERMIT,
        obligations=tuple(obligations or ()),
        advice=tuple(advice or ()),
    )


class TestPhase1ClaimResolution:
    def test_single_provider_single_well_formed_triple_yields_one_entry(self) -> None:
        def _audit() -> None:
            return None

        provider = _StaticProvider(
            "audit",
            [ScopedHandler(signal=DECISION, priority=0, shape="runner", handler=_audit)],
        )
        planner = EnforcementPlanner(providers=[provider])
        plan = planner.plan(_decision(obligations=[{"type": "audit"}]), _STREAM_SIGNALS)
        entries = plan.entries_for(DECISION)
        assert len(entries) == 1
        assert entries[0].handler is _audit

    def test_zero_claims_produce_one_synthetic_runner_at_decision(self) -> None:
        planner = EnforcementPlanner(providers=[])
        plan = planner.plan(_decision(obligations=[{"type": "unknown"}]), _STREAM_SIGNALS)
        decision_entries = plan.entries_for(DECISION)
        assert len(decision_entries) == 1
        assert decision_entries[0].shape == "runner"

    def test_two_claims_produce_one_synthetic_runner(self) -> None:
        provider_a = _StaticProvider(
            "audit",
            [ScopedHandler(signal=DECISION, priority=0, shape="runner", handler=lambda: None)],
        )
        provider_b = _StaticProvider(
            "audit",
            [ScopedHandler(signal=DECISION, priority=0, shape="runner", handler=lambda: None)],
        )
        planner = EnforcementPlanner(providers=[provider_a, provider_b])
        plan = planner.plan(_decision(obligations=[{"type": "audit"}]), _STREAM_SIGNALS)
        assert len(plan.entries_for(DECISION)) == 1

    def test_zero_claims_advice_synthetic_runner_does_not_set_failure(self) -> None:
        planner = EnforcementPlanner(providers=[])
        plan = planner.plan(_decision(advice=[{"type": "unknown"}]), _STREAM_SIGNALS)
        result = plan.execute(DecisionSignal())
        assert result.failure_state is False

    def test_zero_claims_obligation_synthetic_runner_sets_failure(self) -> None:
        planner = EnforcementPlanner(providers=[])
        plan = planner.plan(_decision(obligations=[{"type": "unknown"}]), _STREAM_SIGNALS)
        result = plan.execute(DecisionSignal())
        assert result.failure_state is True

    def test_partially_well_formed_claim_becomes_single_synthetic_runner(self) -> None:
        """If a claim contains one good triple and one bad one, the WHOLE claim collapses."""
        def _good() -> None:
            return None

        def _bad_mapper(_: Any) -> Any:
            return None

        # Bad: mapper at the decision signal (non-data-carrying, runners-only).
        provider = _StaticProvider(
            "mixed",
            [
                ScopedHandler(signal=DECISION, priority=0, shape="runner", handler=_good),
                ScopedHandler(signal=DECISION, priority=1, shape="mapper", handler=_bad_mapper),
            ],
        )
        planner = EnforcementPlanner(providers=[provider])
        plan = planner.plan(_decision(obligations=[{"type": "mixed"}]), _STREAM_SIGNALS)
        # Whole claim discarded -> one synthetic runner, NOT (good runner + synthetic).
        assert len(plan.entries_for(DECISION)) == 1

    def test_unsupported_signal_in_claim_collapses_to_synthetic(self) -> None:
        provider = _StaticProvider(
            "stream-only",
            [ScopedHandler(signal=OUTPUT, priority=0, shape="mapper", handler=lambda v: v)],
        )
        planner = EnforcementPlanner(providers=[provider])
        unsupported = frozenset({DECISION})
        plan = planner.plan(_decision(obligations=[{"type": "stream-only"}]), unsupported)
        # Bad: output not in supported signals -> claim collapses to synthetic at DECISION.
        assert len(plan.entries_for(DECISION)) == 1
        assert plan.entries_for(OUTPUT) == ()

    def test_advice_mapper_collapses_to_synthetic(self) -> None:
        """Mappers are obligation-only by invariant; an advice-tagged mapper is not well-formed."""
        provider = _StaticProvider(
            "transform",
            [ScopedHandler(signal=OUTPUT, priority=0, shape="mapper", handler=lambda v: v)],
        )
        planner = EnforcementPlanner(providers=[provider])
        plan = planner.plan(_decision(advice=[{"type": "transform"}]), _STREAM_SIGNALS)
        assert plan.entries_for(OUTPUT) == ()
        assert len(plan.entries_for(DECISION)) == 1


class TestPhase2OrderingAndCommutativity:
    def test_priorities_sorted_ascending(self) -> None:
        provider = _StaticProvider(
            "ordered",
            [
                ScopedHandler(signal=OUTPUT, priority=10, shape="consumer", handler=lambda v: None),
                ScopedHandler(signal=OUTPUT, priority=1, shape="consumer", handler=lambda v: None),
                ScopedHandler(signal=OUTPUT, priority=5, shape="consumer", handler=lambda v: None),
            ],
        )
        planner = EnforcementPlanner(providers=[provider])
        plan = planner.plan(_decision(obligations=[{"type": "ordered"}]), _STREAM_SIGNALS)
        priorities = [e.priority for e in plan.entries_for(OUTPUT)]
        assert priorities == [1, 5, 10]

    def test_runner_before_mapper_before_consumer_at_equal_priority(self) -> None:
        provider = _StaticProvider(
            "tiebreak",
            [
                ScopedHandler(signal=OUTPUT, priority=0, shape="consumer", handler=lambda v: None),
                ScopedHandler(signal=OUTPUT, priority=0, shape="mapper", handler=lambda v: v),
                ScopedHandler(signal=OUTPUT, priority=0, shape="runner", handler=lambda: None),
            ],
        )
        planner = EnforcementPlanner(providers=[provider])
        plan = planner.plan(_decision(obligations=[{"type": "tiebreak"}]), _STREAM_SIGNALS)
        shapes = [e.shape for e in plan.entries_for(OUTPUT)]
        assert shapes == ["runner", "mapper", "consumer"]

    def test_two_mappers_at_same_priority_each_become_synthetic(self) -> None:
        provider_a = _StaticProvider(
            "ma",
            [ScopedHandler(signal=OUTPUT, priority=0, shape="mapper", handler=lambda v: v)],
        )
        provider_b = _StaticProvider(
            "mb",
            [ScopedHandler(signal=OUTPUT, priority=0, shape="mapper", handler=lambda v: v)],
        )
        planner = EnforcementPlanner(providers=[provider_a, provider_b])
        plan = planner.plan(
            _decision(obligations=[{"type": "ma"}, {"type": "mb"}]),
            _STREAM_SIGNALS,
        )
        # Both same-priority mappers become synthetic runners (at DECISION).
        assert plan.entries_for(OUTPUT) == ()
        assert len(plan.entries_for(DECISION)) == 2

    def test_single_mapper_at_priority_survives(self) -> None:
        provider = _StaticProvider(
            "sole",
            [ScopedHandler(signal=OUTPUT, priority=0, shape="mapper", handler=lambda v: v + 1)],
        )
        planner = EnforcementPlanner(providers=[provider])
        plan = planner.plan(_decision(obligations=[{"type": "sole"}]), _STREAM_SIGNALS)
        result = plan.execute(OutputSignal(value=5))
        assert result.value == 6


class TestSyntheticRunnerSemantics:
    def test_obligation_synthetic_runner_sets_failure_state_when_executed(self) -> None:
        planner = EnforcementPlanner(providers=[])
        plan = planner.plan(_decision(obligations=[{"type": "x"}]), _STREAM_SIGNALS)
        assert plan.execute(DecisionSignal()).failure_state is True

    def test_advice_synthetic_runner_does_not_set_failure_state(self) -> None:
        planner = EnforcementPlanner(providers=[])
        plan = planner.plan(_decision(advice=[{"type": "x"}]), _STREAM_SIGNALS)
        assert plan.execute(DecisionSignal()).failure_state is False
