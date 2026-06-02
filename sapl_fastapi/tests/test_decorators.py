from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

import sapl_fastapi.dependencies as deps
from sapl_base.types import AuthorizationDecision, Decision
from sapl_fastapi import SaplConfig
from sapl_fastapi.decorators import (
    _extract_class_name,
    _extract_request,
    _resolve_args,
    post_enforce,
    pre_enforce,
)


def _permit() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT)


def _deny() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.DENY)


@pytest.fixture
def _configured(monkeypatch):
    """Configure SAPL with a real planner and a mocked PDP client.

    Returns the AsyncMock attached to the PDP client's `decide_once` so
    tests set its `.return_value` per case.
    """
    deps.configure_sapl(SaplConfig(base_url="http://localhost:8443"))
    mock_decide = AsyncMock()
    monkeypatch.setattr(deps.get_pdp_client(), "decide_once", mock_decide)
    yield mock_decide
    deps._runtime._reset_for_tests()


class TestPreEnforcePermitFlow:
    def test_returns_200_on_permit(self, _configured) -> None:
        _configured.return_value = _permit()
        app = FastAPI()

        @app.get("/data")
        @pre_enforce()
        async def get_data(request: Request):
            return {"value": "sensitive"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 200
        assert response.json() == {"value": "sensitive"}

    def test_subscription_includes_request_context(self, _configured) -> None:
        _configured.return_value = _permit()
        app = FastAPI()

        @app.post("/items/{item_id}")
        @pre_enforce()
        async def update_item(item_id: str, request: Request):
            return {"id": item_id}

        client = TestClient(app)
        client.post("/items/42")

        subscription = _configured.call_args[0][0]
        assert subscription.action["method"] == "POST"
        assert subscription.action["handler"] == "update_item"
        assert subscription.resource["path"] == "/items/42"


class TestPreEnforceDenyFlow:
    def test_returns_403_on_deny(self, _configured) -> None:
        _configured.return_value = _deny()
        app = FastAPI()

        @app.get("/secret")
        @pre_enforce()
        async def get_secret(request: Request):
            return {"secret": "should-not-reach"}

        client = TestClient(app)
        response = client.get("/secret")
        assert response.status_code == 403

    def test_returns_403_on_indeterminate(self, _configured) -> None:
        _configured.return_value = AuthorizationDecision.indeterminate()
        app = FastAPI()

        @app.get("/data")
        @pre_enforce()
        async def get_data(request: Request):
            return {"data": "value"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 403


class TestPreEnforceCustomSubscription:
    def test_static_field_overrides(self, _configured) -> None:
        _configured.return_value = _permit()
        app = FastAPI()

        @app.get("/data")
        @pre_enforce(subject="admin", action="read", resource="documents")
        async def get_data(request: Request):
            return {"data": "value"}

        client = TestClient(app)
        client.get("/data")

        subscription = _configured.call_args[0][0]
        assert subscription.subject == "admin"
        assert subscription.action == "read"
        assert subscription.resource == "documents"

    def test_callable_field_overrides(self, _configured) -> None:
        _configured.return_value = _permit()

        def dynamic_subject(ctx: Any) -> str:
            return f"user-via-{ctx.request.method}"

        app = FastAPI()

        @app.get("/data")
        @pre_enforce(subject=dynamic_subject)
        async def get_data(request: Request):
            return {"data": "value"}

        client = TestClient(app)
        client.get("/data")

        subscription = _configured.call_args[0][0]
        assert subscription.subject == "user-via-GET"


class TestPostEnforcePermitFlow:
    def test_returns_200_on_permit(self, _configured) -> None:
        _configured.return_value = _permit()
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
    def test_returns_403_on_deny(self, _configured) -> None:
        _configured.return_value = _deny()
        app = FastAPI()

        @app.get("/data")
        @post_enforce()
        async def get_data(request: Request):
            return {"value": "result"}

        client = TestClient(app)
        response = client.get("/data")
        assert response.status_code == 403


class TestExtractRequest:
    def test_finds_request_in_positional_args(self) -> None:
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "root_path": "", "headers": [], "path_params": {}}
        request = Request(scope)
        assert _extract_request((request,), {}) is request

    def test_finds_request_in_named_kwarg(self) -> None:
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "root_path": "", "headers": [], "path_params": {}}
        request = Request(scope)
        assert _extract_request((), {"request": request}) is request

    def test_finds_request_in_arbitrary_kwarg(self) -> None:
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "root_path": "", "headers": [], "path_params": {}}
        request = Request(scope)
        assert _extract_request((), {"req": request}) is request

    def test_returns_none_when_no_request_present(self) -> None:
        assert _extract_request(("not-a-request",), {"key": "value"}) is None


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

    def test_excludes_request_instances(self) -> None:
        scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "root_path": "", "headers": [], "path_params": {}}
        request = Request(scope)

        def my_handler(request: Request, patient_id: str):
            pass

        result = _resolve_args(my_handler, (request, "P-001"), {})
        assert "request" not in result
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
