"""End-to-end SQL query manipulation through the FastAPI wrapper and the SQLAlchemy shim.

Proves the whole path: a PDP decision carrying a ``sql:queryManipulation`` obligation,
flowing through ``@pre_enforce`` -> the planner -> ``SqlQueryManipulationProvider`` ->
the registered ORM listener, rewrites a real ``SELECT`` so the database returns only the
authorised rows. Only the PDP is mocked. The database, the query, and the rewrite are real.

This is the integration the prior shim unit tests never exercised: they hand-built the
plan and called the listener directly, bypassing the planner. Here the planner alone
decides whether the obligation is dischargeable, which is the property that must hold.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import sapl_fastapi.decorators as decorators
from sapl_base.pep import EnforcementPlanner
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_fastapi.decorators import pre_enforce
from sapl_sqlalchemy import (
    SqlQueryManipulationProvider,
    register_orm_listener,
    unregister_orm_listener,
)

OWNER_OBLIGATION = {
    "type": "sql:queryManipulation",
    "criteria": [{"column": "owner", "op": "=", "value": "alice"}],
}


class Base(DeclarativeBase):
    pass


class Widget(Base):
    __tablename__ = "widget"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    owner: Mapped[str]


class StubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sqlrewrite.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all(
            [Widget(name="alice-widget", owner="alice"), Widget(name="bob-widget", owner="bob")]
        )
        await session.commit()
    yield maker
    await engine.dispose()


@pytest.fixture
def orm_listener():
    register_orm_listener()
    yield
    unregister_orm_listener()


def _wire(monkeypatch, decision: AuthorizationDecision) -> None:
    monkeypatch.setattr(decorators, "get_pdp_client", lambda: StubPdp(decision))
    monkeypatch.setattr(
        decorators, "get_planner", lambda: EnforcementPlanner(providers=(SqlQueryManipulationProvider(),))
    )
    monkeypatch.setattr(decorators, "get_transaction_provider", lambda: None)


def _build_app(session_factory: async_sessionmaker) -> FastAPI:
    app = FastAPI()

    @app.get("/widgets")
    @pre_enforce(action="read", resource="widget")
    async def list_widgets() -> list[str]:
        async with session_factory() as session:
            result = await session.execute(select(Widget))
            return [w.name for w in result.scalars().all()]

    return app


async def _call(app: FastAPI, path: str) -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_obligation_rewrites_select_to_authorized_rows(monkeypatch, session_factory, orm_listener):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(OWNER_OBLIGATION,))
    _wire(monkeypatch, decision)
    resp = await _call(_build_app(session_factory), "/widgets")
    assert resp.status_code == 200
    assert resp.json() == ["alice-widget"]


async def test_obligation_denied_when_shim_not_registered(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(OWNER_OBLIGATION,))
    _wire(monkeypatch, decision)
    resp = await _call(_build_app(session_factory), "/widgets")
    assert resp.status_code == 403


async def test_permit_without_obligation_returns_all_rows(monkeypatch, session_factory, orm_listener):
    decision = AuthorizationDecision(decision=Decision.PERMIT)
    _wire(monkeypatch, decision)
    resp = await _call(_build_app(session_factory), "/widgets")
    assert resp.status_code == 200
    assert sorted(resp.json()) == ["alice-widget", "bob-widget"]
