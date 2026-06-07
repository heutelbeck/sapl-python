"""RSocket+TLS ITs: TLS over the binary transport, each auth mode."""

from __future__ import annotations

import pytest

from sapl_base.transport import (
    RsocketPdpClient,
    RsocketPdpClientOptions,
    TlsConfig,
)
from sapl_base.types import AuthorizationSubscription, Decision
from tests.integration.conftest import API_KEY_PLAIN, BASIC_SECRET, BASIC_USER


@pytest.mark.asyncio
async def test_rsocket_tls_no_auth_permits(
    sapl_node_rsocket_tls_noauth: tuple[str, int, bytes],
) -> None:
    host, port, ca_pem = sapl_node_rsocket_tls_noauth
    client = RsocketPdpClient(
        RsocketPdpClientOptions(host=host, port=port, tls=TlsConfig(ca=ca_pem))
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_tls_basic_auth_permits(
    sapl_node_rsocket_tls_basic: tuple[str, int, bytes],
) -> None:
    host, port, ca_pem = sapl_node_rsocket_tls_basic
    client = RsocketPdpClient(
        RsocketPdpClientOptions(
            host=host,
            port=port,
            tls=TlsConfig(ca=ca_pem),
            username=BASIC_USER,
            secret=BASIC_SECRET,
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_tls_api_key_permits(
    sapl_node_rsocket_tls_apikey: tuple[str, int, bytes],
) -> None:
    host, port, ca_pem = sapl_node_rsocket_tls_apikey
    client = RsocketPdpClient(
        RsocketPdpClientOptions(
            host=host,
            port=port,
            tls=TlsConfig(ca=ca_pem),
            token=API_KEY_PLAIN,
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_tls_no_ca_indeterminate(
    sapl_node_rsocket_tls_noauth: tuple[str, int, bytes],
) -> None:
    """Without the CA bundle, TLS handshake fails → fail-closed INDETERMINATE."""
    host, port, _ = sapl_node_rsocket_tls_noauth
    client = RsocketPdpClient(
        RsocketPdpClientOptions(host=host, port=port, tls=TlsConfig())
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.INDETERMINATE
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_tls_reject_unauthorized_false_permits(
    sapl_node_rsocket_tls_noauth: tuple[str, int, bytes],
) -> None:
    """reject_unauthorized=False accepts self-signed cert without a CA."""
    host, port, _ = sapl_node_rsocket_tls_noauth
    client = RsocketPdpClient(
        RsocketPdpClientOptions(
            host=host, port=port, tls=TlsConfig(reject_unauthorized=False)
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()
