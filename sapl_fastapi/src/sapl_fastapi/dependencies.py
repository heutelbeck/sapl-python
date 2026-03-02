from __future__ import annotations

from typing import Any

from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.content_filter import ContentFilteringProvider, ContentFilterPredicateProvider
from sapl_base.pdp_client import PdpClient

from sapl_fastapi.config import SaplConfig

# Module-level singleton state
_pdp_client: PdpClient | None = None
_constraint_service: ConstraintEnforcementService | None = None
_config: SaplConfig | None = None

ERROR_NOT_CONFIGURED = "SAPL not configured. Call configure_sapl() during app startup."


def configure_sapl(config: SaplConfig) -> None:
    """Initialize SAPL with the given config. Call this during FastAPI startup (lifespan)."""
    global _pdp_client, _constraint_service, _config
    _config = config
    _pdp_client = PdpClient(config.to_pdp_config())
    _constraint_service = ConstraintEnforcementService()
    # Register built-in content filtering providers
    _constraint_service.register_mapping(ContentFilteringProvider())
    _constraint_service.register_filter_predicate(ContentFilterPredicateProvider())


async def cleanup_sapl() -> None:
    """Cleanup SAPL resources. Call this during FastAPI shutdown."""
    global _pdp_client
    if _pdp_client:
        await _pdp_client.close()
        _pdp_client = None


def get_pdp_client() -> PdpClient:
    """Get the PDP client. For use as FastAPI dependency."""
    if _pdp_client is None:
        raise RuntimeError(ERROR_NOT_CONFIGURED)
    return _pdp_client


def get_constraint_service() -> ConstraintEnforcementService:
    """Get the constraint enforcement service. For use as FastAPI dependency."""
    if _constraint_service is None:
        raise RuntimeError(ERROR_NOT_CONFIGURED)
    return _constraint_service


def register_constraint_handler(provider: Any, handler_type: str) -> None:
    """Register a custom constraint handler provider.

    Args:
        provider: The handler provider instance.
        handler_type: One of 'runnable', 'consumer', 'mapping', 'filter_predicate',
                      'error_handler', 'error_mapping', 'method_invocation'.
    """
    service = get_constraint_service()
    registrar = getattr(service, f"register_{handler_type}", None)
    if registrar is None:
        raise ValueError(f"Unknown handler type: {handler_type}")
    registrar(provider)
