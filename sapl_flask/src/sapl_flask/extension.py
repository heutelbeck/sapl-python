from __future__ import annotations

import asyncio
from typing import Any

from flask import Flask

from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.content_filter import ContentFilteringProvider, ContentFilterPredicateProvider
from sapl_base.pdp_client import PdpClient, PdpConfig

ERROR_NOT_INITIALIZED = "SAPL not initialized. Call init_app() first."
ERROR_UNKNOWN_HANDLER_TYPE = "Unknown handler type: %s"


class SaplFlask:
    """Flask extension for SAPL Policy Enforcement.

    Usage::

        sapl = SaplFlask()
        sapl.init_app(app)

        # Or:
        sapl = SaplFlask(app)

    Configuration via app.config:

    - ``SAPL_BASE_URL``: PDP server URL (default: ``https://localhost:8443``)
    - ``SAPL_TOKEN``: Bearer token for authentication
    - ``SAPL_USERNAME``: Basic auth username
    - ``SAPL_PASSWORD``: Basic auth password
    - ``SAPL_TIMEOUT``: Request timeout in seconds (default: ``5.0``)
    - ``SAPL_ALLOW_INSECURE_CONNECTIONS``: Allow HTTP connections (default: ``False``)
    """

    def __init__(self, app: Flask | None = None) -> None:
        self._pdp_client: PdpClient | None = None
        self._constraint_service: ConstraintEnforcementService | None = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Initialize the extension with a Flask application.

        Reads SAPL configuration from ``app.config`` and creates the PDP client
        and constraint enforcement service.

        Args:
            app: The Flask application instance.
        """
        config = PdpConfig(
            base_url=app.config.get("SAPL_BASE_URL", "https://localhost:8443"),
            token=app.config.get("SAPL_TOKEN"),
            username=app.config.get("SAPL_USERNAME"),
            password=app.config.get("SAPL_PASSWORD"),
            timeout=app.config.get("SAPL_TIMEOUT", 5.0),
            allow_insecure_connections=app.config.get("SAPL_ALLOW_INSECURE_CONNECTIONS", False),
        )
        self._pdp_client = PdpClient(config)
        self._constraint_service = ConstraintEnforcementService()
        self._constraint_service.register_mapping(ContentFilteringProvider())
        self._constraint_service.register_filter_predicate(ContentFilterPredicateProvider())

        app.extensions["sapl"] = self

    @property
    def pdp_client(self) -> PdpClient:
        """Return the PDP client.

        Raises:
            RuntimeError: If the extension has not been initialized.
        """
        if self._pdp_client is None:
            raise RuntimeError(ERROR_NOT_INITIALIZED)
        return self._pdp_client

    @property
    def constraint_service(self) -> ConstraintEnforcementService:
        """Return the constraint enforcement service.

        Raises:
            RuntimeError: If the extension has not been initialized.
        """
        if self._constraint_service is None:
            raise RuntimeError(ERROR_NOT_INITIALIZED)
        return self._constraint_service

    def register_constraint_handler(self, provider: Any, handler_type: str) -> None:
        """Register a custom constraint handler provider.

        Args:
            provider: The handler provider instance.
            handler_type: One of ``runnable``, ``consumer``, ``mapping``, ``filter_predicate``,
                ``error_handler``, ``error_mapping``, ``method_invocation``.

        Raises:
            ValueError: If handler_type is not recognized.
        """
        registrar = getattr(self.constraint_service, f"register_{handler_type}", None)
        if registrar is None:
            raise ValueError(ERROR_UNKNOWN_HANDLER_TYPE % handler_type)
        registrar(provider)

    def close(self) -> None:
        """Synchronously close the PDP client and release resources.

        Safe to call from ``atexit`` handlers or Flask teardown callbacks.
        """
        if self._pdp_client is None:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._pdp_client.close())
            else:
                loop.run_until_complete(self._pdp_client.close())
        except RuntimeError:
            asyncio.run(self._pdp_client.close())
        self._pdp_client = None


def get_sapl_extension() -> SaplFlask:
    """Retrieve the SAPL extension from the current Flask application.

    Must be called within a Flask application context.

    Returns:
        The initialized SaplFlask extension instance.

    Raises:
        RuntimeError: If the SAPL extension has not been registered.
    """
    from flask import current_app

    sapl = current_app.extensions.get("sapl")
    if sapl is None:
        raise RuntimeError(
            "SAPL extension not initialized. Call SaplFlask(app) or sapl.init_app(app)."
        )
    return sapl
