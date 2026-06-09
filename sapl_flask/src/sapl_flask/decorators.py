from __future__ import annotations

import asyncio
import functools
import inspect
from typing import TYPE_CHECKING, Any

from flask import abort

from sapl_base.pep import (
    AccessDeniedError,
)
from sapl_base.pep.enforce import (
    post_enforce_blocking as _post_enforce_blocking,
)
from sapl_base.pep.enforce import (
    pre_enforce_blocking as _pre_enforce_blocking,
)
from sapl_base.pep.streaming import run_pipeline
from sapl_flask.extension import get_sapl_extension
from sapl_flask.subscription import SubscriptionBuilder, SubscriptionField

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from sapl_base.types import AuthorizationSubscription


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
) -> Callable:
    """Decorator: authorize BEFORE view execution.

    Queries the PDP with the built subscription, then runs the sync view on the
    blocking enforcement core (off the event loop). On PERMIT the view executes;
    on any other verb the wrapper aborts with 403.
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

            try:
                return _pre_enforce_blocking(
                    func,
                    pdp_client=sapl.pdp_client,
                    planner=sapl.planner,
                    subscription=subscription,
                    args=tuple(args),
                    kwargs=dict(kwargs),
                    transaction=sapl.transaction_provider,
                )
            except AccessDeniedError:
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
) -> Callable:
    """Decorator: authorize AFTER view execution.

    The sync view runs first on the blocking enforcement core (off the event
    loop); the PDP is then queried with a subscription that can reference the
    return value. On deny the wrapper aborts with 403.
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

            try:
                return _post_enforce_blocking(
                    func,
                    pdp_client=sapl.pdp_client,
                    planner=sapl.planner,
                    subscription_builder=_subscription_builder,
                    args=tuple(args),
                    kwargs=dict(kwargs),
                    transaction=sapl.transaction_provider,
                )
            except AccessDeniedError:
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

            return run_pipeline(
                decisions=sapl.pdp_client.decide(subscription),
                planner=sapl.planner,
                rap_factory=_rap_factory,
                signal_transitions=signal_transitions,
                pause_rap_during_suspend=pause_rap_during_suspend,
            )
        return wrapper
    return decorator
