"""End-to-end SQL query rewriting through the Django wrapper and the ORM shim.

A PDP decision carrying a ``sql:queryRewriting`` obligation flows through ``@pre_enforce``
-> the planner -> ``DjangoQueryRewritingProvider`` -> the registered
``SQLCompiler.execute_sql`` hook, rewriting a real query so the database returns only the
authorised rows. Only the PDP is mocked; the database (embedded sqlite), the query, and the
rewrite are real. Both the sync (blocking-core) and async paths are exercised.

Target selection is proven against two models in one call: a criterion on ``username`` filters
the ``User`` query but leaves the ``Group`` query (which has no ``username``) untouched.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.utils import timezone

import sapl_django.decorators as decorators
from sapl_base.pep import EnforcementPlanner
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_django.decorators import pre_enforce
from sapl_django.orm_providers import DjangoQueryRewritingProvider
from sapl_django.orm_shim import register_orm_listener, unregister_orm_listener


class StubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision


def _permit(*obligations: Any) -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=tuple(obligations))


def _criteria(*criteria: Any) -> dict[str, Any]:
    return {"type": "sql:queryRewriting", "criteria": list(criteria)}


def _leaf(column: str, op: str, value: Any = ...) -> dict[str, Any]:
    leaf: dict[str, Any] = {"column": column, "op": op}
    if value is not ...:
        leaf["value"] = value
    return leaf


def _wire(monkeypatch, decision: AuthorizationDecision) -> None:
    monkeypatch.setattr(decorators, "get_pdp_client", lambda: StubPdp(decision))
    monkeypatch.setattr(
        decorators, "get_planner",
        lambda: EnforcementPlanner(providers=(DjangoQueryRewritingProvider(),)),
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


@pytest.fixture
def orm_listener():
    register_orm_listener()
    yield
    unregister_orm_listener()


def _names() -> list[str]:
    return sorted(user.username for user in User.objects.all())


@pytest.mark.django_db(transaction=True)
def test_criteria_equality_filters_rows(monkeypatch, orm_listener):
    User.objects.create(username="alice")
    User.objects.create(username="bob")
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "=", "alice"))))
    assert _enforced_sync(_names)() == ["alice"]


@pytest.mark.django_db(transaction=True)
def test_criteria_in_filters_rows(monkeypatch, orm_listener):
    for name in ("alice", "bob", "carol"):
        User.objects.create(username=name)
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "in", ["alice", "carol"]))))
    assert _enforced_sync(_names)() == ["alice", "carol"]


@pytest.mark.django_db(transaction=True)
def test_criteria_like_filters_rows(monkeypatch, orm_listener):
    for name in ("alice", "amy", "bob"):
        User.objects.create(username=name)
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "like", "a%"))))
    assert _enforced_sync(_names)() == ["alice", "amy"]


@pytest.mark.django_db(transaction=True)
def test_criteria_comparison_filters_rows(monkeypatch, orm_listener):
    alice = User.objects.create(username="alice")
    User.objects.create(username="bob")
    _wire(monkeypatch, _permit(_criteria(_leaf("id", ">", alice.id))))
    assert _enforced_sync(_names)() == ["bob"]


@pytest.mark.django_db(transaction=True)
def test_criteria_is_null_filters_rows(monkeypatch, orm_listener):
    User.objects.create(username="alice", last_login=timezone.now())
    User.objects.create(username="bob")
    _wire(monkeypatch, _permit(_criteria(_leaf("last_login", "isNull"))))
    assert _enforced_sync(_names)() == ["bob"]


@pytest.mark.django_db(transaction=True)
def test_criteria_and_tree_filters_rows(monkeypatch, orm_listener):
    User.objects.create(username="alice", is_active=True)
    User.objects.create(username="bob", is_active=True)
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "=", "alice"), _leaf("is_active", "=", True))))
    assert _enforced_sync(_names)() == ["alice"]


@pytest.mark.django_db(transaction=True)
def test_target_selection_filters_only_models_with_the_column(monkeypatch, orm_listener):
    User.objects.create(username="alice")
    User.objects.create(username="bob")
    Group.objects.create(name="g1")
    Group.objects.create(name="g2")
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "=", "alice"))))

    def op():
        users = sorted(user.username for user in User.objects.all())
        groups = sorted(group.name for group in Group.objects.all())
        return users, groups

    users, groups = _enforced_sync(op)()
    assert users == ["alice"]
    assert groups == ["g1", "g2"]


@pytest.mark.django_db(transaction=True)
def test_update_touches_only_target_rows(monkeypatch, orm_listener):
    User.objects.create(username="alice", first_name="")
    User.objects.create(username="bob", first_name="")
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "=", "alice"))))
    _enforced_sync(lambda: User.objects.update(first_name="changed"))()
    assert User.objects.get(username="alice").first_name == "changed"
    assert User.objects.get(username="bob").first_name == ""


@pytest.mark.django_db(transaction=True)
def test_delete_removes_only_target_rows(monkeypatch, orm_listener):
    User.objects.create(username="alice")
    User.objects.create(username="bob")
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "=", "bob"))))
    _enforced_sync(lambda: User.objects.all().delete())()
    assert _names() == ["alice"]


@pytest.mark.django_db(transaction=True)
def test_conditions_filter_rows(monkeypatch, orm_listener):
    User.objects.create(username="alice")
    User.objects.create(username="bob")
    _wire(monkeypatch, _permit({"type": "sql:queryRewriting", "conditions": ["username = 'alice'"]}))
    assert _enforced_sync(_names)() == ["alice"]


@pytest.mark.django_db(transaction=True)
def test_columns_projection_defers_other_fields(monkeypatch, orm_listener):
    User.objects.create(username="alice", email="alice@example.com")
    _wire(monkeypatch, _permit({"type": "sql:queryRewriting", "columns": ["username"]}))
    result = _enforced_sync(lambda: list(User.objects.all()))()
    assert result[0].username == "alice"
    assert "email" in result[0].get_deferred_fields()


@pytest.mark.django_db(transaction=True)
def test_unsupported_operator_denies(monkeypatch, orm_listener):
    User.objects.create(username="alice")
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "BOGUS", "alice"))))
    run = _enforced_sync(lambda: list(User.objects.all()))
    with pytest.raises(PermissionDenied):
        run()


@pytest.mark.django_db(transaction=True)
def test_obligation_denied_when_shim_not_registered(monkeypatch):
    User.objects.create(username="alice")
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "=", "alice"))))
    run = _enforced_sync(_names)
    with pytest.raises(PermissionDenied):
        run()


@pytest.mark.django_db(transaction=True)
async def test_async_criteria_filters_rows(monkeypatch, orm_listener):
    await User.objects.acreate(username="alice")
    await User.objects.acreate(username="bob")
    _wire(monkeypatch, _permit(_criteria(_leaf("username", "=", "alice"))))

    async def op():
        return sorted([user.username async for user in User.objects.all()])

    assert await _enforced_async(op)() == ["alice"]
