from __future__ import annotations

import pytest
from django.http import HttpRequest, HttpResponse

from sapl_django.middleware import SaplRequestMiddleware, get_current_request


class TestGetCurrentRequest:
    """Tests for get_current_request contextvar accessor."""

    def test_returns_none_outside_middleware(self):
        assert get_current_request() is None


class TestSaplRequestMiddlewareSync:
    """Tests for synchronous middleware request propagation."""

    def test_request_available_during_view(self):
        request = HttpRequest()
        captured_request = None

        def mock_get_response(req):
            nonlocal captured_request
            captured_request = get_current_request()
            return HttpResponse("ok")

        middleware = SaplRequestMiddleware(mock_get_response)
        middleware(request)

        assert captured_request is request

    def test_request_cleared_after_response(self):
        request = HttpRequest()

        def mock_get_response(req):
            return HttpResponse("ok")

        middleware = SaplRequestMiddleware(mock_get_response)
        middleware(request)

        assert get_current_request() is None

    def test_request_cleared_on_exception(self):
        request = HttpRequest()

        def mock_get_response(req):
            raise ValueError("view error")

        middleware = SaplRequestMiddleware(mock_get_response)

        with pytest.raises(ValueError, match="view error"):
            middleware(request)

        assert get_current_request() is None

    def test_returns_response_from_get_response(self):
        request = HttpRequest()
        expected_response = HttpResponse("test content")

        def mock_get_response(req):
            return expected_response

        middleware = SaplRequestMiddleware(mock_get_response)
        result = middleware(request)

        assert result is expected_response


class TestSaplRequestMiddlewareAsync:
    """Tests for asynchronous middleware request propagation."""

    @pytest.mark.asyncio
    async def test_request_available_during_async_view(self):
        request = HttpRequest()
        captured_request = None

        async def mock_get_response(req):
            nonlocal captured_request
            captured_request = get_current_request()
            return HttpResponse("ok")

        middleware = SaplRequestMiddleware(mock_get_response)
        await middleware.__acall__(request)

        assert captured_request is request

    @pytest.mark.asyncio
    async def test_request_cleared_after_async_response(self):
        request = HttpRequest()

        async def mock_get_response(req):
            return HttpResponse("ok")

        middleware = SaplRequestMiddleware(mock_get_response)
        await middleware.__acall__(request)

        assert get_current_request() is None

    @pytest.mark.asyncio
    async def test_request_cleared_on_async_exception(self):
        request = HttpRequest()

        async def mock_get_response(req):
            raise ValueError("async view error")

        middleware = SaplRequestMiddleware(mock_get_response)

        with pytest.raises(ValueError, match="async view error"):
            await middleware.__acall__(request)

        assert get_current_request() is None

    @pytest.mark.asyncio
    async def test_returns_response_from_async_get_response(self):
        request = HttpRequest()
        expected_response = HttpResponse("async content")

        async def mock_get_response(req):
            return expected_response

        middleware = SaplRequestMiddleware(mock_get_response)
        result = await middleware.__acall__(request)

        assert result is expected_response
