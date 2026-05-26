"""OAuth2 token provider for the PDP client.

The PDP client treats OAuth2 access tokens as opaque bearers. JWT
validation is the PDP's responsibility; this module fetches a token
via `client_credentials`, caches it until shortly before expiry,
and exposes `invalidate()` so the transport can force a refresh
after a 401 / 403.

Concurrent callers share a single in-flight refresh via an
`asyncio.Lock` plus pending-task pattern.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import structlog
from authlib.integrations.httpx_client import AsyncOAuth2Client

logger = structlog.get_logger(__name__)


_DEFAULT_REFRESH_GUARD_SECONDS = 30
_DEFAULT_LIFETIME_FALLBACK_SECONDS = 60
_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"

ERROR_MISSING_ACCESS_TOKEN = (
    "OAuth2 client_credentials response did not include an access_token."
)
ERROR_MISSING_TOKEN_ENDPOINT = (
    "OIDC discovery document is missing the token_endpoint claim."
)


@runtime_checkable
class TokenProvider(Protocol):
    """Source of bearer tokens for the PDP client.

    Implementations are responsible for caching, expiry handling,
    and refresh. The transport calls `get_access_token` once per
    request (cheap when cached) and `invalidate` on a 401 / 403 to
    force a refresh on the next attempt.
    """

    async def get_access_token(self) -> str:
        """Return a non-empty bearer token, refreshing if needed."""
        ...

    def invalidate(self) -> None:
        """Drop any cached token; next call performs a fresh acquisition."""
        ...


@dataclass(frozen=True, slots=True)
class OAuth2TokenProviderOptions:
    """Configuration for `AuthlibOAuth2TokenProvider`.

    `issuer_url` is the OIDC issuer (NOT the token endpoint). The
    provider discovers the token endpoint via the
    `/.well-known/openid-configuration` document.
    """

    issuer_url: str
    client_id: str
    client_secret: str
    scope: str | None = None
    refresh_guard_seconds: int = _DEFAULT_REFRESH_GUARD_SECONDS


@dataclass(slots=True)
class _CachedToken:
    access_token: str
    expires_at: float


class AuthlibOAuth2TokenProvider:
    """OAuth2 `client_credentials` token provider using authlib.

    Tokens are reused until their expiry is within
    `refresh_guard_seconds` of now. Concurrent callers share a single
    in-flight refresh.
    """

    def __init__(self, options: OAuth2TokenProviderOptions) -> None:
        self._options = options
        self._cached: _CachedToken | None = None
        self._refresh_lock = asyncio.Lock()
        self._pending_refresh: asyncio.Task[str] | None = None
        self._token_endpoint: str | None = None

    async def get_access_token(self) -> str:
        cached = self._cached
        if cached is not None and cached.expires_at > time.monotonic() + self._options.refresh_guard_seconds:
            return cached.access_token
        async with self._refresh_lock:
            cached = self._cached
            if cached is not None and cached.expires_at > time.monotonic() + self._options.refresh_guard_seconds:
                return cached.access_token
            if self._pending_refresh is not None and not self._pending_refresh.done():
                return await self._pending_refresh
            self._pending_refresh = asyncio.create_task(self._refresh_once())
        try:
            return await self._pending_refresh
        finally:
            self._pending_refresh = None

    def invalidate(self) -> None:
        self._cached = None

    async def _refresh_once(self) -> str:
        token_endpoint = await self._resolve_token_endpoint()
        async with AsyncOAuth2Client(
            client_id=self._options.client_id,
            client_secret=self._options.client_secret,
            token_endpoint_auth_method="client_secret_post",
        ) as client:
            response = await client.fetch_token(
                url=token_endpoint,
                grant_type="client_credentials",
                scope=self._options.scope,
            )
        access_token = response.get("access_token")
        if not access_token:
            raise RuntimeError(ERROR_MISSING_ACCESS_TOKEN)
        lifetime = int(response.get("expires_in", _DEFAULT_LIFETIME_FALLBACK_SECONDS))
        self._cached = _CachedToken(
            access_token=access_token,
            expires_at=time.monotonic() + lifetime,
        )
        logger.debug("oauth2_token_acquired", lifetime_seconds=lifetime)
        return access_token

    async def _resolve_token_endpoint(self) -> str:
        if self._token_endpoint is not None:
            return self._token_endpoint
        import httpx
        discovery_url = self._options.issuer_url.rstrip("/") + _DISCOVERY_SUFFIX
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            metadata = response.json()
        token_endpoint = metadata.get("token_endpoint")
        if not token_endpoint:
            raise RuntimeError(ERROR_MISSING_TOKEN_ENDPOINT)
        self._token_endpoint = token_endpoint
        return token_endpoint
