"""End-to-end transaction rollback through the Django wrapper.

Drives a Django async view protected by ``@pre_enforce`` / ``@post_enforce`` that writes
to a real sync sqlite database (via sync SQLAlchemy). Proves the wrapper threads the
configured transaction provider into the enforcement core, so a post-write denial rolls
the DB transaction back.

Django settings come from ``tests/settings.py`` via pytest-django (``DJANGO_SETTINGS_MODULE``),
so no manual ``settings.configure`` is needed here. The view is called directly with a
``RequestFactory`` request and awaited, which avoids needing a urlconf. Sync SQLAlchemy keeps
the test self-contained and sidesteps Django-ORM-in-async and event-loop issues.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import django
from django.conf import settings

if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
    django.setup()

import pytest
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

import sapl_django.decorators as decorators
from sapl_base.pep import OUTPUT, EnforcementPlanner, ScopedHandler, from_sync_context
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_django.decorators import post_enforce, pre_enforce

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


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/django.db")
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    yield maker
    engine.dispose()


def _count(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(Widget)) or 0


def _wire(monkeypatch, decision: AuthorizationDecision, session: Session, *, failing: bool) -> None:
    providers = (FailingOutputProvider(),) if failing else ()
    monkeypatch.setattr(decorators, "get_pdp_client", lambda: StubPdp(decision))
    monkeypatch.setattr(decorators, "get_planner", lambda: EnforcementPlanner(providers=providers))
    monkeypatch.setattr(
        decorators, "get_transaction_provider",
        lambda: from_sync_context(lambda: session.begin()),
    )


def _post_view(session: Session):
    @post_enforce(action="write", resource="widget")
    async def post_write(request, name):
        session.add(Widget(name=name))
        return {"name": name}

    return post_write


def _pre_view(session: Session):
    @pre_enforce(action="write", resource="widget")
    async def pre_write(request, name):
        session.add(Widget(name=name))
        return {"name": name}

    return pre_write


async def test_post_enforce_permit_commits(monkeypatch, session_factory):
    request = RequestFactory().get("/post/x")
    with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.PERMIT), session, failing=False)
        await _post_view(session)(request, "x")
    assert _count(session_factory) == 1


async def test_post_enforce_deny_rolls_back(monkeypatch, session_factory):
    request = RequestFactory().get("/post/x")
    with session_factory() as session:
        _wire(monkeypatch, AuthorizationDecision(decision=Decision.DENY), session, failing=False)
        view = _post_view(session)
        with pytest.raises(PermissionDenied):
            await view(request, "x")
    assert _count(session_factory) == 0


async def test_post_enforce_output_obligation_failure_rolls_back(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    request = RequestFactory().get("/post/x")
    with session_factory() as session:
        _wire(monkeypatch, decision, session, failing=True)
        view = _post_view(session)
        with pytest.raises(PermissionDenied):
            await view(request, "x")
    assert _count(session_factory) == 0


async def test_pre_enforce_output_obligation_failure_rolls_back(monkeypatch, session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    request = RequestFactory().get("/pre/x")
    with session_factory() as session:
        _wire(monkeypatch, decision, session, failing=True)
        view = _pre_view(session)
        with pytest.raises(PermissionDenied):
            await view(request, "x")
    assert _count(session_factory) == 0
