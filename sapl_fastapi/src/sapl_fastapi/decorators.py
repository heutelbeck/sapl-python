from __future__ import annotations

import asyncio
import functools
import inspect
import json
from typing import TYPE_CHECKING, Any

import structlog
from starlette.requests import Request
from starlette.responses import StreamingResponse

from fastapi import HTTPException

from sapl_base.constraint_bundle import AccessDeniedError
from sapl_base.enforcement import post_enforce as _post_enforce
from sapl_base.enforcement import pre_enforce as _pre_enforce
from sapl_base.streaming import (
    enforce_drop_while_denied as _enforce_drop_while_denied,
)
from sapl_base.streaming import (
    enforce_recoverable_if_denied as _enforce_recoverable_if_denied,
)
from sapl_base.streaming import (
    enforce_till_denied as _enforce_till_denied,
)
from sapl_fastapi.dependencies import get_constraint_service, get_pdp_client
from sapl_fastapi.subscription import SubscriptionBuilder, SubscriptionField

if TYPE_CHECKING:
    from collections.abc import Callable

    from sapl_base.types import AuthorizationDecision, AuthorizationSubscription

log = structlog.get_logger()


def _extract_class_name(func: Callable) -> str:
    """Extract the class name from a method's qualified name.

    Returns empty string for plain functions.
    """
    qualname = getattr(func, "__qualname__", "")
    parts = qualname.split(".")
    return parts[-2] if len(parts) >= 2 else ""


def _resolve_args(func: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    """Resolve all positional and keyword arguments into a named dict.

    Excludes ``self``, ``cls``, and ``Request`` parameters.
    """
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        resolved = dict(bound.arguments)
        resolved.pop("self", None)
        resolved.pop("cls", None)
        resolved = {
            k: v for k, v in resolved.items()
            if not isinstance(v, Request)
        }
        return resolved
    except (TypeError, ValueError):
        return {
            k: v for k, v in kwargs.items()
            if not isinstance(v, Request)
        }


def _extract_request(args: tuple, kwargs: dict) -> Request | None:
    """Extract Starlette Request from function arguments.

    Returns None if no Request is found (enables service-layer usage).
    """
    for arg in args:
        if isinstance(arg, Request):
            return arg
    if "request" in kwargs and isinstance(kwargs["request"], Request):
        return kwargs["request"]
    for value in kwargs.values():
        if isinstance(value, Request):
            return value
    return None


def pre_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
    on_deny: Callable[[AuthorizationDecision], Any] | None = None,
) -> Callable:
    """Decorator: authorize BEFORE method execution.

    Usage:
        @app.get("/data")
        @pre_enforce(action="read", resource="data")
        async def get_data(request: Request):
            return {"data": "sensitive"}
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _extract_request(args, kwargs)
            resolved = _resolve_args(func, args, kwargs)
            subscription = SubscriptionBuilder.build(
                request,
                subject=subject,
                action=action,
                resource=resource,
                environment=environment,
                secrets=secrets,
                function_name=func.__name__,
                class_name=class_name,
                resolved_args=resolved,
            )

            try:
                return await _pre_enforce(
                    pdp_client=get_pdp_client(),
                    constraint_service=get_constraint_service(),
                    subscription=subscription,
                    protected_function=func,
                    args=list(args),
                    kwargs=kwargs,
                    function_name=func.__name__,
                    on_deny=on_deny,
                    class_name=class_name,
                    request=request,
                )
            except AccessDeniedError:
                raise HTTPException(status_code=403)
        return wrapper
    return decorator


def post_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
    on_deny: Callable[[AuthorizationDecision], Any] | None = None,
) -> Callable:
    """Decorator: authorize AFTER method execution."""
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _extract_request(args, kwargs)
            resolved = _resolve_args(func, args, kwargs)

            def subscription_builder(return_value: Any) -> AuthorizationSubscription:
                return SubscriptionBuilder.build(
                    request,
                    subject=subject,
                    action=action,
                    resource=resource,
                    environment=environment,
                    secrets=secrets,
                    function_name=func.__name__,
                    class_name=class_name,
                    resolved_args=resolved,
                    return_value=return_value,
                )

            try:
                return await _post_enforce(
                    pdp_client=get_pdp_client(),
                    constraint_service=get_constraint_service(),
                    subscription_builder=subscription_builder,
                    protected_function=func,
                    args=list(args),
                    kwargs=kwargs,
                    function_name=func.__name__,
                    on_deny=on_deny,
                    class_name=class_name,
                    request=request,
                )
            except AccessDeniedError:
                raise HTTPException(status_code=403)
        return wrapper
    return decorator


def enforce_till_denied(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
    on_stream_deny: Callable[[AuthorizationDecision], Any] | None = None,
) -> Callable:
    """Decorator: streaming enforcement that terminates on first deny.

    The decorated function must return an async generator.
    Returns an SSE StreamingResponse.
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> StreamingResponse:
            request = _extract_request(args, kwargs)
            resolved = _resolve_args(func, args, kwargs)
            subscription = SubscriptionBuilder.build(
                request,
                subject=subject,
                action=action,
                resource=resource,
                environment=environment,
                secrets=secrets,
                function_name=func.__name__,
                class_name=class_name,
                resolved_args=resolved,
            )

            async def data_source():
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            async def sse_generator():
                async for item in _enforce_till_denied(
                    pdp_client=get_pdp_client(),
                    constraint_service=get_constraint_service(),
                    subscription=subscription,
                    data_source=data_source,
                    on_stream_deny=on_stream_deny,
                ):
                    yield _format_sse(item)

            return StreamingResponse(sse_generator(), media_type="text/event-stream")
        return wrapper
    return decorator


def enforce_drop_while_denied(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
) -> Callable:
    """Decorator: streaming enforcement that drops data during deny."""
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> StreamingResponse:
            request = _extract_request(args, kwargs)
            resolved = _resolve_args(func, args, kwargs)
            subscription = SubscriptionBuilder.build(
                request,
                subject=subject,
                action=action,
                resource=resource,
                environment=environment,
                secrets=secrets,
                function_name=func.__name__,
                class_name=class_name,
                resolved_args=resolved,
            )

            async def data_source():
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            async def sse_generator():
                async for item in _enforce_drop_while_denied(
                    pdp_client=get_pdp_client(),
                    constraint_service=get_constraint_service(),
                    subscription=subscription,
                    data_source=data_source,
                ):
                    yield _format_sse(item)

            return StreamingResponse(sse_generator(), media_type="text/event-stream")
        return wrapper
    return decorator


def enforce_recoverable_if_denied(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
    on_stream_deny: Callable[[AuthorizationDecision], Any] | None = None,
    on_stream_recover: Callable[[AuthorizationDecision], Any] | None = None,
) -> Callable:
    """Decorator: streaming enforcement with suspend/resume signals."""
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> StreamingResponse:
            request = _extract_request(args, kwargs)
            resolved = _resolve_args(func, args, kwargs)
            subscription = SubscriptionBuilder.build(
                request,
                subject=subject,
                action=action,
                resource=resource,
                environment=environment,
                secrets=secrets,
                function_name=func.__name__,
                class_name=class_name,
                resolved_args=resolved,
            )

            async def data_source():
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            async def sse_generator():
                async for item in _enforce_recoverable_if_denied(
                    pdp_client=get_pdp_client(),
                    constraint_service=get_constraint_service(),
                    subscription=subscription,
                    data_source=data_source,
                    on_stream_deny=on_stream_deny,
                    on_stream_recover=on_stream_recover,
                ):
                    yield _format_sse(item)

            return StreamingResponse(sse_generator(), media_type="text/event-stream")
        return wrapper
    return decorator


def _format_sse(data: Any) -> str:
    """Format data as SSE event."""
    if isinstance(data, str):
        return f"data: {data}\n\n"
    if isinstance(data, dict):
        return f"data: {json.dumps(data)}\n\n"
    return f"data: {data}\n\n"
