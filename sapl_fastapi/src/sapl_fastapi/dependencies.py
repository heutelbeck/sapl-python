from __future__ import annotations

from sapl_base.pep import ConstraintHandlerProvider, EnforcementPlanner, PepRuntime
from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions

_runtime = PepRuntime()


def configure_sapl(options: HttpPdpClientOptions) -> None:
    """Initialize SAPL with the given options. Call this during FastAPI startup (lifespan)."""
    _runtime.configure(options)


async def cleanup_sapl() -> None:
    """Cleanup SAPL resources. Call this during FastAPI shutdown."""
    await _runtime.close()


def get_pdp_client() -> HttpPdpClient:
    """Get the PDP client. For use as FastAPI dependency."""
    return _runtime.pdp_client


def get_planner() -> EnforcementPlanner:
    """Get the enforcement planner. For use as FastAPI dependency."""
    return _runtime.planner


def register_provider(provider: ConstraintHandlerProvider) -> None:
    """Register a custom constraint handler provider. Rebuilds the planner."""
    _runtime.register_provider(provider)
