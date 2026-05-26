from __future__ import annotations

import asyncio

import pytest
import respx
from httpx import Response

from sapl_base.transport.oauth2 import (
    ERROR_MISSING_ACCESS_TOKEN,
    AuthlibOAuth2TokenProvider,
    OAuth2TokenProviderOptions,
)


def _options() -> OAuth2TokenProviderOptions:
    return OAuth2TokenProviderOptions(
        issuer_url="https://issuer.local/realm",
        client_id="sapl-pdp",
        client_secret="topsecret",
    )


def _route_discovery(mock: respx.MockRouter) -> None:
    mock.get("https://issuer.local/realm/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "issuer": "https://issuer.local/realm",
                "token_endpoint": "https://issuer.local/realm/token",
            },
        )
    )


@pytest.mark.asyncio
async def test_get_access_token_fetches_via_client_credentials() -> None:
    with respx.mock(assert_all_called=True) as mock:
        _route_discovery(mock)
        mock.post("https://issuer.local/realm/token").mock(
            return_value=Response(
                200,
                json={"access_token": "tok-A", "token_type": "Bearer", "expires_in": 300},
            )
        )
        provider = AuthlibOAuth2TokenProvider(_options())
        assert await provider.get_access_token() == "tok-A"


@pytest.mark.asyncio
async def test_cached_token_is_reused_within_refresh_guard() -> None:
    with respx.mock() as mock:
        _route_discovery(mock)
        token_route = mock.post("https://issuer.local/realm/token").mock(
            return_value=Response(
                200,
                json={"access_token": "tok-A", "token_type": "Bearer", "expires_in": 300},
            )
        )
        provider = AuthlibOAuth2TokenProvider(_options())
        await provider.get_access_token()
        await provider.get_access_token()
        assert token_route.call_count == 1


@pytest.mark.asyncio
async def test_invalidate_forces_refresh_on_next_call() -> None:
    with respx.mock() as mock:
        _route_discovery(mock)
        token_route = mock.post("https://issuer.local/realm/token").mock(
            side_effect=[
                Response(200, json={"access_token": "tok-A", "expires_in": 300}),
                Response(200, json={"access_token": "tok-B", "expires_in": 300}),
            ]
        )
        provider = AuthlibOAuth2TokenProvider(_options())
        assert await provider.get_access_token() == "tok-A"
        provider.invalidate()
        assert await provider.get_access_token() == "tok-B"
        assert token_route.call_count == 2


@pytest.mark.asyncio
async def test_concurrent_callers_share_single_in_flight_refresh() -> None:
    with respx.mock() as mock:
        _route_discovery(mock)
        token_route = mock.post("https://issuer.local/realm/token").mock(
            return_value=Response(
                200,
                json={"access_token": "tok-shared", "expires_in": 300},
            )
        )
        provider = AuthlibOAuth2TokenProvider(_options())
        tokens = await asyncio.gather(
            *(provider.get_access_token() for _ in range(5))
        )
        assert tokens == ["tok-shared"] * 5
        assert token_route.call_count == 1


@pytest.mark.asyncio
async def test_missing_access_token_raises() -> None:
    with respx.mock() as mock:
        _route_discovery(mock)
        mock.post("https://issuer.local/realm/token").mock(
            return_value=Response(200, json={"token_type": "Bearer", "expires_in": 300})
        )
        provider = AuthlibOAuth2TokenProvider(_options())
        with pytest.raises(RuntimeError, match=ERROR_MISSING_ACCESS_TOKEN):
            await provider.get_access_token()
