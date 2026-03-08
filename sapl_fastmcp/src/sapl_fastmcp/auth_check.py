"""SAPL auth check for FastMCP's auth= parameter."""

import logging
from collections.abc import Awaitable, Callable

from fastmcp.server.auth import AuthContext

from sapl_base import Decision
from sapl_fastmcp.enforcement import enforce_decision_gate
from sapl_fastmcp.subscription import SaplField, build_subscription

logger = logging.getLogger("sapl.mcp")


def sapl(
    *,
    subject: SaplField = None,
    action: SaplField = None,
    resource: SaplField = None,
    environment: SaplField = None,
    secrets: SaplField = None,
) -> Callable[[AuthContext], Awaitable[bool]]:
    """Create an auth check for FastMCP's auth= parameter.

    Each field can be a static value or a callable ``(AuthContext) -> Any``.
    ``None`` means "use the default" for subject/action/resource, and "omit
    from subscription" for environment/secrets. Falsy values (0, "", False)
    are valid overrides and will not trigger the default.

    configure_sapl() must be called before any tool using sapl() is invoked.
    If not, the auth check raises RuntimeError at request time.

    Usage::

        @mcp.tool(auth=sapl())
        def my_tool(): ...

        @mcp.tool(auth=sapl(action="read_patient"))
        def read_patient(): ...

        @mcp.tool(auth=sapl(subject=lambda ctx: ctx.token.claims.get("sub")))
        def sensitive_tool(): ...
    """
    from sapl_fastmcp import get_constraint_service, get_pdp_client

    async def check(ctx: AuthContext) -> bool:
        _warn_if_stealth(ctx)
        subscription = build_subscription(
            ctx,
            subject=subject,
            action=action,
            resource=resource,
            environment=environment,
            secrets=secrets,
        )
        logger.debug("SAPL subscription: %s", subscription.to_loggable_dict())

        decision = await get_pdp_client().decide_once(subscription)
        logger.debug("SAPL decision: %s", decision.decision)

        if decision.decision not in (Decision.PERMIT, Decision.DENY):
            logger.warning(
                "Access denied: PDP returned %s (no matching policy?)",
                decision.decision,
            )
            return False

        return enforce_decision_gate(get_constraint_service(), decision)

    return check


WARN_STEALTH_IGNORED = (
    "stealth=True on '%s' has no effect with auth= path; use SAPLMiddleware instead"
)


def _warn_if_stealth(ctx: AuthContext) -> None:
    """Log a warning if the component has stealth=True, which is ignored in the auth= path."""
    comp = getattr(ctx, "component", None)
    if comp is None:
        return
    fn = getattr(comp, "fn", None)
    if fn is None:
        return
    config = getattr(fn, "__sapl__", None)
    if config is not None and getattr(config, "stealth", False):
        logger.warning(WARN_STEALTH_IGNORED, getattr(comp, "name", "?"))
