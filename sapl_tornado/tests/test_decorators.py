from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import tornado.testing
import tornado.web

import sapl_tornado.dependencies as deps
from sapl_base.types import AuthorizationDecision, Decision
from sapl_tornado import SaplConfig
from sapl_tornado.decorators import (
    _extract_class_name,
    _extract_request_and_handler,
    _resolve_args,
    post_enforce,
    pre_enforce,
)


def _permit() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT)


def _deny() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.DENY)


class _SaplTestCase(tornado.testing.AsyncHTTPTestCase):
    """Base: configures SAPL with a real planner + a mocked PDP `decide_once`.

    Subclasses set `self.mock_decide.return_value = ...` per test and
    implement `get_app()`.
    """

    def setUp(self) -> None:
        deps.configure_sapl(SaplConfig(base_url="http://localhost:8443"))
        self.mock_decide = AsyncMock()
        deps.get_pdp_client().decide_once = self.mock_decide  # type: ignore[method-assign]
        super().setUp()

    def tearDown(self) -> None:
        super().tearDown()
        deps._runtime._reset_for_tests()


class TestPreEnforcePermitFlow(_SaplTestCase):
    def get_app(self) -> tornado.web.Application:
        class DataHandler(tornado.web.RequestHandler):
            @pre_enforce()
            async def get(self) -> dict[str, Any]:
                return {"value": "sensitive"}

        return tornado.web.Application([(r"/data", DataHandler)])

    def test_returns_200_on_permit(self) -> None:
        self.mock_decide.return_value = _permit()
        response = self.fetch("/data")
        assert response.code == 200
        assert json.loads(response.body) == {"value": "sensitive"}

    def test_subscription_includes_request_context(self) -> None:
        self.mock_decide.return_value = _permit()
        self.fetch("/data")
        subscription = self.mock_decide.call_args[0][0]
        assert subscription.action["method"] == "GET"
        assert subscription.action["handler"] == "get"


class TestPreEnforceDenyFlow(_SaplTestCase):
    def get_app(self) -> tornado.web.Application:
        class SecretHandler(tornado.web.RequestHandler):
            @pre_enforce()
            async def get(self) -> dict[str, Any]:
                return {"secret": "should-not-reach"}

        return tornado.web.Application([(r"/secret", SecretHandler)])

    def test_returns_403_on_deny(self) -> None:
        self.mock_decide.return_value = _deny()
        response = self.fetch("/secret")
        assert response.code == 403

    def test_returns_403_on_indeterminate(self) -> None:
        self.mock_decide.return_value = AuthorizationDecision.indeterminate()
        response = self.fetch("/secret")
        assert response.code == 403


class TestPreEnforceCustomSubscription(_SaplTestCase):
    def get_app(self) -> tornado.web.Application:
        class StaticHandler(tornado.web.RequestHandler):
            @pre_enforce(subject="admin", action="read", resource="documents")
            async def get(self) -> dict[str, Any]:
                return {"data": "value"}

        class CallableHandler(tornado.web.RequestHandler):
            @pre_enforce(subject=lambda ctx: f"user-via-{ctx.request.method}")
            async def get(self) -> dict[str, Any]:
                return {"data": "value"}

        return tornado.web.Application([
            (r"/static", StaticHandler),
            (r"/callable", CallableHandler),
        ])

    def test_static_field_overrides(self) -> None:
        self.mock_decide.return_value = _permit()
        self.fetch("/static")
        subscription = self.mock_decide.call_args[0][0]
        assert subscription.subject == "admin"
        assert subscription.action == "read"
        assert subscription.resource == "documents"

    def test_callable_field_overrides(self) -> None:
        self.mock_decide.return_value = _permit()
        self.fetch("/callable")
        subscription = self.mock_decide.call_args[0][0]
        assert subscription.subject == "user-via-GET"


class TestPostEnforcePermitFlow(_SaplTestCase):
    def get_app(self) -> tornado.web.Application:
        class DataHandler(tornado.web.RequestHandler):
            @post_enforce()
            async def get(self) -> dict[str, Any]:
                return {"value": "result"}

        return tornado.web.Application([(r"/data", DataHandler)])

    def test_returns_200_on_permit(self) -> None:
        self.mock_decide.return_value = _permit()
        response = self.fetch("/data")
        assert response.code == 200
        assert json.loads(response.body) == {"value": "result"}


class TestPostEnforceDenyFlow(_SaplTestCase):
    def get_app(self) -> tornado.web.Application:
        class DataHandler(tornado.web.RequestHandler):
            @post_enforce()
            async def get(self) -> dict[str, Any]:
                return {"value": "result"}

        return tornado.web.Application([(r"/data", DataHandler)])

    def test_returns_403_on_deny(self) -> None:
        self.mock_decide.return_value = _deny()
        response = self.fetch("/data")
        assert response.code == 403


class TestExtractRequestAndHandler:
    def test_finds_handler_in_positional_args(self) -> None:
        handler = MagicMock(spec=tornado.web.RequestHandler)
        handler.request = MagicMock()
        request, found_handler = _extract_request_and_handler((handler,), {})
        assert found_handler is handler
        assert request is handler.request

    def test_returns_none_when_no_handler_present(self) -> None:
        request, handler = _extract_request_and_handler(("not-a-handler",), {"key": "value"})
        assert request is None
        assert handler is None


def _module_level_function() -> None:
    pass


class _TestPatientService:
    def get_patient(self) -> None:
        pass


class _TestOuter:
    class Inner:
        def method(self) -> None:
            pass


class TestExtractClassName:
    def test_plain_function_returns_empty_string(self) -> None:
        assert _extract_class_name(_module_level_function) == ""

    def test_method_returns_class_name(self) -> None:
        assert _extract_class_name(_TestPatientService.get_patient) == "_TestPatientService"

    def test_nested_class_returns_inner_class_name(self) -> None:
        assert _extract_class_name(_TestOuter.Inner.method) == "Inner"


class TestResolveArgs:
    def test_resolves_positional_args(self) -> None:
        def my_handler(patient_id: str, amount: float):
            pass

        assert _resolve_args(my_handler, ("P-001", 100.0), {}) == {
            "patient_id": "P-001", "amount": 100.0,
        }

    def test_excludes_request_handler_instances(self) -> None:
        handler = MagicMock(spec=tornado.web.RequestHandler)

        def my_handler(self, patient_id: str):
            pass

        result = _resolve_args(my_handler, (handler, "P-001"), {})
        assert result == {"patient_id": "P-001"}

    def test_applies_defaults(self) -> None:
        def my_handler(name: str, limit: int = 10):
            pass

        assert _resolve_args(my_handler, ("test",), {}) == {"name": "test", "limit": 10}

    def test_excludes_self(self) -> None:
        class MyService:
            def get_data(self, patient_id: str):
                pass

        result = _resolve_args(MyService.get_data, (MyService(), "P-001"), {})
        assert "self" not in result
        assert result == {"patient_id": "P-001"}
