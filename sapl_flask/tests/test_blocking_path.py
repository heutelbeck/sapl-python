"""Blocking (sync) enforcement path through the Flask wrapper.

Flask is WSGI (always sync), so ``@pre_enforce`` / ``@post_enforce`` run the view
on the blocking enforcement core. This proves the view executes OFF the event
loop (``asyncio.get_running_loop`` raises inside it), so a sync view never runs
inside an asyncio loop. A no-transaction permit case proves the path works
without a configured transaction provider.
"""

from __future__ import annotations

import asyncio
import types
from typing import Any

from flask import Flask

import sapl_flask.decorators as decorators
from sapl_base.pep import EnforcementPlanner
from sapl_base.types import AuthorizationDecision, Decision
from sapl_flask.decorators import pre_enforce


class StubPdp:
    """A PDP that always returns one configured decision."""

    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: Any) -> AuthorizationDecision:
        return self._decision


def _permit() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT)


def _wire(monkeypatch, decision: AuthorizationDecision, *, transaction_provider=None) -> None:
    extension = types.SimpleNamespace(
        pdp_client=StubPdp(decision),
        planner=EnforcementPlanner(),
        transaction_provider=transaction_provider,
    )
    monkeypatch.setattr(decorators, "get_sapl_extension", lambda: extension)


def test_sync_view_runs_off_the_event_loop(monkeypatch):
    observed: dict[str, bool] = {}

    app = Flask(__name__)

    @app.get("/probe")
    @pre_enforce(action="read", resource="loop")
    def probe() -> dict[str, str]:
        try:
            asyncio.get_running_loop()
            observed["in_loop"] = True
        except RuntimeError:
            observed["in_loop"] = False
        return {"status": "ok"}

    _wire(monkeypatch, _permit())
    resp = app.test_client().get("/probe")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
    assert observed["in_loop"] is False


def test_blocking_permit_without_transaction_provider(monkeypatch):
    app = Flask(__name__)

    @app.get("/read")
    @pre_enforce(action="read", resource="thing")
    def read() -> dict[str, str]:
        return {"value": "data"}

    _wire(monkeypatch, _permit(), transaction_provider=None)
    resp = app.test_client().get("/read")

    assert resp.status_code == 200
    assert resp.get_json() == {"value": "data"}
