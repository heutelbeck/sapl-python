"""Shared lazy-singleton helper for framework wrappers.

Encapsulates the runtime triple every wrapper otherwise duplicates:
a `HttpPdpClient`, an `EnforcementPlanner`, and a list of registered
constraint-handler providers. The two built-in JSON content filter
providers are always included; framework-specific providers can be
registered at any time and trigger a planner rebuild.

Wrappers hold one `PepRuntime` instance per process and expose its
methods as module-level functions (FastAPI, Tornado, Django, FastMCP)
or as attributes on a Flask extension object (Flask).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

from sapl_base.pep.filters import ContentFilteringProvider, ContentFilterPredicateProvider
from sapl_base.pep.planner import EnforcementPlanner
from sapl_base.pep.provider import ConstraintHandlerProvider
from sapl_base.pep.transaction import SyncTransactionProvider, TransactionProvider
from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions

ERROR_NOT_CONFIGURED = "SAPL not configured. Call configure() first."


class PepRuntime:
    """Lazy singleton: PDP client + EnforcementPlanner + provider list."""

    __slots__ = ("_lock", "_pdp_client", "_planner", "_providers", "_transaction_provider")

    def __init__(
        self,
        options: HttpPdpClientOptions | None = None,
        providers: Iterable[ConstraintHandlerProvider] = (),
    ) -> None:
        self._lock = threading.Lock()
        self._providers: list[ConstraintHandlerProvider] = list(providers)
        self._transaction_provider: SyncTransactionProvider | TransactionProvider | None = None
        if options is not None:
            self._pdp_client: HttpPdpClient | None = HttpPdpClient(options)
            self._planner: EnforcementPlanner | None = self._build_planner_unlocked()
        else:
            self._pdp_client = None
            self._planner = None

    def configure(self, options: HttpPdpClientOptions) -> None:
        """Initialize or reconfigure the PDP client and rebuild the planner.

        Registered providers are preserved across reconfigure.
        """
        with self._lock:
            self._pdp_client = HttpPdpClient(options)
            self._planner = self._build_planner_unlocked()

    def register_provider(self, provider: ConstraintHandlerProvider) -> None:
        """Register a custom provider; rebuilds the planner if already configured."""
        with self._lock:
            self._providers.append(provider)
            if self._planner is not None:
                self._planner = self._build_planner_unlocked()

    def set_transaction_provider(
        self, provider: SyncTransactionProvider | TransactionProvider | None
    ) -> None:
        """Set (or clear) the transaction provider that pre/post enforce wrap writes in.

        A provider is a zero-arg factory returning a context manager that commits on
        clean exit and rolls back on a propagated exception. It must match the view kind:
        an async context manager for async views (the async core), a sync context manager
        for sync views (the blocking core). When set, a post-write denial (DENY or
        output-obligation failure) rolls the transaction back.
        """
        with self._lock:
            self._transaction_provider = provider

    @property
    def transaction_provider(self) -> SyncTransactionProvider | TransactionProvider | None:
        with self._lock:
            return self._transaction_provider

    @property
    def is_configured(self) -> bool:
        with self._lock:
            return self._pdp_client is not None

    @property
    def pdp_client(self) -> HttpPdpClient:
        with self._lock:
            client = self._pdp_client
        if client is None:
            raise RuntimeError(ERROR_NOT_CONFIGURED)
        return client

    @property
    def planner(self) -> EnforcementPlanner:
        with self._lock:
            planner = self._planner
        if planner is None:
            raise RuntimeError(ERROR_NOT_CONFIGURED)
        return planner

    async def close(self) -> None:
        """Close the PDP client and release resources. Idempotent."""
        with self._lock:
            client = self._pdp_client
            self._pdp_client = None
        if client is not None:
            await client.close()

    def _reset_for_tests(self) -> None:
        """Reset all state to the unconfigured baseline. Test-only."""
        with self._lock:
            self._pdp_client = None
            self._planner = None
            self._providers.clear()
            self._transaction_provider = None

    def _build_planner_unlocked(self) -> EnforcementPlanner:
        defaults: list[ConstraintHandlerProvider] = [
            ContentFilteringProvider(),
            ContentFilterPredicateProvider(),
        ]
        return EnforcementPlanner(providers=tuple(defaults + self._providers))
