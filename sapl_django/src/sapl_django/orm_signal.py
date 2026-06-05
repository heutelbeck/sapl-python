"""DJANGO_QUERY signal kind and signal dataclass.

DJANGO_QUERY fires on every ``SQLCompiler.execute_sql``, the single point all ORM queries
pass through. One hook on the base compiler covers reads and writes (UPDATE/DELETE
row-selection), since the write compilers either inherit ``execute_sql`` or call
``super().execute_sql``. The payload is the structured ``django.db.models.sql.query.Query``
of the executing query, manipulable through Django's ``Q`` and where API without parsing or
building SQL strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sapl_base.pep.signal import SignalKind

DJANGO_QUERY: SignalKind = SignalKind("django_orm_query", data_carrying=True)


@dataclass(frozen=True, slots=True)
class DjangoQuerySignal:
    value: Any
    kind: SignalKind = DJANGO_QUERY
