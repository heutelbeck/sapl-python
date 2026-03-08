"""Types shared between SAPL decorators and middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from fastmcp.server.auth import AccessToken

    from sapl_base import AuthorizationDecision

MiddlewareSaplField = Any
"""A subscription field: static value, ``Callable[[SubscriptionContext], Any]``, or None.

Typed as ``Any`` because the domain allows both arbitrary static values and
callables with signature ``(SubscriptionContext) -> Any``. Python's type system
cannot distinguish "a callable that is the value" from "a callable that produces
the value" -- ``_resolve()`` uses ``callable()`` at runtime to disambiguate.
"""

FinalizeCallback = Callable[["AuthorizationDecision", "SubscriptionContext"], Awaitable[None]]
"""Called after enforcement with the final decision and subscription context."""


@dataclass(frozen=True, slots=True)
class SubscriptionContext:
    """MCP-specific context for building authorization subscriptions.

    Richer than ``sapl_base.constraint_types.SubscriptionContext`` because
    middleware has access to the OAuth token, the FastMCP component object,
    tool arguments, resource URIs, and return values.
    """

    token: AccessToken | None = None
    component: Any = None
    operation: Literal["list", "call", "read", "get"] | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    uri: str | None = None
    return_value: Any = None


@dataclass(frozen=True, slots=True)
class SaplConfig:
    """SAPL enforcement configuration attached to functions by decorators."""

    mode: Literal["pre", "post"] = "pre"
    subject: MiddlewareSaplField = None
    action: MiddlewareSaplField = None
    resource: MiddlewareSaplField = None
    environment: MiddlewareSaplField = None
    secrets: MiddlewareSaplField = None
    finalize: FinalizeCallback | None = None
    stealth: bool = False
    """Hide denied components from listings and mask denials as not-found.

    Only effective with ``SAPLMiddleware``. Has no effect with the
    ``auth=sapl()`` path (a warning is logged at request time).
    """
