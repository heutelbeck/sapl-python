from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

from sapl_flask.extension import SaplFlask, get_sapl_extension


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.config["SAPL_BASE_URL"] = "http://localhost:8443"
    app.config["SAPL_ALLOW_INSECURE_CONNECTIONS"] = True
    return app


class TestInitApp:
    def test_init_app_stores_extension_on_app(self, app: Flask) -> None:
        sapl = SaplFlask()
        sapl.init_app(app)

        assert "sapl" in app.extensions
        assert app.extensions["sapl"] is sapl

    def test_constructor_with_app_initializes_immediately(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        assert "sapl" in app.extensions
        assert sapl._pdp_client is not None
        assert sapl._constraint_service is not None

    def test_init_app_reads_bearer_token_from_config(self) -> None:
        app = Flask(__name__)
        app.config["SAPL_BASE_URL"] = "http://localhost:8443"
        app.config["SAPL_TOKEN"] = "test-token"
        app.config["SAPL_ALLOW_INSECURE_CONNECTIONS"] = True

        sapl = SaplFlask(app)

        assert sapl._pdp_client is not None

    def test_init_app_reads_basic_auth_from_config(self) -> None:
        app = Flask(__name__)
        app.config["SAPL_BASE_URL"] = "http://localhost:8443"
        app.config["SAPL_USERNAME"] = "admin"
        app.config["SAPL_PASSWORD"] = "secret"
        app.config["SAPL_ALLOW_INSECURE_CONNECTIONS"] = True

        sapl = SaplFlask(app)

        assert sapl._pdp_client is not None


class TestProperties:
    def test_pdp_client_available_after_init(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        assert sapl.pdp_client is not None

    def test_constraint_service_available_after_init(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        assert sapl.constraint_service is not None

    def test_pdp_client_raises_when_not_initialized(self) -> None:
        sapl = SaplFlask()

        with pytest.raises(RuntimeError, match="SAPL not initialized"):
            _ = sapl.pdp_client

    def test_constraint_service_raises_when_not_initialized(self) -> None:
        sapl = SaplFlask()

        with pytest.raises(RuntimeError, match="SAPL not initialized"):
            _ = sapl.constraint_service


class TestRegisterConstraintHandler:
    def test_register_mapping_handler(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        mock_provider = MagicMock()

        sapl.register_constraint_handler(mock_provider, "mapping")

        assert mock_provider in sapl.constraint_service._mapping_providers

    def test_register_consumer_handler(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        mock_provider = MagicMock()

        sapl.register_constraint_handler(mock_provider, "consumer")

        assert mock_provider in sapl.constraint_service._consumer_providers

    def test_unknown_handler_type_raises_value_error(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        with pytest.raises(ValueError, match="Unknown handler type"):
            sapl.register_constraint_handler(MagicMock(), "nonexistent")


class TestGetSaplExtension:
    def test_returns_extension_from_current_app(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        with app.app_context():
            result = get_sapl_extension()

        assert result is sapl

    def test_raises_when_not_registered(self, app: Flask) -> None:
        with app.app_context(), pytest.raises(RuntimeError, match="SAPL extension not initialized"):
            get_sapl_extension()


class TestClose:
    def test_close_sets_pdp_client_to_none(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        sapl.close()

        assert sapl._pdp_client is None

    def test_close_is_idempotent(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        sapl.close()
        sapl.close()

        assert sapl._pdp_client is None
