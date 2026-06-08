"""End-to-end SQL query rewriting through the Tornado wrapper and the SQLAlchemy shim.

A PDP decision carrying a ``sql:queryRewriting`` obligation, flowing through
``@pre_enforce`` -> the planner -> ``SqlQueryRewritingProvider`` -> the registered
ORM listener, rewrites a real ``SELECT`` so the database returns only the authorised
rows. Only the PDP is mocked; the database, the query, and the rewrite are real.

Sync SQLAlchemy sessions are not event-loop-bound, so the handler's ``session.execute``
runs in the same task that ``pre_enforce`` set ``current_plan`` on, and the listener
sees the plan when it fires.
"""

from __future__ import annotations

import json
import os
import tempfile

import tornado.testing
import tornado.web
from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tornado.web import RequestHandler

import sapl_tornado.decorators as decorators
from sapl_base.pep import EnforcementPlanner
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_sqlalchemy import (
    SqlQueryRewritingProvider,
    register_orm_listener,
    unregister_orm_listener,
)
from sapl_tornado.decorators import pre_enforce

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

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision


class _SqlTestCase(tornado.testing.AsyncHTTPTestCase):
    """Base: real sync sqlite seeded with two owners, stubbed PDP/planner.

    Subclasses set ``DECISION`` and ``REGISTER``; the handler read path and the
    fixture wiring are shared.
    """

    DECISION: AuthorizationDecision
    REGISTER: bool = True

    def setUp(self) -> None:
        fd, self._db_file = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self._db_file) and os.remove(self._db_file))
        self.engine = create_engine(f"sqlite:///{self._db_file}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        with self.session_factory() as session:
            session.add_all(
                [Widget(name="alice-widget", owner="alice"), Widget(name="bob-widget", owner="bob")]
            )
            session.commit()

        self._patches = [
            ("get_pdp_client", lambda: StubPdp(self.DECISION)),
            ("get_planner", lambda: EnforcementPlanner(providers=(SqlQueryRewritingProvider(),))),
            ("get_transaction_provider", lambda: None),
        ]
        self._originals = {}
        for name, value in self._patches:
            self._originals[name] = getattr(decorators, name)
            setattr(decorators, name, value)
        if self.REGISTER:
            register_orm_listener()

        super().setUp()

    def tearDown(self) -> None:
        if self.REGISTER:
            unregister_orm_listener()
        for name, original in self._originals.items():
            setattr(decorators, name, original)
        self.engine.dispose()
        super().tearDown()

    def get_app(self) -> tornado.web.Application:
        test_case = self

        class WidgetsHandler(RequestHandler):
            @pre_enforce(action="read", resource="widget")
            async def get(self) -> dict[str, list[str]]:
                with test_case.session_factory() as session:
                    result = session.execute(select(Widget))
                    return {"names": [w.name for w in result.scalars().all()]}

        return tornado.web.Application([(r"/widgets", WidgetsHandler)])


class TestObligationRewritesSelect(_SqlTestCase):
    DECISION = AuthorizationDecision(decision=Decision.PERMIT, obligations=(OWNER_OBLIGATION,))

    def test_rewrites_to_authorized_rows(self) -> None:
        response = self.fetch("/widgets")
        assert response.code == 200
        assert json.loads(response.body)["names"] == ["alice-widget"]


class TestObligationDeniedWhenUnregistered(_SqlTestCase):
    DECISION = AuthorizationDecision(decision=Decision.PERMIT, obligations=(OWNER_OBLIGATION,))
    REGISTER = False

    def test_denied(self) -> None:
        response = self.fetch("/widgets")
        assert response.code == 403


class TestPermitWithoutObligation(_SqlTestCase):
    DECISION = AuthorizationDecision(decision=Decision.PERMIT)

    def test_returns_all_rows(self) -> None:
        response = self.fetch("/widgets")
        assert response.code == 200
        assert sorted(json.loads(response.body)["names"]) == ["alice-widget", "bob-widget"]
