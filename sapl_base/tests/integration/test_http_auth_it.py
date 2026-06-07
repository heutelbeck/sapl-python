"""HTTP transport auth ITs against a real SAPL Node.

Correct credentials must decide PERMIT, wrong credentials must
surface `INDETERMINATE` (fail-closed contract).
"""

from __future__ import annotations

import pytest

from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions
from sapl_base.types import AuthorizationSubscription, Decision
from tests.integration.conftest import API_KEY_PLAIN, BASIC_SECRET, BASIC_USER


@pytest.mark.asyncio
async def test_basic_auth_correct_credentials_permits(
    sapl_node_http_basic: str,
) -> None:
    client = HttpPdpClient(
        HttpPdpClientOptions(
            base_url=sapl_node_http_basic,
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
async def test_basic_auth_wrong_credentials_indeterminate(
    sapl_node_http_basic: str,
) -> None:
    client = HttpPdpClient(
        HttpPdpClientOptions(
            base_url=sapl_node_http_basic,
            username=BASIC_USER,
            secret="wrong-secret",
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.INDETERMINATE
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_key_correct_permits(
    sapl_node_http_apikey: str,
) -> None:
    client = HttpPdpClient(
        HttpPdpClientOptions(
            base_url=sapl_node_http_apikey,
            token=API_KEY_PLAIN,
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_key_wrong_indeterminate(
    sapl_node_http_apikey: str,
) -> None:
    client = HttpPdpClient(
        HttpPdpClientOptions(
            base_url=sapl_node_http_apikey,
            token="sapl_wrong_xxx",
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.INDETERMINATE
    finally:
        await client.close()
