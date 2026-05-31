from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

import sapl_django.config as config_module
from sapl_base.pep import EnforcementPlanner
from sapl_base.pep.filters import ContentFilteringProvider, ContentFilterPredicateProvider
from sapl_base.transport import HttpPdpClient
from sapl_django.config import (
    cleanup_sapl,
    get_pdp_client,
    get_planner,
    get_sapl_config,
    register_provider,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    config_module._runtime._reset_for_tests()
    yield
    config_module._runtime._reset_for_tests()


class TestGetSaplConfig:
    def test_returns_config_dict_from_settings(self, settings):
        settings.SAPL_CONFIG = {"base_url": "http://localhost:8443"}
        result = get_sapl_config()
        assert result["base_url"] == "http://localhost:8443"

    @override_settings()
    def test_raises_improperly_configured_when_missing(self, settings):
        del settings.SAPL_CONFIG
        with pytest.raises(ImproperlyConfigured, match="SAPL_CONFIG not found"):
            get_sapl_config()


class TestGetPdpClient:
    def test_creates_pdp_client_from_settings(self, settings):
        settings.SAPL_CONFIG = {
            "base_url": "http://localhost:8443",
            "timeout_seconds": 10.0,
        }
        client = get_pdp_client()
        assert isinstance(client, HttpPdpClient)

    def test_returns_same_instance_on_repeated_calls(self, settings):
        settings.SAPL_CONFIG = {"base_url": "http://localhost:8443"}
        first = get_pdp_client()
        second = get_pdp_client()
        assert first is second

    def test_uses_default_base_url_when_not_specified(self, settings):
        settings.SAPL_CONFIG = {}
        client = get_pdp_client()
        assert isinstance(client, HttpPdpClient)


class TestGetPlanner:
    def test_creates_planner_with_built_in_providers(self):
        planner = get_planner()
        assert isinstance(planner, EnforcementPlanner)
        types = {type(p) for p in planner.providers}
        assert ContentFilteringProvider in types
        assert ContentFilterPredicateProvider in types

    def test_returns_same_instance_on_repeated_calls(self):
        first = get_planner()
        second = get_planner()
        assert first is second


class _ProbeProvider:
    def get_handlers(self, constraint):
        return ()


class TestRegisterProvider:
    def test_registers_custom_provider(self):
        provider = _ProbeProvider()
        register_provider(provider)
        planner = get_planner()
        assert provider in planner.providers

    def test_register_after_get_planner_rebuilds(self):
        first = get_planner()
        provider = _ProbeProvider()
        register_provider(provider)
        second = get_planner()
        assert provider in second.providers
        assert first is not second


class TestCleanupSapl:
    @pytest.mark.asyncio
    async def test_closes_pdp_client(self, settings):
        settings.SAPL_CONFIG = {"base_url": "http://localhost:8443"}
        client = get_pdp_client()
        mock_close = AsyncMock()
        with patch.object(client, "close", mock_close):
            await cleanup_sapl()
        mock_close.assert_awaited_once()
        assert not config_module._runtime.is_configured

    @pytest.mark.asyncio
    async def test_noop_when_no_client(self):
        await cleanup_sapl()
        assert not config_module._runtime.is_configured
