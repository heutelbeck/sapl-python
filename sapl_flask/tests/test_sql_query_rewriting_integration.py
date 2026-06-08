"""End-to-end SQL query rewriting through the Flask wrapper and the SQLAlchemy shim.

A PDP decision carrying a ``sql:queryRewriting`` obligation, flowing through
``@pre_enforce`` -> the planner -> ``SqlQueryRewritingProvider`` -> the registered
ORM listener, rewrites a real ``SELECT`` so the database returns only the authorised
rows. Only the PDP is mocked; the database, the query, and the rewrite are real.

Sync SQLAlchemy is used deliberately: Flask runs the async enforce via ``asyncio.run``
per request, and the view's sync ``session.execute`` runs in that same task, so the
``current_plan`` context variable set by ``pre_enforce`` is visible when the listener
fires. The rewrite assertion proves that end to end.
"""

from __future__ import annotations

import types
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

import sapl_flask.decorators as decorators
from sapl_base.pep import EnforcementPlanner
from sapl_base.types import AuthorizationDecision, Decision
from sapl_flask.decorators import pre_enforce
from sapl_sqlalchemy import (
    SqlQueryRewritingProvider,
    register_orm_listener,
    unregister_orm_listener,
)

OWNER_OBLIGATION = {
    "type": "sql:queryRewriting",
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

    async def decide_once(self, subscription: Any) -> AuthorizationDecision:
        return self._decision


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/flask_sql.db")
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    with maker() as session:
        session.add_all(
            [Widget(name="alice-widget", owner="alice"), Widget(name="bob-widget", owner="bob")]
        )
        session.commit()
    yield maker
    engine.dispose()


@pytest.fixture
def orm_listener():
    register_orm_listener()
    yield
    unregister_orm_listener()


def _wire(monkeypatch, decision: AuthorizationDecision) -> None:
    extension = types.SimpleNamespace(
        pdp_client=StubPdp(decision),
        planner=EnforcementPlanner(providers=(SqlQueryRewritingProvider(),)),
        transaction_provider=None,
    )
    monkeypatch.setattr(decorators, "get_sapl_extension", lambda: extension)


def _build_app(session_factory: sessionmaker[Session]) -> Flask:
    app = Flask(__name__)

    @app.get("/widgets")
    @pre_enforce(action="read", resource="widget")
    def list_widgets() -> dict[str, list[str]]:
        with session_factory() as session:
            result = session.execute(select(Widget))
            return {"names": [w.name for w in result.scalars().all()]}

    return app


def test_obligation_rewrites_select_to_authorized_rows(monkeypatch, session_factory, orm_listener):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(OWNER_OBLIGATION,))
    _wire(monkeypatch, decision)
    resp = _build_app(session_factory).test_client().get("/widgets")
    assert resp.status_code == 200
    assert resp.get_json()["names"] == ["alice-widget"]


def test_obligation_denied_when_shim_not_registered(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(OWNER_OBLIGATION,))
    _wire(monkeypatch, decision)
    resp = _build_app(session_factory).test_client().get("/widgets")
    assert resp.status_code == 403


def test_permit_without_obligation_returns_all_rows(monkeypatch, session_factory, orm_listener):
    decision = AuthorizationDecision(decision=Decision.PERMIT)
    _wire(monkeypatch, decision)
    resp = _build_app(session_factory).test_client().get("/widgets")
    assert resp.status_code == 200
    assert sorted(resp.get_json()["names"]) == ["alice-widget", "bob-widget"]
