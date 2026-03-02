from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, JsonResponse

from sapl_base.constraint_bundle import AccessDeniedError
from sapl_base.types import AuthorizationDecision, Decision

from sapl_django.decorators import (
    _extract_class_name,
    _extract_request,
    _resolve_args,
    _wrap_response,
    post_enforce,
    pre_enforce,
)


def _make_request(
    *,
    method: str = "GET",
    path: str = "/api/test",
    username: str = "testuser",
) -> HttpRequest:
    """Create a minimal Django HttpRequest for testing."""
    request = HttpRequest()
    request.method = method
    request.path = path
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    request.user = SimpleNamespace(username=username)
    return request


def _mock_pdp_permit() -> AsyncMock:
    """Create a mock PDP client that returns PERMIT."""
    mock = AsyncMock()
    mock.decide_once.return_value = AuthorizationDecision.permit()
    return mock


def _mock_pdp_deny() -> AsyncMock:
    """Create a mock PDP client that returns DENY."""
    mock = AsyncMock()
    mock.decide_once.return_value = AuthorizationDecision.deny()
    return mock


def _mock_constraint_service() -> MagicMock:
    """Create a mock constraint enforcement service."""
    mock = MagicMock()
    bundle = MagicMock()
    bundle.handle_on_decision_constraints.return_value = None
    bundle.handle_method_invocation_handlers.return_value = None
    bundle.handle_all_on_next_constraints.side_effect = lambda v: v
    mock.pre_enforce_bundle_for.return_value = bundle
    mock.post_enforce_bundle_for.return_value = bundle
    mock.best_effort_bundle_for.return_value = bundle
    return mock


class TestExtractRequest:
    """Tests for _extract_request helper."""

    def test_extracts_from_positional_args(self):
        request = _make_request()
        result = _extract_request((request,), {})

        assert result is request

    def test_extracts_from_kwargs_by_name(self):
        request = _make_request()
        result = _extract_request((), {"request": request})

        assert result is request

    def test_extracts_from_kwargs_by_type(self):
        request = _make_request()
        result = _extract_request((), {"my_req": request})

        assert result is request

    def test_returns_none_when_no_request(self):
        result = _extract_request(("not_a_request",), {"key": "value"})
        assert result is None


class TestPreEnforce:
    """Tests for the pre_enforce decorator."""

    @pytest.mark.asyncio
    async def test_permit_returns_view_result(self):
        @pre_enforce(action="read", resource="data")
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()

        with patch("sapl_django.decorators.get_pdp_client", return_value=_mock_pdp_permit()), \
             patch("sapl_django.decorators.get_constraint_service", return_value=_mock_constraint_service()):
            result = await my_view(request)

        assert isinstance(result, JsonResponse)

    @pytest.mark.asyncio
    async def test_deny_raises_permission_denied(self):
        @pre_enforce(action="read", resource="data")
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()

        with patch("sapl_django.decorators.get_pdp_client", return_value=_mock_pdp_deny()), \
             patch("sapl_django.decorators.get_constraint_service", return_value=_mock_constraint_service()):
            with pytest.raises(PermissionDenied):
                await my_view(request)

    @pytest.mark.asyncio
    async def test_on_deny_callback_returns_custom_response(self):
        custom_response = JsonResponse({"error": "custom_deny"}, status=403)

        @pre_enforce(
            action="read",
            resource="data",
            on_deny=lambda decision: custom_response,
        )
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()

        with patch("sapl_django.decorators.get_pdp_client", return_value=_mock_pdp_deny()), \
             patch("sapl_django.decorators.get_constraint_service", return_value=_mock_constraint_service()):
            result = await my_view(request)

        assert result is custom_response

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        @pre_enforce(action="read", resource="data")
        async def specific_view_name(request):
            return JsonResponse({"result": "ok"})

        assert specific_view_name.__name__ == "specific_view_name"


class TestPostEnforce:
    """Tests for the post_enforce decorator."""

    @pytest.mark.asyncio
    async def test_permit_returns_view_result(self):
        @post_enforce(action="read", resource="data")
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()

        with patch("sapl_django.decorators.get_pdp_client", return_value=_mock_pdp_permit()), \
             patch("sapl_django.decorators.get_constraint_service", return_value=_mock_constraint_service()):
            result = await my_view(request)

        assert isinstance(result, JsonResponse)

    @pytest.mark.asyncio
    async def test_deny_raises_permission_denied(self):
        @post_enforce(action="read", resource="data")
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()

        with patch("sapl_django.decorators.get_pdp_client", return_value=_mock_pdp_deny()), \
             patch("sapl_django.decorators.get_constraint_service", return_value=_mock_constraint_service()):
            with pytest.raises(PermissionDenied):
                await my_view(request)

    @pytest.mark.asyncio
    async def test_view_executes_before_authorization(self):
        call_order = []

        mock_pdp = AsyncMock()
        mock_pdp.decide_once.return_value = AuthorizationDecision.deny()

        @post_enforce(action="read", resource="data")
        async def my_view(request):
            call_order.append("view")
            return {"result": "ok"}

        # Track when decide_once is called
        original_decide = mock_pdp.decide_once

        async def tracked_decide(*a, **kw):
            call_order.append("pdp")
            return await original_decide(*a, **kw)

        mock_pdp.decide_once = tracked_decide

        request = _make_request()

        with patch("sapl_django.decorators.get_pdp_client", return_value=mock_pdp), \
             patch("sapl_django.decorators.get_constraint_service", return_value=_mock_constraint_service()):
            with pytest.raises(PermissionDenied):
                await my_view(request)

        assert call_order == ["view", "pdp"]

    @pytest.mark.asyncio
    async def test_on_deny_callback_returns_custom_response(self):
        custom_response = JsonResponse({"error": "post_deny"}, status=403)

        @post_enforce(
            action="read",
            resource="data",
            on_deny=lambda decision: custom_response,
        )
        async def my_view(request):
            return {"result": "ok"}

        request = _make_request()

        with patch("sapl_django.decorators.get_pdp_client", return_value=_mock_pdp_deny()), \
             patch("sapl_django.decorators.get_constraint_service", return_value=_mock_constraint_service()):
            result = await my_view(request)

        assert result is custom_response


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
    """Verify _resolve_args maps arguments to names, excluding HttpRequest."""

    def test_resolves_positional_args(self):
        def my_view(patient_id: str, amount: float):
            pass

        result = _resolve_args(my_view, ("P-001", 100.0), {})
        assert result == {"patient_id": "P-001", "amount": 100.0}

    def test_excludes_http_request_instances(self):
        request = _make_request()

        def my_view(request, patient_id: str):
            pass

        result = _resolve_args(my_view, (request, "P-001"), {})
        assert "request" not in result
        assert result == {"patient_id": "P-001"}

    def test_applies_defaults(self):
        def my_view(name: str, limit: int = 10):
            pass

        result = _resolve_args(my_view, ("test",), {})
        assert result == {"name": "test", "limit": 10}

    def test_excludes_self(self):
        class MyService:
            def get_data(self, patient_id: str):
                pass

        result = _resolve_args(MyService.get_data, (MyService(), "P-001"), {})
        assert "self" not in result
        assert result == {"patient_id": "P-001"}


class TestWrapResponse:
    """Verify _wrap_response auto-wraps dict/list to JsonResponse."""

    def test_wraps_dict_to_json_response(self):
        result = _wrap_response({"name": "Jane"})

        assert isinstance(result, JsonResponse)
        assert result.status_code == 200

    def test_wraps_list_to_json_response(self):
        result = _wrap_response([{"id": 1}, {"id": 2}])

        assert isinstance(result, JsonResponse)

    def test_passes_through_json_response_unchanged(self):
        original = JsonResponse({"data": "value"})
        result = _wrap_response(original)

        assert result is original

    def test_passes_through_string_unchanged(self):
        result = _wrap_response("plain text")

        assert result == "plain text"

    def test_passes_through_none_unchanged(self):
        result = _wrap_response(None)

        assert result is None
