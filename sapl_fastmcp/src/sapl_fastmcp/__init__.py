"""SAPL authorization integration for FastMCP."""

import logging
import threading

from sapl_base import PdpClient, PdpConfig
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_fastmcp.auth_check import sapl
from sapl_fastmcp.context import SaplConfig, SubscriptionContext
from sapl_fastmcp.decorators import post_enforce, pre_enforce
from sapl_fastmcp.middleware import SAPLMiddleware

logger = logging.getLogger("sapl.mcp")

ERROR_NOT_CONFIGURED = "SAPL not configured. Call configure_sapl() during startup."

_lock = threading.Lock()
_pdp_client: PdpClient | None = None
_constraint_service: ConstraintEnforcementService | None = None


def configure_sapl(
    config: PdpConfig,
    constraint_service: ConstraintEnforcementService | None = None,
) -> None:
    """Initialize or reconfigure the PDP client and constraint service.

    Thread-safe. Must be called before any tool using sapl() is invoked.
    Pass an existing constraint_service to share handler registrations
    with other integrations (e.g., sapl_fastapi).

    Can be called again to reconfigure (e.g., in tests). The previous
    client and service are replaced.
    """
    global _pdp_client, _constraint_service
    with _lock:
        _pdp_client = PdpClient(config)
        _constraint_service = constraint_service or ConstraintEnforcementService()


def get_pdp_client() -> PdpClient:
    """Return the configured PDP client."""
    with _lock:
        client = _pdp_client
    if client is None:
        raise RuntimeError(ERROR_NOT_CONFIGURED)
    return client


def get_constraint_service() -> ConstraintEnforcementService:
    """Return the constraint service for handler registration."""
    with _lock:
        service = _constraint_service
    if service is None:
        raise RuntimeError(ERROR_NOT_CONFIGURED)
    return service


__all__ = [
    "SAPLMiddleware",
    "SaplConfig",
    "SubscriptionContext",
    "configure_sapl",
    "get_constraint_service",
    "get_pdp_client",
    "post_enforce",
    "pre_enforce",
    "sapl",
]
