from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import httpx
import structlog

from sapl_base.deduplication import deduplicate
from sapl_base.logging_utils import WARN_INSECURE_CONNECTION, truncate
from sapl_base.sse_parser import SseBufferOverflowError, parse_sse_stream
from sapl_base.types import (
    AuthorizationDecision,
    AuthorizationSubscription,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
)
from sapl_base.validation import (
    parse_decision_from_json,
    parse_identifiable_decision_from_json,
    parse_multi_decision_from_json,
    validate_decision_response,
    validate_multi_decision_response,
)

logger = structlog.get_logger(__name__)

ERROR_AUTH_DUAL_CONFIG = "Cannot configure both bearer token and basic auth credentials"
ERROR_AUTH_BASIC_INCOMPLETE = "Basic auth requires both username and password"
ERROR_INSECURE_HTTP = "HTTP URL rejected: set allow_insecure_connections=True to permit insecure connections"
ERROR_DECIDE_ONCE_FAILED = "decide_once request failed, returning INDETERMINATE"
ERROR_DECIDE_ONCE_HTTP_ERROR = "decide_once received HTTP error, returning INDETERMINATE"
ERROR_MULTI_DECIDE_ONCE_FAILED = "multi_decide_once request failed, returning empty"
ERROR_MULTI_DECIDE_ONCE_HTTP_ERROR = "multi_decide_once received HTTP error, returning empty"
ERROR_MULTI_DECIDE_ALL_ONCE_FAILED = "multi_decide_all_once request failed, returning empty"
ERROR_MULTI_DECIDE_ALL_ONCE_HTTP_ERROR = "multi_decide_all_once received HTTP error, returning empty"
ERROR_STREAM_CONNECT_FAILED = "Streaming connection failed"
ERROR_STREAM_AUTH_FAILED = "Streaming connection rejected with authentication error"
ERROR_STREAM_BUFFER_OVERFLOW = "SSE buffer overflow during streaming"
ERROR_STREAM_UNEXPECTED = "Unexpected error during streaming"
WARN_STREAM_RECONNECTING = "Reconnecting streaming subscription after failure"

_API_DECIDE_ONCE = "/api/pdp/decide-once"
_API_DECIDE = "/api/pdp/decide"
_API_MULTI_DECIDE_ONCE = "/api/pdp/multi-decide-once"
_API_MULTI_DECIDE = "/api/pdp/multi-decide"
_API_MULTI_DECIDE_ALL_ONCE = "/api/pdp/multi-decide-all-once"
_API_MULTI_DECIDE_ALL = "/api/pdp/multi-decide-all"

_AUTH_ERROR_CODES = frozenset({401, 403})
_RECONNECTING_SENTINEL = object()


@dataclass(frozen=True, slots=True)
class PdpConfig:
    """Configuration for connecting to a SAPL PDP server.

    REQ-TRANSPORT-1/2: Default is HTTPS. HTTP requires explicit opt-in.
    REQ-AUTH-1/2/3/4: Bearer token or basic auth, never both.
    """

    base_url: str = "https://localhost:8443"
    token: str | None = None
    username: str | None = None
    password: str | None = None
    timeout: float = 5.0
    allow_insecure_connections: bool = False
    streaming_max_retries: int = 0
    streaming_retry_base_delay: float = 1.0
    streaming_retry_max_delay: float = 30.0


class PdpClient:
    """Async HTTP client for communicating with a SAPL PDP server."""

    def __init__(self, config: PdpConfig) -> None:
        _validate_config(config)
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return a usable httpx.AsyncClient, creating one if needed.

        Creates a fresh client on first use and when the previous client
        is no longer usable. For sync frameworks like Flask that call
        asyncio.run() per request (creating a new event loop each time),
        the client bound to the old loop becomes unusable. We detect this
        by checking whether the running event loop matches the one the
        client was created on.
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if (
            self._client is None
            or self._client.is_closed
            or current_loop is not self._client_loop
        ):
            self._client = _build_http_client(self._config)
            self._client_loop = current_loop
        return self._client

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        """Send a one-shot authorization request.

        REQ-RR-1/2/3: POST to /api/pdp/decide-once. On any error, return INDETERMINATE.
        """
        try:
            response = await self._get_client().post(
                _API_DECIDE_ONCE,
                json=subscription.to_dict(),
            )
        except Exception as exc:
            logger.error(
                ERROR_DECIDE_ONCE_FAILED,
                error=str(exc),
                subscription=subscription.to_loggable_dict(),
            )
            return AuthorizationDecision.indeterminate()

        if response.status_code != 200:
            logger.error(
                ERROR_DECIDE_ONCE_HTTP_ERROR,
                status_code=response.status_code,
                body=truncate(response.text),
                subscription=subscription.to_loggable_dict(),
            )
            return AuthorizationDecision.indeterminate()

        try:
            data = response.json()
        except Exception:
            logger.error(
                ERROR_DECIDE_ONCE_HTTP_ERROR,
                status_code=response.status_code,
                body=truncate(response.text),
                subscription=subscription.to_loggable_dict(),
            )
            return AuthorizationDecision.indeterminate()

        return validate_decision_response(data)

    async def decide(self, subscription: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
        """Open a streaming authorization subscription.

        REQ-STREAM-1/2/3/4/5: POST to /api/pdp/decide with SSE. Reconnects
        with exponential backoff and jitter. Applies distinctUntilChanged.
        """
        raw_stream = self._streaming_with_retry(
            _API_DECIDE,
            subscription.to_dict(),
            subscription.to_loggable_dict(),
        )
        deduped_stream = deduplicate(_parse_decision_stream(raw_stream))
        async for decision in deduped_stream:
            yield decision

    async def multi_decide_once(
        self,
        subscription: MultiAuthorizationSubscription,
    ) -> MultiAuthorizationDecision:
        """Send a one-shot multi-decision request to /api/pdp/multi-decide-once."""
        return await self._multi_request_once(
            _API_MULTI_DECIDE_ONCE,
            subscription,
            ERROR_MULTI_DECIDE_ONCE_FAILED,
            ERROR_MULTI_DECIDE_ONCE_HTTP_ERROR,
        )

    async def multi_decide_all_once(
        self,
        subscription: MultiAuthorizationSubscription,
    ) -> MultiAuthorizationDecision:
        """Send a one-shot multi-decide-all request to /api/pdp/multi-decide-all-once."""
        return await self._multi_request_once(
            _API_MULTI_DECIDE_ALL_ONCE,
            subscription,
            ERROR_MULTI_DECIDE_ALL_ONCE_FAILED,
            ERROR_MULTI_DECIDE_ALL_ONCE_HTTP_ERROR,
        )

    async def multi_decide(
        self,
        subscription: MultiAuthorizationSubscription,
    ) -> AsyncIterator[IdentifiableAuthorizationDecision]:
        """Open a streaming multi-decision subscription to /api/pdp/multi-decide.

        Yields individual IdentifiableAuthorizationDecision items as they arrive.
        """
        raw_stream = self._streaming_with_retry(
            _API_MULTI_DECIDE,
            subscription.to_dict(),
            subscription.to_loggable_dict(),
        )
        async for raw_json in raw_stream:
            result = parse_identifiable_decision_from_json(raw_json)
            if result is not None:
                yield result

    async def multi_decide_all(
        self,
        subscription: MultiAuthorizationSubscription,
    ) -> AsyncIterator[MultiAuthorizationDecision]:
        """Open a streaming multi-decide-all subscription to /api/pdp/multi-decide-all.

        Yields complete MultiAuthorizationDecision snapshots.
        """
        raw_stream = self._streaming_with_retry(
            _API_MULTI_DECIDE_ALL,
            subscription.to_dict(),
            subscription.to_loggable_dict(),
        )
        deduped_stream = deduplicate(_parse_multi_decision_stream(raw_stream))
        async for decision in deduped_stream:
            yield decision

    async def close(self) -> None:
        """Close the underlying HTTP client and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _multi_request_once(
        self,
        endpoint: str,
        subscription: MultiAuthorizationSubscription,
        error_request_failed: str,
        error_http_error: str,
    ) -> MultiAuthorizationDecision:
        try:
            response = await self._get_client().post(
                endpoint,
                json=subscription.to_dict(),
            )
        except Exception as exc:
            logger.error(
                error_request_failed,
                error=str(exc),
                subscription=subscription.to_loggable_dict(),
            )
            return MultiAuthorizationDecision()

        if response.status_code != 200:
            logger.error(
                error_http_error,
                status_code=response.status_code,
                body=truncate(response.text),
                subscription=subscription.to_loggable_dict(),
            )
            return MultiAuthorizationDecision()

        try:
            data = response.json()
        except Exception:
            logger.error(
                error_http_error,
                status_code=response.status_code,
                body=truncate(response.text),
                subscription=subscription.to_loggable_dict(),
            )
            return MultiAuthorizationDecision()

        return validate_multi_decision_response(data)

    async def _streaming_with_retry(
        self,
        endpoint: str,
        request_body: dict[str, Any],
        loggable_body: dict[str, Any],
    ) -> AsyncIterator[str]:
        """Connect to an SSE endpoint with exponential backoff retry.

        REQ-STREAM-3: Exponential backoff with jitter. Yields _RECONNECTING_SENTINEL
        before each reconnection so consumers can emit INDETERMINATE.
        REQ-STREAM-4: Auth errors (401/403) are logged every time but still retry.
        REQ-STREAM-5: Buffer overflow triggers reconnection (yields sentinel).
        """
        config = self._config
        attempt = 0

        while True:
            try:
                async with self._get_client().stream(
                    "POST",
                    endpoint,
                    json=request_body,
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    if response.status_code in _AUTH_ERROR_CODES:
                        logger.error(
                            ERROR_STREAM_AUTH_FAILED,
                            status_code=response.status_code,
                            subscription=loggable_body,
                        )
                    elif response.status_code != 200:
                        body = ""
                        async for chunk in response.aiter_text():
                            body += chunk
                            if len(body) > 500:
                                break
                        logger.error(
                            ERROR_STREAM_CONNECT_FAILED,
                            status_code=response.status_code,
                            body=truncate(body),
                            subscription=loggable_body,
                        )
                    else:
                        attempt = 0
                        async for event_data in parse_sse_stream(response.aiter_bytes()):
                            yield event_data
                        # Stream ended normally (server closed); reconnect
            except SseBufferOverflowError:
                logger.error(ERROR_STREAM_BUFFER_OVERFLOW, subscription=loggable_body)
                yield _RECONNECTING_SENTINEL
            except GeneratorExit:
                return
            except Exception as exc:
                logger.error(
                    ERROR_STREAM_UNEXPECTED,
                    error=str(exc),
                    subscription=loggable_body,
                )

            attempt += 1
            if config.streaming_max_retries > 0 and attempt >= config.streaming_max_retries:
                return

            delay = _backoff_delay(
                attempt,
                config.streaming_retry_base_delay,
                config.streaming_retry_max_delay,
            )
            logger.warning(
                WARN_STREAM_RECONNECTING,
                attempt=attempt,
                delay_seconds=delay,
                subscription=loggable_body,
            )

            yield _RECONNECTING_SENTINEL
            await asyncio.sleep(delay)


async def _parse_decision_stream(raw_stream: AsyncIterator[Any]) -> AsyncIterator[AuthorizationDecision]:
    async for raw_json in raw_stream:
        if raw_json is _RECONNECTING_SENTINEL:
            yield AuthorizationDecision.indeterminate()
        else:
            yield parse_decision_from_json(raw_json)


async def _parse_multi_decision_stream(raw_stream: AsyncIterator[Any]) -> AsyncIterator[MultiAuthorizationDecision]:
    async for raw_json in raw_stream:
        if raw_json is _RECONNECTING_SENTINEL:
            yield MultiAuthorizationDecision()
        else:
            yield parse_multi_decision_from_json(raw_json)


def _validate_config(config: PdpConfig) -> None:
    has_token = config.token is not None
    has_username = config.username is not None
    has_password = config.password is not None

    if has_token and (has_username or has_password):
        raise ValueError(ERROR_AUTH_DUAL_CONFIG)

    if has_username != has_password:
        raise ValueError(ERROR_AUTH_BASIC_INCOMPLETE)

    url_lower = config.base_url.lower()
    if url_lower.startswith("http://"):
        if not config.allow_insecure_connections:
            raise ValueError(ERROR_INSECURE_HTTP)
        logger.warning(WARN_INSECURE_CONNECTION, base_url=config.base_url)


def _build_http_client(config: PdpConfig) -> httpx.AsyncClient:
    auth: httpx.Auth | None = None

    if config.token is not None:
        auth = _BearerAuth(config.token)
    elif config.username is not None and config.password is not None:
        auth = httpx.BasicAuth(config.username, config.password)

    verify = not config.allow_insecure_connections

    return httpx.AsyncClient(
        base_url=config.base_url,
        auth=auth,
        timeout=httpx.Timeout(config.timeout),
        verify=verify,
        headers={
            "Content-Type": "application/json",
        },
    )


class _BearerAuth(httpx.Auth):
    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Any:
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


def _backoff_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    jitter = random.uniform(0, delay * 0.5)
    return delay + jitter
