"""A constraint handler provider that fails during planning must not crash the PEP.

Per the Spring PEP (EnforcementPlanner.claimHandlers, R6/A4): a provider that
throws while resolving a constraint is caught, logged, and treated as if it
returned no handlers (no claim). A malformed constraint therefore fails closed
through the UNRESOLVED synthetic-failure substitute rather than letting a raw
exception escape plan(). Providers are queried exactly once per constraint, so
resolution has no doubled side effects.

Traceability: CC-3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sapl_base.pep import (
    DECISION,
    POST_ENFORCE_SUPPORTED,
    DecisionSignal,
    EnforcementPlanner,
    ScopedHandler,
)
from sapl_base.types import AuthorizationDecision, Decision

if TYPE_CHECKING:
    from collections.abc import Sequence


class _ThrowingProvider:
    """Test double: blows up while trying to resolve any constraint."""

    def __init__(self, reason: str = "malformed constraint") -> None:
        self._reason = reason
        self.calls = 0

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        self.calls += 1
        raise ValueError(self._reason)


class _CountingProvider:
    """Test double: claims constraints of `accepted_type`, counting each query."""

    def __init__(self, accepted_type: str, handlers: Sequence[ScopedHandler]) -> None:
        self._accepted_type = accepted_type
        self._handlers = tuple(handlers)
        self.calls = 0

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        self.calls += 1
        if not isinstance(constraint, dict) or constraint.get("type") != self._accepted_type:
            return ()
        return self._handlers


def _decision(
    *, obligations: list[Any] | None = None, advice: list[Any] | None = None
) -> AuthorizationDecision:
    return AuthorizationDecision(
        decision=Decision.PERMIT,
        obligations=tuple(obligations or ()),
        advice=tuple(advice or ()),
    )


class TestProviderRaisingDuringResolution:
    def test_throwing_provider_does_not_escape_plan(self) -> None:
        bad = _ThrowingProvider()
        planner = EnforcementPlanner(providers=[bad])
        decision = _decision(obligations=[{"type": "audit"}])
        # plan() must absorb the provider failure, not propagate it.
        plan = planner.plan(decision, POST_ENFORCE_SUPPORTED)
        assert plan is not None

    def test_throwing_provider_on_obligation_fails_closed(self) -> None:
        bad = _ThrowingProvider()
        planner = EnforcementPlanner(providers=[bad])
        plan = planner.plan(_decision(obligations=[{"type": "audit"}]), POST_ENFORCE_SUPPORTED)
        entries = plan.entries_for(DECISION)
        # Treated as no-claim -> a single synthetic failure runner at the decision signal.
        assert len(entries) == 1
        assert entries[0].shape == "runner"
        assert plan.execute(DecisionSignal()).failure_state is True

    def test_throwing_provider_on_advice_does_not_fail(self) -> None:
        bad = _ThrowingProvider()
        planner = EnforcementPlanner(providers=[bad])
        plan = planner.plan(_decision(advice=[{"type": "audit"}]), POST_ENFORCE_SUPPORTED)
        # Advice that cannot be resolved is silently skipped, not escalated to deny.
        assert plan.execute(DecisionSignal()).failure_state is False

    def test_throwing_provider_queried_once(self) -> None:
        bad = _ThrowingProvider()
        planner = EnforcementPlanner(providers=[bad])
        planner.plan(_decision(obligations=[{"type": "audit"}]), POST_ENFORCE_SUPPORTED)
        assert bad.calls == 1

    def test_throwing_provider_does_not_suppress_a_valid_claim(self) -> None:
        def _audit() -> None:
            return None

        bad = _ThrowingProvider()
        good = _CountingProvider(
            "audit",
            [ScopedHandler(signal=DECISION, priority=0, shape="runner", handler=_audit)],
        )
        planner = EnforcementPlanner(providers=[bad, good])
        plan = planner.plan(_decision(obligations=[{"type": "audit"}]), POST_ENFORCE_SUPPORTED)
        entries = plan.entries_for(DECISION)
        # The throwing provider counts as no claim, leaving exactly one valid claim.
        assert len(entries) == 1
        assert entries[0].handler is _audit


class TestProviderQueriedOncePerConstraint:
    def test_claiming_provider_queried_exactly_once(self) -> None:
        provider = _CountingProvider(
            "audit",
            [ScopedHandler(signal=DECISION, priority=0, shape="runner", handler=lambda: None)],
        )
        planner = EnforcementPlanner(providers=[provider])
        planner.plan(_decision(obligations=[{"type": "audit"}]), POST_ENFORCE_SUPPORTED)
        # Resolution must not double-invoke get_handlers (no doubled side effects).
        assert provider.calls == 1

    def test_provider_side_effect_not_doubled(self) -> None:
        observed: list[dict[str, Any]] = []

        class _RecordingProvider:
            def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
                observed.append(constraint)
                return (
                    ScopedHandler(signal=DECISION, priority=0, shape="runner", handler=lambda: None),
                )

        planner = EnforcementPlanner(providers=[_RecordingProvider()])
        constraint = {"type": "audit"}
        planner.plan(_decision(obligations=[constraint]), POST_ENFORCE_SUPPORTED)
        assert observed == [constraint]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
