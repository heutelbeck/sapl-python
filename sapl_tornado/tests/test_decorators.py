from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import tornado.testing
import tornado.web

import sapl_tornado.dependencies as deps
from sapl_base.constraint_bundle import ConstraintHandlerBundle
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.pdp_client import PdpClient
from sapl_base.types import AuthorizationDecision, Decision
from sapl_tornado.decorators import (
    _extract_class_name,
    _extract_request_and_handler,
    _resolve_args,
    post_enforce,
    pre_enforce,
)


def _make_permit_decision() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT)


def _make_deny_decision() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.DENY)


def _noop() -> None:
    pass


def _noop_consumer(_v: Any) -> None:
    pass


def _identity(v: Any) -> Any:
    return v


def _always_true(_v: Any) -> bool:
    return True


def _noop_error_handler(_e: Exception) -> None:
    pass


def _identity_error(e: Exception) -> Exception:
    return e


def _noop_method_invocation(_ctx: Any) -> None:
    pass


def _make_passthrough_bundle() -> ConstraintHandlerBundle:
    """Bundle that passes values through unchanged."""
    return ConstraintHandlerBundle(
        on_decision_handlers=_noop,
        method_invocation_handlers=_noop_method_invocation,
        on_next_consumers=_noop_consumer,
        on_next_mappings=_identity,
        filter_predicates=_always_true,
        on_error_handlers=_noop_error_handler,
        on_error_mappings=_identity_error,
    )


@pytest.fixture
def _mock_sapl(monkeypatch):
    """Patch sapl_tornado.dependencies module globals with mocks."""
    mock_pdp = MagicMock(spec=PdpClient)
    mock_pdp.decide_once = AsyncMock()
    mock_service = MagicMock(spec=ConstraintEnforcementService)
    monkeypatch.setattr(deps, "_pdp_client", mock_pdp)
    monkeypatch.setattr(deps, "_constraint_service", mock_service)
    return mock_pdp, mock_service


def _make_app(_mock_sapl) -> tornado.web.Application:
    """Create a Tornado application with test handlers using mock SAPL."""
    _mock_pdp, _mock_service = _mock_sapl

    class PermitDataHandler(tornado.web.RequestHandler):
        @pre_enforce()
        async def get(self):
            return {"value": "sensitive"}

    class DenySecretHandler(tornado.web.RequestHandler):
        @pre_enforce()
        async def get(self):
            return {"secret": "should-not-reach"}

    class PostEnforceDataHandler(tornado.web.RequestHandler):
        @post_enforce()
        async def get(self):
            return {"value": "result"}

    class UpdateItemHandler(tornado.web.RequestHandler):
        @pre_enforce()
        async def post(self, item_id):
            return {"id": item_id}

    class StaticFieldHandler(tornado.web.RequestHandler):
        @pre_enforce(subject="admin", action="read", resource="documents")
        async def get(self):
            return {"data": "value"}

    class CallableFieldHandler(tornado.web.RequestHandler):
        @pre_enforce(subject=lambda ctx: f"user-via-{ctx.request.method}")
        async def get(self):
            return {"data": "value"}

    class OnDenyHandler(tornado.web.RequestHandler):
        @pre_enforce(on_deny=lambda d: {"error": "custom_denied", "decision": d.decision.value})
        async def get(self):
            return {"data": "value"}

    class PostDenyHandler(tornado.web.RequestHandler):
        @post_enforce()
        async def get(self):
            return {"value": "result"}

    class PostOnDenyHandler(tornado.web.RequestHandler):
        @post_enforce(on_deny=lambda d: {"denied": True})
        async def get(self):
            return {"value": "result"}

    return tornado.web.Application([
        (r"/data", PermitDataHandler),
        (r"/secret", DenySecretHandler),
        (r"/post-data", PostEnforceDataHandler),
        (r"/items/([^/]+)", UpdateItemHandler),
        (r"/static-fields", StaticFieldHandler),
        (r"/callable-fields", CallableFieldHandler),
        (r"/on-deny", OnDenyHandler),
        (r"/post-deny", PostDenyHandler),
        (r"/post-on-deny", PostOnDenyHandler),
    ])


class TestPreEnforcePermitFlow(tornado.testing.AsyncHTTPTestCase):
    """Verify @pre_enforce returns 200 when PDP permits."""

    def setUp(self):
        self.mock_pdp = MagicMock(spec=PdpClient)
        self.mock_pdp.decide_once = AsyncMock()
        self.mock_service = MagicMock(spec=ConstraintEnforcementService)
        self._orig_pdp = deps._pdp_client
        self._orig_service = deps._constraint_service
        deps._pdp_client = self.mock_pdp
        deps._constraint_service = self.mock_service
        super().setUp()

    def tearDown(self):
        super().tearDown()
        deps._pdp_client = self._orig_pdp
        deps._constraint_service = self._orig_service

    def get_app(self):
        class DataHandler(tornado.web.RequestHandler):
            @pre_enforce()
            async def get(self):
                return {"value": "sensitive"}

        return tornado.web.Application([(r"/data", DataHandler)])

    def test_returns_200_on_permit(self):
        self.mock_pdp.decide_once.return_value = _make_permit_decision()
        self.mock_service.pre_enforce_bundle_for.return_value = _make_passthrough_bundle()

        response = self.fetch("/data")
        assert response.code == 200
        body = json.loads(response.body)
        assert body == {"value": "sensitive"}

    def test_subscription_includes_request_context(self):
        self.mock_pdp.decide_once.return_value = _make_permit_decision()
        self.mock_service.pre_enforce_bundle_for.return_value = _make_passthrough_bundle()

        self.fetch("/data")

        subscription = self.mock_pdp.decide_once.call_args[0][0]
        assert subscription.action["method"] == "GET"
        assert subscription.action["handler"] == "get"


class TestPreEnforceDenyFlow(tornado.testing.AsyncHTTPTestCase):
    """Verify @pre_enforce returns 403 when PDP denies."""

    def setUp(self):
        self.mock_pdp = MagicMock(spec=PdpClient)
        self.mock_pdp.decide_once = AsyncMock()
        self.mock_service = MagicMock(spec=ConstraintEnforcementService)
        self._orig_pdp = deps._pdp_client
        self._orig_service = deps._constraint_service
        deps._pdp_client = self.mock_pdp
        deps._constraint_service = self.mock_service
        super().setUp()

    def tearDown(self):
        super().tearDown()
        deps._pdp_client = self._orig_pdp
        deps._constraint_service = self._orig_service

    def get_app(self):
        class SecretHandler(tornado.web.RequestHandler):
            @pre_enforce()
            async def get(self):
                return {"secret": "should-not-reach"}

        return tornado.web.Application([(r"/secret", SecretHandler)])

    def test_returns_403_on_deny(self):
        self.mock_pdp.decide_once.return_value = _make_deny_decision()
        self.mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        response = self.fetch("/secret")
        assert response.code == 403

    def test_returns_403_on_indeterminate(self):
        self.mock_pdp.decide_once.return_value = AuthorizationDecision.indeterminate()
        self.mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        response = self.fetch("/secret")
        assert response.code == 403


class TestPreEnforceOnDenyCallback(tornado.testing.AsyncHTTPTestCase):
    """Verify on_deny callback returns custom response instead of 403."""

    def setUp(self):
        self.mock_pdp = MagicMock(spec=PdpClient)
        self.mock_pdp.decide_once = AsyncMock()
        self.mock_service = MagicMock(spec=ConstraintEnforcementService)
        self._orig_pdp = deps._pdp_client
        self._orig_service = deps._constraint_service
        deps._pdp_client = self.mock_pdp
        deps._constraint_service = self.mock_service
        super().setUp()

    def tearDown(self):
        super().tearDown()
        deps._pdp_client = self._orig_pdp
        deps._constraint_service = self._orig_service

    def get_app(self):
        def custom_deny_handler(decision: AuthorizationDecision):
            return {"error": "custom_denied", "decision": decision.decision.value}

        class DataHandler(tornado.web.RequestHandler):
            @pre_enforce(on_deny=custom_deny_handler)
            async def get(self):
                return {"data": "value"}

        return tornado.web.Application([(r"/data", DataHandler)])

    def test_on_deny_returns_custom_response(self):
        self.mock_pdp.decide_once.return_value = _make_deny_decision()
        self.mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        response = self.fetch("/data")
        assert response.code == 200
        body = json.loads(response.body)
        assert body["error"] == "custom_denied"
        assert body["decision"] == "DENY"


class TestPreEnforceCustomSubscription(tornado.testing.AsyncHTTPTestCase):
    """Verify custom subscription fields (static and callable)."""

    def setUp(self):
        self.mock_pdp = MagicMock(spec=PdpClient)
        self.mock_pdp.decide_once = AsyncMock()
        self.mock_service = MagicMock(spec=ConstraintEnforcementService)
        self._orig_pdp = deps._pdp_client
        self._orig_service = deps._constraint_service
        deps._pdp_client = self.mock_pdp
        deps._constraint_service = self.mock_service
        super().setUp()

    def tearDown(self):
        super().tearDown()
        deps._pdp_client = self._orig_pdp
        deps._constraint_service = self._orig_service

    def get_app(self):
        class StaticHandler(tornado.web.RequestHandler):
            @pre_enforce(subject="admin", action="read", resource="documents")
            async def get(self):
                return {"data": "value"}

        class CallableHandler(tornado.web.RequestHandler):
            @pre_enforce(subject=lambda ctx: f"user-via-{ctx.request.method}")
            async def get(self):
                return {"data": "value"}

        return tornado.web.Application([
            (r"/static", StaticHandler),
            (r"/callable", CallableHandler),
        ])

    def test_static_field_overrides(self):
        self.mock_pdp.decide_once.return_value = _make_permit_decision()
        self.mock_service.pre_enforce_bundle_for.return_value = _make_passthrough_bundle()

        self.fetch("/static")

        subscription = self.mock_pdp.decide_once.call_args[0][0]
        assert subscription.subject == "admin"
        assert subscription.action == "read"
        assert subscription.resource == "documents"

    def test_callable_field_overrides(self):
        self.mock_pdp.decide_once.return_value = _make_permit_decision()
        self.mock_service.pre_enforce_bundle_for.return_value = _make_passthrough_bundle()

        self.fetch("/callable")

        subscription = self.mock_pdp.decide_once.call_args[0][0]
        assert subscription.subject == "user-via-GET"


class TestPostEnforcePermitFlow(tornado.testing.AsyncHTTPTestCase):
    """Verify @post_enforce returns 200 when PDP permits."""

    def setUp(self):
        self.mock_pdp = MagicMock(spec=PdpClient)
        self.mock_pdp.decide_once = AsyncMock()
        self.mock_service = MagicMock(spec=ConstraintEnforcementService)
        self._orig_pdp = deps._pdp_client
        self._orig_service = deps._constraint_service
        deps._pdp_client = self.mock_pdp
        deps._constraint_service = self.mock_service
        super().setUp()

    def tearDown(self):
        super().tearDown()
        deps._pdp_client = self._orig_pdp
        deps._constraint_service = self._orig_service

    def get_app(self):
        class DataHandler(tornado.web.RequestHandler):
            @post_enforce()
            async def get(self):
                return {"value": "result"}

        return tornado.web.Application([(r"/data", DataHandler)])

    def test_returns_200_on_permit(self):
        self.mock_pdp.decide_once.return_value = _make_permit_decision()
        self.mock_service.post_enforce_bundle_for.return_value = _make_passthrough_bundle()

        response = self.fetch("/data")
        assert response.code == 200
        body = json.loads(response.body)
        assert body == {"value": "result"}


class TestPostEnforceDenyFlow(tornado.testing.AsyncHTTPTestCase):
    """Verify @post_enforce returns 403 when PDP denies."""

    def setUp(self):
        self.mock_pdp = MagicMock(spec=PdpClient)
        self.mock_pdp.decide_once = AsyncMock()
        self.mock_service = MagicMock(spec=ConstraintEnforcementService)
        self._orig_pdp = deps._pdp_client
        self._orig_service = deps._constraint_service
        deps._pdp_client = self.mock_pdp
        deps._constraint_service = self.mock_service
        super().setUp()

    def tearDown(self):
        super().tearDown()
        deps._pdp_client = self._orig_pdp
        deps._constraint_service = self._orig_service

    def get_app(self):
        class DataHandler(tornado.web.RequestHandler):
            @post_enforce()
            async def get(self):
                return {"value": "result"}

        class OnDenyHandler(tornado.web.RequestHandler):
            @post_enforce(on_deny=lambda d: {"denied": True})
            async def get(self):
                return {"value": "result"}

        return tornado.web.Application([
            (r"/data", DataHandler),
            (r"/on-deny", OnDenyHandler),
        ])

    def test_returns_403_on_deny(self):
        self.mock_pdp.decide_once.return_value = _make_deny_decision()
        self.mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        response = self.fetch("/data")
        assert response.code == 403

    def test_on_deny_returns_custom_response(self):
        self.mock_pdp.decide_once.return_value = _make_deny_decision()
        self.mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        response = self.fetch("/on-deny")
        assert response.code == 200
        body = json.loads(response.body)
        assert body == {"denied": True}


class TestExtractRequestAndHandler:
    """Verify _extract_request_and_handler finds handler from argument positions."""

    def test_finds_handler_in_positional_args(self):
        handler = MagicMock(spec=tornado.web.RequestHandler)
        handler.request = MagicMock()
        request, found_handler = _extract_request_and_handler((handler,), {})
        assert found_handler is handler
        assert request is handler.request

    def test_returns_none_when_no_handler_present(self):
        request, handler = _extract_request_and_handler(("not-a-handler",), {"key": "value"})
        assert request is None
        assert handler is None


def _module_level_function():
    """Module-level function with single-part qualname."""
    pass


class _TestPatientService:
    """Test class for class name extraction."""

    def get_patient(self):
        pass


class _TestOuter:
    class Inner:
        def method(self):
            pass


class TestExtractClassName:
    """Verify _extract_class_name detects class names from qualified names."""

    def test_plain_function_returns_empty_string(self):
        assert _extract_class_name(_module_level_function) == ""

    def test_method_returns_class_name(self):
        assert _extract_class_name(_TestPatientService.get_patient) == "_TestPatientService"

    def test_nested_class_returns_inner_class_name(self):
        assert _extract_class_name(_TestOuter.Inner.method) == "Inner"


class TestResolveArgs:
    """Verify _resolve_args maps arguments to names, excluding RequestHandler."""

    def test_resolves_positional_args(self):
        def my_handler(patient_id: str, amount: float):
            pass

        result = _resolve_args(my_handler, ("P-001", 100.0), {})
        assert result == {"patient_id": "P-001", "amount": 100.0}

    def test_excludes_request_handler_instances(self):
        handler = MagicMock(spec=tornado.web.RequestHandler)

        def my_handler(self, patient_id: str):
            pass

        result = _resolve_args(my_handler, (handler, "P-001"), {})
        assert result == {"patient_id": "P-001"}

    def test_applies_defaults(self):
        def my_handler(name: str, limit: int = 10):
            pass

        result = _resolve_args(my_handler, ("test",), {})
        assert result == {"name": "test", "limit": 10}

    def test_excludes_self(self):
        class MyService:
            def get_data(self, patient_id: str):
                pass

        result = _resolve_args(MyService.get_data, (MyService(), "P-001"), {})
        assert "self" not in result
        assert result == {"patient_id": "P-001"}
