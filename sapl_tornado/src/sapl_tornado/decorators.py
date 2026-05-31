from __future__ import annotations

import asyncio
import functools
import inspect
import json
from typing import TYPE_CHECKING, Any

import structlog
from tornado.web import HTTPError, RequestHandler

from sapl_base.pep import (
    AccessDeniedError,
    AccessGrantedSignal,
    AccessSuspendedSignal,
    post_enforce as _post_enforce,
    pre_enforce as _pre_enforce,
)
from sapl_base.pep.streaming import run_pipeline

from sapl_tornado.dependencies import get_pdp_client, get_planner
from sapl_tornado.subscription import SubscriptionBuilder, SubscriptionField

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from tornado.httputil import HTTPServerRequest

    from sapl_base.types import AuthorizationDecision, AuthorizationSubscription

log = structlog.get_logger()


def _extract_class_name(func: Callable) -> str:
    qualname = getattr(func, "__qualname__", "")
    parts = qualname.split(".")
    return parts[-2] if len(parts) >= 2 else ""


def _resolve_args(func: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        resolved = dict(bound.arguments)
        resolved.pop("self", None)
        resolved.pop("cls", None)
        return {k: v for k, v in resolved.items() if not isinstance(v, RequestHandler)}
    except (TypeError, ValueError):
        return {k: v for k, v in kwargs.items() if not isinstance(v, RequestHandler)}


def _extract_request_and_handler(
    args: tuple, kwargs: dict,
) -> tuple[HTTPServerRequest | None, RequestHandler | None]:
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

    if request is None:
        from tornado.httputil import HTTPServerRequest as _HSR
        for arg in args:
            if isinstance(arg, _HSR):
                return arg, handler
        for value in kwargs.values():
            if isinstance(value, _HSR):
                return value, handler

    return request, handler


def _get_path_kwargs(handler: RequestHandler | None) -> dict[str, Any]:
    if handler is None:
        return {}
    return dict(handler.path_kwargs) if hasattr(handler, "path_kwargs") and handler.path_kwargs else {}


def _get_current_user(handler: RequestHandler | None) -> Any:
    if handler is None:
        return None
    try:
        return handler.current_user
    except Exception:
        return None


def _build_subscription(
    func: Callable,
    args: tuple,
    kwargs: dict,
    *,
    subject: SubscriptionField,
    action: SubscriptionField,
    resource: SubscriptionField,
    environment: SubscriptionField,
    secrets: SubscriptionField,
    return_value: Any = None,
) -> tuple[AuthorizationSubscription, RequestHandler | None]:
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
        class_name=_extract_class_name(func),
        resolved_args=resolved,
        return_value=return_value,
        path_kwargs=path_kwargs,
        current_user=current_user,
    )
    return subscription, handler


def pre_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
    on_deny: Callable[[AuthorizationDecision], Any] | None = None,
) -> Callable:
    """Decorator: authorize BEFORE handler execution."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            subscription, handler = _build_subscription(
                func, args, kwargs,
                subject=subject, action=action, resource=resource,
                environment=environment, secrets=secrets,
            )
            try:
                result = await _pre_enforce(
                    func,
                    pdp_client=get_pdp_client(),
                    planner=get_planner(),
                    subscription=subscription,
                    args=tuple(args),
                    kwargs=dict(kwargs),
                )
            except AccessDeniedError as exc:
                if on_deny is not None:
                    deny_result = on_deny(exc.decision)
                    if handler is not None and deny_result is not None:
                        _write_response(handler, deny_result)
                    return deny_result
                raise HTTPError(403) from None
            if handler is not None and result is not None:
                _write_response(handler, result)
            return result
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
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            _, handler = _extract_request_and_handler(args, kwargs)

            def _subscription_builder(return_value: Any) -> AuthorizationSubscription:
                subscription, _ = _build_subscription(
                    func, args, kwargs,
                    subject=subject, action=action, resource=resource,
                    environment=environment, secrets=secrets,
                    return_value=return_value,
                )
                return subscription

            try:
                result = await _post_enforce(
                    func,
                    pdp_client=get_pdp_client(),
                    planner=get_planner(),
                    subscription_builder=_subscription_builder,
                    args=tuple(args),
                    kwargs=dict(kwargs),
                )
            except AccessDeniedError as exc:
                if on_deny is not None:
                    deny_result = on_deny(exc.decision)
                    if handler is not None and deny_result is not None:
                        _write_response(handler, deny_result)
                    return deny_result
                raise HTTPError(403) from None
            if handler is not None and result is not None:
                _write_response(handler, result)
            return result
        return wrapper
    return decorator


def stream_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
    signal_transitions: bool = False,
    pause_rap_during_suspend: bool = False,
) -> Callable:
    """Decorator: SAPL-enforced SSE streaming.

    Writes SSE frames directly to the Tornado handler. DENY emits a final
    ACCESS_DENIED frame; SUSPEND with `signal_transitions=True` emits
    ACCESS_SUSPENDED / ACCESS_RESTORED.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            subscription, handler = _build_subscription(
                func, args, kwargs,
                subject=subject, action=action, resource=resource,
                environment=environment, secrets=secrets,
            )

            async def _async_rap() -> AsyncIterator[Any]:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                async for item in result:
                    yield item

            def _rap_factory() -> AsyncIterator[Any]:
                return _async_rap()

            if handler is not None:
                handler.set_header("Content-Type", "text/event-stream")
                handler.set_header("Cache-Control", "no-cache")

            pipeline = run_pipeline(
                decisions=get_pdp_client().decide(subscription),
                planner=get_planner(),
                rap_factory=_rap_factory,
                signal_transitions=signal_transitions,
                pause_rap_during_suspend=pause_rap_during_suspend,
            )

            try:
                async for item in pipeline:
                    if handler is not None:
                        handler.write(_format_sse(item))
                        handler.flush()
            except AccessDeniedError as exc:
                if handler is not None:
                    handler.write(_format_sse({
                        "type": "ACCESS_DENIED",
                        "reason": getattr(exc, "reason", None),
                    }))
                    handler.flush()

            if handler is not None and not handler._finished:
                handler.finish()
        return wrapper
    return decorator


def _write_response(handler: RequestHandler, result: Any) -> None:
    if isinstance(result, (dict, list)):
        handler.set_header("Content-Type", "application/json")
        handler.write(json.dumps(result))
    else:
        handler.write(str(result))


def _format_sse(data: Any) -> str:
    if isinstance(data, AccessSuspendedSignal):
        return "data: " + json.dumps({"type": "ACCESS_SUSPENDED"}) + "\n\n"
    if isinstance(data, AccessGrantedSignal):
        return "data: " + json.dumps({"type": "ACCESS_RESTORED"}) + "\n\n"
    if isinstance(data, str):
        return f"data: {data}\n\n"
    if isinstance(data, dict):
        return f"data: {json.dumps(data)}\n\n"
    return f"data: {data}\n\n"
