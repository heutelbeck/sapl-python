"""Async-session shim behaviour, driven entirely through the real enforcement path.

``pre_enforce`` is awaited directly with a stubbed PDP decision and real providers;
the protected method runs a real ``AsyncSession`` query. The listener fires on the
sync_session proxy within the same task, so ``current_plan`` is visible. The
concurrency test proves per-coroutine isolation of that context variable.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from tests.models import Base, Patient
from tests.sql_harness import (
    BAD_OPERATOR_OBLIGATION,
    SUBSCRIPTION,
    StubPdp,
    default_providers,
    permit,
    tenant_obligation,
)

from sapl_base.pep import AccessDeniedError, EnforcementPlanner, pre_enforce
from sapl_sqlalchemy import register_orm_listener, unregister_orm_listener

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sapl_base.types import AuthorizationDecision

TENANT_1 = tenant_obligation(1)


@pytest.fixture
async def async_factory(tmp_path) -> AsyncIterator[async_sessionmaker]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/shim_async.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all([Patient(id=1, tenant_id=1, name="alice"), Patient(id=2, tenant_id=2, name="bob")])
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
def _listener_lifecycle() -> Any:
    register_orm_listener(Session)
    yield
    unregister_orm_listener(Session)


async def _enforce(method: Any, decision: AuthorizationDecision) -> Any:
    return await pre_enforce(
        method,
        pdp_client=StubPdp(decision),
        planner=EnforcementPlanner(providers=default_providers()),
        subscription=SUBSCRIPTION,
    )


@pytest.mark.parametrize(
    "decision, expected",
    [(permit(), [1, 2]), (permit(TENANT_1), [1])],
    ids=["no-obligation", "tenant-filter"],
)
async def test_async_permitted_query_returns_expected_rows(
    async_factory: async_sessionmaker, decision: AuthorizationDecision, expected: list[int]
) -> None:
    async def _method() -> list[int]:
        async with async_factory() as session:
            result = await session.execute(select(Patient))
            return sorted(p.tenant_id for p in result.scalars().all())

    assert await _enforce(_method, decision) == expected


async def test_async_provider_mapper_raises_denies(async_factory: async_sessionmaker) -> None:
    async def _method() -> Any:
        async with async_factory() as session:
            return (await session.execute(select(Patient))).scalars().all()

    with pytest.raises(AccessDeniedError) as exc:
        await _enforce(_method, permit(BAD_OPERATOR_OBLIGATION))
    assert exc.value.reason == "SQL_QUERY_OBLIGATION_FAILURE"


async def test_async_concurrency_isolation_between_coroutines(async_factory: async_sessionmaker) -> None:
    async def _enforced(tenant: int) -> list[int]:
        async def _method() -> list[int]:
            async with async_factory() as session:
                result = await session.execute(select(Patient))
                return sorted(p.tenant_id for p in result.scalars().all())

        return await _enforce(_method, permit(tenant_obligation(tenant)))

    rows_one, rows_two = await asyncio.gather(_enforced(1), _enforced(2))
    assert rows_one == [1]
    assert rows_two == [2]
