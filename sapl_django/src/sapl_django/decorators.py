from __future__ import annotations

import asyncio
import functools
import inspect
from typing import TYPE_CHECKING, Any

import structlog
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, JsonResponse

from sapl_base.pep import (
    AccessDeniedError,
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
from sapl_django.config import get_pdp_client, get_planner, get_transaction_provider
from sapl_django.subscription import SubscriptionBuilder, SubscriptionField

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
        return {k: v for k, v in resolved.items() if not isinstance(v, HttpRequest)}
    except (TypeError, ValueError):
        return {k: v for k, v in kwargs.items() if not isinstance(v, HttpRequest)}


def _extract_request(args: tuple, kwargs: dict) -> HttpRequest | None:
    for arg in args:
        if isinstance(arg, HttpRequest):
            return arg
    if "request" in kwargs and isinstance(kwargs["request"], HttpRequest):
        return kwargs["request"]
    for value in kwargs.values():
        if isinstance(value, HttpRequest):
            return value
    return None


def _wrap_response(result: Any, request: HttpRequest | None) -> Any:
    """Auto-wrap dict/list results as JsonResponse for Django views.

    Service-layer calls (no HttpRequest) return raw values unchanged.
    """
    if request is None:
        return result
    if isinstance(result, dict):
        return JsonResponse(result)
    if isinstance(result, list):
        return JsonResponse(result, safe=False)
    return result


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
) -> tuple[AuthorizationSubscription, HttpRequest | None]:
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
        class_name=_extract_class_name(func),
        resolved_args=resolved,
        return_value=return_value,
    )
    return subscription, request


def pre_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
) -> Callable:
    """Decorator: authorize BEFORE view execution.

    Auto-detects the view. Async views run on the async enforcement core; sync
    views run on the blocking core, which executes the view off the event loop so
    synchronous ORM access works (no ``SynchronousOnlyOperation``). The configured
    transaction provider must match the view kind: an async provider for async
    views, a sync context-manager factory (e.g. ``transaction.atomic``) for sync ones.
    """
    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                subscription, request = _build_subscription(
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
                        transaction=get_transaction_provider(),
                    )
                    return _wrap_response(result, request)
                except AccessDeniedError:
                    raise PermissionDenied() from None
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            subscription, request = _build_subscription(
                func, args, kwargs,
                subject=subject, action=action, resource=resource,
                environment=environment, secrets=secrets,
            )
            try:
                result = _pre_enforce_blocking(
                    func,
                    pdp_client=get_pdp_client(),
                    planner=get_planner(),
                    subscription=subscription,
                    args=tuple(args),
                    kwargs=dict(kwargs),
                    transaction=get_transaction_provider(),
                )
                return _wrap_response(result, request)
            except AccessDeniedError:
                raise PermissionDenied() from None
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
    """Decorator: authorize AFTER view execution.

    Async views use the async core; sync views use the blocking core (run off the
    event loop). The configured transaction provider must match the view kind.
    """
    def decorator(func: Callable) -> Callable:
        def _builder(args: tuple, kwargs: dict) -> Callable[[Any], AuthorizationSubscription]:
            def _subscription_builder(return_value: Any) -> AuthorizationSubscription:
                subscription, _ = _build_subscription(
                    func, args, kwargs,
                    subject=subject, action=action, resource=resource,
                    environment=environment, secrets=secrets,
                    return_value=return_value,
                )
                return subscription
            return _subscription_builder

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                _, request = _extract_request_and_resolve(func, args, kwargs)
                try:
                    result = await _post_enforce(
                        func,
                        pdp_client=get_pdp_client(),
                        planner=get_planner(),
                        subscription_builder=_builder(args, kwargs),
                        args=tuple(args),
                        kwargs=dict(kwargs),
                        transaction=get_transaction_provider(),
                    )
                    return _wrap_response(result, request)
                except AccessDeniedError:
                    raise PermissionDenied() from None
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            _, request = _extract_request_and_resolve(func, args, kwargs)
            try:
                result = _post_enforce_blocking(
                    func,
                    pdp_client=get_pdp_client(),
                    planner=get_planner(),
                    subscription_builder=_builder(args, kwargs),
                    args=tuple(args),
                    kwargs=dict(kwargs),
                    transaction=get_transaction_provider(),
                )
                return _wrap_response(result, request)
            except AccessDeniedError:
                raise PermissionDenied() from None
        return sync_wrapper
    return decorator


def _extract_request_and_resolve(func: Callable, args: tuple, kwargs: dict):
    request = _extract_request(args, kwargs)
    return _resolve_args(func, args, kwargs), request


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
    """Decorator: SAPL-enforced streaming.

    The decorated function returns an async iterator. The wrapper drives the Mealy
    FSM and returns the enforced async iterator: it yields the permitted items,
    yields `AccessGrantedSignal` / `AccessSuspendedSignal` boundary markers when
    `signal_transitions=True`, and raises `AccessDeniedError` on terminal denial.
    The caller renders the returned stream to a transport.

    - `signal_transitions=True`: surface Suspended/Permitting boundary markers.
    - `pause_rap_during_suspend=True`: cancel the upstream iterator on entry to
      Suspended; re-subscribe on exit.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            subscription, _ = _build_subscription(
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

            return run_pipeline(
                decisions=get_pdp_client().decide(subscription),
                planner=get_planner(),
                rap_factory=_rap_factory,
                signal_transitions=signal_transitions,
                pause_rap_during_suspend=pause_rap_during_suspend,
            )
        return wrapper
    return decorator
