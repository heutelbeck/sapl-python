"""Subscriber-side helpers for handling boundary signals.

Boundary signals (`AccessSuspendedSignal`, `AccessGrantedSignal`)
arrive as yielded values on the same async iterator as data items.
These helpers let subscribers react to them without manual
`isinstance` filtering at every call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sapl_base.pep.boundary_signals import (
    AccessGrantedSignal,
    AccessSuspendedSignal,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable


async def on_suspend(
    source: AsyncIterator[Any],
    consumer: Callable[[AccessSuspendedSignal], None],
    substitute: Callable[[AccessSuspendedSignal], Any] | None = None,
) -> AsyncIterator[Any]:
    """Invoke `consumer` on every suspend signal in `source`.

    If `substitute` is None, the suspend signal is filtered out of
    the downstream iterator. If `substitute` is provided, its
    return value replaces the signal in the stream.
    """
    async for item in source:
        if isinstance(item, AccessSuspendedSignal):
            consumer(item)
            if substitute is None:
                continue
            yield substitute(item)
            continue
        yield item


async def on_granted(
    source: AsyncIterator[Any],
    consumer: Callable[[AccessGrantedSignal], None],
    substitute: Callable[[AccessGrantedSignal], Any] | None = None,
) -> AsyncIterator[Any]:
    """Invoke `consumer` on every grant signal in `source`.

    Same substitution semantics as `on_suspend`.
    """
    async for item in source:
        if isinstance(item, AccessGrantedSignal):
            consumer(item)
            if substitute is None:
                continue
            yield substitute(item)
            continue
        yield item


async def on_transitions(
    source: AsyncIterator[Any],
    suspend_consumer: Callable[[AccessSuspendedSignal], None],
    grant_consumer: Callable[[AccessGrantedSignal], None],
) -> AsyncIterator[Any]:
    """Observe both boundary kinds, filtering both out of the stream."""
    async for item in source:
        if isinstance(item, AccessSuspendedSignal):
            suspend_consumer(item)
            continue
        if isinstance(item, AccessGrantedSignal):
            grant_consumer(item)
            continue
        yield item
