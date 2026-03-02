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
    def test_defaultSubjectIsAnonymousWithoutUser(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(function_name="test_view")

        assert subscription.subject == "anonymous"

    def test_subjectFromGUser(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            g.user = "alice"
            subscription = SubscriptionBuilder.build(function_name="test_view")

        assert subscription.subject == "alice"

    def test_subjectFromGUserDict(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            g.user = {"username": "bob", "role": "admin"}
            subscription = SubscriptionBuilder.build(function_name="test_view")

        assert subscription.subject == {"username": "bob", "role": "admin"}


class TestDefaultAction:
    def test_defaultActionContainsMethodAndEndpoint(self, app: Flask) -> None:
        with app.test_request_context("/test", method="POST"):
            subscription = SubscriptionBuilder.build(function_name="create_item")

        assert subscription.action == {"method": "POST", "endpoint": "create_item"}

    def test_defaultActionUsesGetMethod(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(function_name="list_items")

        assert subscription.action == {"method": "GET", "endpoint": "list_items"}

    def test_defaultActionWithEmptyFunctionName(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(function_name="")

        assert subscription.action["method"] == "GET"


class TestDefaultResource:
    def test_defaultResourceContainsPath(self, app: Flask) -> None:
        with app.test_request_context("/api/items", method="GET"):
            subscription = SubscriptionBuilder.build(function_name="get_items")

        assert subscription.resource["path"] == "/api/items"
        assert subscription.resource["view_args"] == {}

    def test_defaultResourceIncludesViewArgs(self, app: Flask) -> None:
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
    def test_defaultEnvironmentContainsIp(self, app: Flask) -> None:
        with app.test_request_context(
            "/test",
            method="GET",
            environ_base={"REMOTE_ADDR": "192.168.1.1"},
        ):
            subscription = SubscriptionBuilder.build(function_name="test_view")

        assert subscription.environment == {"ip": "192.168.1.1"}


class TestCustomOverrides:
    def test_staticSubjectOverride(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                subject="custom_user",
                function_name="test_view",
            )

        assert subscription.subject == "custom_user"

    def test_staticActionOverride(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                action="custom_action",
                function_name="test_view",
            )

        assert subscription.action == "custom_action"

    def test_staticResourceOverride(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                resource="custom_resource",
                function_name="test_view",
            )

        assert subscription.resource == "custom_resource"

    def test_staticEnvironmentOverride(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                environment={"custom": True},
                function_name="test_view",
            )

        assert subscription.environment == {"custom": True}

    def test_staticSecretsOverride(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                secrets={"api_key": "hidden"},
                function_name="test_view",
            )

        assert subscription.secrets == {"api_key": "hidden"}

    def test_callableSubjectOverride(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                subject=lambda ctx: "dynamic_user",
                function_name="test_view",
            )

        assert subscription.subject == "dynamic_user"

    def test_callableActionOverride(self, app: Flask) -> None:
        with app.test_request_context("/test", method="PUT"):
            from flask import request as flask_request

            subscription = SubscriptionBuilder.build(
                action=lambda ctx: {"method": flask_request.method, "custom": True},
                function_name="test_view",
            )

        assert subscription.action == {"method": "PUT", "custom": True}

    def test_callableReturningNoneFallsBackToDefault(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                subject=lambda ctx: None,
                function_name="test_view",
            )

        # callable returned None, but _resolve_field returns None,
        # so default kicks in -> "anonymous"
        assert subscription.subject == "anonymous"


class TestSecretsNotInLoggable:
    def test_secretsExcludedFromLoggableDict(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                secrets={"token": "super-secret"},
                function_name="test_view",
            )

        loggable = subscription.to_loggable_dict()
        assert "secrets" not in loggable


class TestSubscriptionContextCallable:
    """Verify callables receive a fully populated SubscriptionContext."""

    def test_callableReceivesResolvedArgs(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                resource=lambda ctx: {"patient_id": ctx.args.get("patient_id")},
                function_name="get_patient",
                resolved_args={"patient_id": "P-001"},
            )

        assert subscription.resource == {"patient_id": "P-001"}

    def test_callableReceivesQueryParams(self, app: Flask) -> None:
        with app.test_request_context("/test?q=search&page=2", method="GET"):
            subscription = SubscriptionBuilder.build(
                resource=lambda ctx: {"query": ctx.query},
                function_name="search",
            )

        assert subscription.resource == {"query": {"q": "search", "page": "2"}}

    def test_callableReceivesClassName(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                subject=lambda ctx: f"class:{ctx.class_name}",
                function_name="get_data",
                class_name="PatientService",
            )

        assert subscription.subject == "class:PatientService"

    def test_callableReceivesReturnValue(self, app: Flask) -> None:
        with app.test_request_context("/test", method="GET"):
            subscription = SubscriptionBuilder.build(
                resource=lambda ctx: {"data": ctx.return_value},
                function_name="get_record",
                return_value={"id": 42},
            )

        assert subscription.resource == {"data": {"id": 42}}


class TestGracefulDegradation:
    """Verify subscription building works outside Flask request context."""

    def test_buildOutsideRequestContext(self) -> None:
        subscription = SubscriptionBuilder.build(
            subject="service-account",
            action="readAll",
            resource="patients",
            function_name="list_patients",
        )

        assert subscription.subject == "service-account"
        assert subscription.action == "readAll"
        assert subscription.resource == "patients"

    def test_defaultsOutsideRequestContext(self) -> None:
        subscription = SubscriptionBuilder.build(function_name="background_task")

        assert subscription.subject == "anonymous"
        assert subscription.action == {"method": "", "endpoint": "background_task"}
        assert subscription.resource == {"path": "", "view_args": {}}
        assert subscription.environment == {}
