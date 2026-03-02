from __future__ import annotations

import pytest
from flask import Flask, g

from sapl_flask.subscription import SubscriptionBuilder


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


class TestDefaultSubject:
    def test_default_subject_is_anonymous_without_user(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(function_name="test_view")

        assert subscription.subject == "anonymous"

    def test_subject_from_g_user(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            g.user = "alice"
            subscription = SubscriptionBuilder.build(function_name="test_view")

        assert subscription.subject == "alice"

    def test_subject_from_g_user_dict(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            g.user = {"username": "bob", "role": "admin"}
            subscription = SubscriptionBuilder.build(function_name="test_view")

        assert subscription.subject == {"username": "bob", "role": "admin"}


class TestDefaultAction:
    def test_default_action_contains_method_and_endpoint(self, app: Flask) -> None:
        with app.test_request_context("/test", method="POST"):
            subscription = SubscriptionBuilder.build(function_name="create_item")

        assert subscription.action == {"method": "POST", "endpoint": "create_item"}

    def test_default_action_uses_get_method(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(function_name="list_items")

        assert subscription.action == {"method": "GET", "endpoint": "list_items"}

    def test_default_action_with_empty_function_name(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(function_name="")

        assert subscription.action["method"] == "GET"


class TestDefaultResource:
    def test_default_resource_contains_path(self, app: Flask) -> None:
        with app.test_request_context("/api/items", method="GET"):
            subscription = SubscriptionBuilder.build(function_name="get_items")

        assert subscription.resource["path"] == "/api/items"
        assert subscription.resource["view_args"] == {}

    def test_default_resource_includes_view_args(self, app: Flask) -> None:
        @app.route("/items/<int:item_id>")
        def get_item(item_id: int) -> str:
            return ""

        with app.test_request_context("/items/42"):
            # Simulate URL matching so view_args are populated
            app.preprocess_request()
            subscription = SubscriptionBuilder.build(function_name="get_item")

        assert subscription.resource["path"] == "/items/42"
        assert subscription.resource["view_args"] == {"item_id": 42}


class TestDefaultEnvironment:
    def test_default_environment_contains_ip(self, app: Flask) -> None:
        with app.test_request_context(
            "/test",
            method="GET",
            environ_base={"REMOTE_ADDR": "192.168.1.1"},
        ):
            subscription = SubscriptionBuilder.build(function_name="test_view")

        assert subscription.environment == {"ip": "192.168.1.1"}


class TestCustomOverrides:
    def test_static_subject_override(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                subject="custom_user",
                function_name="test_view",
            )

        assert subscription.subject == "custom_user"

    def test_static_action_override(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                action="custom_action",
                function_name="test_view",
            )

        assert subscription.action == "custom_action"

    def test_static_resource_override(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                resource="custom_resource",
                function_name="test_view",
            )

        assert subscription.resource == "custom_resource"

    def test_static_environment_override(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                environment={"custom": True},
                function_name="test_view",
            )

        assert subscription.environment == {"custom": True}

    def test_static_secrets_override(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                secrets={"api_key": "hidden"},
                function_name="test_view",
            )

        assert subscription.secrets == {"api_key": "hidden"}

    def test_callable_subject_override(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                subject=lambda ctx: "dynamic_user",
                function_name="test_view",
            )

        assert subscription.subject == "dynamic_user"

    def test_callable_action_override(self, app: Flask) -> None:
        with app.test_request_context("/test", method="PUT"):
            from flask import request as flask_request

            subscription = SubscriptionBuilder.build(
                action=lambda ctx: {"method": flask_request.method, "custom": True},
                function_name="test_view",
            )

        assert subscription.action == {"method": "PUT", "custom": True}

    def test_callable_returning_none_falls_back_to_default(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                subject=lambda ctx: None,
                function_name="test_view",
            )

        # callable returned None, but _resolve_field returns None,
        # so default kicks in -> "anonymous"
        assert subscription.subject == "anonymous"


class TestSecretsNotInLoggable:
    def test_secrets_excluded_from_loggable_dict(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                secrets={"token": "super-secret"},
                function_name="test_view",
            )

        loggable = subscription.to_loggable_dict()
        assert "secrets" not in loggable


class TestSubscriptionContextCallable:
    """Verify callables receive a fully populated SubscriptionContext."""

    def test_callable_receives_resolved_args(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                resource=lambda ctx: {"patient_id": ctx.args.get("patient_id")},
                function_name="get_patient",
                resolved_args={"patient_id": "P-001"},
            )

        assert subscription.resource == {"patient_id": "P-001"}

    def test_callable_receives_query_params(self, app: Flask) -> None:
        with app.test_request_context("/test?q=search&page=2", method="GET"):
            subscription = SubscriptionBuilder.build(
                resource=lambda ctx: {"query": ctx.query},
                function_name="search",
            )

        assert subscription.resource == {"query": {"q": "search", "page": "2"}}

    def test_callable_receives_class_name(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                subject=lambda ctx: f"class:{ctx.class_name}",
                function_name="get_data",
                class_name="PatientService",
            )

        assert subscription.subject == "class:PatientService"

    def test_callable_receives_return_value(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                resource=lambda ctx: {"data": ctx.return_value},
                function_name="get_record",
                return_value={"id": 42},
            )

        assert subscription.resource == {"data": {"id": 42}}


class TestGracefulDegradation:
    """Verify subscription building works outside Flask request context."""

    def test_build_outside_request_context(self) -> None:
        subscription = SubscriptionBuilder.build(
            subject="service-account",
            action="readAll",
            resource="patients",
            function_name="list_patients",
        )

        assert subscription.subject == "service-account"
        assert subscription.action == "readAll"
        assert subscription.resource == "patients"

    def test_defaults_outside_request_context(self) -> None:
        subscription = SubscriptionBuilder.build(function_name="background_task")

        assert subscription.subject == "anonymous"
        assert subscription.action == {"method": "", "endpoint": "background_task"}
        assert subscription.resource == {"path": "", "view_args": {}}
        assert subscription.environment == {}
