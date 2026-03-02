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
    def test_initAppStoresExtensionOnApp(self, app: Flask) -> None:
        sapl = SaplFlask()
        sapl.init_app(app)

        assert "sapl" in app.extensions
        assert app.extensions["sapl"] is sapl

    def test_constructorWithAppInitializesImmediately(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        assert "sapl" in app.extensions
        assert sapl._pdp_client is not None
        assert sapl._constraint_service is not None

    def test_initAppReadsBearerTokenFromConfig(self) -> None:
        app = Flask(__name__)
        app.config["SAPL_BASE_URL"] = "http://localhost:8443"
        app.config["SAPL_TOKEN"] = "test-token"
        app.config["SAPL_ALLOW_INSECURE_CONNECTIONS"] = True

        sapl = SaplFlask(app)

        assert sapl._pdp_client is not None

    def test_initAppReadsBasicAuthFromConfig(self) -> None:
        app = Flask(__name__)
        app.config["SAPL_BASE_URL"] = "http://localhost:8443"
        app.config["SAPL_USERNAME"] = "admin"
        app.config["SAPL_PASSWORD"] = "secret"
        app.config["SAPL_ALLOW_INSECURE_CONNECTIONS"] = True

        sapl = SaplFlask(app)

        assert sapl._pdp_client is not None


class TestProperties:
    def test_pdpClientAvailableAfterInit(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        assert sapl.pdp_client is not None

    def test_constraintServiceAvailableAfterInit(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        assert sapl.constraint_service is not None

    def test_pdpClientRaisesWhenNotInitialized(self) -> None:
        sapl = SaplFlask()

        with pytest.raises(RuntimeError, match="SAPL not initialized"):
            _ = sapl.pdp_client

    def test_constraintServiceRaisesWhenNotInitialized(self) -> None:
        sapl = SaplFlask()

        with pytest.raises(RuntimeError, match="SAPL not initialized"):
            _ = sapl.constraint_service


class TestRegisterConstraintHandler:
    def test_registerMappingHandler(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        mock_provider = MagicMock()

        sapl.register_constraint_handler(mock_provider, "mapping")

        assert mock_provider in sapl.constraint_service._mapping_providers

    def test_registerConsumerHandler(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        mock_provider = MagicMock()

        sapl.register_constraint_handler(mock_provider, "consumer")

        assert mock_provider in sapl.constraint_service._consumer_providers

    def test_unknownHandlerTypeRaisesValueError(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        with pytest.raises(ValueError, match="Unknown handler type"):
            sapl.register_constraint_handler(MagicMock(), "nonexistent")


class TestGetSaplExtension:
    def test_returnsExtensionFromCurrentApp(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        with app.app_context():
            result = get_sapl_extension()

        assert result is sapl

    def test_raisesWhenNotRegistered(self, app: Flask) -> None:
        with app.app_context():
            with pytest.raises(RuntimeError, match="SAPL extension not initialized"):
                get_sapl_extension()


class TestClose:
    def test_closeSetsPdpClientToNone(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        sapl.close()

        assert sapl._pdp_client is None

    def test_closeIsIdempotent(self, app: Flask) -> None:
        sapl = SaplFlask(app)

        sapl.close()
        sapl.close()

        assert sapl._pdp_client is None
