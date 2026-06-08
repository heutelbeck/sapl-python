"""Dummy Django ORM query-rewriting shim, end to end across every query type.

A PDP decision carrying a ``sql:queryRewriting`` obligation flows through ``@pre_enforce``
-> the planner -> the dummy ``DjangoQueryLoggingProvider`` -> the registered
``SQLCompiler.execute_sql`` hook, which fires DJANGO_QUERY with the structured Query. The
dummy logs the query type and returns it unchanged, proving the cut point fires on a real
Django ORM operation. Only the PDP is mocked; the database, the query, and the hook are real.

The single base-compiler hook covers every query kind: reads (``list``, ``values``,
``count``, ``exists``, ``aggregate``) compile there directly, deletes and aggregates inherit
it, and updates reach it through ``SQLUpdateCompiler``'s ``super().execute_sql`` call. Both
the sync (blocking-core) and async paths are exercised; async queries run the compiler in a
``sync_to_async`` worker that inherits the ``current_plan`` context.

The integrity keystone (obligation denied when the shim is not registered) proves the planner
governs: without ``register_orm_listener`` advertising DJANGO_QUERY the obligation is
inadmissible and fails closed, exactly as for the SQLAlchemy shim.
"""

from __future__ import annotations

from typing import Any

import pytest
import structlog
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from structlog.testing import capture_logs

import sapl_django.decorators as decorators
from sapl_base.pep import EnforcementPlanner, ScopedHandler
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_django.decorators import pre_enforce
from sapl_django.orm_shim import DJANGO_QUERY, register_orm_listener, unregister_orm_listener

logger = structlog.get_logger(__name__)

SHIM_FIRED_EVENT = "django_query_rewriting_shim_fired"
QUERY_OBLIGATION = {
    "type": "sql:queryRewriting",
    "criteria": [{"column": "username", "op": "=", "value": "alice"}],
}


def _log_and_pass(query: Any) -> Any:
    logger.info(SHIM_FIRED_EVENT, query_type=type(query).__name__)
    return query


class LoggingProvider:
    """Diagnostic provider: claims sql:queryRewriting, logs the query, returns it unchanged.

    Used to prove the cut point fires across query types, independently of any real lowering.
    """

    def get_handlers(self, constraint: Any) -> tuple[ScopedHandler, ...]:
        if isinstance(constraint, dict) and constraint.get("type") == "sql:queryRewriting":
            return (ScopedHandler(signal=DJANGO_QUERY, priority=30, shape="mapper", handler=_log_and_pass),)
        return ()


class StubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision


def _permit(*obligations: Any) -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=tuple(obligations))


def _wire(monkeypatch, decision: AuthorizationDecision) -> None:
    monkeypatch.setattr(decorators, "get_pdp_client", lambda: StubPdp(decision))
    monkeypatch.setattr(
        decorators, "get_planner",
        lambda: EnforcementPlanner(providers=(LoggingProvider(),)),
    )
    monkeypatch.setattr(decorators, "get_transaction_provider", lambda: None)


def _enforced_sync(op):
    @pre_enforce(action="read", resource="user")
    def _run():
        return op()

    return _run


def _enforced_async(op):
    @pre_enforce(action="read", resource="user")
    async def _run():
        return await op()

    return _run


def _fired(logs) -> list[dict]:
    return [event for event in logs if event.get("event") == SHIM_FIRED_EVENT]


@pytest.fixture
def orm_listener():
    register_orm_listener()
    yield
    unregister_orm_listener()


SYNC_OPS = [
    ("list", lambda: list(User.objects.all())),
    ("count", lambda: User.objects.count()),
    ("exists", lambda: User.objects.exists()),
    ("aggregate", lambda: User.objects.aggregate(n=Count("id"))),
    ("update", lambda: User.objects.filter(username="alice").update(first_name="x")),
    ("delete", lambda: User.objects.filter(username="bob").delete()),
]


async def _aread() -> list[User]:
    return [user async for user in User.objects.all()]


async def _acount() -> int:
    return await User.objects.acount()


async def _aexists() -> bool:
    return await User.objects.aexists()


async def _aupdate() -> int:
    return await User.objects.filter(username="alice").aupdate(first_name="x")


async def _adelete() -> tuple[int, dict[str, int]]:
    return await User.objects.filter(username="bob").adelete()


ASYNC_OPS = [
    ("aread", _aread),
    ("acount", _acount),
    ("aexists", _aexists),
    ("aupdate", _aupdate),
    ("adelete", _adelete),
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("op", [op for _, op in SYNC_OPS], ids=[name for name, _ in SYNC_OPS])
def test_shim_fires_on_sync_query(monkeypatch, orm_listener, op):
    User.objects.create(username="alice")
    User.objects.create(username="bob")
    _wire(monkeypatch, _permit(QUERY_OBLIGATION))

    with capture_logs() as logs:
        _enforced_sync(op)()

    assert _fired(logs)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("op", [op for _, op in ASYNC_OPS], ids=[name for name, _ in ASYNC_OPS])
async def test_shim_fires_on_async_query(monkeypatch, orm_listener, op):
    await User.objects.acreate(username="alice")
    await User.objects.acreate(username="bob")
    _wire(monkeypatch, _permit(QUERY_OBLIGATION))

    with capture_logs() as logs:
        await _enforced_async(op)()

    assert _fired(logs)


@pytest.mark.django_db(transaction=True)
def test_obligation_denied_when_shim_not_registered(monkeypatch):
    _wire(monkeypatch, _permit(QUERY_OBLIGATION))
    run = _enforced_sync(lambda: list(User.objects.all()))
    with pytest.raises(PermissionDenied):
        run()


@pytest.mark.django_db(transaction=True)
def test_permit_without_obligation_does_not_fire(monkeypatch, orm_listener):
    User.objects.create(username="alice")
    _wire(monkeypatch, _permit())

    with capture_logs() as logs:
        names = _enforced_sync(lambda: [user.username for user in User.objects.all()])()

    assert names == ["alice"]
    assert _fired(logs) == []
