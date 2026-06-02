"""Django transactional enforcement is supported on the sync path only.

Django's ``transaction.atomic`` is async-unsafe: entering it under a running event loop
raises ``SynchronousOnlyOperation``. The async enforcement core enters the transaction
scope on the event-loop thread, so an async Django view cannot drive a native Django
transaction through ``from_sync_context(transaction.atomic)``. Transactional enforcement
on Django therefore requires a sync view (the blocking core), where the provider is used
as a plain sync context manager -- that matrix is covered by ``test_blocking_path.py``.

This test pins the limitation. It also proves the failure is safe: the transaction scope
raises before the view body runs, so no partial write is committed. If a future Django
makes ``transaction.atomic`` async-aware, this test starts failing and the async path can
be revisited.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import SynchronousOnlyOperation
from django.db import transaction
from django.test import RequestFactory

import sapl_django.decorators as decorators
from sapl_base.pep import EnforcementPlanner, from_sync_context
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision
from sapl_django.decorators import post_enforce


class StubPdp:
    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision


def _wire(monkeypatch, decision: AuthorizationDecision) -> None:
    monkeypatch.setattr(decorators, "get_pdp_client", lambda: StubPdp(decision))
    monkeypatch.setattr(decorators, "get_planner", lambda: EnforcementPlanner(providers=()))
    monkeypatch.setattr(
        decorators, "get_transaction_provider",
        lambda: from_sync_context(transaction.atomic),
    )


@post_enforce(action="write", resource="user")
async def _post_write(request, name):
    await User.objects.acreate(username=name)
    return {"name": name}


@pytest.mark.django_db(transaction=True)
async def test_async_view_with_django_atomic_provider_is_unsupported(monkeypatch):
    _wire(monkeypatch, AuthorizationDecision(decision=Decision.PERMIT))
    blocked_call = _post_write(RequestFactory().get("/post/alice"), "alice")
    with pytest.raises(SynchronousOnlyOperation):
        await blocked_call
    assert not await User.objects.filter(username="alice").aexists()
