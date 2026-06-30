"""RAP stream errors must reach the subscriber as their original cause.

A failure raised inside the protected resource (the RAP), for example a
database or network error, is a genuine stream error. It is a different
operational event from a per-item obligation-discharge failure. The Mealy
lifecycle terminates a genuine RAP error with EmitError carrying the
ORIGINAL throwable, whereas an obligation failure terminates with
EmitError(AccessDeniedError, reason="OBLIGATION_FAILURE"). Masking a
resource failure as an access-denied/obligation event hides the real cause
from the subscriber.

Traceability: RAP-ERROR-MASKED-AS-OBLIGATION-FAILURE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sapl_base.pep import AccessDeniedError, EnforcementPlanner
from sapl_base.pep.streaming.pipeline import run_pipeline
from sapl_base.types import AuthorizationDecision, Decision

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable


async def _iter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


def _permit() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT)


def _failing_rap_factory(error: BaseException) -> Callable[[], AsyncIterator[Any]]:
    """A protected resource that yields once, then fails with `error`."""

    async def _gen() -> AsyncIterator[Any]:
        yield 1
        raise error

    return _gen


class TestRapResourceFailurePropagation:
    """A genuine resource failure inside the RAP surfaces its real cause."""

    @pytest.mark.asyncio
    async def test_database_failure_raises_original_throwable(self) -> None:
        original = ValueError("db down")
        pipeline = run_pipeline(
            decisions=_iter([_permit()]),
            planner=EnforcementPlanner(),
            rap_factory=_failing_rap_factory(original),
        )

        async def _drain() -> None:
            async for _ in pipeline:
                pass

        with pytest.raises(ValueError, match="db down") as caught:
            await _drain()
        assert caught.value is original

    @pytest.mark.asyncio
    async def test_resource_failure_not_masked_as_obligation_failure(self) -> None:
        pipeline = run_pipeline(
            decisions=_iter([_permit()]),
            planner=EnforcementPlanner(),
            rap_factory=_failing_rap_factory(RuntimeError("network unreachable")),
        )

        async def _drain() -> None:
            async for _ in pipeline:
                pass

        with pytest.raises(BaseException) as caught:  # noqa: PT011, B017
            await _drain()
        assert not isinstance(caught.value, AccessDeniedError)
