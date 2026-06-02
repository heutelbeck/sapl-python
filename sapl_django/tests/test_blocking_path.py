"""Blocking (sync) enforcement path through the Django decorators.

A sync `@pre_enforce`/`@post_enforce` Django view now runs on the blocking core,
which executes the view off the event loop. This proves the keystone -- a sync
view can use the Django ORM with no `SynchronousOnlyOperation` -- and the full
sync transaction matrix with a raw sync provider (`transaction.atomic`).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction

import sapl_django.decorators as decorators
from sapl_base.pep import OUTPUT, EnforcementPlanner, ScopedHandler
from sapl_base.types import AuthorizationDecision, Decision
from sapl_django.decorators import post_enforce, pre_enforce

FAIL_OUTPUT = {"type": "failOutput"}


class AsyncStubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: Any) -> AuthorizationDecision:
        return self._decision


class FailingOutputProvider:
    def get_handlers(self, constraint: Any) -> list[ScopedHandler]:
        if isinstance(constraint, dict) and constraint.get("type") == "failOutput":
            def _raise(value: Any) -> None:
                raise RuntimeError("output obligation handler failed")

            return [ScopedHandler(signal=OUTPUT, priority=0, shape="consumer", handler=_raise)]
        return []


def _permit(*obligations: Any) -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=tuple(obligations))


def _wire(monkeypatch, decision, *, failing=False, transaction_provider=None) -> None:
    providers = (FailingOutputProvider(),) if failing else ()
    monkeypatch.setattr(decorators, "get_pdp_client", lambda: AsyncStubPdp(decision))
    monkeypatch.setattr(decorators, "get_planner", lambda: EnforcementPlanner(providers=providers))
    monkeypatch.setattr(decorators, "get_transaction_provider", lambda: transaction_provider)


@pytest.mark.django_db
def test_sync_view_queries_django_orm_without_synchronous_only_operation(monkeypatch):
    _wire(monkeypatch, _permit())

    @pre_enforce(action="read", resource="user")
    def list_users() -> list[str]:
        return [u.username for u in User.objects.all()]

    assert list_users() == []


@pytest.mark.django_db
def test_blocking_pre_enforce_permit_commits(monkeypatch):
    _wire(monkeypatch, _permit(), transaction_provider=transaction.atomic)

    @pre_enforce(action="write", resource="user")
    def create_user() -> dict[str, str]:
        User.objects.create(username="alice")
        return {"created": "alice"}

    create_user()
    assert User.objects.filter(username="alice").exists()


@pytest.mark.django_db
def test_blocking_post_enforce_deny_rolls_back(monkeypatch):
    _wire(monkeypatch, AuthorizationDecision(decision=Decision.DENY), transaction_provider=transaction.atomic)

    @post_enforce(action="write", resource="user")
    def create_user() -> dict[str, str]:
        User.objects.create(username="bob")
        return {"created": "bob"}

    with pytest.raises(PermissionDenied):
        create_user()
    assert not User.objects.filter(username="bob").exists()


@pytest.mark.django_db
def test_blocking_post_enforce_output_failure_rolls_back(monkeypatch):
    _wire(monkeypatch, _permit(FAIL_OUTPUT), failing=True, transaction_provider=transaction.atomic)

    @post_enforce(action="write", resource="user")
    def create_user() -> dict[str, str]:
        User.objects.create(username="carol")
        return {"created": "carol"}

    with pytest.raises(PermissionDenied):
        create_user()
    assert not User.objects.filter(username="carol").exists()


@pytest.mark.django_db
def test_blocking_pre_enforce_output_failure_rolls_back(monkeypatch):
    _wire(monkeypatch, _permit(FAIL_OUTPUT), failing=True, transaction_provider=transaction.atomic)

    @pre_enforce(action="write", resource="user")
    def create_user() -> dict[str, str]:
        User.objects.create(username="dave")
        return {"created": "dave"}

    with pytest.raises(PermissionDenied):
        create_user()
    assert not User.objects.filter(username="dave").exists()


@pytest.mark.django_db
def test_blocking_no_transaction_provider_still_runs(monkeypatch):
    _wire(monkeypatch, _permit(), transaction_provider=None)

    @pre_enforce(action="write", resource="user")
    def create_user() -> dict[str, str]:
        User.objects.create(username="erin")
        return {"created": "erin"}

    create_user()
    assert User.objects.filter(username="erin").exists()
