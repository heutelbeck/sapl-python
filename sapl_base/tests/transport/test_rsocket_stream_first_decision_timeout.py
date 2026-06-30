"""RSocket subscription resilience when a connected server stays silent.

A connect can succeed (the responder accepts ``request_stream`` and the
initial-request-N) yet never deliver a first decision. Per CR-11 the
protobuf/RSocket streaming path must bound at least the first decision with
a timeout (Spring protobuf: ``.timeout(Mono.delay(timeoutMillis), item ->
Mono.never())``, default 5s), so a connected-but-silent server fails closed
to INDETERMINATE and reconnects instead of blocking the consumer forever.
"""

from __future__ import annotations

import asyncio
import types
from contextlib import suppress
from typing import Any

import pytest

from sapl_base.transport.constants import PdpRoute
from sapl_base.transport.rsocket_pdp_client import (
    RsocketPdpClient,
    RsocketPdpClientOptions,
)

pytestmark = pytest.mark.asyncio


def _client(timeout_seconds: float) -> RsocketPdpClient:
    return RsocketPdpClient(
        RsocketPdpClientOptions(
            host="localhost",
            timeout_seconds=timeout_seconds,
            streaming_retry_base_delay_seconds=0.01,
            streaming_retry_max_delay_seconds=0.02,
        )
    )


def _payload(data: bytes) -> Any:
    return types.SimpleNamespace(data=data)


class _SilentPublisher:
    """Accepts the subscription and the demand, but never emits anything.

    Models a responder that honoured ``request_stream`` and the initial
    request-N yet sends no first payload, completion, or error.
    """

    def initial_request_n(self, _n: int) -> None:
        pass

    def subscribe(self, _subscriber: Any) -> None:
        pass


class _ScriptedPublisher:
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


class _PublisherClient:
    def __init__(self, publisher: Any) -> None:
        self._publisher = publisher

    def request_stream(self, _payload: Any) -> Any:
        return self._publisher


async def _take(iterator: Any, count: int, limit_seconds: float) -> list[Any]:
    items: list[Any] = []

    async def _collect() -> None:
        async for item in iterator:
            items.append(item)
            if len(items) >= count:
                break

    with suppress(TimeoutError):
        await asyncio.wait_for(_collect(), timeout=limit_seconds)
    return items


async def test_silent_server_fails_closed_to_indeterminate_within_timeout(monkeypatch):
    timeout_seconds = 0.3
    client = _client(timeout_seconds)

    async def _fake_connect() -> _PublisherClient:
        return _PublisherClient(_SilentPublisher())

    monkeypatch.setattr(client, "_connect", _fake_connect)

    stream = client._request_stream(
        PdpRoute.DECIDE,
        b"x",
        decode=lambda raw: raw.decode(),
        fallback=lambda: "INDETERMINATE",
    )
    # A bounded first decision must surface well before the consumer's own
    # patience runs out; the timeout is 0.3s, allow generous slack.
    items = await _take(stream, 1, limit_seconds=timeout_seconds + 2.0)
    assert items == ["INDETERMINATE"]


async def test_silent_server_reconnects_and_delivers_once_responder_recovers(monkeypatch):
    timeout_seconds = 0.3
    client = _client(timeout_seconds)
    calls = {"i": 0}

    async def _fake_connect() -> _PublisherClient:
        calls["i"] += 1
        if calls["i"] == 1:
            return _PublisherClient(_SilentPublisher())
        return _PublisherClient(
            _ScriptedPublisher([("next", _payload(b"PERMIT")), ("complete", None)])
        )

    monkeypatch.setattr(client, "_connect", _fake_connect)

    stream = client._request_stream(
        PdpRoute.DECIDE,
        b"x",
        decode=lambda raw: raw.decode(),
        fallback=lambda: "INDETERMINATE",
    )
    items = await _take(stream, 2, limit_seconds=timeout_seconds + 3.0)
    assert "INDETERMINATE" in items
    assert "PERMIT" in items
    assert calls["i"] >= 2
