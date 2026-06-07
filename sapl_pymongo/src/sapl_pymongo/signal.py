"""MONGO_QUERY signal kind and signal dataclass.

`MONGO_QUERY` fires once per intercepted query-issuing call on a wrapped
collection. The signal payload is the structured query the driver is about to
execute: a filter Mapping for find / count / update / delete, or a pipeline list
for aggregate. `operation` names the originating call so a handler can lower a
neutral constraint into the right query shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sapl_base.pep.signal import SignalKind

MONGO_QUERY: SignalKind = SignalKind("pymongo_mongo_query", data_carrying=True)


@dataclass(frozen=True, slots=True)
class MongoQuerySignal:
    value: Any
    operation: str = ""
    kind: SignalKind = MONGO_QUERY
