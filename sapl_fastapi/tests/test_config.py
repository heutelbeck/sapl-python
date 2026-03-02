from __future__ import annotations

import dataclasses

import pytest

from sapl_base.pdp_client import PdpConfig
from sapl_fastapi.config import SaplConfig


class TestSaplConfigDefaults:
    """Verify default field values match PdpConfig defaults."""

    def test_base_url_defaults_to_https_localhost(self):
        config = SaplConfig()
        assert config.base_url == "https://localhost:8443"

    def test_auth_fields_default_to_none(self):
        config = SaplConfig()
        assert config.token is None
        assert config.username is None
        assert config.password is None

    def test_timeout_defaults_to_five_seconds(self):
        config = SaplConfig()
        assert config.timeout == 5.0

    def test_allow_insecure_connections_defaults_to_false(self):
        config = SaplConfig()
        assert config.allow_insecure_connections is False

    def test_streaming_retry_defaults(self):
        config = SaplConfig()
        assert config.streaming_max_retries == 0
        assert config.streaming_retry_base_delay == 1.0
        assert config.streaming_retry_max_delay == 30.0


class TestSaplConfigCustomValues:
    """Verify custom values are preserved through construction."""

    def test_all_fields_accept_custom_values(self):
        config = SaplConfig(
            base_url="https://pdp.example.com:9443",
            token="my-token",
            timeout=10.0,
            allow_insecure_connections=True,
            streaming_max_retries=5,
            streaming_retry_base_delay=2.0,
            streaming_retry_max_delay=60.0,
        )
        assert config.base_url == "https://pdp.example.com:9443"
        assert config.token == "my-token"
        assert config.timeout == 10.0
        assert config.allow_insecure_connections is True
        assert config.streaming_max_retries == 5
        assert config.streaming_retry_base_delay == 2.0
        assert config.streaming_retry_max_delay == 60.0

    def test_basic_auth_credentials(self):
        config = SaplConfig(username="admin", password="secret")
        assert config.username == "admin"
        assert config.password == "secret"


class TestSaplConfigImmutability:
    """Verify frozen dataclass rejects mutation."""

    def test_cannot_set_field_on_frozen_instance(self):
        config = SaplConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.base_url = "https://other:8443"  # type: ignore[misc]

    def test_cannot_delete_field_on_frozen_instance(self):
        config = SaplConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            del config.base_url  # type: ignore[misc]


class TestSaplConfigToPdpConfig:
    """Verify to_pdp_config preserves all fields."""

    def test_default_config_converts_to_matching_pdp_config(self):
        config = SaplConfig()
        pdp_config = config.to_pdp_config()
        assert isinstance(pdp_config, PdpConfig)
        assert pdp_config.base_url == config.base_url
        assert pdp_config.token == config.token
        assert pdp_config.username == config.username
        assert pdp_config.password == config.password
        assert pdp_config.timeout == config.timeout
        assert pdp_config.allow_insecure_connections == config.allow_insecure_connections
        assert pdp_config.streaming_max_retries == config.streaming_max_retries
        assert pdp_config.streaming_retry_base_delay == config.streaming_retry_base_delay
        assert pdp_config.streaming_retry_max_delay == config.streaming_retry_max_delay

    def test_custom_config_converts_to_matching_pdp_config(self):
        config = SaplConfig(
            base_url="https://pdp.example.com:9443",
            token="bearer-token-123",
            timeout=15.0,
            allow_insecure_connections=True,
            streaming_max_retries=3,
            streaming_retry_base_delay=0.5,
            streaming_retry_max_delay=10.0,
        )
        pdp_config = config.to_pdp_config()
        assert pdp_config.base_url == "https://pdp.example.com:9443"
        assert pdp_config.token == "bearer-token-123"
        assert pdp_config.timeout == 15.0
        assert pdp_config.allow_insecure_connections is True
        assert pdp_config.streaming_max_retries == 3
        assert pdp_config.streaming_retry_base_delay == 0.5
        assert pdp_config.streaming_retry_max_delay == 10.0

    def test_basic_auth_preserved_in_pdp_config(self):
        config = SaplConfig(username="admin", password="secret")
        pdp_config = config.to_pdp_config()
        assert pdp_config.username == "admin"
        assert pdp_config.password == "secret"
