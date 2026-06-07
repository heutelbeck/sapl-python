"""Blocking (sync) enforcement path through the FastAPI decorators.

A sync ``def`` ``@pre_enforce`` / ``@post_enforce`` FastAPI endpoint runs on the
blocking core. The decorator returns a sync wrapper, so FastAPI/Starlette runs it
in its threadpool with no running event loop, letting the blocking core bridge the
PDP decision and run a synchronous SQLAlchemy session. This proves the sync path and
the full sync transaction matrix with a raw sync provider (``session.begin()``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

import sapl_fastapi.decorators as decorators
from sapl_base.pep import OUTPUT, EnforcementPlanner, ScopedHandler
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_fastapi.decorators import post_enforce, pre_enforce

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    engine = create_engine(f"sqlite:///{tmp_path}/fastapi_sync.db")
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    yield maker
    engine.dispose()


def _count(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(Widget)) or 0


def _build_app(session: Session) -> FastAPI:
    app = FastAPI()

    @app.get("/post/{name}")
    @post_enforce(action="write", resource="widget")
    def post_write(name: str) -> dict[str, str]:
        session.add(Widget(name=name))
        return {"name": name}

    @app.get("/pre/{name}")
    @pre_enforce(action="write", resource="widget")
    def pre_write(name: str) -> dict[str, str]:
        session.add(Widget(name=name))
        return {"name": name}

    return app


def _wire(monkeypatch, decision: AuthorizationDecision, session: Session, *, failing: bool) -> None:
    providers = (FailingOutputProvider(),) if failing else ()
    monkeypatch.setattr(decorators, "get_pdp_client", lambda: StubPdp(decision))
    monkeypatch.setattr(decorators, "get_planner", lambda: EnforcementPlanner(providers=providers))
    monkeypatch.setattr(decorators, "get_transaction_provider", lambda: (lambda: session.begin()))


async def _call(app: FastAPI, path: str) -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_blocking_pre_enforce_permit_commits(monkeypatch, session_factory):
    with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.PERMIT), session, failing=False)
        resp = await _call(_build_app(session), "/pre/x")
    assert resp.status_code == 200
    assert _count(session_factory) == 1


async def test_blocking_post_enforce_permit_commits(monkeypatch, session_factory):
    with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.PERMIT), session, failing=False)
        resp = await _call(_build_app(session), "/post/x")
    assert resp.status_code == 200
    assert _count(session_factory) == 1


async def test_blocking_post_enforce_deny_rolls_back(monkeypatch, session_factory):
    with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.DENY), session, failing=False)
        resp = await _call(_build_app(session), "/post/x")
    assert resp.status_code == 403
    assert _count(session_factory) == 0


async def test_blocking_post_enforce_output_failure_rolls_back(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    with session_factory() as session:
        _wire(monkeypatch, decision, session, failing=True)
        resp = await _call(_build_app(session), "/post/x")
    assert resp.status_code == 403
    assert _count(session_factory) == 0


async def test_blocking_pre_enforce_output_failure_rolls_back(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    with session_factory() as session:
        _wire(monkeypatch, decision, session, failing=True)
        resp = await _call(_build_app(session), "/pre/x")
    assert resp.status_code == 403
    assert _count(session_factory) == 0


async def test_blocking_no_transaction_provider_still_commits(monkeypatch, session_factory):
    with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.PERMIT), session, failing=False)
        monkeypatch.setattr(decorators, "get_transaction_provider", lambda: None)
        resp = await _call(_build_app(session), "/pre/x")
        session.commit()
    assert resp.status_code == 200
    assert _count(session_factory) == 1
