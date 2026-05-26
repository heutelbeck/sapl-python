from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from sapl_base.pep import AccessGrantedSignal, AccessSuspendedSignal
from sapl_base.pep.streaming.transition_signals import (
    on_granted,
    on_suspend,
    on_transitions,
)
from sapl_base.types import AuthorizationDecision, Decision


async def _stream(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


async def _drain(it: AsyncIterator[Any]) -> list[Any]:
    return [x async for x in it]


def _suspend_signal() -> AccessSuspendedSignal:
    return AccessSuspendedSignal(decision=AuthorizationDecision(decision=Decision.SUSPEND))


def _granted_signal() -> AccessGrantedSignal:
    return AccessGrantedSignal(decision=AuthorizationDecision(decision=Decision.PERMIT))


@pytest.mark.asyncio
async def test_on_suspend_filters_signals_and_invokes_consumer() -> None:
    seen: list[AccessSuspendedSignal] = []
    items = [1, _suspend_signal(), 2, _suspend_signal(), 3]
    out = await _drain(on_suspend(_stream(items), seen.append))
    assert out == [1, 2, 3]
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_on_suspend_substitute_replaces_signal_with_value() -> None:
    out = await _drain(
        on_suspend(
            _stream([1, _suspend_signal(), 2]),
            consumer=lambda _: None,
            substitute=lambda _: "paused",
        )
    )
    assert out == [1, "paused", 2]


@pytest.mark.asyncio
async def test_on_granted_filters_signals_and_invokes_consumer() -> None:
    seen: list[AccessGrantedSignal] = []
    items = [_granted_signal(), 1, _granted_signal()]
    out = await _drain(on_granted(_stream(items), seen.append))
    assert out == [1]
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_on_transitions_observes_both_kinds() -> None:
    suspend_seen: list[AccessSuspendedSignal] = []
    granted_seen: list[AccessGrantedSignal] = []
    items = [_granted_signal(), 1, _suspend_signal(), 2, _granted_signal(), 3]
    out = await _drain(on_transitions(_stream(items), suspend_seen.append, granted_seen.append))
    assert out == [1, 2, 3]
    assert len(suspend_seen) == 1
    assert len(granted_seen) == 2


@pytest.mark.asyncio
async def test_on_suspend_passes_non_signal_values_through() -> None:
    out = await _drain(on_suspend(_stream(["a", "b", "c"]), consumer=lambda _: None))
    assert out == ["a", "b", "c"]
