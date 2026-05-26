"""HTTPS ITs: TLS connection to a SAPL Node with self-signed cert."""

from __future__ import annotations

import pytest

from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions, TlsConfig
from sapl_base.types import AuthorizationSubscription, Decision


@pytest.mark.asyncio
async def test_https_with_ca_bundle_validates_and_permits(
    sapl_node_https_noauth: tuple[str, bytes],
) -> None:
    """Client validates self-signed cert via the CA bundle in TlsConfig."""
    base_url, ca_pem = sapl_node_https_noauth
    client = HttpPdpClient(
        HttpPdpClientOptions(
            base_url=base_url,
            tls=TlsConfig(ca=ca_pem),
        )
    )
    try:
        decision = await client.decide_once(
            AuthorizationSubscription(subject="alice", action="read", resource="doc-1")
        )
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_https_without_ca_bundle_falls_back_to_indeterminate(
    sapl_node_https_noauth: tuple[str, bytes],
) -> None:
    """No CA configured AND a self-signed server cert: client treats as transport failure."""
    base_url, _ = sapl_node_https_noauth
    client = HttpPdpClient(HttpPdpClientOptions(base_url=base_url))
    try:
        decision = await client.decide_once(
            AuthorizationSubscription(subject="alice", action="read", resource="doc-1")
        )
        assert decision.decision == Decision.INDETERMINATE
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_https_with_reject_unauthorized_false_permits(
    sapl_node_https_noauth: tuple[str, bytes],
) -> None:
    """reject_unauthorized=False (test-only) accepts the self-signed cert without a CA."""
    base_url, _ = sapl_node_https_noauth
    client = HttpPdpClient(
        HttpPdpClientOptions(
            base_url=base_url,
            tls=TlsConfig(reject_unauthorized=False),
        )
    )
    try:
        decision = await client.decide_once(
            AuthorizationSubscription(subject="alice", action="read", resource="doc-1")
        )
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()
