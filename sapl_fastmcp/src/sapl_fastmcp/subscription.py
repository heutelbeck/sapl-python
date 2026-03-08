"""SAPL subscription building for auth-check and middleware paths."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastmcp.server.auth import AccessToken, AuthContext

from sapl_base import AuthorizationSubscription

if TYPE_CHECKING:
    from sapl_fastmcp.context import SaplConfig, SubscriptionContext

SaplField = Any | Callable[[AuthContext], Any]
"""A subscription field: static value, ``Callable[[AuthContext], Any]``, or None.

Typed as ``Any`` because the domain allows both arbitrary static values and
callables. Python's type system cannot express this union without collapsing
to ``Any`` -- ``_resolve()`` uses ``callable()`` at runtime to disambiguate.
"""


def build_subscription(
    ctx: AuthContext,
    *,
    subject: SaplField = None,
    action: SaplField = None,
    resource: SaplField = None,
    environment: SaplField = None,
    secrets: SaplField = None,
) -> AuthorizationSubscription:
    """Build an AuthorizationSubscription from an AuthContext.

    Each field can be a static value, a callable ``(AuthContext) -> Any``,
    or None. None means "use the default" for subject/action/resource
    and "omit" for environment/secrets. Falsy values (0, "", False) are
    valid overrides and will not trigger the default.
    """
    sub = _resolve(subject, ctx, _default_subject)
    act = _resolve(action, ctx, _default_auth_action)
    res = _resolve(resource, ctx, _default_auth_resource)
    return _validate_and_build(
        sub, act, res,
        _resolve(environment, ctx, _default_none),
        _resolve(secrets, ctx, _default_none),
    )


def build_middleware_subscription(
    ctx: SubscriptionContext,
    config: SaplConfig,
) -> AuthorizationSubscription:
    """Build an ``AuthorizationSubscription`` from middleware context and config.

    Each field in *config* can be a static value, a callable
    ``(SubscriptionContext) -> Any``, or None (use default). Falsy values
    (0, "", False) are valid overrides and will not trigger the default.
    """
    sub = _resolve(config.subject, ctx, _default_subject)
    act = _resolve(config.action, ctx, _default_middleware_action)
    res = _resolve(config.resource, ctx, _default_middleware_resource)
    return _validate_and_build(
        sub, act, res,
        _resolve(config.environment, ctx, _default_none),
        _resolve(config.secrets, ctx, _default_none),
    )


# -- Shared internals --


def _resolve(
    override: Any,
    ctx: Any,
    default: Callable[[Any], Any],
) -> Any:
    """Resolve a single subscription field value."""
    if override is not None:
        return override(ctx) if callable(override) else override
    return default(ctx)


def _validate_and_build(
    sub: Any, act: Any, res: Any, env: Any, secrets: Any,
) -> AuthorizationSubscription:
    """Validate mandatory fields and construct the subscription."""
    missing = [k for k, v in [("subject", sub), ("action", act), ("resource", res)] if v is None]
    if missing:
        raise ValueError(f"Mandatory field(s) resolved to None: {', '.join(missing)}")
    return AuthorizationSubscription(
        subject=sub, action=act, resource=res, environment=env, secrets=secrets,
    )


def _default_subject(ctx: Any) -> Any:
    """Derive subject from the auth token.

    Returns the full claims dict when available so that policies can access
    any claim the authorization server provides (custom roles, org membership,
    etc.). To restrict to a single field, pass a custom resolver::

        sapl(subject=lambda ctx: ctx.token.claims.get("sub"))
    """
    if ctx.token is None:
        return "anonymous"
    if isinstance(ctx.token, AccessToken):
        if ctx.token.claims:
            return ctx.token.claims
        if ctx.token.client_id:
            return ctx.token.client_id
    return "anonymous"


def _default_none(_ctx: Any) -> None:
    return None


# -- Auth-check defaults --


def _default_auth_action(ctx: Any) -> str | None:
    if ctx.component is not None and hasattr(ctx.component, "name"):
        return ctx.component.name
    return None


def _default_auth_resource(_ctx: Any) -> str:
    return "mcp"


# -- Middleware defaults --


def _default_middleware_action(ctx: SubscriptionContext) -> str | None:
    """Derive action from the operation verb (call, read, get, list)."""
    return ctx.operation


def _default_middleware_resource(ctx: SubscriptionContext) -> Any:
    """Derive resource from the component being acted on.

    The resource identifies the target: component name, arguments, URI.
    """
    result: dict[str, Any] = {}
    if ctx.component is not None and hasattr(ctx.component, "name"):
        result["name"] = ctx.component.name
    if ctx.operation in ("call", "get") and ctx.arguments:
        result["arguments"] = dict(ctx.arguments)
    if ctx.operation == "read" and ctx.uri:
        result["uri"] = ctx.uri
    if ctx.component is not None and hasattr(ctx.component, "tags") and ctx.component.tags:
        result["tags"] = list(ctx.component.tags)
    return result if result else "mcp"
