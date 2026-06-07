"""HTTPS + auth ITs: TLS + each auth mode together."""

from __future__ import annotations

import pytest

from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions, TlsConfig
from sapl_base.types import AuthorizationSubscription, Decision
from tests.integration.conftest import API_KEY_PLAIN, BASIC_SECRET, BASIC_USER


@pytest.mark.asyncio
async def test_https_basic_auth_permits(
    sapl_node_https_basic: tuple[str, bytes],
) -> None:
    base_url, ca_pem = sapl_node_https_basic
    client = HttpPdpClient(
        HttpPdpClientOptions(
            base_url=base_url,
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
async def test_https_api_key_permits(
    sapl_node_https_apikey: tuple[str, bytes],
) -> None:
    base_url, ca_pem = sapl_node_https_apikey
    client = HttpPdpClient(
        HttpPdpClientOptions(
            base_url=base_url,
            tls=TlsConfig(ca=ca_pem),
            token=API_KEY_PLAIN,
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()
