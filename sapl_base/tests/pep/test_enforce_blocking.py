"""Blocking enforcement core: runs the method synchronously, off any event loop.

The defining property is that the protected method executes with no running event
loop even when the PDP client is async (driven to completion first). That is what
lets a synchronous ORM (Django, sync SQLAlchemy) run inside the protected region.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from sapl_base.pep import (
    OUTPUT,
    AccessDeniedError,
    EnforcementPlanner,
    ScopedHandler,
)
from sapl_base.pep.enforce import post_enforce_blocking, pre_enforce_blocking
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision

SUB = AuthorizationSubscription(subject="s", action="a", resource="r")
FAIL_OUTPUT = {"type": "failOutput"}


def _permit(*obligations: Any) -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=tuple(obligations))


class SyncStubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    def decide_once(self, subscription: Any) -> AuthorizationDecision:
        return self._decision


class AsyncStubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: Any) -> AuthorizationDecision:
        return self._decision


class FailingOutputProvider:
    def get_handlers(self, constraint: Any) -> list[ScopedHandler]:
        if isinstance(constraint, dict) and constraint.get("type") == "failOutput":
            def _raise(value: Any) -> None:
                raise RuntimeError("output obligation handler failed")

            return [ScopedHandler(signal=OUTPUT, priority=0, shape="consumer", handler=_raise)]
        return []


class RecordingTransaction:
    """Sync transaction provider + context manager that records commit vs rollback."""

    def __init__(self) -> None:
        self.committed: bool | None = None

    def __call__(self) -> RecordingTransaction:
        return self

    def __enter__(self) -> RecordingTransaction:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.committed = exc_type is None
        return False


def test_method_runs_with_no_running_event_loop_even_with_async_client():
    observed: dict[str, bool] = {}

    def _method() -> str:
        try:
            asyncio.get_running_loop()
            observed["in_loop"] = True
        except RuntimeError:
            observed["in_loop"] = False
        return "ok"

    result = pre_enforce_blocking(
        _method, pdp_client=AsyncStubPdp(_permit()), planner=EnforcementPlanner(), subscription=SUB
    )
    assert result == "ok"
    assert observed["in_loop"] is False


@pytest.mark.parametrize(
    "pdp_client",
    [SyncStubPdp(_permit()), AsyncStubPdp(_permit())],
    ids=["sync-client", "async-client-bridged"],
)
def test_permit_returns_result_for_both_client_kinds(pdp_client):
    def _method() -> str:
        return "value"

    assert (
        pre_enforce_blocking(_method, pdp_client=pdp_client, planner=EnforcementPlanner(), subscription=SUB)
        == "value"
    )


def test_deny_raises_access_denied():
    def _method() -> str:
        return "value"

    with pytest.raises(AccessDeniedError) as exc:
        pre_enforce_blocking(
            _method,
            pdp_client=SyncStubPdp(AuthorizationDecision(decision=Decision.DENY)),
            planner=EnforcementPlanner(),
            subscription=SUB,
        )
    assert exc.value.reason == "VERB_DENY"


def test_output_obligation_failure_raises():
    def _method() -> str:
        return "value"

    with pytest.raises(AccessDeniedError) as exc:
        pre_enforce_blocking(
            _method,
            pdp_client=SyncStubPdp(_permit(FAIL_OUTPUT)),
            planner=EnforcementPlanner(providers=(FailingOutputProvider(),)),
            subscription=SUB,
        )
    assert exc.value.reason == "OUTPUT_FAILURE"


def test_transaction_commits_on_permit():
    transaction = RecordingTransaction()

    def _method() -> str:
        return "value"

    result = pre_enforce_blocking(
        _method,
        pdp_client=SyncStubPdp(_permit()),
        planner=EnforcementPlanner(),
        subscription=SUB,
        transaction=transaction,
    )
    assert result == "value"
    assert transaction.committed is True


def test_transaction_rolls_back_on_output_obligation_failure():
    transaction = RecordingTransaction()

    def _method() -> str:
        return "value"

    with pytest.raises(AccessDeniedError):
        pre_enforce_blocking(
            _method,
            pdp_client=SyncStubPdp(_permit(FAIL_OUTPUT)),
            planner=EnforcementPlanner(providers=(FailingOutputProvider(),)),
            subscription=SUB,
            transaction=transaction,
        )
    assert transaction.committed is False


def test_post_enforce_blocking_permit_returns_result():
    def _method() -> dict[str, int]:
        return {"id": 1}

    result = post_enforce_blocking(
        _method,
        pdp_client=AsyncStubPdp(_permit()),
        planner=EnforcementPlanner(),
        subscription_builder=lambda _rv: SUB,
    )
    assert result == {"id": 1}


def test_post_enforce_blocking_deny_rolls_back():
    transaction = RecordingTransaction()

    def _method() -> dict[str, int]:
        return {"id": 1}

    with pytest.raises(AccessDeniedError):
        post_enforce_blocking(
            _method,
            pdp_client=SyncStubPdp(AuthorizationDecision(decision=Decision.DENY)),
            planner=EnforcementPlanner(),
            subscription_builder=lambda _rv: SUB,
            transaction=transaction,
        )
    assert transaction.committed is False
