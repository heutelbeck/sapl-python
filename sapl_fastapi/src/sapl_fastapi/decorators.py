from __future__ import annotations

import asyncio
import functools
import inspect
import json
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import StreamingResponse

from sapl_base.pep import (
    AccessDeniedError,
    AccessGrantedSignal,
    AccessSuspendedSignal,
)
from sapl_base.pep import (
    post_enforce as _post_enforce,
)
from sapl_base.pep import (
    pre_enforce as _pre_enforce,
)
from sapl_base.pep.enforce import (
    post_enforce_blocking as _post_enforce_blocking,
)
from sapl_base.pep.enforce import (
    pre_enforce_blocking as _pre_enforce_blocking,
)
from sapl_base.pep.streaming import run_pipeline
from sapl_fastapi.dependencies import get_pdp_client, get_planner, get_transaction_provider
from sapl_fastapi.subscription import SubscriptionBuilder, SubscriptionField

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from sapl_base.types import AuthorizationSubscription

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
        return {k: v for k, v in resolved.items() if not isinstance(v, Request)}
    except (TypeError, ValueError):
        return {k: v for k, v in kwargs.items() if not isinstance(v, Request)}


def _extract_request(args: tuple, kwargs: dict) -> Request | None:
    for arg in args:
        if isinstance(arg, Request):
            return arg
    if "request" in kwargs and isinstance(kwargs["request"], Request):
        return kwargs["request"]
    for value in kwargs.values():
        if isinstance(value, Request):
            return value
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
) -> AuthorizationSubscription:
    request = _extract_request(args, kwargs)
    resolved = _resolve_args(func, args, kwargs)
    return SubscriptionBuilder.build(
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
    )


def pre_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
) -> Callable:
    """Decorator: authorize BEFORE method execution.

    Auto-detects the endpoint kind. Async endpoints run on the async enforcement
    core; sync endpoints run on the blocking core via a sync wrapper, which
    FastAPI/Starlette then runs in its threadpool so the bridged PDP call executes
    with no running event loop. The configured transaction provider must match the
    endpoint kind: an async provider for async endpoints, a sync context-manager
    factory for sync ones.
    """
    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                subscription = _build_subscription(
                    func, args, kwargs,
                    subject=subject, action=action, resource=resource,
                    environment=environment, secrets=secrets,
                )
                try:
                    return await _pre_enforce(
                        func,
                        pdp_client=get_pdp_client(),
                        planner=get_planner(),
                        subscription=subscription,
                        args=tuple(args),
                        kwargs=dict(kwargs),
                        transaction=get_transaction_provider(),
                    )
                except AccessDeniedError:
                    raise HTTPException(status_code=403) from None
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            subscription = _build_subscription(
                func, args, kwargs,
                subject=subject, action=action, resource=resource,
                environment=environment, secrets=secrets,
            )
            try:
                return _pre_enforce_blocking(
                    func,
                    pdp_client=get_pdp_client(),
                    planner=get_planner(),
                    subscription=subscription,
                    args=tuple(args),
                    kwargs=dict(kwargs),
                    transaction=get_transaction_provider(),
                )
            except AccessDeniedError:
                raise HTTPException(status_code=403) from None
        return sync_wrapper
    return decorator


def post_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
) -> Callable:
    """Decorator: authorize AFTER method execution.

    The view runs first, then the PDP is queried with a subscription that
    can reference the return value through the `resource`/`action`/...
    callables (each receives a `SubscriptionContext` whose `return_value`
    is populated).
    """
    def decorator(func: Callable) -> Callable:
        def _builder(args: tuple, kwargs: dict) -> Callable[[Any], AuthorizationSubscription]:
            def _subscription_builder(return_value: Any) -> AuthorizationSubscription:
                return _build_subscription(
                    func, args, kwargs,
                    subject=subject, action=action, resource=resource,
                    environment=environment, secrets=secrets,
                    return_value=return_value,
                )
            return _subscription_builder

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await _post_enforce(
                        func,
                        pdp_client=get_pdp_client(),
                        planner=get_planner(),
                        subscription_builder=_builder(args, kwargs),
                        args=tuple(args),
                        kwargs=dict(kwargs),
                        transaction=get_transaction_provider(),
                    )
                except AccessDeniedError:
                    raise HTTPException(status_code=403) from None
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return _post_enforce_blocking(
                    func,
                    pdp_client=get_pdp_client(),
                    planner=get_planner(),
                    subscription_builder=_builder(args, kwargs),
                    args=tuple(args),
                    kwargs=dict(kwargs),
                    transaction=get_transaction_provider(),
                )
            except AccessDeniedError:
                raise HTTPException(status_code=403) from None
        return sync_wrapper
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

    The decorated function returns an async iterator. The wrapper drives
    the Mealy FSM and yields items as SSE frames on `text/event-stream`.

    - `signal_transitions=True`: emit ACCESS_SUSPENDED / ACCESS_GRANTED
      SSE frames on Suspended/Permitting boundary transitions.
    - `pause_rap_during_suspend=True`: cancel the upstream iterator on
      entry to Suspended; re-subscribe on exit.

    DENY is terminal; a final ACCESS_DENIED SSE frame is emitted before
    the stream closes. Use SUSPEND in policies for keep-alive semantics.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> StreamingResponse:
            subscription = _build_subscription(
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

            async def _sse_generator() -> AsyncIterator[bytes]:
                pipeline = run_pipeline(
                    decisions=get_pdp_client().decide(subscription),
                    planner=get_planner(),
                    rap_factory=_rap_factory,
                    signal_transitions=signal_transitions,
                    pause_rap_during_suspend=pause_rap_during_suspend,
                )
                try:
                    async for item in pipeline:
                        yield _format_sse(item).encode("utf-8")
                except AccessDeniedError as exc:
                    yield _format_sse({
                        "type": "ACCESS_DENIED",
                        "reason": getattr(exc, "reason", None),
                    }).encode("utf-8")

            return StreamingResponse(_sse_generator(), media_type="text/event-stream")
        return wrapper
    return decorator


def _format_sse(data: Any) -> str:
    if isinstance(data, AccessSuspendedSignal):
        return "data: " + json.dumps({"type": "ACCESS_SUSPENDED"}) + "\n\n"
    if isinstance(data, AccessGrantedSignal):
        return "data: " + json.dumps({"type": "ACCESS_GRANTED"}) + "\n\n"
    if isinstance(data, str):
        return f"data: {data}\n\n"
    if isinstance(data, dict):
        return f"data: {json.dumps(data)}\n\n"
    return f"data: {data}\n\n"
