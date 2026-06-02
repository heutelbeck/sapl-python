"""RSocket client resilience, unit-tested with a fake transport (no real node).

Covers the contract: one-off requests fail-close to INDETERMINATE without throwing;
subscriptions never terminate on a transport error or a server-side complete -- they
emit INDETERMINATE and reconnect.
"""

from __future__ import annotations

import types
from typing import Any

import pytest
from rsocket.exceptions import RSocketTransportError

from sapl_base.transport.constants import PdpRoute
from sapl_base.transport.rsocket_pdp_client import RsocketPdpClient, RsocketPdpClientOptions
from sapl_base.types import AuthorizationSubscription, Decision

pytestmark = pytest.mark.asyncio


def _client() -> RsocketPdpClient:
    return RsocketPdpClient(
        RsocketPdpClientOptions(
            host="localhost",
            streaming_retry_base_delay_seconds=0.01,
            streaming_retry_max_delay_seconds=0.02,
        )
    )


def _payload(data: bytes) -> Any:
    return types.SimpleNamespace(data=data)


class _FakePublisher:
    def __init__(self, events: list[tuple[str, Any]]) -> None:
        self._events = events

    def initial_request_n(self, _n: int) -> None:
        pass

    def subscribe(self, subscriber: Any) -> None:
        for kind, value in self._events:
            if kind == "next":
                subscriber.on_next(value)
            elif kind == "complete":
                subscriber.on_complete()
            elif kind == "error":
                subscriber.on_error(value)


class _FakeClient:
    def __init__(self, events: list[tuple[str, Any]]) -> None:
        self._events = events

    def request_stream(self, _payload: Any) -> _FakePublisher:
        return _FakePublisher(self._events)


async def _take(iterator: Any, count: int, limit_seconds: float = 2.0) -> list[Any]:
    import asyncio
    from contextlib import suppress

    items: list[Any] = []

    async def _collect() -> None:
        async for item in iterator:
            items.append(item)
            if len(items) >= count:
                break

    with suppress(TimeoutError):
        await asyncio.wait_for(_collect(), timeout=limit_seconds)
    return items


async def test_decide_once_fail_closes_to_indeterminate_on_connect_error(monkeypatch):
    client = _client()

    async def _boom() -> Any:
        raise RSocketTransportError("setup failed")

    monkeypatch.setattr(client, "_connect", _boom)
    decision = await client.decide_once(AuthorizationSubscription())
    assert decision.decision == Decision.INDETERMINATE


async def test_stream_reconnects_on_server_complete_and_never_terminates(monkeypatch):
    client = _client()
    scripts = [
        [("next", _payload(b"PERMIT")), ("complete", None)],
        [("next", _payload(b"DENY")), ("complete", None)],
    ]
    calls = {"i": 0}

    async def _fake_connect() -> _FakeClient:
        script = scripts[min(calls["i"], len(scripts) - 1)]
        calls["i"] += 1
        return _FakeClient(script)

    monkeypatch.setattr(client, "_connect", _fake_connect)

    stream = client._request_stream(
        PdpRoute.DECIDE, b"x", decode=lambda raw: raw.decode(), fallback=lambda: "INDETERMINATE"
    )
    items = await _take(stream, 4)
    assert items[0] == "PERMIT"
    assert "INDETERMINATE" in items
    assert "DENY" in items
    assert calls["i"] >= 2


async def test_stream_reconnects_on_transport_error(monkeypatch):
    client = _client()
    calls = {"i": 0}

    async def _fake_connect() -> _FakeClient:
        calls["i"] += 1
        if calls["i"] == 1:
            raise RSocketTransportError("connect dropped")
        return _FakeClient([("next", _payload(b"PERMIT")), ("complete", None)])

    monkeypatch.setattr(client, "_connect", _fake_connect)

    stream = client._request_stream(
        PdpRoute.DECIDE, b"x", decode=lambda raw: raw.decode(), fallback=lambda: "INDETERMINATE"
    )
    items = await _take(stream, 2)
    assert "INDETERMINATE" in items
    assert "PERMIT" in items
