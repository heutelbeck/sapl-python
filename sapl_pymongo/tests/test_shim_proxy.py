"""Unit coverage for the collection proxies and the discharge mechanics.

These drive the sync and async proxies directly with a plan installed in the request
context (no full enforcement), so every wrapped method, the keyword/positional/default
argument paths, the no-plan and empty-plan passthroughs, the obligation-failure and
DROP fail-closed branches, and attribute delegation are all exercised in isolation.
"""

from __future__ import annotations

from typing import Any

import pytest
from sapl_pymongo.shim import AsyncMongoCollectionProxy, MongoCollectionProxy
from sapl_pymongo.signal import MONGO_QUERY

from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.plan import DROP, EnforcementPlan, PlanEntry
from sapl_base.pep.request_context import reset_current_plan, set_current_plan


def _plan(handler: Any) -> EnforcementPlan:
    entry = PlanEntry(
        signal=MONGO_QUERY, priority=30, shape="mapper", tag="obligation", constraint={}, handler=handler
    )
    return EnforcementPlan({MONGO_QUERY: (entry,)})


@pytest.fixture
def plan_ctx():
    token = set_current_plan(_plan(lambda query: {"__rewritten__": query}))
    yield
    reset_current_plan(token)


class _Recorder:
    def __init__(self) -> None:
        self.last: Any = None
        self.plain = "passthrough"

    def _record(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        self.last = (name, args[0] if args else kwargs.get("filter", kwargs.get("pipeline")))
        return f"{name}-result"


class SyncStub(_Recorder):
    def find(self, *args: Any, **kwargs: Any) -> str:
        return self._record("find", args, kwargs)

    def find_one(self, *args: Any, **kwargs: Any) -> str:
        return self._record("find_one", args, kwargs)

    def aggregate(self, *args: Any, **kwargs: Any) -> str:
        return self._record("aggregate", args, kwargs)

    def count_documents(self, *args: Any, **kwargs: Any) -> str:
        return self._record("count_documents", args, kwargs)

    def update_one(self, *args: Any, **kwargs: Any) -> str:
        return self._record("update_one", args, kwargs)

    def update_many(self, *args: Any, **kwargs: Any) -> str:
        return self._record("update_many", args, kwargs)

    def delete_one(self, *args: Any, **kwargs: Any) -> str:
        return self._record("delete_one", args, kwargs)

    def delete_many(self, *args: Any, **kwargs: Any) -> str:
        return self._record("delete_many", args, kwargs)


class AsyncStub(_Recorder):
    def find(self, *args: Any, **kwargs: Any) -> str:
        return self._record("find", args, kwargs)

    async def find_one(self, *args: Any, **kwargs: Any) -> str:
        return self._record("find_one", args, kwargs)

    async def aggregate(self, *args: Any, **kwargs: Any) -> str:
        return self._record("aggregate", args, kwargs)

    async def count_documents(self, *args: Any, **kwargs: Any) -> str:
        return self._record("count_documents", args, kwargs)

    async def update_one(self, *args: Any, **kwargs: Any) -> str:
        return self._record("update_one", args, kwargs)

    async def update_many(self, *args: Any, **kwargs: Any) -> str:
        return self._record("update_many", args, kwargs)

    async def delete_one(self, *args: Any, **kwargs: Any) -> str:
        return self._record("delete_one", args, kwargs)

    async def delete_many(self, *args: Any, **kwargs: Any) -> str:
        return self._record("delete_many", args, kwargs)


@pytest.mark.parametrize(
    ("invoke", "name", "query"),
    [
        (lambda p: p.find({"a": 1}), "find", {"a": 1}),
        (lambda p: p.find_one({"a": 1}), "find_one", {"a": 1}),
        (lambda p: p.aggregate([{"a": 1}]), "aggregate", [{"a": 1}]),
        (lambda p: p.count_documents({"a": 1}), "count_documents", {"a": 1}),
        (lambda p: p.update_one({"a": 1}, {"$set": {}}), "update_one", {"a": 1}),
        (lambda p: p.update_many({"a": 1}, {"$set": {}}), "update_many", {"a": 1}),
        (lambda p: p.delete_one({"a": 1}), "delete_one", {"a": 1}),
        (lambda p: p.delete_many({"a": 1}), "delete_many", {"a": 1}),
    ],
)
def test_sync_methods_discharge_and_delegate(plan_ctx, invoke, name, query):
    stub = SyncStub()
    result = invoke(MongoCollectionProxy(stub))
    assert result == f"{name}-result"
    assert stub.last == (name, {"__rewritten__": query})


async def test_async_methods_discharge_and_delegate(plan_ctx):
    stub = AsyncStub()
    proxy = AsyncMongoCollectionProxy(stub)

    proxy.find({"a": 1})
    assert stub.last == ("find", {"__rewritten__": {"a": 1}})
    await proxy.find_one({"a": 1})
    assert stub.last == ("find_one", {"__rewritten__": {"a": 1}})
    await proxy.aggregate([{"a": 1}])
    assert stub.last == ("aggregate", {"__rewritten__": [{"a": 1}]})
    await proxy.count_documents({"a": 1})
    assert stub.last == ("count_documents", {"__rewritten__": {"a": 1}})
    await proxy.update_one({"a": 1}, {"$set": {}})
    assert stub.last == ("update_one", {"__rewritten__": {"a": 1}})
    await proxy.update_many({"a": 1}, {"$set": {}})
    assert stub.last == ("update_many", {"__rewritten__": {"a": 1}})
    await proxy.delete_one({"a": 1})
    assert stub.last == ("delete_one", {"__rewritten__": {"a": 1}})
    await proxy.delete_many({"a": 1})
    assert stub.last == ("delete_many", {"__rewritten__": {"a": 1}})


def test_keyword_filter_argument_is_discharged(plan_ctx):
    stub = SyncStub()
    MongoCollectionProxy(stub).find(filter={"a": 1})
    assert stub.last == ("find", {"__rewritten__": {"a": 1}})


def test_absent_filter_defaults_to_empty_then_discharged(plan_ctx):
    stub = SyncStub()
    MongoCollectionProxy(stub).find()
    assert stub.last == ("find", {"__rewritten__": {}})


def test_absent_pipeline_without_default_passes_through(plan_ctx):
    stub = SyncStub()
    MongoCollectionProxy(stub).aggregate()
    assert stub.last == ("aggregate", None)


def test_no_active_plan_passes_query_through_unchanged():
    stub = SyncStub()
    MongoCollectionProxy(stub).find({"a": 1})
    assert stub.last == ("find", {"a": 1})


def test_plan_without_mongo_query_entries_passes_through():
    token = set_current_plan(EnforcementPlan({}))
    try:
        stub = SyncStub()
        MongoCollectionProxy(stub).find({"a": 1})
        assert stub.last == ("find", {"a": 1})
    finally:
        reset_current_plan(token)


def test_obligation_handler_failure_fails_closed():
    def boom(query: Any) -> Any:
        raise RuntimeError("handler failed")

    token = set_current_plan(_plan(boom))
    try:
        proxy = MongoCollectionProxy(SyncStub())
        with pytest.raises(AccessDeniedError):
            proxy.find({"a": 1})
    finally:
        reset_current_plan(token)


def test_handler_dropping_the_query_fails_closed():
    token = set_current_plan(_plan(lambda query: DROP))
    try:
        proxy = MongoCollectionProxy(SyncStub())
        with pytest.raises(AccessDeniedError):
            proxy.find({"a": 1})
    finally:
        reset_current_plan(token)


def test_unwrapped_attribute_delegates_to_collection():
    assert MongoCollectionProxy(SyncStub()).plain == "passthrough"
    assert AsyncMongoCollectionProxy(SyncStub()).plain == "passthrough"
