"""SQL_QUERY signal kind and signal dataclass.

`SQL_QUERY` fires once per ORM execute call. The signal payload is the
SQLAlchemy `Executable` extracted from `ORMExecuteState.statement` at
the dispatch site of `Session.execute`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sapl_base.pep.signal import SignalKind

SQL_QUERY: SignalKind = SignalKind("sqlalchemy_sql_query", data_carrying=True)


@dataclass(frozen=True, slots=True)
class SqlQuerySignal:
    value: Any
    kind: SignalKind = SQL_QUERY
