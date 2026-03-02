from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse

_current_request: ContextVar[HttpRequest | None] = ContextVar("_current_request", default=None)


def get_current_request() -> HttpRequest | None:
    """Return the current Django request from context, or None if outside a request."""
    return _current_request.get()


class SaplRequestMiddleware:
    """Propagates the Django HttpRequest via contextvars for SAPL subscription building.

    Add to MIDDLEWARE in settings:
        MIDDLEWARE = [
            "sapl_django.middleware.SaplRequestMiddleware",
            ...
        ]
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Synchronous request handler."""
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)

    async def __acall__(self, request: HttpRequest) -> HttpResponse:
        """Asynchronous request handler for ASGI deployments."""
        token = _current_request.set(request)
        try:
            return await self.get_response(request)
        finally:
            _current_request.reset(token)
