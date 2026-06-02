from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, JsonResponse

from sapl_base.pep import EnforcementPlanner
from sapl_base.types import AuthorizationDecision
from sapl_django.decorators import (
    _extract_class_name,
    _extract_request,
    _resolve_args,
    post_enforce,
    pre_enforce,
)


def _make_request(
    *,
    method: str = "GET",
    path: str = "/api/test",
    username: str = "testuser",
) -> HttpRequest:
    request = HttpRequest()
    request.method = method
    request.path = path
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    request.user = SimpleNamespace(username=username)
    return request


def _mock_pdp(decision: AuthorizationDecision) -> AsyncMock:
    mock = AsyncMock()
    mock.decide_once.return_value = decision
    return mock


def _real_planner() -> EnforcementPlanner:
    return EnforcementPlanner()


class TestExtractRequest:
    def test_extracts_from_positional_args(self):
        request = _make_request()
        assert _extract_request((request,), {}) is request

    def test_extracts_from_kwargs_by_name(self):
        request = _make_request()
        assert _extract_request((), {"request": request}) is request

    def test_extracts_from_kwargs_by_type(self):
        request = _make_request()
        assert _extract_request((), {"my_req": request}) is request

    def test_returns_none_when_no_request(self):
        assert _extract_request(("not_a_request",), {"key": "value"}) is None


class TestPreEnforce:
    @pytest.mark.asyncio
    async def test_permit_returns_view_result(self):
        @pre_enforce(action="read", resource="data")
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()
        with patch("sapl_django.decorators.get_pdp_client",
                   return_value=_mock_pdp(AuthorizationDecision.permit())), \
             patch("sapl_django.decorators.get_planner", return_value=_real_planner()):
            result = await my_view(request)
        assert isinstance(result, JsonResponse)

    @pytest.mark.asyncio
    async def test_deny_raises_access_denied(self):
        @pre_enforce(action="read", resource="data")
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()
        with patch("sapl_django.decorators.get_pdp_client",
                   return_value=_mock_pdp(AuthorizationDecision.deny())), \
             patch("sapl_django.decorators.get_planner", return_value=_real_planner()), \
             pytest.raises(PermissionDenied):
            await my_view(request)

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        @pre_enforce(action="read", resource="data")
        async def specific_view_name(request):
            return JsonResponse({"result": "ok"})

        assert specific_view_name.__name__ == "specific_view_name"


class TestPostEnforce:
    @pytest.mark.asyncio
    async def test_permit_returns_view_result(self):
        @post_enforce(action="read", resource="data")
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()
        with patch("sapl_django.decorators.get_pdp_client",
                   return_value=_mock_pdp(AuthorizationDecision.permit())), \
             patch("sapl_django.decorators.get_planner", return_value=_real_planner()):
            result = await my_view(request)
        assert isinstance(result, JsonResponse)

    @pytest.mark.asyncio
    async def test_deny_raises_access_denied(self):
        @post_enforce(action="read", resource="data")
        async def my_view(request):
            return JsonResponse({"result": "ok"})

        request = _make_request()
        with patch("sapl_django.decorators.get_pdp_client",
                   return_value=_mock_pdp(AuthorizationDecision.deny())), \
             patch("sapl_django.decorators.get_planner", return_value=_real_planner()), \
             pytest.raises(PermissionDenied):
            await my_view(request)

    @pytest.mark.asyncio
    async def test_view_executes_before_authorization(self):
        call_order = []

        mock_pdp = AsyncMock()
        mock_pdp.decide_once.return_value = AuthorizationDecision.deny()
        original_decide = mock_pdp.decide_once

        async def tracked_decide(*a, **kw):
            call_order.append("pdp")
            return await original_decide(*a, **kw)

        mock_pdp.decide_once = tracked_decide

        @post_enforce(action="read", resource="data")
        async def my_view(request):
            call_order.append("view")
            return {"result": "ok"}

        request = _make_request()
        with patch("sapl_django.decorators.get_pdp_client", return_value=mock_pdp), \
             patch("sapl_django.decorators.get_planner", return_value=_real_planner()), \
             pytest.raises(PermissionDenied):
            await my_view(request)
        assert call_order == ["view", "pdp"]


def _module_level_function():
    pass


class _TestPatientService:
    def get_patient(self):
        pass


class _TestOuter:
    class Inner:
        def method(self):
            pass


class TestExtractClassName:
    def test_plain_function_returns_empty_string(self):
        assert _extract_class_name(_module_level_function) == ""

    def test_method_returns_class_name(self):
        assert _extract_class_name(_TestPatientService.get_patient) == "_TestPatientService"

    def test_nested_class_returns_inner_class_name(self):
        assert _extract_class_name(_TestOuter.Inner.method) == "Inner"


class TestResolveArgs:
    def test_resolves_positional_args(self):
        def my_view(patient_id: str, amount: float):
            pass

        assert _resolve_args(my_view, ("P-001", 100.0), {}) == {
            "patient_id": "P-001", "amount": 100.0,
        }

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

        assert _resolve_args(my_view, ("test",), {}) == {"name": "test", "limit": 10}

    def test_excludes_self(self):
        class MyService:
            def get_data(self, patient_id: str):
                pass

        result = _resolve_args(MyService.get_data, (MyService(), "P-001"), {})
        assert "self" not in result
        assert result == {"patient_id": "P-001"}
