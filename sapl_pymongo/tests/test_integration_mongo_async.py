"""Async end-to-end integration against a real MongoDB via testcontainers.

Closes the gap the mongomock integration cannot reach: mongomock has no async driver, so
this proves the async proxy plus a real ``AsyncMongoClient`` narrow stored documents per
obligation on the async enforcement path (FastAPI, Tornado, async Django). Only the PDP is
mocked; the query and its execution against a real mongod are real.

Skips cleanly when Docker or testcontainers is unavailable, so it runs in CI (the public
mongo image is pullable) and on developer machines with Docker, and is skipped otherwise.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from pymongo import AsyncMongoClient

from sapl_base.pep import EnforcementPlanner
from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.enforce import pre_enforce
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_pymongo import MongoDbQueryRewritingProvider, unregister_mongo_shim, wrap_async_collection

try:
    from testcontainers.mongodb import MongoDbContainer
except ImportError:
    MongoDbContainer = None

DOCUMENTS = [
    {"_id": 1, "owner": "alice", "tenant": 1, "status": "active"},
    {"_id": 2, "owner": "bob", "tenant": 1, "status": "active"},
    {"_id": 3, "owner": "alice", "tenant": 2, "status": "archived"},
]

TYPE = "mongo:queryRewriting"
SUBSCRIPTION = AuthorizationSubscription(subject="u", action="read", resource="widget")


class StubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision


@pytest.fixture(scope="module")
def mongo_url():
    if MongoDbContainer is None:
        pytest.skip("testcontainers not installed")
    try:
        container = MongoDbContainer("mongo:7")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker/MongoDB container unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    unregister_mongo_shim()


@pytest_asyncio.fixture
async def widgets(mongo_url):
    client: AsyncMongoClient[Any] = AsyncMongoClient(mongo_url)
    collection = client.get_database("test").get_collection("widgets")
    await collection.delete_many({})
    await collection.insert_many([dict(document) for document in DOCUMENTS])
    yield wrap_async_collection(collection)
    await collection.delete_many({})
    await client.close()


async def _list_owners(widgets: Any) -> list[str]:
    return sorted([document["owner"] async for document in widgets.find({})])


async def _run(widgets: Any, decision: AuthorizationDecision) -> list[str]:
    async def endpoint() -> list[str]:
        return await _list_owners(widgets)

    return await pre_enforce(
        endpoint,
        pdp_client=StubPdp(decision),
        planner=EnforcementPlanner(providers=(MongoDbQueryRewritingProvider(),)),
        subscription=SUBSCRIPTION,
    )


def _permit(obligation: dict[str, Any] | None = None) -> AuthorizationDecision:
    obligations = (obligation,) if obligation is not None else ()
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=obligations)


async def test_permit_without_obligation_returns_all_owners(widgets):
    assert await _run(widgets, _permit()) == ["alice", "alice", "bob"]


async def test_owner_criteria_narrows_to_alice(widgets):
    obligation = {"type": TYPE, "criteria": [{"column": "owner", "op": "=", "value": "alice"}]}
    assert await _run(widgets, _permit(obligation)) == ["alice", "alice"]


async def test_string_condition_narrows_to_active(widgets):
    obligation = {"type": TYPE, "conditions": ['{"status": "active"}']}
    assert await _run(widgets, _permit(obligation)) == ["alice", "bob"]


async def test_deny_blocks_the_endpoint(widgets):
    decision = AuthorizationDecision(decision=Decision.DENY)

    async def run() -> list[str]:
        return await _run(widgets, decision)

    with pytest.raises(AccessDeniedError):
        await run()
