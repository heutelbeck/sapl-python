"""RSocket transport ITs against a real SAPL Node.

Exercises request_response and request_stream over the RSocket
port. Also checks cross-transport parity: identical decisions
arrive over HTTP and RSocket for the same subscription.
"""

from __future__ import annotations

import asyncio

import pytest

from sapl_base.transport import (
    HttpPdpClient,
    HttpPdpClientOptions,
    RsocketPdpClient,
    RsocketPdpClientOptions,
)
from sapl_base.types import (
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationSubscription,
)


async def _retry_until(call, ok, attempts: int = 5):
    """Cold-start tolerance for one-offs: a fresh RSocket connection can hit a
    transient setup error that correctly fail-closes to INDETERMINATE; a retried
    (warm) connection then succeeds. The client fail-closes fast by design (no
    retry on one-offs), so the test rides out the cold-connect transient itself."""
    result = await call()
    for _ in range(attempts - 1):
        if ok(result):
            break
        result = await call()
    return result


@pytest.mark.asyncio
async def test_rsocket_decide_once_returns_permit(
    sapl_node_dual_transport_noauth: tuple[str, str, int],
) -> None:
    _, host, port = sapl_node_dual_transport_noauth
    client = RsocketPdpClient(RsocketPdpClientOptions(host=host, port=port))
    try:
        decision = await _retry_until(
            lambda: client.decide_once(
                AuthorizationSubscription(subject="alice", action="read", resource="doc-1")
            ),
            lambda d: d.decision == Decision.PERMIT,
        )
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_multi_decide_all_once_returns_flat_id_map(
    sapl_node_dual_transport_noauth: tuple[str, str, int],
) -> None:
    _, host, port = sapl_node_dual_transport_noauth
    client = RsocketPdpClient(RsocketPdpClientOptions(host=host, port=port))
    try:
        multi = MultiAuthorizationSubscription(
            subscriptions={
                "a": AuthorizationSubscription(action="read"),
                "b": AuthorizationSubscription(action="write"),
            }
        )
        result = await _retry_until(
            lambda: client.multi_decide_all_once(multi),
            lambda r: r.decisions.get("a") is not None,
        )
        assert result.decisions["a"].decision == Decision.PERMIT
        assert result.decisions["b"].decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_decide_stream_yields_first_decision(
    sapl_node_dual_transport_noauth: tuple[str, str, int],
) -> None:
    _, host, port = sapl_node_dual_transport_noauth
    client = RsocketPdpClient(RsocketPdpClientOptions(host=host, port=port))
    try:
        subscription = AuthorizationSubscription(
            subject="alice", action="read", resource="doc-1"
        )
        async def _first() -> Decision:
            async for decision in client.decide(subscription):
                if decision.decision != Decision.INDETERMINATE:
                    return decision.decision
            return Decision.INDETERMINATE
        verb = await asyncio.wait_for(_first(), timeout=10.0)
        assert verb == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_cross_transport_parity(
    sapl_node_dual_transport_noauth: tuple[str, str, int],
) -> None:
    """The same subscription decided via HTTP and RSocket must produce identical verbs."""
    http_url, rs_host, rs_port = sapl_node_dual_transport_noauth
    http = HttpPdpClient(HttpPdpClientOptions(base_url=http_url))
    rsocket = RsocketPdpClient(RsocketPdpClientOptions(host=rs_host, port=rs_port))
    try:
        subscription = AuthorizationSubscription(
            subject="alice", action="read", resource="doc-1"
        )
        http_decision = await http.decide_once(subscription)
        rs_decision = await rsocket.decide_once(subscription)
        assert http_decision.decision == rs_decision.decision
        assert rs_decision.decision == Decision.PERMIT
    finally:
        await http.close()
        await rsocket.close()
