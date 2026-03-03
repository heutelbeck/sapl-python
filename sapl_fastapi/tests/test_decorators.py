from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

import sapl_fastapi.dependencies as deps
from sapl_base.constraint_bundle import ConstraintHandlerBundle
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.pdp_client import PdpClient
from sapl_base.types import AuthorizationDecision, Decision
from sapl_fastapi.decorators import (
    _extract_class_name,
    _extract_request,
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
    """Patch sapl_fastapi.dependencies module globals with mocks.

    Returns a tuple of (mock_pdp_client, mock_constraint_service).
    """
    mock_pdp = MagicMock(spec=PdpClient)
    mock_pdp.decide_once = AsyncMock()
    mock_service = MagicMock(spec=ConstraintEnforcementService)
    monkeypatch.setattr(deps, "_pdp_client", mock_pdp)
    monkeypatch.setattr(deps, "_constraint_service", mock_service)
    return mock_pdp, mock_service


class TestPreEnforcePermitFlow:
    """Verify @pre_enforce returns 200 when PDP permits."""

    def test_returns_200_on_permit(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_permit_decision()
        mock_service.pre_enforce_bundle_for.return_value = _make_passthrough_bundle()

        app = FastAPI()

        @app.get("/data")
        @pre_enforce()
        async def get_data(request: Request):
            return {"value": "sensitive"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 200
        assert response.json() == {"value": "sensitive"}

    def test_subscription_includes_request_context(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_permit_decision()
        mock_service.pre_enforce_bundle_for.return_value = _make_passthrough_bundle()

        app = FastAPI()

        @app.post("/items/{item_id}")
        @pre_enforce()
        async def update_item(item_id: str, request: Request):
            return {"id": item_id}

        client = TestClient(app)
        client.post("/items/42")

        subscription = mock_pdp.decide_once.call_args[0][0]
        assert subscription.action["method"] == "POST"
        assert subscription.action["handler"] == "update_item"
        assert subscription.resource["path"] == "/items/42"


class TestPreEnforceDenyFlow:
    """Verify @pre_enforce returns 403 when PDP denies."""

    def test_returns_403_on_deny(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_deny_decision()
        mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        app = FastAPI()

        @app.get("/secret")
        @pre_enforce()
        async def get_secret(request: Request):
            return {"secret": "should-not-reach"}

        client = TestClient(app)
        response = client.get("/secret")
        assert response.status_code == 403

    def test_returns_403_on_indeterminate(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = AuthorizationDecision.indeterminate()
        mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        app = FastAPI()

        @app.get("/data")
        @pre_enforce()
        async def get_data(request: Request):
            return {"data": "value"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 403


class TestPreEnforceOnDenyCallback:
    """Verify on_deny callback returns custom response instead of 403."""

    def test_on_deny_returns_custom_response(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_deny_decision()
        mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        def custom_deny_handler(decision: AuthorizationDecision):
            return {"error": "custom_denied", "decision": decision.decision.value}

        app = FastAPI()

        @app.get("/data")
        @pre_enforce(on_deny=custom_deny_handler)
        async def get_data(request: Request):
            return {"data": "value"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 200
        body = response.json()
        assert body["error"] == "custom_denied"
        assert body["decision"] == "DENY"


class TestPreEnforceCustomSubscription:
    """Verify custom subscription fields (static and callable)."""

    def test_static_field_overrides(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_permit_decision()
        mock_service.pre_enforce_bundle_for.return_value = _make_passthrough_bundle()

        app = FastAPI()

        @app.get("/data")
        @pre_enforce(subject="admin", action="read", resource="documents")
        async def get_data(request: Request):
            return {"data": "value"}

        client = TestClient(app)
        client.get("/data")

        subscription = mock_pdp.decide_once.call_args[0][0]
        assert subscription.subject == "admin"
        assert subscription.action == "read"
        assert subscription.resource == "documents"

    def test_callable_field_overrides(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_permit_decision()
        mock_service.pre_enforce_bundle_for.return_value = _make_passthrough_bundle()

        def dynamic_subject(ctx) -> str:
            return f"user-via-{ctx.request.method}"

        app = FastAPI()

        @app.get("/data")
        @pre_enforce(subject=dynamic_subject)
        async def get_data(request: Request):
            return {"data": "value"}

        client = TestClient(app)
        client.get("/data")

        subscription = mock_pdp.decide_once.call_args[0][0]
        assert subscription.subject == "user-via-GET"


class TestPostEnforcePermitFlow:
    """Verify @post_enforce returns 200 when PDP permits."""

    def test_returns_200_on_permit(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_permit_decision()
        mock_service.post_enforce_bundle_for.return_value = _make_passthrough_bundle()

        app = FastAPI()

        @app.get("/data")
        @post_enforce()
        async def get_data(request: Request):
            return {"value": "result"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 200
        assert response.json() == {"value": "result"}


class TestPostEnforceDenyFlow:
    """Verify @post_enforce returns 403 when PDP denies."""

    def test_returns_403_on_deny(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_deny_decision()
        mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        app = FastAPI()

        @app.get("/data")
        @post_enforce()
        async def get_data(request: Request):
            return {"value": "result"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 403

    def test_on_deny_returns_custom_response(self, _mock_sapl):
        mock_pdp, mock_service = _mock_sapl
        mock_pdp.decide_once.return_value = _make_deny_decision()
        mock_service.best_effort_bundle_for.return_value = _make_passthrough_bundle()

        def custom_deny(decision: AuthorizationDecision):
            return {"denied": True}

        app = FastAPI()

        @app.get("/data")
        @post_enforce(on_deny=custom_deny)
        async def get_data(request: Request):
            return {"value": "result"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 200
        assert response.json() == {"denied": True}


class TestExtractRequest:
    """Verify _extract_request finds Request from various argument positions."""

    def test_finds_request_in_positional_args(self):
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "root_path": "", "headers": [], "path_params": {}}
        request = Request(scope)
        result = _extract_request((request,), {})
        assert result is request

    def test_finds_request_in_named_kwarg(self):
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "root_path": "", "headers": [], "path_params": {}}
        request = Request(scope)
        result = _extract_request((), {"request": request})
        assert result is request

    def test_finds_request_in_arbitrary_kwarg(self):
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "root_path": "", "headers": [], "path_params": {}}
        request = Request(scope)
        result = _extract_request((), {"req": request})
        assert result is request

    def test_returns_none_when_no_request_present(self):
        result = _extract_request(("not-a-request",), {"key": "value"})
        assert result is None


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
    """Verify _resolve_args maps arguments to names, excluding Request."""

    def test_resolves_positional_args(self):
        def my_handler(patient_id: str, amount: float):
            pass

        result = _resolve_args(my_handler, ("P-001", 100.0), {})
        assert result == {"patient_id": "P-001", "amount": 100.0}

    def test_excludes_request_instances(self):
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "root_path": "", "headers": [], "path_params": {}}
        request = Request(scope)

        def my_handler(request: Request, patient_id: str):
            pass

        result = _resolve_args(my_handler, (request, "P-001"), {})
        assert "request" not in result
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
