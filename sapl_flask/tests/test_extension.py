from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from flask import Flask

from sapl_base.pep import OUTPUT, ScopedHandler
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
        assert app.extensions["sapl"] is sapl

    def test_constructor_with_app_initializes_immediately(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        assert "sapl" in app.extensions
        assert sapl.pdp_client is not None
        assert sapl.planner is not None

    def test_init_app_reads_bearer_token_from_config(self) -> None:
        app = Flask(__name__)
        app.config["SAPL_BASE_URL"] = "http://localhost:8443"
        app.config["SAPL_TOKEN"] = "test-token"
        app.config["SAPL_ALLOW_INSECURE_CONNECTIONS"] = True
        sapl = SaplFlask(app)
        assert sapl.pdp_client is not None

    def test_init_app_reads_basic_auth_from_config(self) -> None:
        app = Flask(__name__)
        app.config["SAPL_BASE_URL"] = "http://localhost:8443"
        app.config["SAPL_USERNAME"] = "admin"
        app.config["SAPL_SECRET"] = "secret"
        sapl = SaplFlask(app)
        assert sapl.pdp_client is not None


class TestProperties:
    def test_pdp_client_available_after_init(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        assert sapl.pdp_client is not None

    def test_planner_available_after_init(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        assert sapl.planner is not None

    def test_pdp_client_raises_when_not_initialized(self) -> None:
        sapl = SaplFlask()
        with pytest.raises(RuntimeError, match="SAPL not configured"):
            _ = sapl.pdp_client

    def test_planner_raises_when_not_initialized(self) -> None:
        sapl = SaplFlask()
        with pytest.raises(RuntimeError, match="SAPL not configured"):
            _ = sapl.planner


class _ProbeProvider:
    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "probe":
            return ()
        return (
            ScopedHandler(signal=OUTPUT, priority=0, shape="mapper", handler=lambda v: v),
        )


class TestRegisterProvider:
    def test_provider_passed_via_constructor_is_active(self, app: Flask) -> None:
        provider = _ProbeProvider()
        sapl = SaplFlask(app, providers=[provider])
        handlers = sapl.planner.providers
        assert provider in handlers

    def test_register_provider_after_init_rebuilds_planner(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        provider = _ProbeProvider()
        sapl.register_provider(provider)
        assert provider in sapl.planner.providers

    def test_content_filtering_providers_registered_by_default(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        type_names = {type(p).__name__ for p in sapl.planner.providers}
        assert "ContentFilteringProvider" in type_names
        assert "ContentFilterPredicateProvider" in type_names


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
        assert not sapl._runtime.is_configured

    def test_close_is_idempotent(self, app: Flask) -> None:
        sapl = SaplFlask(app)
        sapl.close()
        sapl.close()
        assert not sapl._runtime.is_configured
