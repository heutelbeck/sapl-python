from __future__ import annotations

from typing import Any

import pytest

from sapl_base.pep import EnforcementPlanner
from sapl_base.pep.enforce import pre_enforce
from sapl_base.pep.request_context import (
    current_plan,
    reset_current_plan,
    set_current_plan,
)
from sapl_base.types import (
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationDecision,
)


class _ScriptedPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, _: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision

    async def multi_decide_all_once(self, _: Any) -> MultiAuthorizationDecision:
        return MultiAuthorizationDecision()

    def decide(self, _: Any):  # pragma: no cover
        async def _gen():
            yield self._decision
        return _gen()

    def multi_decide(self, _: Any):  # pragma: no cover
        async def _gen():
            return
            yield  # pragma: no cover
        return _gen()

    def multi_decide_all(self, _: Any):  # pragma: no cover
        async def _gen():
            return
            yield  # pragma: no cover
        return _gen()

    async def close(self) -> None:
        return None


def _subscription() -> AuthorizationSubscription:
    return AuthorizationSubscription(subject="alice", action="read", resource="doc-1")


def test_default_is_none() -> None:
    assert current_plan() is None


def test_set_and_reset_round_trip() -> None:
    sentinel = object()
    token = set_current_plan(sentinel)  # type: ignore[arg-type]
    try:
        assert current_plan() is sentinel
    finally:
        reset_current_plan(token)
    assert current_plan() is None


@pytest.mark.asyncio
async def test_pre_enforce_sets_plan_in_context_during_method_invocation() -> None:
    seen_inside_method: list[Any] = []

    async def _method() -> str:
        seen_inside_method.append(current_plan())
        return "done"

    pdp = _ScriptedPdp(AuthorizationDecision(decision=Decision.PERMIT))
    await pre_enforce(
        _method,
        pdp_client=pdp,
        planner=EnforcementPlanner(),
        subscription=_subscription(),
    )
    assert len(seen_inside_method) == 1
    assert seen_inside_method[0] is not None


@pytest.mark.asyncio
async def test_pre_enforce_resets_plan_after_method_returns() -> None:
    async def _method() -> str:
        return "done"

    pdp = _ScriptedPdp(AuthorizationDecision(decision=Decision.PERMIT))
    await pre_enforce(
        _method, pdp_client=pdp, planner=EnforcementPlanner(),
        subscription=_subscription()
    )
    assert current_plan() is None


@pytest.mark.asyncio
async def test_pre_enforce_resets_plan_even_when_method_raises() -> None:
    async def _method() -> str:
        raise RuntimeError("boom")

    pdp = _ScriptedPdp(AuthorizationDecision(decision=Decision.PERMIT))
    with pytest.raises(RuntimeError, match="boom"):
        await pre_enforce(
            _method, pdp_client=pdp, planner=EnforcementPlanner(),
            subscription=_subscription()
        )
    assert current_plan() is None
