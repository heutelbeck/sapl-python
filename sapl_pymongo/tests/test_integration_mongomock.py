"""End-to-end integration: one endpoint, different obligations, different results.

A real (in-memory mongomock) collection is wrapped once at "startup" and queried by an
application endpoint that lists the owners of the widgets it returns. The endpoint code is
fixed; only the PDP decision changes between cases. Each mongo:queryRewriting obligation
rewrites the filter the driver executes, so the same endpoint returns a different result set
per obligation. A DENY blocks it entirely.

This proves the whole chain end to end: decision obligation -> planner -> provider ->
shim cut point -> rewritten filter -> mongomock query execution -> narrowed result. Only
the PDP is mocked; the query and its execution against stored documents are real.

The blocking path (pre_enforce_blocking) backs Flask and sync Django. The async path's
rewrite is pinned in test_shim_wiring; mongomock has no async driver, so real-data
execution is proven once here on the path mongomock supports.
"""

from __future__ import annotations

from typing import Any

import mongomock
import pytest

from sapl_base.pep import EnforcementPlanner
from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.enforce import pre_enforce_blocking
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_pymongo import MongoDbQueryRewritingProvider, unregister_mongo_shim, wrap_collection

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


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    unregister_mongo_shim()


@pytest.fixture
def widgets():
    collection = mongomock.MongoClient().db.widgets
    collection.insert_many([dict(document) for document in DOCUMENTS])
    return wrap_collection(collection)


def _list_owners(widgets: Any) -> list[str]:
    """The application endpoint: returns the owners of the widgets the caller may see."""
    return sorted(document["owner"] for document in widgets.find({}))


def _run(widgets: Any, decision: AuthorizationDecision) -> list[str]:
    return pre_enforce_blocking(
        lambda: _list_owners(widgets),
        pdp_client=StubPdp(decision),
        planner=EnforcementPlanner(providers=(MongoDbQueryRewritingProvider(),)),
        subscription=SUBSCRIPTION,
    )


def _permit(obligation: dict[str, Any] | None = None) -> AuthorizationDecision:
    obligations = (obligation,) if obligation is not None else ()
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=obligations)


def test_permit_without_obligation_returns_all_owners(widgets):
    assert _run(widgets, _permit()) == ["alice", "alice", "bob"]


def test_owner_criteria_narrows_to_alice(widgets):
    obligation = {"type": TYPE, "criteria": [{"column": "owner", "op": "=", "value": "alice"}]}
    assert _run(widgets, _permit(obligation)) == ["alice", "alice"]


def test_tenant_criteria_narrows_to_tenant_one(widgets):
    obligation = {"type": TYPE, "criteria": [{"column": "tenant", "op": "=", "value": 1}]}
    assert _run(widgets, _permit(obligation)) == ["alice", "bob"]


def test_status_via_string_condition_narrows_to_active(widgets):
    obligation = {"type": TYPE, "conditions": ['{"status": "active"}']}
    assert _run(widgets, _permit(obligation)) == ["alice", "bob"]


def test_combined_criteria_narrows_to_single_document(widgets):
    obligation = {
        "type": TYPE,
        "criteria": [{"column": "owner", "op": "=", "value": "alice"}, {"column": "status", "op": "=", "value": "active"}],
    }
    assert _run(widgets, _permit(obligation)) == ["alice"]


def test_in_operator_narrows_to_listed_owners(widgets):
    obligation = {"type": TYPE, "criteria": [{"column": "owner", "op": "in", "value": ["bob"]}]}
    assert _run(widgets, _permit(obligation)) == ["bob"]


def test_deny_blocks_the_endpoint(widgets):
    decision = AuthorizationDecision(decision=Decision.DENY)

    def run() -> list[str]:
        return _run(widgets, decision)

    with pytest.raises(AccessDeniedError):
        run()
