"""HTTP transport ITs against a real SAPL Node.

Covers one-shot decide, streaming decide (SSE), and one-shot
multi-decide-all end-to-end against a running container.
"""

from __future__ import annotations

import asyncio

import pytest

from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions
from sapl_base.types import (
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationSubscription,
)


@pytest.mark.asyncio
async def test_decide_once_against_real_pdp_returns_permit(
    sapl_node_http_noauth: str,
) -> None:
    client = HttpPdpClient(HttpPdpClientOptions(base_url=sapl_node_http_noauth))
    try:
        decision = await client.decide_once(
            AuthorizationSubscription(subject="alice", action="read", resource="doc-1")
        )
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_decide_stream_yields_at_least_one_decision(
    sapl_node_http_noauth: str,
) -> None:
    client = HttpPdpClient(HttpPdpClientOptions(base_url=sapl_node_http_noauth))
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
async def test_multi_decide_all_once_returns_flat_id_map(
    sapl_node_http_noauth: str,
) -> None:
    client = HttpPdpClient(HttpPdpClientOptions(base_url=sapl_node_http_noauth))
    try:
        multi = MultiAuthorizationSubscription(
            subscriptions={
                "read-doc": AuthorizationSubscription(action="read", resource="doc-1"),
                "write-doc": AuthorizationSubscription(action="write", resource="doc-1"),
            }
        )
        result = await client.multi_decide_all_once(multi)
        assert result.decisions["read-doc"].decision == Decision.PERMIT
        assert result.decisions["write-doc"].decision == Decision.PERMIT
    finally:
        await client.close()
