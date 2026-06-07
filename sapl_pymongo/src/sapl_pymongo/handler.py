"""Type alias for handlers attached to MONGO_QUERY."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MongoQueryMapper = Callable[[Any], Any]
"""A mapper takes the current Mongo query (a filter Mapping or an aggregation
pipeline list) and returns the transformed query. Returning the DROP sentinel is
undefined; mappers raise to deny."""
