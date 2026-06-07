"""End-to-end transaction rollback through the Tornado wrapper.

Drives a real Tornado app (via ``AsyncHTTPTestCase`` + ``self.fetch``) whose handlers
write to a real SYNC sqlite database and are protected by ``@pre_enforce`` /
``@post_enforce``. Proves the wrapper threads the configured transaction provider into
the enforcement core, so a post-write denial (DENY or output-obligation failure) rolls
the DB transaction back.

Sync SQLAlchemy sessions are not event-loop-bound, so using them inside Tornado's
IOLoop is fine and needs no greenlet/aiosqlite.
"""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING, Any

import tornado.testing
import tornado.web
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import sapl_tornado.decorators as decorators
from sapl_base.pep import (
    OUTPUT,
    EnforcementPlanner,
    ScopedHandler,
    from_sync_context,
)
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_tornado.decorators import post_enforce, pre_enforce

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


class _TransactionTestCase(tornado.testing.AsyncHTTPTestCase):
    """Base: real sync sqlite engine, stubbed PDP/planner/transaction provider.

    Subclasses set ``DECISION``, ``FAILING`` and ``PATH``; the request-handler write
    path and assertions are shared.
    """

    DECISION: AuthorizationDecision
    FAILING: bool = False
    PATH: str = "/post/x"

    def setUp(self) -> None:
        self._db_file = self.get_temp_file()
        self.engine = create_engine(f"sqlite:///{self._db_file}")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.session = self.session_factory()

        providers = (FailingOutputProvider(),) if self.FAILING else ()
        self._patches = [
            ("get_pdp_client", lambda: StubPdp(self.DECISION)),
            ("get_planner", lambda: EnforcementPlanner(providers=providers)),
            (
                "get_transaction_provider",
                lambda: from_sync_context(lambda: self.session.begin()),
            ),
        ]
        self._originals = {}
        for name, value in self._patches:
            self._originals[name] = getattr(decorators, name)
            setattr(decorators, name, value)

        super().setUp()

    def tearDown(self) -> None:
        for name, original in self._originals.items():
            setattr(decorators, name, original)
        self.session.close()
        self.engine.dispose()
        super().tearDown()

    def get_temp_file(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def _widget_count(self) -> int:
        with self.session_factory() as session:
            return session.scalar(select(func.count()).select_from(Widget)) or 0

    def get_app(self) -> tornado.web.Application:
        test_case = self

        class PostHandler(tornado.web.RequestHandler):
            @post_enforce(action="write", resource="widget")
            async def get(self) -> dict[str, str]:
                test_case.session.add(Widget(name="created"))
                return {"name": "created"}

        class PreHandler(tornado.web.RequestHandler):
            @pre_enforce(action="write", resource="widget")
            async def get(self) -> dict[str, str]:
                test_case.session.add(Widget(name="created"))
                return {"name": "created"}

        return tornado.web.Application([
            (r"/post/x", PostHandler),
            (r"/pre/x", PreHandler),
        ])


class TestPostEnforcePermitCommits(_TransactionTestCase):
    DECISION = AuthorizationDecision(decision=Decision.PERMIT)
    FAILING = False
    PATH = "/post/x"

    def test_permit_commits_row(self) -> None:
        response = self.fetch(self.PATH)
        assert response.code == 200
        assert self._widget_count() == 1


class TestPostEnforceDenyRollsBack(_TransactionTestCase):
    DECISION = AuthorizationDecision(decision=Decision.DENY)
    FAILING = False
    PATH = "/post/x"

    def test_deny_rolls_back_row(self) -> None:
        response = self.fetch(self.PATH)
        assert response.code == 403
        assert self._widget_count() == 0


class TestPostEnforceOutputFailureRollsBack(_TransactionTestCase):
    DECISION = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    FAILING = True
    PATH = "/post/x"

    def test_output_failure_rolls_back_row(self) -> None:
        response = self.fetch(self.PATH)
        assert response.code == 403
        assert self._widget_count() == 0


class TestPreEnforceOutputFailureRollsBack(_TransactionTestCase):
    DECISION = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    FAILING = True
    PATH = "/pre/x"

    def test_output_failure_rolls_back_row(self) -> None:
        response = self.fetch(self.PATH)
        assert response.code == 403
        assert self._widget_count() == 0
