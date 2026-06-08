"""Collection proxies that fire MONGO_QUERY on query-issuing calls.

PyMongo exposes no mutating query hook (its monitoring API is observe-only), so
the cut point is a proxy over the collection's query methods. Each wrapped method
reads the active EnforcementPlan from the request context, discharges MONGO_QUERY
with the structured query (a filter Mapping or a pipeline list), and delegates to
the underlying driver with the handler's returned query. With the logging provider
the query is returned unchanged.

`register_mongo_shim` advertises MONGO_QUERY to the planner so `pre_enforce`
schedules a matching ``mongo:queryRewriting`` obligation onto this shim instead
of failing it closed as inadmissible. The proxies are duck-typed over the
collection method surface and do not import pymongo: a synchronous proxy backs the
blocking PEP path (Flask, sync Django) and an asynchronous proxy backs the async
path (FastAPI, Tornado, async Django).
"""

from __future__ import annotations

from typing import Any

from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.plan import ABSENT
from sapl_base.pep.request_context import current_plan
from sapl_base.pep.shim_signals import register_shim_signal, unregister_shim_signal
from sapl_pymongo.signal import MONGO_QUERY, MongoQuerySignal


def register_mongo_shim() -> None:
    """Advertise MONGO_QUERY as a supported signal. Idempotent."""
    register_shim_signal(MONGO_QUERY)


def unregister_mongo_shim() -> None:
    """Withdraw MONGO_QUERY. Idempotent."""
    unregister_shim_signal(MONGO_QUERY)


def _discharge(query: Any, operation: str) -> Any:
    plan = current_plan()
    if plan is None or not plan.has_entries(MONGO_QUERY):
        return query
    result = plan.execute(MongoQuerySignal(value=query, operation=operation))
    if result.failure_state:
        raise AccessDeniedError(
            "Access denied", decision=None, reason="MONGO_QUERY_OBLIGATION_FAILURE"
        )
    if result.value is ABSENT:
        raise AccessDeniedError(
            "Access denied", decision=None, reason="MONGO_QUERY_INVALID_RETURN"
        )
    return result.value


def _intercept(
    operation: str,
    key: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    default: Any = None,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Discharge the query argument named ``key`` (keyword or first positional).

    When neither is present and ``default`` is given, discharge that default so a
    query with no app-supplied filter still receives the obligation's constraints.
    """
    if key in kwargs:
        return args, {**kwargs, key: _discharge(kwargs[key], operation)}
    if args:
        return (_discharge(args[0], operation), *args[1:]), kwargs
    if default is not None:
        return (_discharge(default, operation),), kwargs
    return args, kwargs


class MongoCollectionProxy:
    """Synchronous collection proxy for the blocking PEP path (Flask, sync Django)."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def find(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("find", "filter", args, kwargs, default={})
        return self._collection.find(*args, **kwargs)

    def find_one(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("find_one", "filter", args, kwargs, default={})
        return self._collection.find_one(*args, **kwargs)

    def aggregate(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("aggregate", "pipeline", args, kwargs)
        return self._collection.aggregate(*args, **kwargs)

    def count_documents(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("count_documents", "filter", args, kwargs, default={})
        return self._collection.count_documents(*args, **kwargs)

    def update_one(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("update_one", "filter", args, kwargs)
        return self._collection.update_one(*args, **kwargs)

    def update_many(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("update_many", "filter", args, kwargs)
        return self._collection.update_many(*args, **kwargs)

    def delete_one(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("delete_one", "filter", args, kwargs)
        return self._collection.delete_one(*args, **kwargs)

    def delete_many(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("delete_many", "filter", args, kwargs)
        return self._collection.delete_many(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._collection, name)


class AsyncMongoCollectionProxy:
    """Asynchronous collection proxy for the async PEP path (FastAPI, Tornado, async Django).

    ``find`` returns an AsyncCursor synchronously (iteration is awaited by the
    caller), so it is not a coroutine; the remaining methods are coroutines.
    """

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def find(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("find", "filter", args, kwargs, default={})
        return self._collection.find(*args, **kwargs)

    async def find_one(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("find_one", "filter", args, kwargs, default={})
        return await self._collection.find_one(*args, **kwargs)

    async def aggregate(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("aggregate", "pipeline", args, kwargs)
        return await self._collection.aggregate(*args, **kwargs)

    async def count_documents(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("count_documents", "filter", args, kwargs, default={})
        return await self._collection.count_documents(*args, **kwargs)

    async def update_one(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("update_one", "filter", args, kwargs)
        return await self._collection.update_one(*args, **kwargs)

    async def update_many(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("update_many", "filter", args, kwargs)
        return await self._collection.update_many(*args, **kwargs)

    async def delete_one(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("delete_one", "filter", args, kwargs)
        return await self._collection.delete_one(*args, **kwargs)

    async def delete_many(self, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _intercept("delete_many", "filter", args, kwargs)
        return await self._collection.delete_many(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._collection, name)


def wrap_collection(collection: Any) -> MongoCollectionProxy:
    """Wrap a synchronous pymongo Collection so its queries fire MONGO_QUERY.

    Registers the shim signal, so advertising the capability and installing a cut point
    are inseparable. Wrap collections once at application startup, before any enforcement
    runs, so the planner already admits the obligation when it plans.
    """
    register_mongo_shim()
    return MongoCollectionProxy(collection)


def wrap_async_collection(collection: Any) -> AsyncMongoCollectionProxy:
    """Wrap a pymongo AsyncCollection so its queries fire MONGO_QUERY.

    Registers the shim signal, so advertising the capability and installing a cut point
    are inseparable. Wrap collections once at application startup, before any enforcement
    runs, so the planner already admits the obligation when it plans.
    """
    register_mongo_shim()
    return AsyncMongoCollectionProxy(collection)
