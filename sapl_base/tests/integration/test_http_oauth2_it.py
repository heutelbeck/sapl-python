"""OAuth2 IT: SAPL Node validates a real JWT.

Acquires a JWT from a co-located mock-oauth2-server and exercises
the HTTP client's static-bearer auth path. The mock and the SAPL
Node share a docker network so the issuer URL the Node discovers
via JWKS and the issuer URL the JWT carries agree.
"""

from __future__ import annotations

import pytest

from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions
from sapl_base.types import AuthorizationSubscription, Decision
from tests.integration.conftest import _fetch_oauth_token


@pytest.mark.asyncio
async def test_oauth2_jwt_decides_permit(
    sapl_node_http_oauth2: tuple[str, str, int],
) -> None:
    base_url, oauth_host, oauth_port = sapl_node_http_oauth2
    token = _fetch_oauth_token(oauth_host, oauth_port)
    client = HttpPdpClient(HttpPdpClientOptions(base_url=base_url, token=token))
    try:
        decision = await client.decide_once(
            AuthorizationSubscription(subject="alice", action="read", resource="doc-1")
        )
        assert decision.decision == Decision.PERMIT
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_oauth2_invalid_token_indeterminate(
    sapl_node_http_oauth2: tuple[str, str, int],
) -> None:
    base_url, _, _ = sapl_node_http_oauth2
    client = HttpPdpClient(
        HttpPdpClientOptions(base_url=base_url, token="not.a.real.jwt")
    )
    try:
        decision = await client.decide_once(AuthorizationSubscription(action="read"))
        assert decision.decision == Decision.INDETERMINATE
    finally:
        await client.close()
