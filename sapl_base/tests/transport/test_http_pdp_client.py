from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
import respx
from httpx import Response

from sapl_base.transport.http_pdp_client import (
    ERROR_HTTP_BASE_REQUIRED,
    ERROR_HTTP_NON_LOOPBACK,
    ERROR_MIXED_AUTH,
    ERROR_PARTIAL_BASIC_AUTH,
    HttpPdpClient,
    HttpPdpClientOptions,
)
from sapl_base.transport.oauth2 import TokenProvider
from sapl_base.types import (
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationSubscription,
)

_BASE = "http://127.0.0.1:8080"
_DECIDE_ONCE = f"{_BASE}/api/pdp/decide-once"
_DECIDE = f"{_BASE}/api/pdp/decide"
_MULTI_ONCE = f"{_BASE}/api/pdp/multi-decide-all-once"


def _opts(**overrides: Any) -> HttpPdpClientOptions:
    defaults: dict[str, Any] = {"base_url": _BASE}
    defaults.update(overrides)
    return HttpPdpClientOptions(**defaults)


class _FakeProvider:
    def __init__(self, token: str = "tok-A") -> None:
        self.token = token
        self.invalidate_calls = 0

    async def get_access_token(self) -> str:
        return self.token

    def invalidate(self) -> None:
        self.invalidate_calls += 1
        self.token = "tok-B"


class TestConstruction:
    def test_missing_base_url_rejected(self) -> None:
        with pytest.raises(ValueError, match=ERROR_HTTP_BASE_REQUIRED):
            HttpPdpClient(HttpPdpClientOptions(base_url=""))

    def test_plaintext_http_to_non_loopback_rejected(self) -> None:
        with pytest.raises(ValueError, match=re.escape(ERROR_HTTP_NON_LOOPBACK)):
            HttpPdpClient(HttpPdpClientOptions(base_url="http://remote.example/"))

    def test_plaintext_http_loopback_is_allowed(self) -> None:
        HttpPdpClient(_opts(base_url="http://localhost:8080"))

    def test_mixed_auth_rejected(self) -> None:
        with pytest.raises(ValueError, match=re.escape(ERROR_MIXED_AUTH)):
            HttpPdpClient(_opts(token="t", username="u", secret="s"))

    def test_partial_basic_auth_rejected(self) -> None:
        with pytest.raises(ValueError, match=re.escape(ERROR_PARTIAL_BASIC_AUTH)):
            HttpPdpClient(_opts(username="u"))


@pytest.mark.asyncio
class TestDecideOnce:
    async def test_returns_permit_when_pdp_replies_permit(self) -> None:
        async with _client_for_test() as client:
            with respx.mock() as mock:
                mock.post(_DECIDE_ONCE).mock(
                    return_value=Response(200, json={"decision": "PERMIT"})
                )
                decision = await client.decide_once(AuthorizationSubscription(action="read"))
                assert decision.decision == Decision.PERMIT

    async def test_returns_indeterminate_on_http_500(self) -> None:
        async with _client_for_test() as client:
            with respx.mock() as mock:
                mock.post(_DECIDE_ONCE).mock(return_value=Response(500, json={}))
                decision = await client.decide_once(AuthorizationSubscription())
                assert decision.decision == Decision.INDETERMINATE

    async def test_returns_indeterminate_on_garbage_response_shape(self) -> None:
        async with _client_for_test() as client:
            with respx.mock() as mock:
                mock.post(_DECIDE_ONCE).mock(
                    return_value=Response(200, json={"decision": "BANANA"})
                )
                decision = await client.decide_once(AuthorizationSubscription())
                assert decision.decision == Decision.INDETERMINATE

    async def test_decodes_suspend_verb(self) -> None:
        async with _client_for_test() as client:
            with respx.mock() as mock:
                mock.post(_DECIDE_ONCE).mock(
                    return_value=Response(200, json={"decision": "SUSPEND"})
                )
                decision = await client.decide_once(AuthorizationSubscription())
                assert decision.decision == Decision.SUSPEND

    async def test_401_with_token_provider_invalidates_and_retries_once(self) -> None:
        provider = _FakeProvider()
        async with _client_for_test(token_provider=provider) as client:
            with respx.mock() as mock:
                route = mock.post(_DECIDE_ONCE).mock(
                    side_effect=[
                        Response(401),
                        Response(200, json={"decision": "PERMIT"}),
                    ]
                )
                decision = await client.decide_once(AuthorizationSubscription())
                assert decision.decision == Decision.PERMIT
                assert provider.invalidate_calls == 1
                assert route.call_count == 2

    async def test_401_with_no_token_provider_returns_indeterminate(self) -> None:
        async with _client_for_test() as client:
            with respx.mock() as mock:
                mock.post(_DECIDE_ONCE).mock(return_value=Response(401))
                decision = await client.decide_once(AuthorizationSubscription())
                assert decision.decision == Decision.INDETERMINATE

    async def test_redacts_secrets_in_log_summary(self) -> None:
        from sapl_base.transport.http_pdp_client import _summarise_subscription
        summary = _summarise_subscription(
            AuthorizationSubscription(
                subject="alice",
                action="read",
                secrets={"api_key": "should-not-leak"},
            )
        )
        assert "secrets" not in summary["fields"]


@pytest.mark.asyncio
class TestMultiDecideAllOnce:
    async def test_returns_flat_id_to_decision_map(self) -> None:
        async with _client_for_test() as client:
            with respx.mock() as mock:
                mock.post(_MULTI_ONCE).mock(
                    return_value=Response(
                        200,
                        json={
                            "a": {"decision": "PERMIT"},
                            "b": {"decision": "DENY"},
                        },
                    )
                )
                subscription = MultiAuthorizationSubscription(
                    subscriptions={
                        "a": AuthorizationSubscription(action="read"),
                        "b": AuthorizationSubscription(action="write"),
                    }
                )
                result = await client.multi_decide_all_once(subscription)
                assert result.decisions["a"].decision == Decision.PERMIT
                assert result.decisions["b"].decision == Decision.DENY

    async def test_empty_decisions_on_transport_error(self) -> None:
        async with _client_for_test() as client:
            with respx.mock() as mock:
                mock.post(_MULTI_ONCE).mock(return_value=Response(503))
                subscription = MultiAuthorizationSubscription(
                    subscriptions={"a": AuthorizationSubscription()}
                )
                result = await client.multi_decide_all_once(subscription)
                assert result.decisions == {}


@pytest.mark.asyncio
class TestStreaming:
    async def test_yields_decoded_frames(self) -> None:
        sse_body = b'data: {"decision":"PERMIT"}\n\ndata: {"decision":"DENY"}\n\n'
        async with _client_for_test(streaming_retry_base_delay_seconds=5.0) as client:
            with respx.mock() as mock:
                mock.post(_DECIDE).mock(
                    return_value=Response(200, content=sse_body, headers={"content-type": "text/event-stream"})
                )
                decisions = await _drain(client.decide(AuthorizationSubscription()))
                verbs = [d.decision for d in decisions]
                assert Decision.PERMIT in verbs
                assert Decision.DENY in verbs

    async def test_skips_comment_and_blank_lines(self) -> None:
        sse_body = b': keep-alive\n\n\ndata: {"decision":"PERMIT"}\n\n'
        async with _client_for_test(streaming_retry_base_delay_seconds=5.0) as client:
            with respx.mock() as mock:
                mock.post(_DECIDE).mock(
                    return_value=Response(200, content=sse_body)
                )
                decisions = await _drain(client.decide(AuthorizationSubscription()))
                assert any(d.decision == Decision.PERMIT for d in decisions)

    async def test_seeds_indeterminate_on_reconnect_after_error(self) -> None:
        sse_body_a = b'data: {"decision":"PERMIT"}\n\n'
        sse_body_b = b'data: {"decision":"DENY"}\n\n'
        async with _client_for_test(
            streaming_retry_base_delay_seconds=0.01,
            streaming_retry_max_delay_seconds=0.05,
        ) as client:
            with respx.mock() as mock:
                mock.post(_DECIDE).mock(
                    side_effect=[
                        Response(200, content=sse_body_a),
                        Response(500),
                        Response(200, content=sse_body_b),
                    ]
                )
                decisions = await _take(client.decide(AuthorizationSubscription()), 3)
                verbs = [d.decision for d in decisions]
                assert Decision.PERMIT in verbs
                assert Decision.INDETERMINATE in verbs
                assert Decision.DENY in verbs

    async def test_dedupes_consecutive_equal_decisions_within_attempt(self) -> None:
        sse_body = b'data: {"decision":"PERMIT"}\n\ndata: {"decision":"PERMIT"}\n\n'
        async with _client_for_test(streaming_retry_base_delay_seconds=5.0) as client:
            with respx.mock() as mock:
                mock.post(_DECIDE).mock(return_value=Response(200, content=sse_body))
                decisions = await _drain(client.decide(AuthorizationSubscription()))
                permits = [d for d in decisions if d.decision == Decision.PERMIT]
                assert len(permits) == 1


# ---- helpers ----

class _ClientCtx:
    def __init__(self, **opts: object) -> None:
        self._client = HttpPdpClient(_opts(**opts))

    async def __aenter__(self) -> HttpPdpClient:
        return self._client

    async def __aexit__(self, *_: object) -> None:
        await self._client.close()


def _client_for_test(**opts: object) -> _ClientCtx:
    return _ClientCtx(**opts)


async def _drain(iterator: AsyncIterator[object], limit_seconds: float = 1.0) -> list[object]:
    items: list[object] = []
    async def _collect() -> None:
        async for item in iterator:
            items.append(item)
    try:
        await asyncio.wait_for(_collect(), timeout=limit_seconds)
    except asyncio.TimeoutError:
        pass
    return items


async def _take(iterator: AsyncIterator[object], count: int, limit_seconds: float = 2.0) -> list[object]:
    """Take the first `count` items from a (now never-ending) subscription, then stop."""
    items: list[object] = []
    async def _collect() -> None:
        async for item in iterator:
            items.append(item)
            if len(items) >= count:
                break
    try:
        await asyncio.wait_for(_collect(), timeout=limit_seconds)
    except asyncio.TimeoutError:
        pass
    return items
