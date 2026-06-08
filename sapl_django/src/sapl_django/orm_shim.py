"""Django ORM cut point: a ``SQLCompiler.execute_sql`` hook that fires DJANGO_QUERY.

Django has no structured global execute hook like SQLAlchemy's ``do_orm_execute``. The
single universal point every query passes through is ``SQLCompiler.execute_sql``: all reads
(iteration, ``values``, ``count``, ``exists``, ``aggregate``) compile and run there, deletes
and aggregates inherit it, and updates reach it through ``SQLUpdateCompiler``'s
``super().execute_sql`` call. So one hook on the base compiler covers reads and writes, sync
and async (async queries run the same compiler in a ``sync_to_async`` worker, which inherits
the ``current_plan`` context). It exposes the structured ``django.db.models.sql.Query``
(``self.query``), manipulable through Django's ``Q`` and where API without touching SQL
strings.

The hook is installed by ``register_orm_listener`` and gated on ``current_plan``, so it is a
no-op for queries outside an enforced call. It advertises DJANGO_QUERY so the planner
schedules a matching ``sql:queryRewriting`` obligation onto this shim instead of failing
it closed as inadmissible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from django.db.models.sql.compiler import SQLCompiler

from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.plan import ABSENT
from sapl_base.pep.request_context import current_plan
from sapl_base.pep.shim_signals import register_shim_signal, unregister_shim_signal
from sapl_django.orm_signal import DJANGO_QUERY, DjangoQuerySignal

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

ERROR_INVALID_RETURN = "DJANGO_QUERY_INVALID_RETURN"
ERROR_OBLIGATION_FAILURE = "DJANGO_QUERY_OBLIGATION_FAILURE"
WARN_DROP_INVALID = (
    "DROP is not defined for DJANGO_QUERY; handlers must return a query or raise to deny"
)

_original_execute_sql: Callable[..., Any] | None = None


def register_orm_listener() -> None:
    """Install the SAPL cut point on ``SQLCompiler.execute_sql`` and advertise DJANGO_QUERY.

    Idempotent. Advertises DJANGO_QUERY so the planner schedules a matching
    ``sql:queryRewriting`` obligation onto this shim instead of failing it closed as
    inadmissible. Call ``unregister_orm_listener`` to withdraw both.
    """
    global _original_execute_sql
    register_shim_signal(DJANGO_QUERY)
    if _original_execute_sql is not None:
        return
    original = SQLCompiler.execute_sql

    def _sapl_execute_sql(self: SQLCompiler, *args: Any, **kwargs: Any) -> Any:
        plan = current_plan()
        if plan is not None and plan.has_entries(DJANGO_QUERY):
            result = plan.execute(DjangoQuerySignal(value=self.query))
            if result.failure_state:
                raise AccessDeniedError("Access denied", decision=None, reason=ERROR_OBLIGATION_FAILURE)
            if result.value is ABSENT:
                logger.warning("django_query_handler_returned_drop_invalid", note=WARN_DROP_INVALID)
                raise AccessDeniedError("Access denied", decision=None, reason=ERROR_INVALID_RETURN)
            if result.value is not self.query:
                self.query = result.value
        return original(self, *args, **kwargs)

    _original_execute_sql = original
    SQLCompiler.execute_sql = _sapl_execute_sql


def unregister_orm_listener() -> None:
    """Remove the cut point and withdraw DJANGO_QUERY. Idempotent."""
    global _original_execute_sql
    unregister_shim_signal(DJANGO_QUERY)
    if _original_execute_sql is None:
        return
    SQLCompiler.execute_sql = _original_execute_sql
    _original_execute_sql = None
