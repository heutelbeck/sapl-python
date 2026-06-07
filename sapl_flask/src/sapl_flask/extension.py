from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sapl_base.pep import ConstraintHandlerProvider, EnforcementPlanner, PepRuntime
from sapl_base.transport import HttpPdpClient, HttpPdpClientOptions

if TYPE_CHECKING:
    from collections.abc import Iterable

    from flask import Flask

    from sapl_base.pep.transaction import SyncTransactionProvider, TransactionProvider


class SaplFlask:
    """Flask extension for SAPL Policy Enforcement.

    Usage::

        sapl = SaplFlask()
        sapl.init_app(app)

        # Or:
        sapl = SaplFlask(app)

        # With extra providers:
        sapl = SaplFlask(app, providers=[MyCustomProvider()])

    `ContentFilteringProvider` and `ContentFilterPredicateProvider` are
    registered automatically. Add more via the `providers` constructor
    argument or `register_provider()` after init.

    Configuration via app.config:

    - ``SAPL_BASE_URL``: PDP server URL (default: ``https://localhost:8443``).
      Plain HTTP is rejected unless the host is loopback.
    - ``SAPL_TOKEN``: Bearer token for authentication.
    - ``SAPL_USERNAME`` + ``SAPL_SECRET``: Basic auth credentials.
    - ``SAPL_TIMEOUT``: Connect/write/pool timeout in seconds for one-shot
      requests (default: ``5.0``). Streaming SSE reads are not idle-timed.
    """

    def __init__(
        self,
        app: Flask | None = None,
        *,
        providers: Iterable[ConstraintHandlerProvider] = (),
    ) -> None:
        self._runtime = PepRuntime(providers=providers)
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Initialize the extension with a Flask application."""
        self._runtime.configure(HttpPdpClientOptions(
            base_url=app.config.get("SAPL_BASE_URL", "https://localhost:8443"),
            token=app.config.get("SAPL_TOKEN"),
            username=app.config.get("SAPL_USERNAME"),
            secret=app.config.get("SAPL_SECRET"),
            timeout_seconds=app.config.get("SAPL_TIMEOUT", 5.0),
        ))
        app.extensions["sapl"] = self

    @property
    def pdp_client(self) -> HttpPdpClient:
        return self._runtime.pdp_client

    @property
    def planner(self) -> EnforcementPlanner:
        return self._runtime.planner

    def register_provider(self, provider: ConstraintHandlerProvider) -> None:
        """Add a constraint handler provider. Rebuilds the planner."""
        self._runtime.register_provider(provider)

    @property
    def transaction_provider(self) -> SyncTransactionProvider | TransactionProvider | None:
        return self._runtime.transaction_provider

    def set_transaction_provider(
        self, provider: SyncTransactionProvider | TransactionProvider | None
    ) -> None:
        """Set (or clear) the transaction provider that pre/post enforce wrap DB writes in.

        Flask is WSGI (always sync), so the provider is a zero-arg factory returning a sync
        context manager that commits on success and rolls back on a propagated exception. For
        a sync SQLAlchemy session use ``set_transaction_provider(lambda: session.begin())``.
        When set, a post-write denial (DENY or output-obligation failure) rolls the
        transaction back.
        """
        self._runtime.set_transaction_provider(provider)

    def close(self) -> None:
        """Synchronously close the PDP client and release resources.

        Intended for `atexit` registration. Runs the async close via
        `asyncio.run`. Idempotent.
        """
        if not self._runtime.is_configured:
            return
        asyncio.run(self._runtime.close())


def get_sapl_extension() -> SaplFlask:
    """Retrieve the SAPL extension from the current Flask application."""
    from flask import current_app

    sapl = current_app.extensions.get("sapl")
    if sapl is None:
        raise RuntimeError(
            "SAPL extension not initialized. Call SaplFlask(app) or sapl.init_app(app)."
        )
    return sapl
