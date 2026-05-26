"""RSocket auth ITs against a real SAPL Node.

Exercises the Setup-payload auth flow (SIMPLE / BEARER well-known
auth types prefixed with the type byte) end-to-end. Wrong
credentials must surface `INDETERMINATE`.
"""

from __future__ import annotations

import pytest

from sapl_base.transport import RsocketPdpClient, RsocketPdpClientOptions
from sapl_base.types import AuthorizationSubscription, Decision

from tests.integration.conftest import (
    API_KEY_PLAIN,
    BASIC_SECRET,
    BASIC_USER,
    _fetch_oauth_token,
)


@pytest.mark.asyncio
async def test_rsocket_basic_auth_correct_credentials_permits(
    sapl_node_rsocket_basic: tuple[str, int],
) -> None:
    host, port = sapl_node_rsocket_basic
    client = RsocketPdpClient(
        RsocketPdpClientOptions(
            host=host, port=port, username=BASIC_USER, secret=BASIC_SECRET
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_basic_auth_wrong_credentials_indeterminate(
    sapl_node_rsocket_basic: tuple[str, int],
) -> None:
    host, port = sapl_node_rsocket_basic
    client = RsocketPdpClient(
        RsocketPdpClientOptions(
            host=host, port=port, username=BASIC_USER, secret="wrong"
        )
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.INDETERMINATE
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_api_key_correct_permits(
    sapl_node_rsocket_apikey: tuple[str, int],
) -> None:
    host, port = sapl_node_rsocket_apikey
    client = RsocketPdpClient(
        RsocketPdpClientOptions(host=host, port=port, token=API_KEY_PLAIN)
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_api_key_wrong_indeterminate(
    sapl_node_rsocket_apikey: tuple[str, int],
) -> None:
    host, port = sapl_node_rsocket_apikey
    client = RsocketPdpClient(
        RsocketPdpClientOptions(host=host, port=port, token="sapl_wrong_xxx")
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.INDETERMINATE
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_oauth2_jwt_decides_permit(
    sapl_node_rsocket_oauth2: tuple[int, str, int],
) -> None:
    rsocket_port, oauth_host, oauth_port = sapl_node_rsocket_oauth2
    token = _fetch_oauth_token(oauth_host, oauth_port)
    client = RsocketPdpClient(
        RsocketPdpClientOptions(host="127.0.0.1", port=rsocket_port, token=token)
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rsocket_oauth2_invalid_token_indeterminate(
    sapl_node_rsocket_oauth2: tuple[int, str, int],
) -> None:
    rsocket_port, _, _ = sapl_node_rsocket_oauth2
    client = RsocketPdpClient(
        RsocketPdpClientOptions(host="127.0.0.1", port=rsocket_port, token="not.a.real.jwt")
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.INDETERMINATE
    finally:
        await client.close()
