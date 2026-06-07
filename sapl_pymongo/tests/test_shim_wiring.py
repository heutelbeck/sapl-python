"""Cross-framework wiring validation for the PyMongo MONGO_QUERY shim.

The four supported framework wrappers (Flask, FastAPI, Tornado, Django) all delegate
enforcement to two base entry points: ``pre_enforce`` on the async path and
``pre_enforce_blocking`` on the blocking path. Proving the cut point applies the
obligation through both base paths therefore proves it for every framework: Flask uses
the blocking path, Tornado the async path, FastAPI and Django both.

What is validated here:

- With a wrapped collection (which registers the shim) a mongo:queryManipulation
  obligation flows through the planner to MongoDbQueryManipulationProvider, and the cut
  point rewrites the filter the collection receives. The recording stub captures that
  filter, so the test asserts the exact rewrite that reached the driver on each path.
- Without the shim registered the obligation is inadmissible and enforcement fails closed
  before the method runs. This is the auto-detect gate: nothing in pre_enforce knows about
  "shims"; it plans against the signals that are registered.
- A PERMIT with no obligation leaves the filter unchanged.

Only the PDP is mocked. The plan, the planner admission decision, the contextvar carrying
the plan into the query, the provider, and the cut point are all real. The collection is a
recording stub because the real-database narrowing is proven in the mongomock integration.
"""

from __future__ import annotations

from typing import Any

import pytest

from sapl_base.pep import EnforcementPlanner
from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.enforce import pre_enforce, pre_enforce_blocking
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_pymongo import (
    MongoDbQueryManipulationProvider,
    unregister_mongo_shim,
    wrap_async_collection,
    wrap_collection,
)

OWNER_OBLIGATION = {"type": "mongo:queryManipulation", "criteria": [{"column": "owner", "op": "=", "value": "alice"}]}
USER_FILTER = {"status": "active"}
NARROWED = {"$and": [USER_FILTER, {"owner": "alice"}]}
SUBSCRIPTION = AuthorizationSubscription(subject="u", action="read", resource="widget")


class SyncRecordingCollection:
    def __init__(self) -> None:
        self.received: Any = None

    def find(self, query_filter: Any, *args: Any, **kwargs: Any) -> list[str]:
        self.received = query_filter
        return ["row"]


class AsyncRecordingCollection:
    def __init__(self) -> None:
        self.received: Any = None

    async def find_one(self, query_filter: Any, *args: Any, **kwargs: Any) -> dict[str, int]:
        self.received = query_filter
        return {"row": 1}


class StubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision


def _planner() -> EnforcementPlanner:
    return EnforcementPlanner(providers=(MongoDbQueryManipulationProvider(),))


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    unregister_mongo_shim()


def _permit(obligation: dict[str, Any] | None = None) -> AuthorizationDecision:
    obligations = (obligation,) if obligation is not None else ()
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=obligations)


async def test_async_path_applies_rewrite():
    collection = AsyncRecordingCollection()
    wrapped = wrap_async_collection(collection)

    async def handler() -> dict[str, int]:
        return await wrapped.find_one(USER_FILTER)

    result = await pre_enforce(
        handler, pdp_client=StubPdp(_permit(OWNER_OBLIGATION)), planner=_planner(), subscription=SUBSCRIPTION
    )

    assert result == {"row": 1}
    assert collection.received == NARROWED


def test_blocking_path_applies_rewrite():
    collection = SyncRecordingCollection()
    wrapped = wrap_collection(collection)

    def handler() -> list[str]:
        return wrapped.find(USER_FILTER)

    result = pre_enforce_blocking(
        handler, pdp_client=StubPdp(_permit(OWNER_OBLIGATION)), planner=_planner(), subscription=SUBSCRIPTION
    )

    assert result == ["row"]
    assert collection.received == NARROWED


async def test_async_path_fails_closed_when_shim_not_registered():
    async def handler() -> str:
        return "reached"

    enforce = pre_enforce(
        handler, pdp_client=StubPdp(_permit(OWNER_OBLIGATION)), planner=_planner(), subscription=SUBSCRIPTION
    )
    with pytest.raises(AccessDeniedError):
        await enforce


def test_blocking_path_fails_closed_when_shim_not_registered():
    def handler() -> str:
        return "reached"

    def enforce() -> str:
        return pre_enforce_blocking(
            handler, pdp_client=StubPdp(_permit(OWNER_OBLIGATION)), planner=_planner(), subscription=SUBSCRIPTION
        )

    with pytest.raises(AccessDeniedError):
        enforce()


def test_permit_without_obligation_leaves_filter_unchanged():
    collection = SyncRecordingCollection()
    wrapped = wrap_collection(collection)

    def handler() -> list[str]:
        return wrapped.find(USER_FILTER)

    result = pre_enforce_blocking(
        handler, pdp_client=StubPdp(_permit()), planner=_planner(), subscription=SUBSCRIPTION
    )

    assert result == ["row"]
    assert collection.received == USER_FILTER
