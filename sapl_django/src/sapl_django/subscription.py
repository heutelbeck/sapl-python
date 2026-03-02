from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sapl_base.constraint_types import SubscriptionContext
from sapl_base.types import AuthorizationSubscription

if TYPE_CHECKING:
    from django.http import HttpRequest

SubscriptionField = Any | Callable[[SubscriptionContext], Any]


class SubscriptionBuilder:
    """Builds AuthorizationSubscription from a Django HttpRequest."""

    @staticmethod
    def build(
        request: HttpRequest | None = None,
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
        """Build a subscription with defaults extracted from the request.

        Defaults:
        - subject: explicit param > request.user > JWT claims from header > "anonymous"
        - action: { method: request.method, view: function_name }
        - resource: { path: request.path, kwargs: resolver_match.kwargs }
        - environment: { ip: request.META.get("REMOTE_ADDR") }

        Args:
            request: The Django HttpRequest (None for service-layer calls).
            subject: Override for subject field (static value or callable).
            action: Override for action field (static value or callable).
            resource: Override for resource field (static value or callable).
            environment: Override for environment field (static value or callable).
            secrets: Override for secrets field (static value or callable).
            function_name: Name of the decorated view function.
            class_name: Qualified class name (empty for plain functions).
            resolved_args: Named arguments of the protected function.
            return_value: Return value of the view (for post_enforce).

        Returns:
            A fully populated AuthorizationSubscription.
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
    request: HttpRequest | None,
    function_name: str,
    class_name: str,
    resolved_args: dict[str, Any],
    return_value: Any,
) -> SubscriptionContext:
    """Build a SubscriptionContext from the Django HttpRequest."""
    params: dict[str, str] = {}
    query: dict[str, Any] = {}
    body: Any = None

    if request is not None:
        resolver_match = getattr(request, "resolver_match", None)
        if resolver_match is not None:
            params = dict(resolver_match.kwargs)
        query = dict(request.GET)

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
    """Resolve a subscription field: call it if callable, return as-is otherwise."""
    if field is None:
        return None
    if callable(field):
        return field(context)
    return field


def _default_subject(request: HttpRequest | None) -> Any:
    """Extract subject with priority: request.user > JWT claims > 'anonymous'.

    When request.user is anonymous or unauthenticated, checks the Authorization
    header for a Bearer token and base64-decodes its payload (no cryptographic
    verification -- the PDP handles that).
    """
    if request is None:
        return "anonymous"
    user = getattr(request, "user", None)
    if user is not None and _is_authenticated(user):
        username = getattr(user, "username", None)
        if username:
            return username
    claims = _extract_jwt_claims(request)
    if claims is not None:
        return claims
    return "anonymous"


def _is_authenticated(user: Any) -> bool:
    """Check if a Django user object represents an authenticated user.

    Uses is_authenticated when available (standard Django User / AnonymousUser),
    falls back to checking for a non-empty username.
    """
    if hasattr(user, "is_authenticated"):
        return bool(user.is_authenticated)
    if hasattr(user, "username"):
        return bool(user.username)
    return False


_log = logging.getLogger(__name__)


def _extract_jwt_claims(request: HttpRequest) -> dict[str, Any] | None:
    """Base64-decode JWT payload from the Authorization header.

    Returns the claims dict, or None if no valid Bearer token is present.
    Only decodes the payload segment -- no signature verification.
    """
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    parts = token.split(".")
    if len(parts) != 3:
        return None
    # Stash the raw token on the request so decorator secrets lambdas can access it
    request.sapl_token = token
    try:
        payload_b64 = parts[1]
        # JWT uses base64url encoding without padding
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded)
        claims: dict[str, Any] = json.loads(payload_bytes)
        return claims
    except Exception:
        _log.debug("Failed to decode JWT payload from Authorization header")
        return None


def _default_action(request: HttpRequest | None, function_name: str) -> dict[str, str]:
    """Build default action dict from HTTP method and view function name."""
    if request is None:
        return {"method": "", "view": function_name}
    return {"method": request.method, "view": function_name}


def _default_resource(request: HttpRequest | None) -> dict[str, Any]:
    """Build default resource dict from request path and URL kwargs."""
    if request is None:
        return {"path": "", "kwargs": {}}
    result: dict[str, Any] = {"path": request.path}
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is not None:
        result["kwargs"] = dict(resolver_match.kwargs)
    else:
        result["kwargs"] = {}
    return result


def _default_environment(request: HttpRequest | None) -> dict[str, Any]:
    """Build default environment dict from request metadata."""
    env: dict[str, Any] = {}
    if request is not None:
        remote_addr = request.META.get("REMOTE_ADDR")
        if remote_addr:
            env["ip"] = remote_addr
    return env
