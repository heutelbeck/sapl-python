from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from sapl_base.pep import (
    DECISION,
    OUTPUT,
    AccessDeniedError,
    AccessGrantedSignal,
    AccessSuspendedSignal,
    EnforcementPlanner,
    ScopedHandler,
)
from sapl_base.pep.streaming.pipeline import run_pipeline
from sapl_base.types import AuthorizationDecision, Decision


async def _iter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


def _permit() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT)


def _deny() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.DENY)


def _suspend() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.SUSPEND)


def _rap_factory(items: list[Any]) -> Callable[[], AsyncIterator[Any]]:
    def _factory() -> AsyncIterator[Any]:
        return _iter(items)
    return _factory


async def _collect(
    iterator: AsyncIterator[Any], limit_seconds: float = 1.0
) -> list[Any]:
    collected: list[Any] = []
    async def _go() -> None:
        async for item in iterator:
            collected.append(item)
    try:
        await asyncio.wait_for(_go(), timeout=limit_seconds)
    except asyncio.TimeoutError:
        pass
    return collected


@pytest.mark.asyncio
async def test_permit_then_data_forwards_items() -> None:
    pipeline = run_pipeline(
        decisions=_iter([_permit()]),
        planner=EnforcementPlanner(),
        rap_factory=_rap_factory([1, 2, 3]),
    )
    out = await _collect(pipeline)
    assert out == [1, 2, 3]


@pytest.mark.asyncio
async def test_signal_transitions_off_drops_grant_emission() -> None:
    pipeline = run_pipeline(
        decisions=_iter([_permit()]),
        planner=EnforcementPlanner(),
        rap_factory=_rap_factory([1]),
        signal_transitions=False,
    )
    out = await _collect(pipeline)
    assert all(not isinstance(x, AccessGrantedSignal) for x in out)


@pytest.mark.asyncio
async def test_signal_transitions_on_yields_granted_signal() -> None:
    pipeline = run_pipeline(
        decisions=_iter([_permit()]),
        planner=EnforcementPlanner(),
        rap_factory=_rap_factory([1]),
        signal_transitions=True,
    )
    out = await _collect(pipeline)
    assert any(isinstance(x, AccessGrantedSignal) for x in out)
    assert 1 in out


@pytest.mark.asyncio
async def test_permit_then_deny_terminates_with_access_denied() -> None:
    pipeline = run_pipeline(
        decisions=_iter([_permit(), _deny()]),
        planner=EnforcementPlanner(),
        rap_factory=_rap_factory([1, 2]),
    )
    with pytest.raises(AccessDeniedError):
        async for _ in pipeline:
            pass


@pytest.mark.asyncio
async def test_initial_deny_terminates_before_any_data() -> None:
    pipeline = run_pipeline(
        decisions=_iter([_deny()]),
        planner=EnforcementPlanner(),
        rap_factory=_rap_factory([1, 2, 3]),
    )
    with pytest.raises(AccessDeniedError):
        async for _ in pipeline:
            pass


@pytest.mark.asyncio
async def test_initial_indeterminate_routes_to_deny() -> None:
    indeterminate = AuthorizationDecision(decision=Decision.INDETERMINATE)
    pipeline = run_pipeline(
        decisions=_iter([indeterminate]),
        planner=EnforcementPlanner(),
        rap_factory=_rap_factory([1]),
    )
    with pytest.raises(AccessDeniedError):
        async for _ in pipeline:
            pass


@pytest.mark.asyncio
async def test_suspend_drops_items_until_permit() -> None:
    pipeline = run_pipeline(
        decisions=_iter([_suspend()]),
        planner=EnforcementPlanner(),
        rap_factory=_rap_factory([1, 2, 3]),
        signal_transitions=True,
    )
    out = await _collect(pipeline)
    assert all(not isinstance(x, int) for x in out)
    assert any(isinstance(x, AccessSuspendedSignal) for x in out)


class _BlackeningProvider:
    """Test provider: maps every output value to its uppercase form."""

    def get_handlers(self, constraint: Any) -> list[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "uppercase":
            return []
        return [
            ScopedHandler(
                signal=OUTPUT,
                priority=0,
                shape="mapper",
                handler=lambda v: v.upper() if isinstance(v, str) else v,
            )
        ]


@pytest.mark.asyncio
async def test_output_mapper_transforms_items_under_permit() -> None:
    permit_with_obligation = AuthorizationDecision(
        decision=Decision.PERMIT,
        obligations=({"type": "uppercase"},),
    )
    pipeline = run_pipeline(
        decisions=_iter([permit_with_obligation]),
        planner=EnforcementPlanner(providers=[_BlackeningProvider()]),
        rap_factory=_rap_factory(["alice", "bob"]),
    )
    out = await _collect(pipeline)
    assert out == ["ALICE", "BOB"]


@pytest.mark.asyncio
async def test_permit_obligation_failure_in_decision_signal_terminates() -> None:
    """Decision-scoped obligation failure on PERMIT classifies as deny."""

    def _broken() -> None:
        raise RuntimeError("audit pipeline is down")

    class _Provider:
        def get_handlers(self, constraint: Any) -> list[ScopedHandler]:
            if not isinstance(constraint, dict) or constraint.get("type") != "audit":
                return []
            return [
                ScopedHandler(
                    signal=DECISION, priority=0, shape="runner", handler=_broken
                )
            ]

    permit_with_failing_audit = AuthorizationDecision(
        decision=Decision.PERMIT, obligations=({"type": "audit"},)
    )
    pipeline = run_pipeline(
        decisions=_iter([permit_with_failing_audit]),
        planner=EnforcementPlanner(providers=[_Provider()]),
        rap_factory=_rap_factory([1, 2]),
    )
    with pytest.raises(AccessDeniedError):
        async for _ in pipeline:
            pass


@pytest.mark.asyncio
async def test_pause_rap_during_suspend_cancels_rap_task() -> None:
    """When pause_rap_during_suspend is set, entering Suspended cancels the RAP."""
    rap_calls = 0

    def _factory() -> AsyncIterator[Any]:
        nonlocal rap_calls
        rap_calls += 1
        return _iter([1, 2, 3])

    pipeline = run_pipeline(
        decisions=_iter([_permit(), _suspend(), _permit()]),
        planner=EnforcementPlanner(),
        rap_factory=_factory,
        pause_rap_during_suspend=True,
    )
    await _collect(pipeline, limit_seconds=0.5)
    # RAP started at first PERMIT, cancelled on SUSPEND, restarted on second PERMIT.
    assert rap_calls >= 2


@pytest.mark.asyncio
async def test_normal_rap_completion_ends_subscription_cleanly() -> None:
    pipeline = run_pipeline(
        decisions=_iter([_permit()]),
        planner=EnforcementPlanner(),
        rap_factory=_rap_factory([1, 2]),
    )
    out = []
    async for item in pipeline:
        out.append(item)
    assert out == [1, 2]
