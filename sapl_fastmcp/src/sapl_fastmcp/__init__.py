"""SAPL authorization integration for FastMCP."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sapl_base.pep import ConstraintHandlerProvider, EnforcementPlanner, PepRuntime
from sapl_fastmcp.auth_check import sapl
from sapl_fastmcp.context import SaplConfig, SubscriptionContext
from sapl_fastmcp.decorators import post_enforce, pre_enforce
from sapl_fastmcp.middleware import SAPLMiddleware

if TYPE_CHECKING:
    from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions

logger = logging.getLogger("sapl.mcp")

_runtime = PepRuntime()


def configure_sapl(config: HttpPdpClientOptions) -> None:
    """Initialize or reconfigure the PDP client and rebuild the planner.

    Thread-safe. Must be called before any tool using sapl() is invoked.
    Can be called again to reconfigure (e.g., in tests). The previous
    client and planner are replaced; registered providers are preserved.
    """
    _runtime.configure(config)


def register_provider(provider: ConstraintHandlerProvider) -> None:
    """Register a constraint handler provider.

    Rebuilds the planner if it is already configured so that the new
    provider is visible to subsequent enforcement.
    """
    _runtime.register_provider(provider)


def get_pdp_client() -> HttpPdpClient:
    """Return the configured PDP client."""
    return _runtime.pdp_client


def get_planner() -> EnforcementPlanner:
    """Return the configured enforcement planner."""
    return _runtime.planner


def _reset_for_tests() -> None:
    """Reset module-level singletons. Intended for test isolation only."""
    _runtime._reset_for_tests()


__all__ = [
    "SAPLMiddleware",
    "SaplConfig",
    "SubscriptionContext",
    "configure_sapl",
    "get_pdp_client",
    "get_planner",
    "post_enforce",
    "pre_enforce",
    "register_provider",
    "sapl",
]
