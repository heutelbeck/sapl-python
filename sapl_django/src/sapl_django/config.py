from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from sapl_base.pep import ConstraintHandlerProvider, EnforcementPlanner, PepRuntime
from sapl_base.pep.transaction import SyncTransactionProvider, TransactionProvider
from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions

ERROR_MISSING_CONFIG = "SAPL_CONFIG not found in Django settings"

_runtime = PepRuntime()


def get_sapl_config() -> dict[str, Any]:
    """Read and validate the SAPL_CONFIG dict from Django settings.

    Raises ImproperlyConfigured if SAPL_CONFIG is not defined.
    """
    config = getattr(settings, "SAPL_CONFIG", None)
    if config is None:
        raise ImproperlyConfigured(ERROR_MISSING_CONFIG)
    return config


def get_pdp_client() -> HttpPdpClient:
    """Return the singleton PDP client, building it lazily from settings."""
    if not _runtime.is_configured:
        _runtime.configure(_options_from_settings())
    return _runtime.pdp_client


def get_planner() -> EnforcementPlanner:
    """Return the singleton enforcement planner."""
    if not _runtime.is_configured:
        _runtime.configure(_options_from_settings())
    return _runtime.planner


def register_provider(provider: ConstraintHandlerProvider) -> None:
    """Register a custom constraint handler provider. Rebuilds the planner."""
    _runtime.register_provider(provider)


def set_transaction_provider(
    provider: SyncTransactionProvider | TransactionProvider | None,
) -> None:
    """Set (or clear) the transaction provider that pre/post enforce wrap DB writes in.

    A provider is a zero-arg factory returning a context manager that commits on clean
    exit and rolls back on a propagated exception. It must match the view kind. Sync views
    run on the blocking core, which uses a sync context manager, so pass Django's own
    ``transaction.atomic`` directly. Async views run on the async core, which uses an async
    context manager. Django's ``transaction.atomic`` is async-unsafe and cannot back an
    async view, so transactional enforcement over the Django ORM is a sync-view feature.
    When set, a post-write denial (DENY or output-obligation failure) rolls the
    transaction back.
    """
    _runtime.set_transaction_provider(provider)


def get_transaction_provider() -> SyncTransactionProvider | TransactionProvider | None:
    """Get the configured transaction provider, or None if unset."""
    return _runtime.transaction_provider


async def cleanup_sapl() -> None:
    """Close the PDP client and release resources."""
    await _runtime.close()


def _options_from_settings() -> HttpPdpClientOptions:
    config = get_sapl_config()
    return HttpPdpClientOptions(
        base_url=config.get("base_url", "https://localhost:8443"),
        token=config.get("token"),
        username=config.get("username"),
        secret=config.get("secret"),
        timeout_seconds=config.get("timeout_seconds", 5.0),
        streaming_retry_base_delay_seconds=config.get(
            "streaming_retry_base_delay_seconds", 1.0
        ),
        streaming_retry_max_delay_seconds=config.get(
            "streaming_retry_max_delay_seconds", 30.0
        ),
    )
