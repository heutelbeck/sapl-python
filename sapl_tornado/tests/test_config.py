from __future__ import annotations

import dataclasses

import pytest

from sapl_tornado import SaplConfig


class TestSaplConfigDefaults:
    def test_base_url_required(self):
        with pytest.raises(TypeError):
            SaplConfig()

    def test_auth_fields_default_to_none(self):
        config = SaplConfig(base_url="https://localhost:8443")
        assert config.token is None
        assert config.username is None
        assert config.secret is None

    def test_timeout_default(self):
        config = SaplConfig(base_url="https://localhost:8443")
        assert config.timeout_seconds == 5.0


class TestSaplConfigCustomValues:
    def test_all_fields_accept_custom_values(self):
        config = SaplConfig(
            base_url="https://pdp.example.com:9443",
            token="my-token",
            timeout_seconds=10.0,
            streaming_max_retries=5,
            streaming_retry_base_delay_seconds=2.0,
            streaming_retry_max_delay_seconds=60.0,
        )
        assert config.base_url == "https://pdp.example.com:9443"
        assert config.token == "my-token"
        assert config.timeout_seconds == 10.0
        assert config.streaming_max_retries == 5

    def test_basic_auth_credentials(self):
        config = SaplConfig(
            base_url="https://localhost:8443", username="admin", secret="secret"
        )
        assert config.username == "admin"
        assert config.secret == "secret"


class TestSaplConfigImmutability:
    def test_cannot_set_field_on_frozen_instance(self):
        config = SaplConfig(base_url="https://localhost:8443")
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.base_url = "https://other:8443"  # type: ignore[misc]
