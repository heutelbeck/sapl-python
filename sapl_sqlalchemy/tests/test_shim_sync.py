"""Sync-session shim behaviour, driven entirely through the real enforcement path.

Each test wires a stubbed PDP decision and real providers into ``pre_enforce`` and
runs a real query inside the protected method. The planner builds the plan; the
registered ``do_orm_execute`` listener reads it via ``current_plan`` and rewrites,
denies, or no-ops. Sync sessions execute inside the per-call ``asyncio.run`` task,
so the ``current_plan`` context variable set by ``pre_enforce`` is visible when the
listener fires.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import ORMExecuteState, Session
from tests.models import Patient
from tests.sql_harness import (
    BAD_OPERATOR_OBLIGATION,
    DROP_OBLIGATION,
    IDENTITY_OBLIGATION,
    SUBSCRIPTION,
    DropMapperProvider,
    IdentityMapperProvider,
    StubPdp,
    default_providers,
    permit,
    tenant_obligation,
)

from sapl_base.pep import AccessDeniedError, EnforcementPlanner, pre_enforce
from sapl_sqlalchemy import register_orm_listener, unregister_orm_listener

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sapl_base.types import AuthorizationDecision

TENANT_1 = tenant_obligation(1)
TENANT_2 = tenant_obligation(2)
NO_MATCH = tenant_obligation(999)


@pytest.fixture(autouse=True)
def _listener_isolation() -> Iterator[None]:
    register_orm_listener(Session)
    try:
        yield
    finally:
        unregister_orm_listener(Session)


def _enforce(method: Any, decision: AuthorizationDecision, *, providers: Any = None) -> Any:
    async def _run() -> Any:
        return await pre_enforce(
            method,
            pdp_client=StubPdp(decision),
            planner=EnforcementPlanner(providers=providers if providers is not None else default_providers()),
            subscription=SUBSCRIPTION,
        )

    return asyncio.run(_run())


def _seed(session: Session) -> None:
    session.add_all([Patient(id=1, tenant_id=1, name="alice"), Patient(id=2, tenant_id=2, name="bob")])
    session.commit()


@pytest.mark.parametrize(
    "decision, providers, expected",
    [
        (permit(), default_providers(), [1, 2]),
        (permit(TENANT_1), default_providers(), [1]),
        (permit(NO_MATCH), default_providers(), []),
        (permit(IDENTITY_OBLIGATION), (IdentityMapperProvider(),), [1, 2]),
    ],
    ids=["no-obligation", "tenant-filter", "filter-matches-nothing", "identity-mapper-no-rewrite"],
)
def test_permitted_query_returns_expected_rows(
    session: Session, decision: AuthorizationDecision, providers: Any, expected: list[int]
) -> None:
    _seed(session)

    async def _method() -> list[int]:
        return sorted(p.tenant_id for p in session.execute(select(Patient)).scalars().all())

    assert _enforce(_method, decision, providers=providers) == expected


@pytest.mark.parametrize(
    "decision, providers, reason",
    [
        (permit(BAD_OPERATOR_OBLIGATION), default_providers(), "SQL_QUERY_OBLIGATION_FAILURE"),
        (permit(DROP_OBLIGATION), (DropMapperProvider(),), "SQL_QUERY_INVALID_RETURN"),
    ],
    ids=["provider-mapper-raises", "mapper-returns-drop"],
)
def test_query_time_obligation_failure_denies(
    session: Session, decision: AuthorizationDecision, providers: Any, reason: str
) -> None:
    async def _method() -> Any:
        return session.execute(select(Patient)).scalars().all()

    with pytest.raises(AccessDeniedError) as exc:
        _enforce(_method, decision, providers=providers)
    assert exc.value.reason == reason


def test_two_sql_obligations_deny_before_method_as_non_commuting(session: Session) -> None:
    ran: list[bool] = []

    async def _method() -> Any:
        ran.append(True)
        return session.execute(select(Patient)).scalars().all()

    with pytest.raises(AccessDeniedError) as exc:
        _enforce(_method, permit(TENANT_1, TENANT_2))
    assert exc.value.reason == "OBLIGATION_FAILURE"
    assert ran == []


def test_sapl_listener_runs_before_later_listeners(session: Session) -> None:
    seen: list[Any] = []

    def _second(state: ORMExecuteState) -> None:
        seen.append(state.statement)

    event.listen(Session, "do_orm_execute", _second)
    try:

        async def _method() -> Any:
            return session.execute(select(Patient)).scalars().all()

        _enforce(_method, permit(TENANT_1))
        assert "WHERE" in str(seen[0])
    finally:
        event.remove(Session, "do_orm_execute", _second)


def test_order_last_runs_after_other_listeners(session: Session, emitted_sql: list[str]) -> None:
    unregister_orm_listener(Session)
    seen_first: list[Any] = []

    def _first(state: ORMExecuteState) -> None:
        seen_first.append(state.statement)

    event.listen(Session, "do_orm_execute", _first)
    register_orm_listener(Session, order="last")
    try:

        async def _method() -> Any:
            return session.execute(select(Patient)).scalars().all()

        _enforce(_method, permit(TENANT_1))
        assert "WHERE" not in str(seen_first[0])
        assert any("WHERE tenant_id" in s for s in emitted_sql)
    finally:
        event.remove(Session, "do_orm_execute", _first)


def test_idempotent_registration_applies_rewrite_once(session: Session, emitted_sql: list[str]) -> None:
    register_orm_listener(Session)
    register_orm_listener(Session)

    async def _method() -> Any:
        return session.execute(select(Patient)).scalars().all()

    _enforce(_method, permit(TENANT_1))
    assert len([s for s in emitted_sql if "WHERE tenant_id" in s]) == 1


def test_core_level_execute_is_not_intercepted(engine: Any, emitted_sql: list[str]) -> None:
    async def _method() -> None:
        with engine.connect() as conn:
            conn.execute(select(Patient))

    _enforce(_method, permit(TENANT_1))
    assert any("FROM patient" in s for s in emitted_sql)
    assert not any("WHERE tenant_id" in s for s in emitted_sql)
