"""Tests for sapl_fastmcp configuration (configure_sapl, getters)."""

import pytest

import sapl_fastmcp
from sapl_base import PdpConfig
from sapl_base.constraint_engine import ConstraintEnforcementService

_TEST_CONFIG = PdpConfig(
    base_url="http://localhost:8443", allow_insecure_connections=True
)


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level singletons before each test."""
    sapl_fastmcp._pdp_client = None
    sapl_fastmcp._constraint_service = None
    yield
    sapl_fastmcp._pdp_client = None
    sapl_fastmcp._constraint_service = None


class TestConfigureSapl:
    """Tests for configure_sapl."""

    def test_creates_pdp_client_and_service(self):
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)

        assert sapl_fastmcp._pdp_client is not None
        assert sapl_fastmcp._constraint_service is not None

    def test_uses_provided_constraint_service(self):
        custom_service = ConstraintEnforcementService()
        sapl_fastmcp.configure_sapl(_TEST_CONFIG, constraint_service=custom_service)

        assert sapl_fastmcp._constraint_service is custom_service

    def test_reconfigure_replaces_previous_client(self):
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)
        original_client = sapl_fastmcp._pdp_client

        second_config = PdpConfig(
            base_url="http://other:9999", allow_insecure_connections=True
        )
        sapl_fastmcp.configure_sapl(second_config)

        assert sapl_fastmcp._pdp_client is not original_client

class TestGetPdpClient:
    """Tests for get_pdp_client."""

    def test_raises_when_not_configured(self):
        with pytest.raises(RuntimeError, match="SAPL not configured"):
            sapl_fastmcp.get_pdp_client()

    def test_returns_client_after_configure(self):
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)
        client = sapl_fastmcp.get_pdp_client()
        assert client is not None


class TestGetConstraintService:
    """Tests for get_constraint_service."""

    def test_raises_when_not_configured(self):
        with pytest.raises(RuntimeError, match="SAPL not configured"):
            sapl_fastmcp.get_constraint_service()

    def test_returns_service_after_configure(self):
        sapl_fastmcp.configure_sapl(_TEST_CONFIG)
        service = sapl_fastmcp.get_constraint_service()
        assert service is not None
