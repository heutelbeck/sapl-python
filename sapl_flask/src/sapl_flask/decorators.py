from __future__ import annotations

import asyncio
import functools
import inspect
import json
from typing import TYPE_CHECKING, Any

from flask import Response

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
from sapl_flask.extension import get_sapl_extension
from sapl_flask.subscription import SubscriptionBuilder, SubscriptionField

if TYPE_CHECKING:
    from collections.abc import Callable

    from sapl_base.types import AuthorizationDecision, AuthorizationSubscription


def _extract_class_name(func: Callable) -> str:
    """Extract the class name from a method's qualified name.

    Returns empty string for plain functions.
    """
    qualname = getattr(func, "__qualname__", "")
    parts = qualname.split(".")
    return parts[-2] if len(parts) >= 2 else ""


def _resolve_args(func: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    """Resolve all positional and keyword arguments into a named dict.

    Excludes ``self`` and ``cls`` parameters.
    """
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        resolved = dict(bound.arguments)
        resolved.pop("self", None)
        resolved.pop("cls", None)
        return resolved
    except (TypeError, ValueError):
        return dict(kwargs)


def pre_enforce(
    *,
    subject: SubscriptionField = None,
    action: SubscriptionField = None,
    resource: SubscriptionField = None,
    environment: SubscriptionField = None,
    secrets: SubscriptionField = None,
    on_deny: Callable[[AuthorizationDecision], Any] | None = None,
) -> Callable:
    """Decorator: authorize BEFORE view execution.

    Queries the PDP with the built subscription. If the decision is PERMIT,
    the view function executes normally. Otherwise, returns 403 or the
    result of the ``on_deny`` callback.

    Usage::

        @app.route("/data")
        @pre_enforce(action="read", resource="data")
        def get_data():
            return {"data": "sensitive"}

    Args:
        subject: Override for subscription subject.
        action: Override for subscription action.
        resource: Override for subscription resource.
        environment: Override for subscription environment.
        secrets: Override for subscription secrets.
        on_deny: Optional callback receiving the AuthorizationDecision on deny.

    Returns:
        A decorator that wraps the view function with pre-enforcement.
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sapl = get_sapl_extension()
            resolved = _resolve_args(func, args, kwargs)
            subscription = SubscriptionBuilder.build(
                subject=subject,
                action=action,
                resource=resource,
                environment=environment,
                secrets=secrets,
                function_name=func.__name__,
                class_name=class_name,
                resolved_args=resolved,
            )

            async def async_func(*a: Any, **kw: Any) -> Any:
                return func(*a, **kw)

            return asyncio.run(_pre_enforce(
                pdp_client=sapl.pdp_client,
                constraint_service=sapl.constraint_service,
                subscription=subscription,
                protected_function=async_func,
                args=list(args),
                kwargs=kwargs,
                function_name=func.__name__,
                on_deny=on_deny,
                class_name=class_name,
                request=resolved.get("request"),
            ))
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
    """Decorator: authorize AFTER view execution.

    The view function executes first, then the PDP is queried with a subscription
    that includes the return value. If denied, returns 403 or the result of
    the ``on_deny`` callback.

    Args:
        subject: Override for subscription subject.
        action: Override for subscription action.
        resource: Override for subscription resource.
        environment: Override for subscription environment.
        secrets: Override for subscription secrets.
        on_deny: Optional callback receiving the AuthorizationDecision on deny.

    Returns:
        A decorator that wraps the view function with post-enforcement.
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sapl = get_sapl_extension()
            resolved = _resolve_args(func, args, kwargs)

            def subscription_builder(return_value: Any) -> AuthorizationSubscription:
                return SubscriptionBuilder.build(
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

            async def async_func(*a: Any, **kw: Any) -> Any:
                return func(*a, **kw)

            return asyncio.run(_post_enforce(
                pdp_client=sapl.pdp_client,
                constraint_service=sapl.constraint_service,
                subscription_builder=subscription_builder,
                protected_function=async_func,
                args=list(args),
                kwargs=kwargs,
                function_name=func.__name__,
                on_deny=on_deny,
                class_name=class_name,
                request=resolved.get("request"),
            ))
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

    The decorated function must return an async generator. Returns a Flask
    ``Response`` with ``text/event-stream`` content type, streaming SSE events.

    Args:
        subject: Override for subscription subject.
        action: Override for subscription action.
        resource: Override for subscription resource.
        environment: Override for subscription environment.
        secrets: Override for subscription secrets.
        on_stream_deny: Optional callback invoked when access is denied.

    Returns:
        A decorator that wraps the view function with streaming enforcement.
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Response:
            sapl = get_sapl_extension()
            resolved = _resolve_args(func, args, kwargs)
            subscription = SubscriptionBuilder.build(
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

            def sync_generator():
                loop = asyncio.new_event_loop()
                try:
                    agen = _enforce_till_denied(
                        pdp_client=sapl.pdp_client,
                        constraint_service=sapl.constraint_service,
                        subscription=subscription,
                        data_source=data_source,
                        on_stream_deny=on_stream_deny,
                    )
                    agen_iter = agen.__aiter__()
                    while True:
                        try:
                            item = loop.run_until_complete(agen_iter.__anext__())
                            yield _format_sse(item)
                        except StopAsyncIteration:
                            break
                finally:
                    loop.close()

            return Response(sync_generator(), mimetype="text/event-stream")
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
    """Decorator: streaming enforcement that silently drops data during deny.

    Data items arriving while the policy denies access are discarded. When
    a new PERMIT decision arrives, forwarding resumes.

    Args:
        subject: Override for subscription subject.
        action: Override for subscription action.
        resource: Override for subscription resource.
        environment: Override for subscription environment.
        secrets: Override for subscription secrets.

    Returns:
        A decorator that wraps the view function with drop-while-denied streaming.
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Response:
            sapl = get_sapl_extension()
            resolved = _resolve_args(func, args, kwargs)
            subscription = SubscriptionBuilder.build(
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

            def sync_generator():
                loop = asyncio.new_event_loop()
                try:
                    agen = _enforce_drop_while_denied(
                        pdp_client=sapl.pdp_client,
                        constraint_service=sapl.constraint_service,
                        subscription=subscription,
                        data_source=data_source,
                    )
                    agen_iter = agen.__aiter__()
                    while True:
                        try:
                            item = loop.run_until_complete(agen_iter.__anext__())
                            yield _format_sse(item)
                        except StopAsyncIteration:
                            break
                finally:
                    loop.close()

            return Response(sync_generator(), mimetype="text/event-stream")
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
    """Decorator: streaming enforcement with suspend/resume signals.

    When access transitions from PERMIT to DENY, the ``on_stream_deny`` callback
    is invoked. When access transitions back to PERMIT, ``on_stream_recover`` is
    invoked. Data items are dropped while denied.

    Args:
        subject: Override for subscription subject.
        action: Override for subscription action.
        resource: Override for subscription resource.
        environment: Override for subscription environment.
        secrets: Override for subscription secrets.
        on_stream_deny: Callback for PERMIT-to-DENY transitions.
        on_stream_recover: Callback for DENY-to-PERMIT transitions.

    Returns:
        A decorator that wraps the view function with recoverable streaming.
    """
    def decorator(func: Callable) -> Callable:
        class_name = _extract_class_name(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Response:
            sapl = get_sapl_extension()
            resolved = _resolve_args(func, args, kwargs)
            subscription = SubscriptionBuilder.build(
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

            def sync_generator():
                loop = asyncio.new_event_loop()
                try:
                    agen = _enforce_recoverable_if_denied(
                        pdp_client=sapl.pdp_client,
                        constraint_service=sapl.constraint_service,
                        subscription=subscription,
                        data_source=data_source,
                        on_stream_deny=on_stream_deny,
                        on_stream_recover=on_stream_recover,
                    )
                    agen_iter = agen.__aiter__()
                    while True:
                        try:
                            item = loop.run_until_complete(agen_iter.__anext__())
                            yield _format_sse(item)
                        except StopAsyncIteration:
                            break
                finally:
                    loop.close()

            return Response(sync_generator(), mimetype="text/event-stream")
        return wrapper
    return decorator


def _format_sse(data: Any) -> str:
    """Format a data item as a Server-Sent Events message.

    Args:
        data: The data to format. Dicts are JSON-serialized.

    Returns:
        An SSE-formatted string.
    """
    if isinstance(data, dict):
        return f"data: {json.dumps(data)}\n\n"
    return f"data: {data}\n\n"
