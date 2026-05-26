from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import event, false, select, text
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker

from sapl_base.pep import DROP, AccessDeniedError, EnforcementPlan, PlanEntry
from sapl_base.pep.request_context import reset_current_plan, set_current_plan

from sapl_sqlalchemy import (
    SQL_QUERY,
    register_orm_listener,
    unregister_orm_listener,
)
from sapl_sqlalchemy.shim import _sapl_listener

from tests.models import Patient


def _mapper_plan(mapper: Any, *, priority: int = 30) -> EnforcementPlan:
    return EnforcementPlan(
        {
            SQL_QUERY: (
                PlanEntry(
                    signal=SQL_QUERY,
                    priority=priority,
                    shape="mapper",
                    tag="obligation",
                    constraint={},
                    handler=mapper,
                ),
            )
        }
    )


def _empty_plan() -> EnforcementPlan:
    return EnforcementPlan({})


def _add_tenant_predicate(stmt: Any) -> Any:
    return stmt.where(text("tenant_id = 1"))


@pytest.fixture(autouse=True)
def _listener_isolation() -> Iterator[None]:
    register_orm_listener(Session)
    try:
        yield
    finally:
        unregister_orm_listener(Session)


def _with_plan(plan: EnforcementPlan | None):
    token = set_current_plan(plan)
    return token


def test_no_plan_does_not_rewrite(
    session: Session, emitted_sql: list[str]
) -> None:
    session.execute(select(Patient))
    assert any("FROM patient" in s for s in emitted_sql)
    assert not any("tenant_id = 1" in s for s in emitted_sql)


def test_plan_without_sql_query_entries_does_not_rewrite(
    session: Session, emitted_sql: list[str]
) -> None:
    token = _with_plan(_empty_plan())
    try:
        session.execute(select(Patient))
    finally:
        reset_current_plan(token)
    assert not any("tenant_id = 1" in s for s in emitted_sql)


def test_mapper_rewrites_statement(
    session: Session, emitted_sql: list[str]
) -> None:
    token = _with_plan(_mapper_plan(_add_tenant_predicate))
    try:
        session.execute(select(Patient))
    finally:
        reset_current_plan(token)
    assert any("tenant_id = 1" in s for s in emitted_sql)


def test_handler_raises_yields_obligation_failure(session: Session) -> None:
    def _raises(_: Any) -> Any:
        raise RuntimeError("boom")

    token = _with_plan(_mapper_plan(_raises))
    try:
        with pytest.raises(AccessDeniedError) as exc:
            session.execute(select(Patient))
        assert exc.value.reason == "SQL_QUERY_OBLIGATION_FAILURE"
    finally:
        reset_current_plan(token)


def test_handler_returning_drop_yields_invalid_return(session: Session) -> None:
    def _returns_drop(_: Any) -> Any:
        return DROP

    token = _with_plan(_mapper_plan(_returns_drop))
    try:
        with pytest.raises(AccessDeniedError) as exc:
            session.execute(select(Patient))
        assert exc.value.reason == "SQL_QUERY_INVALID_RETURN"
    finally:
        reset_current_plan(token)


def test_where_false_yields_zero_rows(session: Session) -> None:
    session.add(Patient(id=1, tenant_id=1, name="alice"))
    session.commit()

    def _no_rows(stmt: Any) -> Any:
        return stmt.where(false())

    token = _with_plan(_mapper_plan(_no_rows))
    try:
        result = session.execute(select(Patient)).scalars().all()
    finally:
        reset_current_plan(token)
    assert result == []


def test_best_effort_discharge_with_one_failing_mapper(session: Session) -> None:
    def _ok(stmt: Any) -> Any:
        return stmt.where(text("status = 'active'"))

    def _fails(_: Any) -> Any:
        raise RuntimeError("boom")

    plan = EnforcementPlan(
        {
            SQL_QUERY: (
                PlanEntry(
                    signal=SQL_QUERY, priority=30, shape="mapper",
                    tag="obligation", constraint={}, handler=_ok,
                ),
                PlanEntry(
                    signal=SQL_QUERY, priority=40, shape="mapper",
                    tag="obligation", constraint={}, handler=_fails,
                ),
            )
        }
    )
    token = _with_plan(plan)
    try:
        with pytest.raises(AccessDeniedError) as exc:
            session.execute(select(Patient))
        assert exc.value.reason == "SQL_QUERY_OBLIGATION_FAILURE"
    finally:
        reset_current_plan(token)


def test_default_ordering_runs_sapl_listener_first(session: Session) -> None:
    seen_by_second: list[Any] = []

    def _second(state: ORMExecuteState) -> None:
        seen_by_second.append(state.statement)

    event.listen(Session, "do_orm_execute", _second)
    try:
        token = _with_plan(_mapper_plan(_add_tenant_predicate))
        try:
            session.execute(select(Patient))
        finally:
            reset_current_plan(token)
        assert "tenant_id = 1" in str(seen_by_second[0])
    finally:
        event.remove(Session, "do_orm_execute", _second)


def test_order_last_runs_after_other_listeners(
    session: Session, emitted_sql: list[str]
) -> None:
    unregister_orm_listener(Session)

    seen_by_first: list[Any] = []

    def _first(state: ORMExecuteState) -> None:
        seen_by_first.append(state.statement)

    event.listen(Session, "do_orm_execute", _first)
    register_orm_listener(Session, order="last")
    try:
        token = _with_plan(_mapper_plan(_add_tenant_predicate))
        try:
            session.execute(select(Patient))
        finally:
            reset_current_plan(token)
        assert "tenant_id = 1" not in str(seen_by_first[0])
        assert any("tenant_id = 1" in s for s in emitted_sql)
    finally:
        event.remove(Session, "do_orm_execute", _first)


def test_identity_return_does_not_reassign(
    session: Session, emitted_sql: list[str]
) -> None:
    def _identity(stmt: Any) -> Any:
        return stmt

    token = _with_plan(_mapper_plan(_identity))
    try:
        session.execute(select(Patient))
    finally:
        reset_current_plan(token)
    assert any("FROM patient" in s for s in emitted_sql)


def test_idempotent_registration(session: Session, emitted_sql: list[str]) -> None:
    register_orm_listener(Session)
    register_orm_listener(Session)
    token = _with_plan(_mapper_plan(_add_tenant_predicate))
    try:
        session.execute(select(Patient))
    finally:
        reset_current_plan(token)
    rewritten = [s for s in emitted_sql if "tenant_id = 1" in s]
    assert len(rewritten) == 1


def test_core_level_execute_bypass_is_not_intercepted(
    engine: Any, emitted_sql: list[str]
) -> None:
    token = _with_plan(_mapper_plan(_add_tenant_predicate))
    try:
        with engine.connect() as conn:
            conn.execute(select(Patient))
    finally:
        reset_current_plan(token)
    assert any("FROM patient" in s for s in emitted_sql)
    assert not any("tenant_id = 1" in s for s in emitted_sql)
