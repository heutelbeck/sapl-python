from __future__ import annotations

from sapl_base.pep import ConstraintHandlerProvider, EnforcementPlanner, PepRuntime
from sapl_base.pep.transaction import TransactionProvider
from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions

_runtime = PepRuntime()


def configure_sapl(options: HttpPdpClientOptions) -> None:
    """Initialize SAPL with the given options. Call before starting the IOLoop."""
    _runtime.configure(options)


async def cleanup_sapl() -> None:
    """Cleanup SAPL resources. Call during Tornado shutdown."""
    await _runtime.close()


def get_pdp_client() -> HttpPdpClient:
    return _runtime.pdp_client


def get_planner() -> EnforcementPlanner:
    return _runtime.planner


def register_provider(provider: ConstraintHandlerProvider) -> None:
    """Register a custom constraint handler provider. Rebuilds the planner."""
    _runtime.register_provider(provider)


def set_transaction_provider(provider: TransactionProvider | None) -> None:
    """Set (or clear) the transaction provider that pre/post enforce wrap DB writes in.

    A provider is a zero-arg factory returning an async context manager that commits on
    success and rolls back on a propagated exception. When set, a post-write denial (DENY
    or output-obligation failure) rolls the transaction back instead of committing.
    """
    _runtime.set_transaction_provider(provider)


def get_transaction_provider() -> TransactionProvider | None:
    """Get the configured transaction provider, or None if unset."""
    return _runtime.transaction_provider
