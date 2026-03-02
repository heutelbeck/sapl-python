from __future__ import annotations

import asyncio
import functools
import inspect
import json
from typing import TYPE_CHECKING, Any

import structlog
from tornado.web import RequestHandler

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
from sapl_tornado.dependencies import get_constraint_service, get_pdp_client
from sapl_tornado.subscription import SubscriptionBuilder, SubscriptionField

if TYPE_CHECKING:
    from collections.abc import Callable

    from tornado.httputil import HTTPServerRequest

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

    Excludes ``self``, ``cls``, and ``RequestHandler`` parameters.
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
            if not isinstance(v, RequestHandler)
        }
        return resolved
    except (TypeError, ValueError):
        return {
            k: v for k, v in kwargs.items()
            if not isinstance(v, RequestHandler)
        }


def _extract_request_and_handler(
    args: tuple, kwargs: dict,
) -> tuple[HTTPServerRequest | None, RequestHandler | None]:
    """Extract HTTPServerRequest and RequestHandler from function arguments.

    For Tornado handler methods, ``args[0]`` is ``self`` (a RequestHandler).
    """
    handler: RequestHandler | None = None
    for arg in args:
        if isinstance(arg, RequestHandler):
            handler = arg
            break
    if handler is None:
        for value in kwargs.values():
            if isinstance(value, RequestHandler):
                handler = value
                break

    request = handler.request if handler is not None else None

    # Also check for bare HTTPServerRequest in args (service-layer edge case)
    if request is None:
        from tornado.httputil import HTTPServerRequest
        for arg in args:
            if isinstance(arg, HTTPServerRequest):
                return arg, handler
        for value in kwargs.values():
            if isinstance(value, HTTPServerRequest):
                return value, handler

    return request, handler


def _get_path_kwargs(handler: RequestHandler | None) -> dict[str, Any]:
    """Extract path kwargs from a Tornado RequestHandler."""
    if handler is None:
        return {}
    return dict(handler.path_kwargs) if hasattr(handler, "path_kwargs") and handler.path_kwargs else {}


def _get_current_user(handler: RequestHandler | None) -> Any:
    """Get current_user from a Tornado RequestHandler."""
    if handler is None:
        return None
    try:
        return handler.current_user
    except Exception:
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
    """Decorator: authorize BEFORE handler execution.

    Usage::

        class PatientHandler(tornado.web.RequestHandler):
            @pre_enforce(action="read", resource="patient")
            async def get(self, patient_id):
                return {"id": patient_id}
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request, handler = _extract_request_and_handler(args, kwargs)
            path_kwargs = _get_path_kwargs(handler)
            current_user = _get_current_user(handler)
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
                path_kwargs=path_kwargs,
                current_user=current_user,
            )

            try:
                result = await _pre_enforce(
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
                if handler is not None and result is not None:
                    _write_response(handler, result)
                return result
            except AccessDeniedError:
                from tornado.web import HTTPError
                raise HTTPError(403, reason="Access denied") from None
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
    """Decorator: authorize AFTER handler execution."""
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request, handler = _extract_request_and_handler(args, kwargs)
            path_kwargs = _get_path_kwargs(handler)
            current_user = _get_current_user(handler)
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
                    path_kwargs=path_kwargs,
                    current_user=current_user,
                )

            try:
                result = await _post_enforce(
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
                if handler is not None and result is not None:
                    _write_response(handler, result)
                return result
            except AccessDeniedError:
                from tornado.web import HTTPError
                raise HTTPError(403, reason="Access denied") from None
        return wrapper
    return decorator


def service_pre_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
) -> Callable:
    """Decorator: authorize BEFORE service method execution.

    Like ``pre_enforce`` but for service-layer methods:
    - Does not catch ``AccessDeniedError`` (caller handles it)
    - Does not write response to handler
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request, handler = _extract_request_and_handler(args, kwargs)
            path_kwargs = _get_path_kwargs(handler)
            current_user = _get_current_user(handler)
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
                path_kwargs=path_kwargs,
                current_user=current_user,
            )

            return await _pre_enforce(
                pdp_client=get_pdp_client(),
                constraint_service=get_constraint_service(),
                subscription=subscription,
                protected_function=func,
                args=list(args),
                kwargs=kwargs,
                function_name=func.__name__,
                class_name=class_name,
                request=request,
            )
        return wrapper
    return decorator


def service_post_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
) -> Callable:
    """Decorator: authorize AFTER service method execution.

    Like ``post_enforce`` but for service-layer methods:
    - Does not catch ``AccessDeniedError`` (caller handles it)
    - Does not write response to handler
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request, handler = _extract_request_and_handler(args, kwargs)
            path_kwargs = _get_path_kwargs(handler)
            current_user = _get_current_user(handler)
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
                    path_kwargs=path_kwargs,
                    current_user=current_user,
                )

            return await _post_enforce(
                pdp_client=get_pdp_client(),
                constraint_service=get_constraint_service(),
                subscription_builder=subscription_builder,
                protected_function=func,
                args=list(args),
                kwargs=kwargs,
                function_name=func.__name__,
                class_name=class_name,
                request=request,
            )
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
    Writes SSE events directly to the Tornado response.
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            request, handler = _extract_request_and_handler(args, kwargs)
            path_kwargs = _get_path_kwargs(handler)
            current_user = _get_current_user(handler)
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
                path_kwargs=path_kwargs,
                current_user=current_user,
            )

            async def data_source():
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            if handler is not None:
                handler.set_header("Content-Type", "text/event-stream")
                handler.set_header("Cache-Control", "no-cache")

            try:
                async for item in _enforce_till_denied(
                    pdp_client=get_pdp_client(),
                    constraint_service=get_constraint_service(),
                    subscription=subscription,
                    data_source=data_source,
                    on_stream_deny=on_stream_deny,
                ):
                    if handler is not None:
                        handler.write(_format_sse(item))
                        handler.flush()
            except Exception:
                pass

            if handler is not None and not handler._finished:
                handler.finish()
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
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            request, handler = _extract_request_and_handler(args, kwargs)
            path_kwargs = _get_path_kwargs(handler)
            current_user = _get_current_user(handler)
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
                path_kwargs=path_kwargs,
                current_user=current_user,
            )

            async def data_source():
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            if handler is not None:
                handler.set_header("Content-Type", "text/event-stream")
                handler.set_header("Cache-Control", "no-cache")

            try:
                async for item in _enforce_drop_while_denied(
                    pdp_client=get_pdp_client(),
                    constraint_service=get_constraint_service(),
                    subscription=subscription,
                    data_source=data_source,
                ):
                    if handler is not None:
                        handler.write(_format_sse(item))
                        handler.flush()
            except Exception:
                pass

            if handler is not None and not handler._finished:
                handler.finish()
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
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            request, handler = _extract_request_and_handler(args, kwargs)
            path_kwargs = _get_path_kwargs(handler)
            current_user = _get_current_user(handler)
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
                path_kwargs=path_kwargs,
                current_user=current_user,
            )

            async def data_source():
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result

            if handler is not None:
                handler.set_header("Content-Type", "text/event-stream")
                handler.set_header("Cache-Control", "no-cache")

            try:
                async for item in _enforce_recoverable_if_denied(
                    pdp_client=get_pdp_client(),
                    constraint_service=get_constraint_service(),
                    subscription=subscription,
                    data_source=data_source,
                    on_stream_deny=on_stream_deny,
                    on_stream_recover=on_stream_recover,
                ):
                    if handler is not None:
                        handler.write(_format_sse(item))
                        handler.flush()
            except Exception:
                pass

            if handler is not None and not handler._finished:
                handler.finish()
        return wrapper
    return decorator


def _write_response(handler: RequestHandler, result: Any) -> None:
    """Write a result to the Tornado response."""
    if isinstance(result, (dict, list)):
        handler.set_header("Content-Type", "application/json; charset=UTF-8")
        handler.write(json.dumps(result))
    elif isinstance(result, str):
        handler.write(result)
    elif result is not None:
        handler.write(json.dumps(result))


def _format_sse(data: Any) -> str:
    """Format data as SSE event."""
    if isinstance(data, str):
        return f"data: {data}\n\n"
    if isinstance(data, dict):
        return f"data: {json.dumps(data)}\n\n"
    return f"data: {data}\n\n"
