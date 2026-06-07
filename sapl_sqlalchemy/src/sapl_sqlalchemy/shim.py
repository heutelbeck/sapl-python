"""SQLAlchemy ORM event listener that fires SQL_QUERY on every ORM execute."""

from __future__ import annotations

from typing import Any, Literal

import structlog
from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

from sapl_base.pep.boundary_signals import AccessDeniedError
from sapl_base.pep.plan import ABSENT
from sapl_base.pep.request_context import current_plan
from sapl_base.pep.shim_signals import register_shim_signal, unregister_shim_signal
from sapl_sqlalchemy.signal import SQL_QUERY, SqlQuerySignal

logger = structlog.get_logger(__name__)


def _sapl_listener(state: ORMExecuteState) -> None:
    plan = current_plan()
    if plan is None or not plan.has_entries(SQL_QUERY):
        return

    result = plan.execute(SqlQuerySignal(value=state.statement))

    if result.failure_state:
        raise AccessDeniedError(
            "Access denied",
            decision=None,
            reason="SQL_QUERY_OBLIGATION_FAILURE",
        )

    if result.value is ABSENT:
        logger.warning(
            "sql_query_handler_returned_drop_invalid",
            note=(
                "DROP is not defined for SQL_QUERY; handlers must "
                "return a statement or raise to deny"
            ),
        )
        raise AccessDeniedError(
            "Access denied",
            decision=None,
            reason="SQL_QUERY_INVALID_RETURN",
        )

    if result.value is not state.statement:
        state.statement = result.value


def register_orm_listener(
    target: Any = Session,
    *,
    order: Literal["first", "last"] = "first",
) -> None:
    """Attach the SAPL listener to a Session class or instance.

    Default target is the Session class, which covers every Session
    instantiated. AsyncSession is not a valid target; register on
    Session and the listener fires for AsyncSession executes via the
    sync_session proxy.

    order="first" prepends so the listener runs before any other
    `do_orm_execute` listener on the same target. Required for correct
    interaction with cache or sharding listeners that derive state
    from the statement. order="last" is an audited escape hatch.

    Idempotent: a second call with the same listener is a no-op.

    Also advertises SQL_QUERY as a supported signal so the planner schedules
    a matching `sql:queryManipulation` obligation onto this shim instead of
    failing it closed as inadmissible.
    """
    register_shim_signal(SQL_QUERY)
    if event.contains(target, "do_orm_execute", _sapl_listener):
        return
    event.listen(
        target,
        "do_orm_execute",
        _sapl_listener,
        insert=(order == "first"),
    )


def unregister_orm_listener(target: Any = Session) -> None:
    unregister_shim_signal(SQL_QUERY)
    if event.contains(target, "do_orm_execute", _sapl_listener):
        event.remove(target, "do_orm_execute", _sapl_listener)
