from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from sapl_base.pep import AccessDeniedError, EnforcementPlan, PlanEntry
from sapl_base.pep.request_context import reset_current_plan, set_current_plan

from sapl_sqlalchemy import (
    SQL_QUERY,
    register_orm_listener,
    unregister_orm_listener,
)

from tests.models import Base, Patient


def _mapper_plan(mapper: Any) -> EnforcementPlan:
    return EnforcementPlan(
        {
            SQL_QUERY: (
                PlanEntry(
                    signal=SQL_QUERY,
                    priority=30,
                    shape="mapper",
                    tag="obligation",
                    constraint={},
                    handler=mapper,
                ),
            )
        }
    )


@pytest.fixture
async def async_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(
    async_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def emitted_async_sql(async_engine: AsyncEngine) -> Any:
    statements: list[str] = []
    sync_engine = async_engine.sync_engine

    def _capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _capture)
    yield statements
    event.remove(sync_engine, "before_cursor_execute", _capture)


@pytest.fixture(autouse=True)
def _listener_lifecycle() -> Any:
    register_orm_listener(Session)
    yield
    unregister_orm_listener(Session)


def _add_tenant_predicate(stmt: Any) -> Any:
    return stmt.where(text("tenant_id = 1"))


async def test_async_happy_path_rewrites_statement(
    async_session: AsyncSession, emitted_async_sql: list[str]
) -> None:
    token = set_current_plan(_mapper_plan(_add_tenant_predicate))
    try:
        await async_session.execute(select(Patient))
    finally:
        reset_current_plan(token)
    assert any("tenant_id = 1" in s for s in emitted_async_sql)


async def test_async_no_plan_does_not_rewrite(
    async_session: AsyncSession, emitted_async_sql: list[str]
) -> None:
    await async_session.execute(select(Patient))
    assert any("FROM patient" in s for s in emitted_async_sql)
    assert not any("tenant_id = 1" in s for s in emitted_async_sql)


async def test_async_handler_raises_propagates_access_denied(
    async_session: AsyncSession,
) -> None:
    def _raises(_: Any) -> Any:
        raise RuntimeError("boom")

    token = set_current_plan(_mapper_plan(_raises))
    try:
        with pytest.raises(AccessDeniedError) as exc:
            await async_session.execute(select(Patient))
        assert exc.value.reason == "SQL_QUERY_OBLIGATION_FAILURE"
    finally:
        reset_current_plan(token)


async def test_async_concurrency_isolation_between_coroutines(
    async_engine: AsyncEngine, emitted_async_sql: list[str]
) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    barrier = asyncio.Event()

    async def _run_with_tenant(tenant_id: int) -> None:
        def _predicate(stmt: Any) -> Any:
            return stmt.where(text(f"tenant_id = {tenant_id}"))

        token = set_current_plan(_mapper_plan(_predicate))
        try:
            await barrier.wait()
            async with factory() as session:
                await session.execute(select(Patient))
        finally:
            reset_current_plan(token)

    task_a = asyncio.create_task(_run_with_tenant(1))
    task_b = asyncio.create_task(_run_with_tenant(2))
    await asyncio.sleep(0)
    barrier.set()
    await asyncio.gather(task_a, task_b)

    has_one = any("tenant_id = 1" in s for s in emitted_async_sql)
    has_two = any("tenant_id = 2" in s for s in emitted_async_sql)
    assert has_one and has_two
