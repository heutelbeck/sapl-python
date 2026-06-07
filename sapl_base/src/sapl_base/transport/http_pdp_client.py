"""HTTP transport for the SAPL PDP client.

Implements the `PdpClient` Protocol over the SAPL Node's
`/api/pdp/*` endpoints (JSON for unary, SSE for streaming). Strict
fail-closed: every code path that loses contact with the PDP, or
fails to validate the response, surfaces `INDETERMINATE` rather
than raising.

Reconnection policy:

- 1 s initial backoff, exponential x2 with multiplicative jitter
  (0.5-1.0), 30 s cap, infinite retries by default.
- `INDETERMINATE` seeded on every reconnect attempt so subscribers
  never see a stale decision through a PDP outage.
- Log escalation: WARN for attempts 1-4, ERROR from attempt 5
  onward.
- 401 / 403 calls `token_provider.invalidate()`; one-shot methods
  retry once, streaming methods reconnect through the regular
  backoff path.
- 64 KB SSE buffer cap; an SSE frame larger than the cap aborts
  the connection (which then reconnects).
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from sapl_base.logging_utils import truncate
from sapl_base.transport.constants import (
    DEFAULT_RETRY_BASE_DELAY_SECONDS,
    DEFAULT_RETRY_MAX_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    LOOPBACK_HOSTS,
    MAX_CONSTRAINT_COUNT,
    MAX_SSE_BUFFER_BYTES,
    PDP_API_PREFIX,
    RETRY_ESCALATION_THRESHOLD,
    PdpRoute,
)
from sapl_base.types import (
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from sapl_base.transport.oauth2 import TokenProvider
    from sapl_base.transport.tls_config import TlsConfig

logger = structlog.get_logger(__name__)

ERROR_HTTP_BASE_REQUIRED = "HttpPdpClient requires a base_url."
ERROR_HTTP_NON_LOOPBACK = (
    "PDP base URL uses plain HTTP and targets a non-loopback host. "
    "Plaintext authorization decisions to a remote host are refused. "
    "Use HTTPS (https://...) or run the PDP on localhost."
)
ERROR_MIXED_AUTH = (
    "PDP authentication conflict: more than one of (token, username/secret, "
    "token_provider) is configured. Use exactly one."
)
ERROR_PARTIAL_BASIC_AUTH = (
    "PDP Basic Auth requires both username and secret to be configured."
)

WARN_LOOPBACK_PLAINTEXT_HTTP = (
    "PDP connection uses unencrypted HTTP on loopback. Acceptable for "
    "local dev; production must use HTTPS."
)


@dataclass(frozen=True, slots=True)
class HttpPdpClientOptions:
    """Configuration for `HttpPdpClient`.

    Auth options are mutually exclusive: pass exactly one of
    `token`, (`username` + `secret`), or `token_provider`. Pass none
    when targeting a SAPL Node configured with `allow-no-auth`.
    """

    base_url: str
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


def _summarise_subscription(subscription: AuthorizationSubscription) -> dict[str, Any]:
    loggable = subscription.to_loggable_dict()
    action = loggable.get("action")
    return {
        "fields": sorted(loggable.keys()),
        "action": action if isinstance(action, str) else "<non-string>",
    }


def _summarise_multi(subscription: MultiAuthorizationSubscription) -> dict[str, Any]:
    ids = list(subscription.subscriptions.keys())
    return {"count": len(ids), "ids": ids}


def _warn_if_constraint_oversized(label: str, value: list[Any]) -> None:
    if len(value) > MAX_CONSTRAINT_COUNT:
        logger.warning(
            "constraint_array_oversized",
            label=label,
            count=len(value),
            cap=MAX_CONSTRAINT_COUNT,
        )


def _validate_decision(raw: Any) -> AuthorizationDecision:
    if not isinstance(raw, dict):
        logger.warning("decision_response_not_object", raw_type=type(raw).__name__)
        return AuthorizationDecision.indeterminate()
    verb = raw.get("decision")
    if not isinstance(verb, str):
        logger.warning("decision_field_missing_or_not_string", raw=verb)
        return AuthorizationDecision.indeterminate()
    try:
        decision_enum = Decision(verb)
    except ValueError:
        logger.warning("decision_field_invalid_value", raw=verb)
        return AuthorizationDecision.indeterminate()
    obligations: tuple[Any, ...] = ()
    advice: tuple[Any, ...] = ()
    if isinstance(raw.get("obligations"), list):
        _warn_if_constraint_oversized("obligations", raw["obligations"])
        obligations = tuple(raw["obligations"])
    if isinstance(raw.get("advice"), list):
        _warn_if_constraint_oversized("advice", raw["advice"])
        advice = tuple(raw["advice"])
    if "resource" in raw:
        return AuthorizationDecision(
            decision=decision_enum,
            obligations=obligations,
            advice=advice,
            resource=raw["resource"],
        )
    return AuthorizationDecision(
        decision=decision_enum, obligations=obligations, advice=advice
    )


def _validate_identifiable(raw: Any) -> IdentifiableAuthorizationDecision | None:
    if not isinstance(raw, dict):
        logger.warning("identifiable_response_not_object", raw_type=type(raw).__name__)
        return None
    subscription_id = raw.get("subscriptionId")
    if not isinstance(subscription_id, str) or not subscription_id:
        logger.warning("identifiable_subscription_id_invalid", raw=subscription_id)
        return None
    return IdentifiableAuthorizationDecision(
        subscription_id=subscription_id,
        decision=_validate_decision(raw.get("decision")),
    )


def _validate_multi(raw: Any) -> MultiAuthorizationDecision | None:
    if not isinstance(raw, dict):
        logger.warning("multi_response_not_object", raw_type=type(raw).__name__)
        return None
    decisions: dict[str, AuthorizationDecision] = {}
    for subscription_id, value in raw.items():
        decisions[subscription_id] = _validate_decision(value)
    return MultiAuthorizationDecision(decisions=decisions)


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with multiplicative jitter (0.5-1.0)."""
    raw_delay = min(base * (2 ** (attempt - 1)), cap)
    return raw_delay * (0.5 + random.random() * 0.5)


def _build_ssl_context(tls: TlsConfig) -> tuple[Any, list[str]]:
    """Build a Python ssl.SSLContext from PEM contents in `tls`.

    Returns `(ssl_context, temp_files_to_clean_on_close)`. Client
    cert+key require on-disk PEM files because Python's stdlib
    `SSLContext.load_cert_chain` does not accept in-memory bytes;
    we write them to a private tempdir and return the paths for
    the caller to delete at shutdown.
    """
    import ssl
    import tempfile
    from pathlib import Path

    ctx = ssl.create_default_context()
    if not tls.reject_unauthorized:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if tls.ca is not None:
        ca_text = tls.ca.decode() if isinstance(tls.ca, bytes) else tls.ca
        ctx.load_verify_locations(cadata=ca_text)
    temp_files: list[str] = []
    if tls.cert is not None and tls.key is not None:
        combined = b""
        for part in (tls.cert, tls.key):
            combined += part.encode() if isinstance(part, str) else part
            if not combined.endswith(b"\n"):
                combined += b"\n"
        fd, path = tempfile.mkstemp(prefix="sapl-mtls-", suffix=".pem")
        try:
            with open(fd, "wb") as handle:
                handle.write(combined)
        finally:
            pass
        Path(path).chmod(0o600)
        ctx.load_cert_chain(certfile=path)
        temp_files.append(path)
    return ctx, temp_files


class HttpPdpClient:
    """HTTP / SSE transport for the SAPL Node PDP API.

    Conforms to the `PdpClient` Protocol. See module docstring for
    the fail-closed contract and the canonical reconnection policy.
    """

    def __init__(self, options: HttpPdpClientOptions) -> None:
        if not options.base_url:
            raise ValueError(ERROR_HTTP_BASE_REQUIRED)
        self._validate_auth(options)
        parsed = urlparse(options.base_url)
        if parsed.scheme == "http":
            if not parsed.hostname or not _is_loopback(parsed.hostname):
                raise ValueError(f"{ERROR_HTTP_NON_LOOPBACK} URL: {options.base_url}")
            logger.warning("plaintext_http_on_loopback")

        self._options = options
        self._token_provider = options.token_provider
        self._static_authorization: str | None = self._build_static_authorization(options)
        self._timeout = httpx.Timeout(options.timeout_seconds)
        self._streaming_timeout = httpx.Timeout(
            connect=options.timeout_seconds,
            read=None,
            write=options.timeout_seconds,
            pool=options.timeout_seconds,
        )
        self._retry_base = options.streaming_retry_base_delay_seconds
        self._retry_cap = options.streaming_retry_max_delay_seconds

        self._verify: Any = True
        self._temp_files: list[str] = []
        if options.tls is not None and parsed.scheme == "https":
            self._verify, self._temp_files = _build_ssl_context(options.tls)
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

        base = options.base_url if options.base_url.endswith("/") else options.base_url + "/"
        prefix = urljoin(base, PDP_API_PREFIX.lstrip("/"))
        self._url = {route: urljoin(prefix, route.value) for route in PdpRoute}

        logger.info("http_pdp_client_configured", base_url=options.base_url)

    @staticmethod
    def _validate_auth(options: HttpPdpClientOptions) -> None:
        has_token = bool(options.token)
        has_basic_user = bool(options.username)
        has_basic_secret = bool(options.secret)
        has_basic = has_basic_user or has_basic_secret
        has_provider = options.token_provider is not None
        if sum([has_token, has_basic, has_provider]) > 1:
            raise ValueError(ERROR_MIXED_AUTH)
        if has_basic and not (has_basic_user and has_basic_secret):
            raise ValueError(ERROR_PARTIAL_BASIC_AUTH)

    @staticmethod
    def _build_static_authorization(options: HttpPdpClientOptions) -> str | None:
        if options.token:
            return f"Bearer {options.token}"
        if options.username and options.secret:
            encoded = base64.b64encode(
                f"{options.username}:{options.secret}".encode()
            ).decode()
            return f"Basic {encoded}"
        return None

    async def _resolve_authorization(self) -> str | None:
        if self._token_provider is not None:
            token = await self._token_provider.get_access_token()
            return f"Bearer {token}"
        return self._static_authorization

    async def decide_once(
        self, subscription: AuthorizationSubscription
    ) -> AuthorizationDecision:
        logger.debug(
            "requesting_decision", subscription=_summarise_subscription(subscription)
        )
        raw = await self._post_json(
            self._url[PdpRoute.DECIDE_ONCE], subscription.to_dict()
        )
        if raw is None:
            return AuthorizationDecision.indeterminate()
        decision = _validate_decision(raw)
        logger.debug("decision_received", verb=decision.decision.value)
        return decision

    async def multi_decide_all_once(
        self, subscription: MultiAuthorizationSubscription
    ) -> MultiAuthorizationDecision:
        logger.debug(
            "requesting_multi_decide_all_once",
            subscription=_summarise_multi(subscription),
        )
        raw = await self._post_json(
            self._url[PdpRoute.MULTI_DECIDE_ALL_ONCE],
            subscription.to_dict(),
        )
        if raw is None:
            return MultiAuthorizationDecision()
        return _validate_multi(raw) or MultiAuthorizationDecision()

    def decide(
        self, subscription: AuthorizationSubscription
    ) -> AsyncIterator[AuthorizationDecision]:
        return self._stream_sse(
            url=self._url[PdpRoute.DECIDE],
            body=subscription.to_dict(),
            validate=lambda raw: _validate_decision(raw),
            seed=lambda: AuthorizationDecision.indeterminate(),
        )

    def multi_decide(
        self, subscription: MultiAuthorizationSubscription
    ) -> AsyncIterator[IdentifiableAuthorizationDecision]:
        ids = list(subscription.subscriptions.keys())
        return self._stream_sse(
            url=self._url[PdpRoute.MULTI_DECIDE],
            body=subscription.to_dict(),
            validate=_validate_identifiable,
            seed_many=lambda: [
                IdentifiableAuthorizationDecision(
                    subscription_id=sid,
                    decision=AuthorizationDecision.indeterminate(),
                )
                for sid in ids
            ],
        )

    def multi_decide_all(
        self, subscription: MultiAuthorizationSubscription
    ) -> AsyncIterator[MultiAuthorizationDecision]:
        ids = list(subscription.subscriptions.keys())
        return self._stream_sse(
            url=self._url[PdpRoute.MULTI_DECIDE_ALL],
            body=subscription.to_dict(),
            validate=_validate_multi,
            seed=lambda: MultiAuthorizationDecision(
                decisions={
                    sid: AuthorizationDecision.indeterminate() for sid in ids
                }
            ),
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Return a usable AsyncClient bound to the current event loop.

        Sync frameworks (e.g., Flask under `asyncio.run`) create a fresh
        event loop per request; the AsyncClient bound to a previous
        loop becomes unusable. We detect this and rebuild the client.
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
            self._client = httpx.AsyncClient(timeout=self._timeout, verify=self._verify)
            self._client_loop = current_loop
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        for path in self._temp_files:
            try:
                import os
                os.unlink(path)
            except OSError:
                logger.warning("temp_pem_cleanup_failed", path=path)
        self._temp_files = []

    def _handle_auth_failure(self) -> bool:
        if self._token_provider is None:
            return False
        self._token_provider.invalidate()
        return True

    async def _post_json(
        self, url: str, body: dict[str, Any], retried: bool = False
    ) -> Any | None:
        try:
            headers = {"Content-Type": "application/json"}
            authorization = await self._resolve_authorization()
            if authorization:
                headers["Authorization"] = authorization
            response = await self._get_client().post(url, json=body, headers=headers)
            if response.status_code >= 400:
                excerpt = truncate(response.text or "")
                logger.error(
                    "pdp_returned_http_error",
                    url=url,
                    status=response.status_code,
                    body=excerpt,
                )
                if response.status_code in (401, 403) and self._handle_auth_failure() and not retried:
                    return await self._post_json(url, body, retried=True)
                return None
            return response.json()
        except httpx.TimeoutException:
            logger.error("pdp_request_timed_out", url=url)
            return None
        except httpx.RequestError as error:
            logger.error(
                "pdp_request_failed",
                url=url,
                error=str(error) or repr(error),
                error_type=type(error).__name__,
            )
            return None
        except json.JSONDecodeError as error:
            logger.error("pdp_response_not_json", url=url, error=str(error))
            return None

    async def _stream_sse(
        self,
        url: str,
        body: dict[str, Any],
        validate: Callable[[Any], Any | None],
        seed: Callable[[], Any] | None = None,
        seed_many: Callable[[], list[Any]] | None = None,
    ) -> AsyncIterator[Any]:
        """Subscription. Never terminates: a transport error OR a graceful server
        completion both seed INDETERMINATE and reconnect with bounded exponential
        backoff, forever. Ends only when the consumer stops iterating."""
        attempt = 0
        last_emitted: Any = _UNSET
        while True:
            if attempt > 0:
                delay = _backoff_delay(attempt, self._retry_base, self._retry_cap)
                level = "warning" if attempt < RETRY_ESCALATION_THRESHOLD else "error"
                getattr(logger, level)(
                    "pdp_streaming_reconnect",
                    delay_seconds=round(delay, 2),
                    attempt=attempt,
                )
                if seed_many is not None:
                    for seeded in seed_many():
                        if seeded != last_emitted:
                            last_emitted = seeded
                            yield seeded
                elif seed is not None:
                    seeded = seed()
                    if seeded != last_emitted:
                        last_emitted = seeded
                        yield seeded
                await asyncio.sleep(delay)

            try:
                async for parsed in self._sse_lines(url, body):
                    validated = validate(parsed)
                    if validated is None:
                        continue
                    attempt = 0
                    if validated != last_emitted:
                        last_emitted = validated
                        yield validated
                attempt += 1
            except _SseBufferOverflowError:
                attempt += 1
                logger.error("sse_buffer_overflow", url=url)
            except (httpx.HTTPError, OSError) as error:
                attempt += 1
                logger.warning("pdp_streaming_connection_lost", url=url, error=str(error))

    async def _sse_lines(
        self, url: str, body: dict[str, Any]
    ) -> AsyncIterator[Any]:
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        authorization = await self._resolve_authorization()
        if authorization:
            headers["Authorization"] = authorization
        async with self._get_client().stream(
            "POST", url, json=body, headers=headers, timeout=self._streaming_timeout
        ) as response:
            if response.status_code >= 400:
                excerpt = truncate(
                    (await response.aread()).decode(errors="replace")
                )
                logger.error(
                    "pdp_streaming_http_error",
                    url=url,
                    status=response.status_code,
                    body=excerpt,
                )
                if response.status_code in (401, 403):
                    self._handle_auth_failure()
                raise httpx.HTTPStatusError(
                    f"PDP returned HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                if len(buffer) > MAX_SSE_BUFFER_BYTES:
                    raise _SseBufferOverflowError()
                while "\n" in buffer:
                    line, _, buffer = buffer.partition("\n")
                    trimmed = line.strip()
                    if not trimmed or trimmed.startswith(":"):
                        continue
                    data = trimmed[5:].strip() if trimmed.startswith("data:") else trimmed
                    if not data:
                        continue
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning("sse_frame_not_valid_json", frame=truncate(data))


class _SseBufferOverflowError(Exception):
    """Raised internally when an SSE frame exceeds MAX_SSE_BUFFER_BYTES."""


_UNSET = object()
