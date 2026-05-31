"""Tests for sapl_fastmcp configuration (configure_sapl, getters)."""

import pytest

import sapl_fastmcp
from sapl_base.transport import HttpPdpClientOptions

_TEST_CONFIG = HttpPdpClientOptions(base_url="http://localhost:8443")


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level singletons before each test."""
    sapl_fastmcp._reset_for_tests()
    yield
    sapl_fastmcp._reset_for_tests()


class TestConfigureSapl:
    """Tests for configure_sapl."""

    def test_creates_pdp_client_and_planner(self):
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)

        assert sapl_fastmcp._runtime.is_configured
        assert sapl_fastmcp.get_pdp_client() is not None
        assert sapl_fastmcp.get_planner() is not None

    def test_reconfigure_replaces_previous_client(self):
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)
        original_client = sapl_fastmcp.get_pdp_client()

        second_config = HttpPdpClientOptions(base_url="http://localhost:9999")
        sapl_fastmcp.configure_sapl(second_config)

        assert sapl_fastmcp.get_pdp_client() is not original_client


class TestGetPdpClient:
    """Tests for get_pdp_client."""

    def test_raises_when_not_configured(self):
        with pytest.raises(RuntimeError, match="SAPL not configured"):
            sapl_fastmcp.get_pdp_client()

    def test_returns_client_after_configure(self):
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)
        client = sapl_fastmcp.get_pdp_client()
        assert client is not None


class TestGetPlanner:
    """Tests for get_planner."""

    def test_raises_when_not_configured(self):
        with pytest.raises(RuntimeError, match="SAPL not configured"):
            sapl_fastmcp.get_planner()

    def test_returns_planner_after_configure(self):
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)
        planner = sapl_fastmcp.get_planner()
        assert planner is not None

    def test_registered_provider_persists_across_reconfigure(self):
        class _NoopProvider:
            def get_handlers(self, constraint):
                return ()

        provider = _NoopProvider()
        sapl_fastmcp.register_provider(provider)
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)

        planner = sapl_fastmcp.get_planner()
        assert provider in planner.providers
