from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from flask import Flask

from sapl_base.types import AuthorizationDecision
from sapl_flask.decorators import _extract_class_name, _resolve_args, post_enforce, pre_enforce
from sapl_flask.extension import SaplFlask


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.config["SAPL_BASE_URL"] = "http://localhost:8443"
    app.config["SAPL_ALLOW_INSECURE_CONNECTIONS"] = True
    SaplFlask(app)
    return app


def _mock_decide_once(decision: AuthorizationDecision) -> AsyncMock:
    mock = AsyncMock(return_value=decision)
    return mock


class TestPreEnforcePermit:
    def test_permit_returns200(self, app: Flask) -> None:
        @app.route("/data")
        @pre_enforce(action="read", resource="data")
        def get_data():
            return {"result": "ok"}

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.permit()),
        ), app.test_client() as client:
            response = client.get("/data")

        assert response.status_code == 200

    def test_permit_returns_view_result(self, app: Flask) -> None:
        @app.route("/data")
        @pre_enforce(action="read", resource="data")
        def get_data():
            return "hello"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.permit()),
        ), app.test_client() as client:
            response = client.get("/data")

        assert response.data == b"hello"


class TestPreEnforceDeny:
    def test_deny_returns403(self, app: Flask) -> None:
        @app.route("/secret")
        @pre_enforce(action="read", resource="secret")
        def get_secret():
            return "should not reach"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.deny()),
        ), app.test_client() as client:
            response = client.get("/secret")

        assert response.status_code == 403

    def test_indeterminate_returns403(self, app: Flask) -> None:
        @app.route("/unknown")
        @pre_enforce(action="read", resource="unknown")
        def get_unknown():
            return "should not reach"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.indeterminate()),
        ), app.test_client() as client:
            response = client.get("/unknown")

        assert response.status_code == 403

    def test_view_body_not_executed_on_deny(self, app: Flask) -> None:
        executed = []

        @app.route("/side-effect")
        @pre_enforce(action="read", resource="side-effect")
        def get_side_effect():
            executed.append(True)
            return "executed"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.deny()),
        ), app.test_client() as client:
            client.get("/side-effect")

        assert executed == []


class TestPreEnforceOnDeny:
    def test_on_deny_callback_returns_custom_response(self, app: Flask) -> None:
        def custom_deny(decision: AuthorizationDecision) -> str:
            return "custom deny"

        @app.route("/custom")
        @pre_enforce(action="read", resource="custom", on_deny=custom_deny)
        def get_custom():
            return "should not reach"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.deny()),
        ), app.test_client() as client:
            response = client.get("/custom")

        assert response.status_code == 200
        assert response.data == b"custom deny"


class TestPostEnforcePermit:
    def test_permit_returns_200_with_result(self, app: Flask) -> None:
        @app.route("/post-data")
        @post_enforce(action="read", resource="post-data")
        def get_post_data():
            return "post result"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.permit()),
        ), app.test_client() as client:
            response = client.get("/post-data")

        assert response.status_code == 200
        assert response.data == b"post result"


class TestPostEnforceDeny:
    def test_deny_returns_403_after_execution(self, app: Flask) -> None:
        executed = []

        @app.route("/post-secret")
        @post_enforce(action="read", resource="post-secret")
        def get_post_secret():
            executed.append(True)
            return "secret data"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.deny()),
        ), app.test_client() as client:
            response = client.get("/post-secret")

        assert response.status_code == 403
        assert executed == [True]


class TestPostEnforceOnDeny:
    def test_on_deny_callback_returns_custom_response(self, app: Flask) -> None:
        def custom_deny(decision: AuthorizationDecision) -> str:
            return "post custom deny"

        @app.route("/post-custom")
        @post_enforce(action="read", resource="post-custom", on_deny=custom_deny)
        def get_post_custom():
            return "should execute then deny"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.deny()),
        ), app.test_client() as client:
            response = client.get("/post-custom")

        assert response.status_code == 200
        assert response.data == b"post custom deny"


class TestDecoratorPreservesMetadata:
    def test_pre_enforce_preserves_function_name(self, app: Flask) -> None:
        @pre_enforce(action="read")
        def my_view():
            return "ok"

        assert my_view.__name__ == "my_view"

    def test_post_enforce_preserves_function_name(self, app: Flask) -> None:
        @post_enforce(action="read")
        def my_other_view():
            return "ok"

        assert my_other_view.__name__ == "my_other_view"


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

    def test_plain_function_returns_empty_string(self) -> None:
        assert _extract_class_name(_module_level_function) == ""

    def test_method_returns_class_name(self) -> None:
        assert _extract_class_name(_TestPatientService.get_patient) == "_TestPatientService"

    def test_nested_class_returns_inner_class_name(self) -> None:
        assert _extract_class_name(_TestOuter.Inner.method) == "Inner"


class TestResolveArgs:
    """Verify _resolve_args maps positional and keyword arguments to names."""

    def test_resolves_positional_args(self) -> None:
        def my_view(patient_id, amount):
            pass

        result = _resolve_args(my_view, ("P-001", 100.0), {})
        assert result == {"patient_id": "P-001", "amount": 100.0}

    def test_resolves_kwargs(self) -> None:
        def my_view(patient_id, amount=50.0):
            pass

        result = _resolve_args(my_view, ("P-001",), {"amount": 200.0})
        assert result == {"patient_id": "P-001", "amount": 200.0}

    def test_applies_defaults(self) -> None:
        def my_view(name, limit=10):
            pass

        result = _resolve_args(my_view, ("test",), {})
        assert result == {"name": "test", "limit": 10}

    def test_excludes_self(self) -> None:
        class MyService:
            def get_data(self, patient_id):
                pass

        result = _resolve_args(MyService.get_data, (MyService(), "P-001"), {})
        assert "self" not in result
        assert result == {"patient_id": "P-001"}

    def test_falls_back_to_kwargs_on_bind_failure(self) -> None:
        def my_view(a, b, c):
            pass

        result = _resolve_args(my_view, (), {"x": 1, "y": 2})
        assert result == {"x": 1, "y": 2}
