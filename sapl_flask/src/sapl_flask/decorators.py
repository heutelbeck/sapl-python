from __future__ import annotations

import asyncio
import functools
import inspect
import json
from typing import TYPE_CHECKING, Any

from flask import Response, abort

from sapl_base.pep import (
    AccessDeniedError,
    AccessGrantedSignal,
    AccessSuspendedSignal,
    post_enforce as _post_enforce,
    pre_enforce as _pre_enforce,
)
from sapl_base.pep.streaming import run_pipeline

from sapl_flask.extension import get_sapl_extension
from sapl_flask.subscription import SubscriptionBuilder, SubscriptionField

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from sapl_base.types import AuthorizationDecision, AuthorizationSubscription


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
        return resolved
    except (TypeError, ValueError):
        return dict(kwargs)


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
    resolved = _resolve_args(func, args, kwargs)
    return SubscriptionBuilder.build(
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
    on_deny: Callable[[AuthorizationDecision], Any] | None = None,
) -> Callable:
    """Decorator: authorize BEFORE view execution.

    Queries the PDP with the built subscription. On PERMIT the view
    executes; on any other verb the wrapper aborts with 403 (or calls
    `on_deny(decision)` if supplied and returns its result).
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sapl = get_sapl_extension()
            subscription = _build_subscription(
                func, args, kwargs,
                subject=subject, action=action, resource=resource,
                environment=environment, secrets=secrets,
            )

            async def _async_func(*a: Any, **kw: Any) -> Any:
                return func(*a, **kw)

            try:
                return asyncio.run(_pre_enforce(
                    _async_func,
                    pdp_client=sapl.pdp_client,
                    planner=sapl.planner,
                    subscription=subscription,
                    args=tuple(args),
                    kwargs=dict(kwargs),
                ))
            except AccessDeniedError as exc:
                if on_deny is not None:
                    return on_deny(exc.decision)
                abort(403)
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

    The view runs first; the PDP is then queried with a subscription
    that can reference the return value. On deny the wrapper aborts
    with 403 (or calls `on_deny(decision)`).
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sapl = get_sapl_extension()

            def _subscription_builder(return_value: Any) -> AuthorizationSubscription:
                return _build_subscription(
                    func, args, kwargs,
                    subject=subject, action=action, resource=resource,
                    environment=environment, secrets=secrets,
                    return_value=return_value,
                )

            async def _async_func(*a: Any, **kw: Any) -> Any:
                return func(*a, **kw)

            try:
                return asyncio.run(_post_enforce(
                    _async_func,
                    pdp_client=sapl.pdp_client,
                    planner=sapl.planner,
                    subscription_builder=_subscription_builder,
                    args=tuple(args),
                    kwargs=dict(kwargs),
                ))
            except AccessDeniedError as exc:
                if on_deny is not None:
                    return on_deny(exc.decision)
                abort(403)
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

    The decorated function returns an async iterator of data items.
    The wrapper opens a PDP subscription stream, drives the Mealy FSM,
    and yields items as SSE `data:` frames on `text/event-stream`.

    Flags map to `run_pipeline`:

    - `signal_transitions`: when True, emits `ACCESS_SUSPENDED` and
      `ACCESS_RESTORED` SSE frames on Suspended/Permitting transitions.
    - `pause_rap_during_suspend`: when True, cancels the upstream
      async iterator on entry to Suspended and re-subscribes on exit.

    DENY is terminal: a final `ACCESS_DENIED` SSE frame is emitted and
    the stream closes. For keep-alive semantics, the policy must emit
    SUSPEND.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Response:
            sapl = get_sapl_extension()
            subscription = _build_subscription(
                func, args, kwargs,
                subject=subject, action=action, resource=resource,
                environment=environment, secrets=secrets,
            )

            def _rap_factory() -> AsyncIterator[Any]:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    raise TypeError(
                        "stream_enforce target must return an async iterator, not a coroutine"
                    )
                return result

            def _sse_generator() -> Any:
                loop = asyncio.new_event_loop()
                try:
                    pipeline = run_pipeline(
                        decisions=sapl.pdp_client.decide(subscription),
                        planner=sapl.planner,
                        rap_factory=_rap_factory,
                        signal_transitions=signal_transitions,
                        pause_rap_during_suspend=pause_rap_during_suspend,
                    )
                    aiter_ = pipeline.__aiter__()
                    while True:
                        try:
                            item = loop.run_until_complete(aiter_.__anext__())
                        except StopAsyncIteration:
                            break
                        except AccessDeniedError as exc:
                            yield _format_sse({
                                "type": "ACCESS_DENIED",
                                "reason": getattr(exc, "reason", None),
                            })
                            break
                        yield _format_sse(item)
                finally:
                    loop.close()

            return Response(_sse_generator(), mimetype="text/event-stream")
        return wrapper
    return decorator


def _format_sse(data: Any) -> str:
    if isinstance(data, AccessSuspendedSignal):
        return "data: " + json.dumps({"type": "ACCESS_SUSPENDED"}) + "\n\n"
    if isinstance(data, AccessGrantedSignal):
        return "data: " + json.dumps({"type": "ACCESS_RESTORED"}) + "\n\n"
    if isinstance(data, dict):
        return f"data: {json.dumps(data)}\n\n"
    return f"data: {data}\n\n"
