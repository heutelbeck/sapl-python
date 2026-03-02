from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sapl_base.constraint_types import SubscriptionContext
from sapl_base.types import AuthorizationSubscription

SubscriptionField = Any | Callable[[SubscriptionContext], Any]


class SubscriptionBuilder:
    """Builds AuthorizationSubscription from Flask request context."""

    @staticmethod
    def build(
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
        """Build a subscription with defaults derived from the current Flask request.

        Fields can be static values or callables receiving a SubscriptionContext.

        Defaults:

        - subject: ``g.user``, flask-login ``current_user``, JWT claims from Bearer token, or ``"anonymous"``
        - action: ``{"method": request.method, "endpoint": function_name}``
        - resource: ``{"path": request.path, "view_args": request.view_args}``
        - environment: ``{"ip": request.remote_addr}`` (when available)

        Args:
            subject: Override for the subject field.
            action: Override for the action field.
            resource: Override for the resource field.
            environment: Override for the environment field.
            secrets: Override for the secrets field (never logged).
            function_name: Name of the protected view function.
            class_name: Qualified class name (empty for plain functions).
            resolved_args: Named arguments of the protected function.
            return_value: Return value of the view (for post-enforce).

        Returns:
            A fully resolved authorization subscription.
        """
        context = _build_context(
            function_name=function_name,
            class_name=class_name,
            resolved_args=resolved_args or {},
            return_value=return_value,
        )

        resolved_subject = _resolve_field(subject, context)
        if resolved_subject is None:
            resolved_subject = _default_subject()

        resolved_action = _resolve_field(action, context)
        if resolved_action is None:
            resolved_action = _default_action(function_name)

        resolved_resource = _resolve_field(resource, context)
        if resolved_resource is None:
            resolved_resource = _default_resource()

        resolved_environment = _resolve_field(environment, context)
        if resolved_environment is None:
            resolved_environment = _default_environment()

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
    function_name: str,
    class_name: str,
    resolved_args: dict[str, Any],
    return_value: Any,
) -> SubscriptionContext:
    """Build a SubscriptionContext from the current Flask request (if available)."""
    request_obj = None
    params: dict[str, str] = {}
    query: dict[str, Any] = {}
    body: Any = None

    try:
        from flask import request as flask_request

        request_obj = flask_request._get_current_object()
        params = dict(flask_request.view_args or {})
        query = dict(flask_request.args)
        body = flask_request.get_json(silent=True)
    except RuntimeError:
        pass

    return SubscriptionContext(
        args=resolved_args,
        function_name=function_name,
        class_name=class_name,
        request=request_obj,
        params=params,
        query=query,
        body=body,
        return_value=return_value,
    )


def _resolve_field(field: SubscriptionField, context: SubscriptionContext) -> Any:
    """Resolve a subscription field: return static values directly, call callables."""
    if field is None:
        return None
    if callable(field):
        return field(context)
    return field


def _default_subject() -> Any:
    """Derive subject from g.user, flask-login current_user, JWT claims, or anonymous.

    Resolution order:
    1. ``flask.g.user`` (set by application code or middleware)
    2. ``flask_login.current_user`` (when flask-login is installed)
    3. JWT claims decoded from the ``Authorization: Bearer <token>`` header
       (base64 payload decode only -- no cryptographic verification, the PDP handles that)
    4. ``"anonymous"``
    """
    try:
        from flask import g

        user = getattr(g, "user", None)
        if user is not None:
            return user
    except RuntimeError:
        pass
    try:
        from flask_login import current_user

        if current_user.is_authenticated:
            return getattr(current_user, "username", str(current_user))
    except (ImportError, RuntimeError):
        pass

    claims = _extract_jwt_claims()
    if claims is not None:
        return claims

    return "anonymous"


def _extract_jwt_claims() -> dict[str, Any] | None:
    """Extract JWT claims from the Authorization header without cryptographic verification.

    Returns the decoded payload dict if a well-formed Bearer JWT is present,
    or ``None`` otherwise.  Only the base64 payload is decoded -- signature
    verification is left to the PDP.
    """
    try:
        from flask import request as flask_request

        auth_header = flask_request.headers.get("Authorization", "")
    except RuntimeError:
        return None

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer "):]
    parts = token.split(".")
    if len(parts) != 3:
        return None

    # Stash the raw token on flask.g so decorator secrets lambdas can access it
    try:
        from flask import g

        g.token = token
    except RuntimeError:
        pass

    try:
        import base64
        import json

        payload_b64 = parts[1]
        # JWT uses base64url encoding without padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception:
        return None


def _default_action(function_name: str) -> dict[str, str]:
    """Derive action from the HTTP method and view function name."""
    try:
        from flask import request as flask_request

        return {
            "method": flask_request.method,
            "endpoint": function_name or flask_request.endpoint or "",
        }
    except RuntimeError:
        return {"method": "", "endpoint": function_name}


def _default_resource() -> dict[str, Any]:
    """Derive resource from the request path and view arguments."""
    try:
        from flask import request as flask_request

        return {
            "path": flask_request.path,
            "view_args": dict(flask_request.view_args or {}),
        }
    except RuntimeError:
        return {"path": "", "view_args": {}}


def _default_environment() -> dict[str, Any]:
    """Derive environment from request metadata."""
    env: dict[str, Any] = {}
    try:
        from flask import request as flask_request

        if flask_request.remote_addr:
            env["ip"] = flask_request.remote_addr
    except RuntimeError:
        pass
    return env
