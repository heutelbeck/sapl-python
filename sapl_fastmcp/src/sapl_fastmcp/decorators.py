"""SAPL enforcement decorators for MCP tools, resources, and prompts.

Metadata-only decorators that attach a ``SaplConfig`` as ``fn.__sapl__``.
The function itself is returned unchanged (not wrapped), preserving its
identity for FastMCP's introspection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sapl_fastmcp.context import FinalizeCallback, MiddlewareSaplField, SaplConfig

if TYPE_CHECKING:
    from collections.abc import Callable


def pre_enforce(
    *,
    subject: MiddlewareSaplField = None,
    action: MiddlewareSaplField = None,
    resource: MiddlewareSaplField = None,
    environment: MiddlewareSaplField = None,
    secrets: MiddlewareSaplField = None,
    finalize: FinalizeCallback | None = None,
    stealth: bool = False,
) -> Callable[..., Any]:
    """Attach pre-enforce SAPL configuration to a function.

    The PDP is queried BEFORE the tool executes. If the decision is not
    PERMIT, the tool never runs.

    When ``stealth=True``, denied access raises ``NotFoundError`` instead of
    ``AccessDeniedError``, making hidden components indistinguishable from
    non-existent ones.
    """
    return _sapl_decorator(
        "pre",
        subject=subject,
        action=action,
        resource=resource,
        environment=environment,
        secrets=secrets,
        finalize=finalize,
        stealth=stealth,
    )


def post_enforce(
    *,
    subject: MiddlewareSaplField = None,
    action: MiddlewareSaplField = None,
    resource: MiddlewareSaplField = None,
    environment: MiddlewareSaplField = None,
    secrets: MiddlewareSaplField = None,
    finalize: FinalizeCallback | None = None,
    stealth: bool = False,
) -> Callable[..., Any]:
    """Attach post-enforce SAPL configuration to a function.

    The tool executes FIRST, then the PDP is queried with the return value
    available in ``SubscriptionContext.return_value``. If the decision is
    not PERMIT, the result is suppressed.

    When ``stealth=True``, denied access raises ``NotFoundError`` instead of
    ``AccessDeniedError``, making hidden components indistinguishable from
    non-existent ones.
    """
    return _sapl_decorator(
        "post",
        subject=subject,
        action=action,
        resource=resource,
        environment=environment,
        secrets=secrets,
        finalize=finalize,
        stealth=stealth,
    )


def _sapl_decorator(
    mode: Literal["pre", "post"],
    **kwargs: Any,
) -> Callable[..., Any]:
    config = SaplConfig(mode=mode, **kwargs)

    def decorator(fn: Any) -> Any:
        if hasattr(fn, "__sapl__"):
            raise TypeError(
                f"Cannot apply both @pre_enforce and @post_enforce to {fn.__qualname__}. "
                "Use one or the other."
            )
        fn.__sapl__ = config
        return fn

    return decorator
