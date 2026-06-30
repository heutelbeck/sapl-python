"""Fail-closed resilience of the HTTP PDP transport.

Two operational hazards a remote PDP can inflict on a PEP:

1. A silently dead-but-open SSE socket (200 accepted, one decision sent,
   then total silence with no FIN/RST). The transport must apply a
   per-item inactivity timeout so the gap fails closed, seeds
   INDETERMINATE, and reconnects, while genuine keep-alive frames keep a
   quiet stream alive. (Spring RemoteHttpReactivePolicyDecisionPoint:
   inactivityTimeoutMillis = 60_000, liveness runs before keep-alives are
   dropped.)

2. A multi-decision response that names the same subscription id twice.
   Spring rejects duplicate ids fail-closed at the decode boundary rather
   than silently last-wins-merging them.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx
from httpx import Response

from sapl_base.transport.http_pdp_client import HttpPdpClient, HttpPdpClientOptions
from sapl_base.types import (
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationSubscription,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_BASE = "http://127.0.0.1:8080"
_DECIDE = f"{_BASE}/api/pdp/decide"
_MULTI_ONCE = f"{_BASE}/api/pdp/multi-decide-all-once"

_PERMIT_FRAME = b'data: {"decision":"PERMIT"}\n\n'
_DENY_FRAME = b'data: {"decision":"DENY"}\n\n'
_KEEPALIVE_FRAME = b": keep-alive\n\n"


class _ScriptedStream(httpx.AsyncByteStream):
    """Replays scripted (gap_before, payload) byte chunks, then optionally
    holds the connection open in silence to mimic a dead-but-open socket
    that never sends a FIN or RST."""

    def __init__(
        self, chunks: list[tuple[float, bytes]], trailing_silence: float = 0.0
    ) -> None:
        self._chunks = chunks
        self._trailing_silence = trailing_silence

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for gap, payload in self._chunks:
            if gap:
                await asyncio.sleep(gap)
            yield payload
        if self._trailing_silence:
            await asyncio.sleep(self._trailing_silence)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
class TestStreamLivenessOnDeadButOpenSocket:
    async def test_silent_socket_fails_closed_then_reconnects(self) -> None:
        """One PERMIT, then the socket goes silent without closing. Liveness
        must fire, seed INDETERMINATE, and reconnect onto a fresh stream."""
        hanging = Response(
            200,
            stream=_ScriptedStream([(0.0, _PERMIT_FRAME)], trailing_silence=30.0),
        )
        recovered = Response(200, content=_DENY_FRAME)
        async with _client_for_test(
            streaming_inactivity_timeout_seconds=0.2,
            streaming_retry_base_delay_seconds=0.01,
            streaming_retry_max_delay_seconds=0.05,
        ) as client:
            with respx.mock() as mock:
                mock.post(_DECIDE).mock(side_effect=[hanging, recovered])
                verbs = [
                    d.decision
                    for d in await _take(client.decide(_sub()), 3, limit_seconds=3.0)
                ]
        assert verbs == [Decision.PERMIT, Decision.INDETERMINATE, Decision.DENY]

    async def test_keep_alive_frames_keep_a_quiet_stream_alive(self) -> None:
        """A stream that emits only SSE keep-alive comments faster than the
        inactivity window must not be torn down. Liveness resets on every
        received frame, so the eventual real decision arrives without a
        spurious INDETERMINATE reconnect."""
        chunks = [(0.05, _KEEPALIVE_FRAME) for _ in range(5)]
        chunks.append((0.05, _DENY_FRAME))
        quiet = Response(200, stream=_ScriptedStream(chunks))
        async with _client_for_test(
            streaming_inactivity_timeout_seconds=0.2,
            streaming_retry_base_delay_seconds=0.01,
            streaming_retry_max_delay_seconds=0.05,
        ) as client:
            with respx.mock() as mock:
                mock.post(_DECIDE).mock(return_value=quiet)
                verbs = [
                    d.decision
                    for d in await _take(client.decide(_sub()), 1, limit_seconds=3.0)
                ]
        assert verbs == [Decision.DENY]
        assert Decision.INDETERMINATE not in verbs


@pytest.mark.asyncio
class TestMultiDecisionDuplicateIdsRejected:
    async def test_duplicate_subscription_id_fails_closed(self) -> None:
        """A multi response that names the same id twice with conflicting
        verbs is malformed. Spring rejects it fail-closed rather than
        silently keeping whichever decision parsed last."""
        duplicate_payload = (
            '{"read": {"decision": "PERMIT"}, "read": {"decision": "DENY"}}'
        )
        subscription = MultiAuthorizationSubscription(
            subscriptions={"read": AuthorizationSubscription(action="read")}
        )
        async with _client_for_test() as client:
            with respx.mock() as mock:
                mock.post(_MULTI_ONCE).mock(
                    return_value=Response(
                        200,
                        text=duplicate_payload,
                        headers={"content-type": "application/json"},
                    )
                )
                result = await client.multi_decide_all_once(subscription)
        assert result.decisions == {}


def _sub() -> AuthorizationSubscription:
    return AuthorizationSubscription(action="read")


def _opts(**overrides: Any) -> HttpPdpClientOptions:
    defaults: dict[str, Any] = {"base_url": _BASE}
    defaults.update(overrides)
    return HttpPdpClientOptions(**defaults)


class _ClientCtx:
    def __init__(self, **opts: Any) -> None:
        self._client = HttpPdpClient(_opts(**opts))

    async def __aenter__(self) -> HttpPdpClient:
        return self._client

    async def __aexit__(self, *_: object) -> None:
        await self._client.close()


def _client_for_test(**opts: Any) -> _ClientCtx:
    return _ClientCtx(**opts)


async def _take(
    iterator: AsyncIterator[Any], count: int, limit_seconds: float = 2.0
) -> list[Any]:
    items: list[Any] = []

    async def _collect() -> None:
        async for item in iterator:
            items.append(item)
            if len(items) >= count:
                break

    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_collect(), timeout=limit_seconds)
    return items
