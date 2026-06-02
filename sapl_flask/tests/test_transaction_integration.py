"""End-to-end transaction rollback through the Flask wrapper.

Drives a real Flask app (via its sync test client) whose views write to a real
sync sqlite database and are protected by ``@pre_enforce`` / ``@post_enforce``.
Proves the wrapper threads the configured transaction provider into the
enforcement core, so a post-write denial rolls the DB transaction back.

A sync SQLAlchemy session is used deliberately: Flask runs the async enforce via
``asyncio.run`` per request, so a sync (not loop-bound) session avoids any
event-loop fragility around the per-request loop.
"""

from __future__ import annotations

import types
from collections.abc import Sequence
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

import sapl_flask.decorators as decorators
from sapl_base.pep import OUTPUT, EnforcementPlanner, ScopedHandler
from sapl_base.pep.transaction import from_sync_context
from sapl_base.types import AuthorizationDecision, Decision
from sapl_flask.decorators import post_enforce, pre_enforce

FAIL_OUTPUT = {"type": "failOutput"}


class Base(DeclarativeBase):
    pass


class Widget(Base):
    __tablename__ = "widget"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class StubPdp:
    """A PDP that always returns one configured decision."""

    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: Any) -> AuthorizationDecision:
        return self._decision


class FailingOutputProvider:
    """Claims the ``failOutput`` obligation with an OUTPUT consumer that raises."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if isinstance(constraint, dict) and constraint.get("type") == "failOutput":
            def _raise(value: Any) -> None:
                raise RuntimeError("output obligation handler failed")

            return [ScopedHandler(signal=OUTPUT, priority=0, shape="consumer", handler=_raise)]
        return []


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/flask.db")
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    yield maker
    engine.dispose()


def _widget_count(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(Widget)) or 0


def _build_app(session: Session) -> Flask:
    app = Flask(__name__)

    @app.get("/post/<name>")
    @post_enforce(action="write", resource="widget")
    def post_write(name: str) -> dict[str, str]:
        session.add(Widget(name=name))
        return {"name": name}

    @app.get("/pre/<name>")
    @pre_enforce(action="write", resource="widget")
    def pre_write(name: str) -> dict[str, str]:
        session.add(Widget(name=name))
        return {"name": name}

    return app


def _wire(monkeypatch, decision: AuthorizationDecision, session: Session, *, failing: bool) -> None:
    providers = (FailingOutputProvider(),) if failing else ()
    extension = types.SimpleNamespace(
        pdp_client=StubPdp(decision),
        planner=EnforcementPlanner(providers=providers),
        transaction_provider=from_sync_context(lambda: session.begin()),
    )
    monkeypatch.setattr(decorators, "get_sapl_extension", lambda: extension)


def test_post_enforce_permit_commits(monkeypatch, session_factory):
    with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.PERMIT), session, failing=False)
        client = _build_app(session).test_client()
        resp = client.get("/post/x")
    assert resp.status_code == 200
    assert _widget_count(session_factory) == 1


def test_post_enforce_deny_rolls_back(monkeypatch, session_factory):
    with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.DENY), session, failing=False)
        client = _build_app(session).test_client()
        resp = client.get("/post/x")
    assert resp.status_code == 403
    assert _widget_count(session_factory) == 0


def test_post_enforce_output_obligation_failure_rolls_back(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    with session_factory() as session:
        _wire(monkeypatch, decision, session, failing=True)
        client = _build_app(session).test_client()
        resp = client.get("/post/x")
    assert resp.status_code == 403
    assert _widget_count(session_factory) == 0


def test_pre_enforce_output_obligation_failure_rolls_back(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    with session_factory() as session:
        _wire(monkeypatch, decision, session, failing=True)
        client = _build_app(session).test_client()
        resp = client.get("/pre/x")
    assert resp.status_code == 403
    assert _widget_count(session_factory) == 0
