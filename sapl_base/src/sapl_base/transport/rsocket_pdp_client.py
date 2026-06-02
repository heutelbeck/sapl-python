"""RSocket transport for the SAPL PDP client.

Wire surface required by the SAPL Node:

- Setup-payload auth metadata: `<well-known-type-byte><auth-payload>`.
  Type byte is `0x80 | type_id` (SIMPLE=0, BEARER=1). No composite
  metadata wrapper.
- Per-request metadata: the bare UTF-8 bytes of the route name
  (e.g. `b"decide-once"`). The acceptor performs byte-equality
  matching against pre-encoded route tables; composite metadata
  with a routing sub-entry is rejected.
- Per-request data: protobuf-encoded `AuthorizationSubscription`
  or `MultiAuthorizationSubscription`.
- `request_stream` initial-request-N: `0x7FFFFFFF` (31-bit unsigned
  max). Larger values overflow on the server side.

TLS via `asyncio.open_connection(host, port, ssl=ssl_context)`:
the caller builds the SSL context from `TlsConfig`, opens the
encrypted stream, and hands the reader/writer pair to rsocket-py's
`TransportTCP`.

Fail-closed: all error paths surface `INDETERMINATE` (one-shot)
or terminate the iterator after emitting `INDETERMINATE` (stream).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import structlog
from rsocket.exceptions import RSocketError
from rsocket.extensions.authentication import (
    AuthenticationBearer,
    AuthenticationSimple,
)
from rsocket.extensions.authentication_types import WellKnownAuthenticationTypes
from rsocket.frame_helpers import ensure_bytes
from rsocket.payload import Payload
from rsocket.rsocket_client import RSocketClient
from rsocket.transports.tcp import TransportTCP

from sapl_base.transport.codec.sapl_proto_codec import (
    decode_decision,
    decode_identifiable_decision,
    decode_multi_decision,
    encode_multi_subscription,
    encode_subscription,
)
from sapl_base.transport.constants import (
    DEFAULT_RETRY_BASE_DELAY_SECONDS,
    DEFAULT_RETRY_MAX_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    LOOPBACK_HOSTS,
    PdpRoute,
)
from sapl_base.transport.oauth2 import TokenProvider
from sapl_base.transport.tls_config import TlsConfig
from sapl_base.types import (
    AuthorizationDecision,
    AuthorizationSubscription,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
)

logger = structlog.get_logger(__name__)

DEFAULT_RSOCKET_PORT = 7000
INITIAL_REQUEST_N = 0x7FFFFFFF

ERROR_HOST_REQUIRED = "RsocketPdpClient requires a host (or base_url to derive it)."
ERROR_MIXED_AUTH = (
    "PDP authentication conflict: more than one of (token, username/secret, "
    "token_provider) is configured. Use exactly one."
)
ERROR_NON_LOOPBACK_PLAINTEXT = (
    "RSocket connection without TLS targets a non-loopback host. "
    "Plaintext authorization decisions to a remote host are refused. "
    "Configure tls=... or run the PDP on localhost."
)
ERROR_PARTIAL_BASIC_AUTH = (
    "PDP Basic Auth requires both username and secret to be configured."
)


@dataclass(frozen=True, slots=True)
class RsocketPdpClientOptions:
    """Configuration for `RsocketPdpClient`.

    Pass `host` directly, or pass `base_url` and let the client
    derive the host from it. Auth options (`token`, `username`/
    `secret`, `token_provider`) are mutually exclusive.
    """

    host: str | None = None
    port: int = DEFAULT_RSOCKET_PORT
    base_url: str | None = None
    token: str | None = None
    username: str | None = None
    secret: str | None = None
    token_provider: TokenProvider | None = None
    tls: TlsConfig | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    streaming_retry_base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS
    streaming_retry_max_delay_seconds: float = DEFAULT_RETRY_MAX_DELAY_SECONDS


def _is_loopback(host: str) -> bool:
    return host.lower() in LOOPBACK_HOSTS


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with multiplicative jitter (0.5-1.0)."""
    raw_delay = min(base * (2 ** (attempt - 1)), cap)
    return raw_delay * (0.5 + random.random() * 0.5)


def _setup_metadata_simple(username: str, password: str) -> bytes:
    type_id = WellKnownAuthenticationTypes.SIMPLE.value.id
    return bytes([0x80 | type_id]) + AuthenticationSimple(username, password).serialize()


def _setup_metadata_bearer(token: str) -> bytes:
    type_id = WellKnownAuthenticationTypes.BEARER.value.id
    return bytes([0x80 | type_id]) + AuthenticationBearer(token).serialize()


class RsocketPdpClient:
    """RSocket transport for the SAPL Node PDP API.

    Conforms to the `PdpClient` Protocol. See module docstring for
    the protocol details (route metadata, setup auth, initial-N).
    """

    def __init__(self, options: RsocketPdpClientOptions) -> None:
        host = options.host or self._extract_host(options.base_url)
        if not host:
            raise ValueError(ERROR_HOST_REQUIRED)
        self._validate_auth(options)
        if options.tls is None and not _is_loopback(host):
            raise ValueError(f"{ERROR_NON_LOOPBACK_PLAINTEXT} host: {host}")

        self._host = host
        self._port = options.port
        self._tls = options.tls
        self._token_provider = options.token_provider
        self._static_token: str | None = options.token
        self._username: str | None = options.username
        self._secret: str | None = options.secret
        self._timeout = options.timeout_seconds
        self._retry_base = options.streaming_retry_base_delay_seconds
        self._retry_cap = options.streaming_retry_max_delay_seconds

        self._client: RSocketClient | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connect_lock = asyncio.Lock()
        logger.info("rsocket_pdp_client_configured", host=host, port=options.port)

    @staticmethod
    def _validate_auth(options: RsocketPdpClientOptions) -> None:
        has_token = bool(options.token)
        has_basic = bool(options.username) or bool(options.secret)
        has_provider = options.token_provider is not None
        if sum([has_token, has_basic, has_provider]) > 1:
            raise ValueError(ERROR_MIXED_AUTH)
        if has_basic and not (options.username and options.secret):
            raise ValueError(ERROR_PARTIAL_BASIC_AUTH)

    @staticmethod
    def _extract_host(base_url: str | None) -> str | None:
        if base_url is None:
            return None
        parsed = urlparse(base_url)
        return parsed.hostname

    async def decide_once(
        self, subscription: AuthorizationSubscription
    ) -> AuthorizationDecision:
        payload = await self._request_response(
            PdpRoute.DECIDE_ONCE, encode_subscription(subscription)
        )
        if payload is None:
            return AuthorizationDecision.indeterminate()
        return decode_decision(payload.data or b"")

    async def multi_decide_all_once(
        self, subscription: MultiAuthorizationSubscription
    ) -> MultiAuthorizationDecision:
        payload = await self._request_response(
            PdpRoute.MULTI_DECIDE_ALL_ONCE, encode_multi_subscription(subscription)
        )
        if payload is None:
            return MultiAuthorizationDecision()
        return decode_multi_decision(payload.data or b"")

    def decide(
        self, subscription: AuthorizationSubscription
    ) -> AsyncIterator[AuthorizationDecision]:
        return self._request_stream(
            route=PdpRoute.DECIDE,
            data=encode_subscription(subscription),
            decode=lambda raw: decode_decision(raw),
            fallback=lambda: AuthorizationDecision.indeterminate(),
        )

    def multi_decide(
        self, subscription: MultiAuthorizationSubscription
    ) -> AsyncIterator[IdentifiableAuthorizationDecision]:
        ids = list(subscription.subscriptions.keys())

        def _decode(raw: bytes) -> IdentifiableAuthorizationDecision | None:
            return decode_identifiable_decision(raw)

        def _fallback() -> IdentifiableAuthorizationDecision:
            return IdentifiableAuthorizationDecision(
                subscription_id=ids[0] if ids else "",
                decision=AuthorizationDecision.indeterminate(),
            )

        return self._request_stream(
            route=PdpRoute.MULTI_DECIDE,
            data=encode_multi_subscription(subscription),
            decode=_decode,
            fallback=_fallback,
        )

    def multi_decide_all(
        self, subscription: MultiAuthorizationSubscription
    ) -> AsyncIterator[MultiAuthorizationDecision]:
        ids = list(subscription.subscriptions.keys())
        return self._request_stream(
            route=PdpRoute.MULTI_DECIDE_ALL,
            data=encode_multi_subscription(subscription),
            decode=lambda raw: decode_multi_decision(raw),
            fallback=lambda: MultiAuthorizationDecision(
                decisions={
                    sid: AuthorizationDecision.indeterminate() for sid in ids
                }
            ),
        )

    async def close(self) -> None:
        async with self._connect_lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except (RSocketError, OSError, asyncio.CancelledError, RuntimeError) as error:
                logger.debug("rsocket_close_warning", error=str(error))
            self._client = None
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass
            self._writer = None

    async def _connect(self) -> RSocketClient:
        async with self._connect_lock:
            if self._client is not None:
                return self._client
            setup_metadata = await self._build_setup_metadata()
            ssl_ctx = None
            if self._tls is not None:
                ssl_ctx, _ = _build_ssl_context_for_rsocket(self._tls, self._host)
            reader, writer = await asyncio.open_connection(
                self._host, self._port, ssl=ssl_ctx
            )
            client = RSocketClient(
                single_transport_provider(TransportTCP(reader, writer)),
                setup_payload=Payload(data=b"", metadata=setup_metadata),
            )
            await client.__aenter__()
            self._client = client
            self._writer = writer
            return client

    async def _build_setup_metadata(self) -> bytes | None:
        if self._token_provider is not None:
            token = await self._token_provider.get_access_token()
            return _setup_metadata_bearer(token)
        if self._static_token:
            return _setup_metadata_bearer(self._static_token)
        if self._username and self._secret:
            return _setup_metadata_simple(self._username, self._secret)
        return None

    async def _request_response(self, route: PdpRoute, data: bytes) -> Payload | None:
        """One-shot request. Fail-closed: any connection-setup or request error
        returns ``None`` (the caller maps it to INDETERMINATE). No retry."""
        try:
            client = await self._connect()
            payload = Payload(data=data, metadata=ensure_bytes(route.value))
            return await asyncio.wait_for(
                client.request_response(payload), timeout=self._timeout
            )
        except (RSocketError, OSError, TimeoutError, RuntimeError) as error:
            if isinstance(error, RSocketError) and self._token_provider is not None:
                self._token_provider.invalidate()
            logger.error(
                "rsocket_request_response_failed",
                route=route.value,
                error=str(error),
                error_type=type(error).__name__,
            )
            await self._reset_connection()
            return None

    async def _request_stream(
        self,
        route: PdpRoute,
        data: bytes,
        decode: Callable[[bytes], Any],
        fallback: Callable[[], Any],
    ) -> AsyncIterator[Any]:
        """Subscription. Never terminates on a transport error or a server-side
        stream completion: emits INDETERMINATE and reconnects with bounded
        exponential backoff, forever. Ends only when the consumer stops iterating
        (`GeneratorExit`) or the client is disposed. Consecutive identical decisions
        are de-duplicated, so exactly one INDETERMINATE is emitted per outage."""
        last: Any = _UNSET
        attempt = 0
        while True:
            connected = False
            try:
                client = await self._connect()
                connected = True
                queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
                publisher = client.request_stream(
                    Payload(data=data, metadata=ensure_bytes(route.value))
                )
                publisher.initial_request_n(INITIAL_REQUEST_N)  # type: ignore[union-attr]
                publisher.subscribe(_QueueSubscriber(queue))  # type: ignore[union-attr]
                while True:
                    kind, value = await queue.get()
                    if kind == "next":
                        attempt = 0
                        decoded = decode(value.data or b"")
                        if decoded is not None and decoded != last:
                            last = decoded
                            yield decoded
                    elif kind == "complete":
                        break
                    elif kind == "error":
                        logger.warning(
                            "rsocket_stream_error", route=route.value, error=str(value)
                        )
                        break
            except (RSocketError, OSError, TimeoutError, RuntimeError) as error:
                logger.warning(
                    "rsocket_stream_reconnecting", route=route.value, error=str(error)
                )
            finally:
                if connected:
                    await self._reset_connection()
            seed = fallback()
            if seed is not None and seed != last:
                last = seed
                yield seed
            attempt += 1
            await asyncio.sleep(_backoff_delay(attempt, self._retry_base, self._retry_cap))

    async def _reset_connection(self) -> None:
        with suppress(RSocketError, OSError, asyncio.CancelledError, RuntimeError):
            await self._close_locked()


async def single_transport_provider(transport: TransportTCP) -> AsyncIterator[TransportTCP]:
    """Yield exactly one transport for `RSocketClient`.

    `RSocketClient` consumes an async-iterator of transports, taking
    a fresh one per connect attempt. For a single connection we
    yield once.
    """
    yield transport


class _QueueSubscriber:
    """Bridges rsocket-py Publisher callbacks into an asyncio.Queue."""

    def __init__(self, queue: asyncio.Queue[tuple[str, Any]]) -> None:
        self._queue = queue
        self._subscription: Any = None

    def on_subscribe(self, subscription: Any) -> None:
        self._subscription = subscription
        subscription.request(INITIAL_REQUEST_N)

    def on_next(self, value: Any, is_complete: bool = False) -> None:
        self._queue.put_nowait(("next", value))
        if is_complete:
            self._queue.put_nowait(("complete", None))

    def on_complete(self) -> None:
        self._queue.put_nowait(("complete", None))

    def on_error(self, exception: Exception) -> None:
        self._queue.put_nowait(("error", exception))


def _build_ssl_context_for_rsocket(tls: TlsConfig, host: str) -> tuple[Any, list[str]]:
    """Build the ssl.SSLContext for the RSocket TCP connection.

    Delegates to the shared PEM-to-SSLContext helper. SNI is selected
    by the caller through `asyncio.open_connection`'s `server_hostname`
    kwarg, not on the context itself.
    """
    from sapl_base.transport.http_pdp_client import _build_ssl_context

    return _build_ssl_context(tls)


_UNSET = object()
