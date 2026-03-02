from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

WARN_DEPTH_LIMIT_EXCEEDED = "Deep equality comparison exceeded max depth, treating as not equal"

logger = structlog.get_logger(__name__)


def deep_equal(a: Any, b: Any, max_depth: int = 20) -> bool:
    """Deep equality comparison with depth limit.

    REQ-DEDUP-2: Prevents stack overflow on deeply nested or circular
    structures by treating values as unequal when the depth limit is
    exceeded.
    """
    return _deep_equal_recursive(a, b, max_depth, current_depth=0)


async def deduplicate[T](stream: AsyncIterator[T]) -> AsyncIterator[T]:
    """Suppress consecutive duplicate items from an async stream.

    REQ-DEDUP-1: Only emits an item when it differs from the immediately
    preceding item, using deep structural equality.
    """
    sentinel = object()
    previous: Any = sentinel

    async for item in stream:
        if previous is sentinel or not deep_equal(previous, item):
            previous = item
            yield item


def _deep_equal_recursive(a: Any, b: Any, max_depth: int, current_depth: int) -> bool:
    if current_depth > max_depth:
        logger.warning(WARN_DEPTH_LIMIT_EXCEEDED, max_depth=max_depth)
        return False

    if a is b:
        return True

    if type(a) is not type(b):
        return False

    if isinstance(a, dict):
        if len(a) != len(b):
            return False
        for key in a:
            if key not in b:
                return False
            if not _deep_equal_recursive(a[key], b[key], max_depth, current_depth + 1):
                return False
        return True

    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        for item_a, item_b in zip(a, b, strict=True):
            if not _deep_equal_recursive(item_a, item_b, max_depth, current_depth + 1):
                return False
        return True

    if isinstance(a, (set, frozenset)):
        return a == b

    return a == b
