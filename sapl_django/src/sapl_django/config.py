from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.content_filter import ContentFilteringProvider, ContentFilterPredicateProvider
from sapl_base.pdp_client import PdpClient, PdpConfig

ERROR_MISSING_CONFIG = "SAPL_CONFIG not found in Django settings"
ERROR_NOT_CONFIGURED = "SAPL not configured. Ensure SAPL_CONFIG is set in Django settings."
ERROR_UNKNOWN_HANDLER_TYPE = "Unknown handler type: %s"

_pdp_client: PdpClient | None = None
_constraint_service: ConstraintEnforcementService | None = None


def get_sapl_config() -> dict[str, Any]:
    """Read and validate the SAPL_CONFIG dict from Django settings.

    Returns:
        The SAPL configuration dictionary.

    Raises:
        ImproperlyConfigured: If SAPL_CONFIG is not defined in settings.
    """
    config = getattr(settings, "SAPL_CONFIG", None)
    if config is None:
        raise ImproperlyConfigured(ERROR_MISSING_CONFIG)
    return config


def get_pdp_client() -> PdpClient:
    """Return the singleton PDP client, creating it lazily from Django settings.

    Returns:
        The configured PdpClient instance.

    Raises:
        ImproperlyConfigured: If SAPL_CONFIG is not defined in settings.
    """
    global _pdp_client
    if _pdp_client is None:
        config = get_sapl_config()
        _pdp_client = PdpClient(PdpConfig(
            base_url=config.get("base_url", "https://localhost:8443"),
            token=config.get("token"),
            username=config.get("username"),
            password=config.get("password"),
            timeout=config.get("timeout", 5.0),
            allow_insecure_connections=config.get("allow_insecure_connections", False),
            streaming_max_retries=config.get("streaming_max_retries", 0),
            streaming_retry_base_delay=config.get("streaming_retry_base_delay", 1.0),
            streaming_retry_max_delay=config.get("streaming_retry_max_delay", 30.0),
        ))
    return _pdp_client


def get_constraint_service() -> ConstraintEnforcementService:
    """Return the singleton constraint enforcement service with built-in providers.

    Returns:
        The configured ConstraintEnforcementService instance.
    """
    global _constraint_service
    if _constraint_service is None:
        _constraint_service = ConstraintEnforcementService()
        _constraint_service.register_mapping(ContentFilteringProvider())
        _constraint_service.register_filter_predicate(ContentFilterPredicateProvider())
    return _constraint_service


def register_constraint_handler(provider: Any, handler_type: str) -> None:
    """Register a custom constraint handler provider.

    Args:
        provider: The handler provider instance.
        handler_type: One of 'runnable', 'consumer', 'mapping', 'filter_predicate',
                      'error_handler', 'error_mapping', 'method_invocation'.

    Raises:
        ValueError: If handler_type is not a recognized registration method.
    """
    service = get_constraint_service()
    registrar = getattr(service, f"register_{handler_type}", None)
    if registrar is None:
        raise ValueError(ERROR_UNKNOWN_HANDLER_TYPE % handler_type)
    registrar(provider)


async def cleanup_sapl() -> None:
    """Close the PDP client and release resources.

    Call during Django shutdown or in test teardown.
    """
    global _pdp_client
    if _pdp_client is not None:
        await _pdp_client.close()
        _pdp_client = None
