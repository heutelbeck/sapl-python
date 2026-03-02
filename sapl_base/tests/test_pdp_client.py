from __future__ import annotations

import json

import httpx
import pytest

from sapl_base.pdp_client import (
    ERROR_AUTH_BASIC_INCOMPLETE,
    ERROR_AUTH_DUAL_CONFIG,
    ERROR_INSECURE_HTTP,
    PdpClient,
    PdpConfig,
)
from sapl_base.types import (
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationSubscription,
)


class TestPdpConfigValidation:
    def test_default_config_is_valid(self):
        config = PdpConfig()
        client = PdpClient(config)
        assert client is not None

    def test_rejects_dual_auth_config(self):
        config = PdpConfig(
            token="my-token",
            username="user",
            password="pass",
        )
        with pytest.raises(ValueError, match=ERROR_AUTH_DUAL_CONFIG):
            PdpClient(config)

    def test_rejects_incomplete_basic_auth_username_only(self):
        config = PdpConfig(username="user")
        with pytest.raises(ValueError, match=ERROR_AUTH_BASIC_INCOMPLETE):
            PdpClient(config)

    def test_rejects_incomplete_basic_auth_password_only(self):
        config = PdpConfig(password="pass")
        with pytest.raises(ValueError, match=ERROR_AUTH_BASIC_INCOMPLETE):
            PdpClient(config)

    def test_accepts_complete_basic_auth(self):
        config = PdpConfig(username="user", password="pass")
        client = PdpClient(config)
        assert client is not None

    def test_accepts_bearer_token(self):
        config = PdpConfig(token="my-token")
        client = PdpClient(config)
        assert client is not None

    def test_rejects_http_without_insecure_flag(self):
        config = PdpConfig(base_url="http://localhost:8080")
        with pytest.raises(ValueError, match=ERROR_INSECURE_HTTP):
            PdpClient(config)

    def test_accepts_http_with_insecure_flag(self):
        config = PdpConfig(
            base_url="http://localhost:8080",
            allow_insecure_connections=True,
        )
        client = PdpClient(config)
        assert client is not None

    def test_accepts_https_url(self):
        config = PdpConfig(base_url="https://pdp.example.com")
        client = PdpClient(config)
        assert client is not None

    def test_case_insensitive_http_check(self):
        config = PdpConfig(base_url="HTTP://localhost:8080")
        with pytest.raises(ValueError, match=ERROR_INSECURE_HTTP):
            PdpClient(config)


class TestDecideOnce:
    @pytest.fixture()
    def subscription(self):
        return AuthorizationSubscription(
            subject="alice",
            action="read",
            resource="document",
        )

    async def test_successful_permit(self, httpx_mock, subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            json={"decision": "PERMIT"},
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.decide_once(subscription)
            assert result.decision == Decision.PERMIT
        finally:
            await client.close()

    async def test_successful_deny_with_obligations(self, httpx_mock, subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            json={
                "decision": "DENY",
                "obligations": [{"type": "log"}],
                "advice": [{"info": "reason"}],
            },
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.decide_once(subscription)
            assert result.decision == Decision.DENY
            assert result.obligations == ({"type": "log"},)
            assert result.advice == ({"info": "reason"},)
        finally:
            await client.close()

    async def test_http_error_returns_indeterminate(self, httpx_mock, subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            status_code=500,
            text="Internal Server Error",
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.decide_once(subscription)
            assert result.decision == Decision.INDETERMINATE
        finally:
            await client.close()

    async def test_network_error_returns_indeterminate(self, httpx_mock, subscription):
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://localhost:8443/api/pdp/decide-once",
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.decide_once(subscription)
            assert result.decision == Decision.INDETERMINATE
        finally:
            await client.close()

    async def test_timeout_returns_indeterminate(self, httpx_mock, subscription):
        httpx_mock.add_exception(
            httpx.ReadTimeout("Read timed out"),
            url="https://localhost:8443/api/pdp/decide-once",
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.decide_once(subscription)
            assert result.decision == Decision.INDETERMINATE
        finally:
            await client.close()

    async def test_malformed_json_response_returns_indeterminate(self, httpx_mock, subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            text="not json at all",
            status_code=200,
            headers={"Content-Type": "text/plain"},
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.decide_once(subscription)
            assert result.decision == Decision.INDETERMINATE
        finally:
            await client.close()

    async def test_auth_error_returns_indeterminate(self, httpx_mock, subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            status_code=401,
            text="Unauthorized",
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.decide_once(subscription)
            assert result.decision == Decision.INDETERMINATE
        finally:
            await client.close()

    async def test_bearer_auth_header_sent(self, httpx_mock, subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            json={"decision": "PERMIT"},
        )
        config = PdpConfig(token="my-secret-token")
        client = PdpClient(config)
        try:
            await client.decide_once(subscription)
            request = httpx_mock.get_request()
            assert request is not None
            assert request.headers["Authorization"] == "Bearer my-secret-token"
        finally:
            await client.close()

    async def test_basic_auth_header_sent(self, httpx_mock, subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            json={"decision": "PERMIT"},
        )
        config = PdpConfig(username="user", password="pass")
        client = PdpClient(config)
        try:
            await client.decide_once(subscription)
            request = httpx_mock.get_request()
            assert request is not None
            auth_header = request.headers.get("Authorization", "")
            assert auth_header.startswith("Basic ")
        finally:
            await client.close()

    async def test_secrets_not_in_request_body_when_none(self, httpx_mock, subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            json={"decision": "PERMIT"},
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            await client.decide_once(subscription)
            request = httpx_mock.get_request()
            assert request is not None
            body = json.loads(request.content)
            assert "secrets" not in body
        finally:
            await client.close()

    async def test_secrets_included_in_request_body_when_present(self, httpx_mock):
        sub = AuthorizationSubscription(
            subject="alice",
            action="read",
            resource="doc",
            secrets={"api_key": "secret123"},
        )
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/decide-once",
            json={"decision": "PERMIT"},
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            await client.decide_once(sub)
            request = httpx_mock.get_request()
            assert request is not None
            body = json.loads(request.content)
            assert body["secrets"] == {"api_key": "secret123"}
        finally:
            await client.close()


class TestMultiDecideOnce:
    @pytest.fixture()
    def multi_subscription(self):
        return MultiAuthorizationSubscription(
            subscriptions={
                "sub1": AuthorizationSubscription(subject="alice", action="read"),
                "sub2": AuthorizationSubscription(subject="bob", action="write"),
            }
        )

    async def test_successful_multi_decision(self, httpx_mock, multi_subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/multi-decide-once",
            json={
                "sub1": {"decision": "PERMIT"},
                "sub2": {"decision": "DENY"},
            },
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.multi_decide_once(multi_subscription)
            assert result.decisions["sub1"].decision == Decision.PERMIT
            assert result.decisions["sub2"].decision == Decision.DENY
        finally:
            await client.close()

    async def test_http_error_returns_empty_multi_decision(self, httpx_mock, multi_subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/multi-decide-once",
            status_code=500,
            text="Error",
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.multi_decide_once(multi_subscription)
            assert result.decisions == {}
        finally:
            await client.close()

    async def test_network_error_returns_empty_multi_decision(self, httpx_mock, multi_subscription):
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://localhost:8443/api/pdp/multi-decide-once",
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.multi_decide_once(multi_subscription)
            assert result.decisions == {}
        finally:
            await client.close()


class TestMultiDecideAllOnce:
    @pytest.fixture()
    def multi_subscription(self):
        return MultiAuthorizationSubscription(
            subscriptions={
                "sub1": AuthorizationSubscription(subject="alice"),
            }
        )

    async def test_successful_multi_decide_all(self, httpx_mock, multi_subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/multi-decide-all-once",
            json={
                "sub1": {"decision": "PERMIT"},
            },
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.multi_decide_all_once(multi_subscription)
            assert result.decisions["sub1"].decision == Decision.PERMIT
        finally:
            await client.close()

    async def test_http_error_returns_empty(self, httpx_mock, multi_subscription):
        httpx_mock.add_response(
            url="https://localhost:8443/api/pdp/multi-decide-all-once",
            status_code=503,
            text="Service Unavailable",
        )
        config = PdpConfig()
        client = PdpClient(config)
        try:
            result = await client.multi_decide_all_once(multi_subscription)
            assert result.decisions == {}
        finally:
            await client.close()


class TestClientLifecycle:
    @pytest.mark.httpx_mock(assert_all_requests_were_expected=False)
    async def test_close_returns_indeterminate_on_subsequent_request(self, httpx_mock):
        config = PdpConfig()
        client = PdpClient(config)
        await client.close()
        # After close, requests fail-close to INDETERMINATE (not raise)
        result = await client.decide_once(AuthorizationSubscription())
        assert result.decision == Decision.INDETERMINATE
