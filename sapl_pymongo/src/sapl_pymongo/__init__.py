"""SAPL signal source for PyMongo collection queries."""

from sapl_pymongo.handler import MongoQueryMapper
from sapl_pymongo.providers import MongoDbQueryRewritingProvider
from sapl_pymongo.shim import (
    AsyncMongoCollectionProxy,
    MongoCollectionProxy,
    register_mongo_shim,
    unregister_mongo_shim,
    wrap_async_collection,
    wrap_collection,
)
from sapl_pymongo.signal import MONGO_QUERY, MongoQuerySignal

__all__ = [
    "MONGO_QUERY",
    "AsyncMongoCollectionProxy",
    "MongoCollectionProxy",
    "MongoDbQueryRewritingProvider",
    "MongoQueryMapper",
    "MongoQuerySignal",
    "register_mongo_shim",
    "unregister_mongo_shim",
    "wrap_async_collection",
    "wrap_collection",
]
