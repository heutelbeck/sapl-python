from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sapl_base.constraint_types import SubscriptionContext
from sapl_base.types import AuthorizationSubscription

if TYPE_CHECKING:
    from starlette.requests import Request

SubscriptionField = Any | Callable[[SubscriptionContext], Any]


class SubscriptionBuilder:
    """Builds AuthorizationSubscription from FastAPI/Starlette request context."""

    @staticmethod
    def build(
        request: Request | None = None,
        *,
        subject: SubscriptionField = None,
        action: SubscriptionField = None,
        resource: SubscriptionField = None,
        environment: SubscriptionField = None,
        secrets: SubscriptionField = None,
        function_name: str = "",
        class_name: str = "",
        resolved_args: dict[str, Any] | None = None,
        return_value: Any = None,
    ) -> AuthorizationSubscription:
        """Build a subscription with defaults from the request.

        Defaults:
        - subject: request.scope["user"] or request.state.user, else "anonymous"
        - action: { method: request.method, handler: function_name }
        - resource: { path: request.url.path, params: dict(request.path_params) }
        - environment: { ip: request.client.host if available }
        """
        context = _build_context(
            request=request,
            function_name=function_name,
            class_name=class_name,
            resolved_args=resolved_args or {},
            return_value=return_value,
        )

        resolved_subject = _resolve_field(subject, context)
        if resolved_subject is None:
            resolved_subject = _default_subject(request)

        resolved_action = _resolve_field(action, context)
        if resolved_action is None:
            resolved_action = _default_action(request, function_name)

        resolved_resource = _resolve_field(resource, context)
        if resolved_resource is None:
            resolved_resource = _default_resource(request)

        resolved_environment = _resolve_field(environment, context)
        if resolved_environment is None:
            resolved_environment = _default_environment(request)

        resolved_secrets = _resolve_field(secrets, context)

        return AuthorizationSubscription(
            subject=resolved_subject,
            action=resolved_action,
            resource=resolved_resource,
            environment=resolved_environment,
            secrets=resolved_secrets,
        )


def _build_context(
    *,
    request: Request | None,
    function_name: str,
    class_name: str,
    resolved_args: dict[str, Any],
    return_value: Any,
) -> SubscriptionContext:
    """Build a SubscriptionContext from the FastAPI/Starlette request."""
    params: dict[str, str] = {}
    query: dict[str, Any] = {}
    body: Any = None

    if request is not None:
        params = dict(request.path_params)
        query = dict(request.query_params)

    return SubscriptionContext(
        args=resolved_args,
        function_name=function_name,
        class_name=class_name,
        request=request,
        params=params,
        query=query,
        body=body,
        return_value=return_value,
    )


def _resolve_field(field: SubscriptionField, context: SubscriptionContext) -> Any:
    if field is None:
        return None
    if callable(field):
        return field(context)
    return field


def _default_subject(request: Request | None) -> Any:
    if request is None:
        return "anonymous"
    user = getattr(request.state, "user", None) if hasattr(request, "state") else None
    if user is None:
        user = request.scope.get("user")
    if user is not None:
        return user
    return "anonymous"


def _default_action(request: Request | None, function_name: str) -> dict[str, str]:
    if request is None:
        return {"method": "", "handler": function_name}
    return {"method": request.method, "handler": function_name}


def _default_resource(request: Request | None) -> dict[str, Any]:
    if request is None:
        return {"path": "", "params": {}}
    return {"path": request.url.path, "params": dict(request.path_params)}


def _default_environment(request: Request | None) -> dict[str, Any]:
    env: dict[str, Any] = {}
    if request is not None and request.client:
        env["ip"] = request.client.host
    return env
