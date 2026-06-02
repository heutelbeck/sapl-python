"""End-to-end transaction rollback through the FastAPI wrapper.

Drives a real FastAPI app (via an in-process ASGI client) whose endpoints write to a
real async sqlite database and are protected by ``@pre_enforce`` / ``@post_enforce``.
Proves the wrapper threads the configured transaction provider into the enforcement
core, so a post-write denial rolls the DB transaction back.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import sapl_fastapi.decorators as decorators
from sapl_base.pep import OUTPUT, EnforcementPlanner, ScopedHandler
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_fastapi.decorators import post_enforce, pre_enforce

FAIL_OUTPUT = {"type": "failOutput"}


class Base(DeclarativeBase):
    pass


class Widget(Base):
    __tablename__ = "widget"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class StubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision


class FailingOutputProvider:
    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if isinstance(constraint, dict) and constraint.get("type") == "failOutput":
            def _raise(value: Any) -> None:
                raise RuntimeError("output obligation handler failed")

            return [ScopedHandler(signal=OUTPUT, priority=0, shape="consumer", handler=_raise)]
        return []


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/fastapi.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(Widget)) or 0


def _build_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()

    @app.get("/post/{name}")
    @post_enforce(action="write", resource="widget")
    async def post_write(name: str) -> dict[str, str]:
        session.add(Widget(name=name))
        return {"name": name}

    @app.get("/pre/{name}")
    @pre_enforce(action="write", resource="widget")
    async def pre_write(name: str) -> dict[str, str]:
        session.add(Widget(name=name))
        return {"name": name}

    return app


def _wire(monkeypatch, decision: AuthorizationDecision, session: AsyncSession, *, failing: bool) -> None:
    providers = (FailingOutputProvider(),) if failing else ()
    monkeypatch.setattr(decorators, "get_pdp_client", lambda: StubPdp(decision))
    monkeypatch.setattr(decorators, "get_planner", lambda: EnforcementPlanner(providers=providers))
    monkeypatch.setattr(decorators, "get_transaction_provider", lambda: (lambda: session.begin()))


async def _call(app: FastAPI, path: str) -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_post_enforce_permit_commits(monkeypatch, session_factory):
    async with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.PERMIT), session, failing=False)
        resp = await _call(_build_app(session), "/post/x")
    assert resp.status_code == 200
    assert await _count(session_factory) == 1


async def test_post_enforce_deny_rolls_back(monkeypatch, session_factory):
    async with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.DENY), session, failing=False)
        resp = await _call(_build_app(session), "/post/x")
    assert resp.status_code == 403
    assert await _count(session_factory) == 0


async def test_post_enforce_output_obligation_failure_rolls_back(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    async with session_factory() as session:
        _wire(monkeypatch, decision, session, failing=True)
        resp = await _call(_build_app(session), "/post/x")
    assert resp.status_code == 403
    assert await _count(session_factory) == 0


async def test_pre_enforce_output_obligation_failure_rolls_back(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    async with session_factory() as session:
        _wire(monkeypatch, decision, session, failing=True)
        resp = await _call(_build_app(session), "/pre/x")
    assert resp.status_code == 403
    assert await _count(session_factory) == 0
