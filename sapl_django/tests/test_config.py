from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

import sapl_django.config as config_module
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.content_filter import ContentFilteringProvider, ContentFilterPredicateProvider
from sapl_base.pdp_client import PdpClient
from sapl_django.config import (
    cleanup_sapl,
    get_constraint_service,
    get_pdp_client,
    get_sapl_config,
    register_constraint_handler,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset module-level singletons before each test."""
    config_module._pdp_client = None
    config_module._constraint_service = None
    yield
    config_module._pdp_client = None
    config_module._constraint_service = None


class TestGetSaplConfig:
    """Tests for reading SAPL_CONFIG from Django settings."""

    def test_returns_config_dict_from_settings(self, settings):
        settings.SAPL_CONFIG = {"base_url": "http://localhost:8443", "allow_insecure_connections": True}
        result = get_sapl_config()

        assert result["base_url"] == "http://localhost:8443"
        assert result["allow_insecure_connections"] is True

    @override_settings()
    def test_raises_improperly_configured_when_missing(self, settings):
        del settings.SAPL_CONFIG
        with pytest.raises(ImproperlyConfigured, match="SAPL_CONFIG not found"):
            get_sapl_config()


class TestGetPdpClient:
    """Tests for PDP client singleton creation."""

    def test_creates_pdp_client_from_settings(self, settings):
        settings.SAPL_CONFIG = {
            "base_url": "http://localhost:8443",
            "allow_insecure_connections": True,
            "timeout": 10.0,
        }
        client = get_pdp_client()

        assert isinstance(client, PdpClient)

    def test_returns_same_instance_on_repeated_calls(self, settings):
        settings.SAPL_CONFIG = {
            "base_url": "http://localhost:8443",
            "allow_insecure_connections": True,
        }
        first = get_pdp_client()
        second = get_pdp_client()

        assert first is second

    def test_uses_default_base_url_when_not_specified(self, settings):
        settings.SAPL_CONFIG = {"allow_insecure_connections": False}
        # This should not raise - defaults to https://localhost:8443
        client = get_pdp_client()

        assert isinstance(client, PdpClient)


class TestGetConstraintService:
    """Tests for constraint enforcement service singleton."""

    def test_creates_service_with_built_in_providers(self):
        service = get_constraint_service()

        assert isinstance(service, ConstraintEnforcementService)
        # Verify built-in providers are registered by checking internal lists
        mapping_types = [type(p) for p in service._mapping_providers]
        filter_types = [type(p) for p in service._filter_predicate_providers]

        assert ContentFilteringProvider in mapping_types
        assert ContentFilterPredicateProvider in filter_types

    def test_returns_same_instance_on_repeated_calls(self):
        first = get_constraint_service()
        second = get_constraint_service()

        assert first is second


class TestRegisterConstraintHandler:
    """Tests for custom handler registration."""

    def test_registers_valid_handler_type(self):
        mock_provider = type("MockProvider", (), {
            "is_responsible": lambda self, c: False,
            "get_handler": lambda self, c: lambda: None,
            "get_signal": lambda self: None,
        })()

        register_constraint_handler(mock_provider, "runnable")

        service = get_constraint_service()
        assert mock_provider in service._runnable_providers

    def test_raises_value_error_for_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown handler type"):
            register_constraint_handler(object(), "nonexistent")


class TestCleanupSapl:
    """Tests for cleanup_sapl resource release."""

    @pytest.mark.asyncio
    async def test_closes_pdp_client(self, settings):
        settings.SAPL_CONFIG = {
            "base_url": "http://localhost:8443",
            "allow_insecure_connections": True,
        }
        client = get_pdp_client()
        mock_close = AsyncMock()

        with patch.object(client, "close", mock_close):
            await cleanup_sapl()

        mock_close.assert_awaited_once()
        assert config_module._pdp_client is None

    @pytest.mark.asyncio
    async def test_noop_when_no_client(self):
        # Should not raise
        await cleanup_sapl()

        assert config_module._pdp_client is None
