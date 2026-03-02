from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

from sapl_base.constraint_bundle import AccessDeniedError
from sapl_base.types import AuthorizationDecision, Decision

from sapl_flask.decorators import _extract_class_name, _resolve_args, pre_enforce, post_enforce
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
    def test_permitReturns200(self, app: Flask) -> None:
        @app.route("/data")
        @pre_enforce(action="read", resource="data")
        def get_data():
            return {"result": "ok"}

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.permit()),
        ):
            with app.test_client() as client:
                response = client.get("/data")

        assert response.status_code == 200

    def test_permitReturnsViewResult(self, app: Flask) -> None:
        @app.route("/data")
        @pre_enforce(action="read", resource="data")
        def get_data():
            return "hello"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.permit()),
        ):
            with app.test_client() as client:
                response = client.get("/data")

        assert response.data == b"hello"


class TestPreEnforceDeny:
    def test_denyReturns403(self, app: Flask) -> None:
        @app.route("/secret")
        @pre_enforce(action="read", resource="secret")
        def get_secret():
            return "should not reach"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.deny()),
        ):
            with app.test_client() as client:
                response = client.get("/secret")

        assert response.status_code == 403

    def test_indeterminateReturns403(self, app: Flask) -> None:
        @app.route("/unknown")
        @pre_enforce(action="read", resource="unknown")
        def get_unknown():
            return "should not reach"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.indeterminate()),
        ):
            with app.test_client() as client:
                response = client.get("/unknown")

        assert response.status_code == 403

    def test_viewBodyNotExecutedOnDeny(self, app: Flask) -> None:
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
        ):
            with app.test_client() as client:
                client.get("/side-effect")

        assert executed == []


class TestPreEnforceOnDeny:
    def test_onDenyCallbackReturnsCustomResponse(self, app: Flask) -> None:
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
        ):
            with app.test_client() as client:
                response = client.get("/custom")

        assert response.status_code == 200
        assert response.data == b"custom deny"


class TestPostEnforcePermit:
    def test_permitReturns200WithResult(self, app: Flask) -> None:
        @app.route("/post-data")
        @post_enforce(action="read", resource="post-data")
        def get_post_data():
            return "post result"

        with patch.object(
            app.extensions["sapl"].pdp_client,
            "decide_once",
            _mock_decide_once(AuthorizationDecision.permit()),
        ):
            with app.test_client() as client:
                response = client.get("/post-data")

        assert response.status_code == 200
        assert response.data == b"post result"


class TestPostEnforceDeny:
    def test_denyReturns403AfterExecution(self, app: Flask) -> None:
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
        ):
            with app.test_client() as client:
                response = client.get("/post-secret")

        assert response.status_code == 403
        assert executed == [True]


class TestPostEnforceOnDeny:
    def test_onDenyCallbackReturnsCustomResponse(self, app: Flask) -> None:
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
        ):
            with app.test_client() as client:
                response = client.get("/post-custom")

        assert response.status_code == 200
        assert response.data == b"post custom deny"


class TestDecoratorPreservesMetadata:
    def test_preEnforcePreservesFunctionName(self, app: Flask) -> None:
        @pre_enforce(action="read")
        def my_view():
            return "ok"

        assert my_view.__name__ == "my_view"

    def test_postEnforcePreservesFunctionName(self, app: Flask) -> None:
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

    def test_plainFunctionReturnsEmptyString(self) -> None:
        assert _extract_class_name(_module_level_function) == ""

    def test_methodReturnsClassName(self) -> None:
        assert _extract_class_name(_TestPatientService.get_patient) == "_TestPatientService"

    def test_nestedClassReturnsInnerClassName(self) -> None:
        assert _extract_class_name(_TestOuter.Inner.method) == "Inner"


class TestResolveArgs:
    """Verify _resolve_args maps positional and keyword arguments to names."""

    def test_resolvesPositionalArgs(self) -> None:
        def my_view(patient_id, amount):
            pass

        result = _resolve_args(my_view, ("P-001", 100.0), {})
        assert result == {"patient_id": "P-001", "amount": 100.0}

    def test_resolvesKwargs(self) -> None:
        def my_view(patient_id, amount=50.0):
            pass

        result = _resolve_args(my_view, ("P-001",), {"amount": 200.0})
        assert result == {"patient_id": "P-001", "amount": 200.0}

    def test_appliesDefaults(self) -> None:
        def my_view(name, limit=10):
            pass

        result = _resolve_args(my_view, ("test",), {})
        assert result == {"name": "test", "limit": 10}

    def test_excludesSelf(self) -> None:
        class MyService:
            def get_data(self, patient_id):
                pass

        result = _resolve_args(MyService.get_data, (MyService(), "P-001"), {})
        assert "self" not in result
        assert result == {"patient_id": "P-001"}

    def test_fallsBackToKwargsOnBindFailure(self) -> None:
        def my_view(a, b, c):
            pass

        result = _resolve_args(my_view, (), {"x": 1, "y": 2})
        assert result == {"x": 1, "y": 2}
