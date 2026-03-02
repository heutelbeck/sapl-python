from __future__ import annotations

from typing import Any

from starlette.requests import Request

from sapl_fastapi.subscription import SubscriptionBuilder


def _make_request(
    *,
    method: str = "GET",
    path: str = "/items",
    path_params: dict[str, Any] | None = None,
    client_host: str | None = "127.0.0.1",
    scope_user: Any = None,
    state_user: Any = None,
) -> Request:
    """Build a mock Starlette Request with configurable fields."""
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "path_params": path_params or {},
        "query_string": b"",
        "root_path": "",
        "headers": [],
    }
    if scope_user is not None:
        scope["user"] = scope_user
    if client_host is not None:
        scope["client"] = (client_host, 0)

    request = Request(scope)

    if state_user is not None:
        request.state.user = state_user

    return request


class TestDefaultSubject:
    """Verify subject defaults from request context."""

    def test_uses_scope_user_when_present(self):
        request = _make_request(scope_user={"id": "user-1", "role": "admin"})
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.subject == {"id": "user-1", "role": "admin"}

    def test_uses_state_user_when_scope_user_absent(self):
        request = _make_request(state_user="state-user")
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.subject == "state-user"

    def test_prefers_state_user_over_scope_user(self):
        request = _make_request(scope_user="scope-user", state_user="state-user")
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.subject == "state-user"

    def test_falls_back_to_anonymous_when_no_user(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.subject == "anonymous"


class TestDefaultAction:
    """Verify action defaults from request method and function name."""

    def test_includes_http_method_and_handler_name(self):
        request = _make_request(method="POST")
        sub = SubscriptionBuilder.build(request, function_name="create_item")
        assert sub.action == {"method": "POST", "handler": "create_item"}

    def test_get_method(self):
        request = _make_request(method="GET")
        sub = SubscriptionBuilder.build(request, function_name="list_items")
        assert sub.action == {"method": "GET", "handler": "list_items"}


class TestDefaultResource:
    """Verify resource defaults from request path."""

    def test_includes_path_and_empty_params(self):
        request = _make_request(path="/api/items")
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.resource == {"path": "/api/items", "params": {}}

    def test_includes_path_params(self):
        request = _make_request(path="/api/items/42", path_params={"item_id": "42"})
        sub = SubscriptionBuilder.build(request, function_name="get_item")
        assert sub.resource == {"path": "/api/items/42", "params": {"item_id": "42"}}


class TestDefaultEnvironment:
    """Verify environment defaults from client info."""

    def test_includes_client_ip(self):
        request = _make_request(client_host="10.0.0.1")
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.environment == {"ip": "10.0.0.1"}

    def test_empty_when_no_client(self):
        request = _make_request(client_host=None)
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.environment == {}


class TestCustomFieldOverrides:
    """Verify static and callable field overrides."""

    def test_static_subject_override(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, subject="custom-subject", function_name="handler",
        )
        assert sub.subject == "custom-subject"

    def test_static_action_override(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, action="read:items", function_name="handler",
        )
        assert sub.action == "read:items"

    def test_static_resource_override(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, resource={"type": "item", "id": 42}, function_name="handler",
        )
        assert sub.resource == {"type": "item", "id": 42}

    def test_static_environment_override(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, environment={"region": "eu-west"}, function_name="handler",
        )
        assert sub.environment == {"region": "eu-west"}

    def test_static_secrets_override(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, secrets={"api_key": "abc"}, function_name="handler",
        )
        assert sub.secrets == {"api_key": "abc"}

    def test_callable_subject_receives_context(self):
        request = _make_request()

        def subject_fn(ctx) -> str:
            return f"user-from-{ctx.request.method}-{ctx.return_value}"

        sub = SubscriptionBuilder.build(
            request, subject=subject_fn, function_name="handler", return_value="result",
        )
        assert sub.subject == "user-from-GET-result"

    def test_callable_resource_uses_return_value(self):
        request = _make_request()

        def resource_fn(ctx) -> dict:
            return {"result_type": type(ctx.return_value).__name__}

        sub = SubscriptionBuilder.build(
            request, resource=resource_fn, function_name="handler", return_value=[1, 2, 3],
        )
        assert sub.resource == {"result_type": "list"}

    def test_secrets_default_to_none(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(request, function_name="handler")
        assert sub.secrets is None


class TestSubscriptionContextCallable:
    """Verify callables receive a fully populated SubscriptionContext."""

    def test_callable_receives_resolved_args(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request,
            resource=lambda ctx: {"patient_id": ctx.args.get("patient_id")},
            function_name="get_patient",
            resolved_args={"patient_id": "P-001"},
        )
        assert sub.resource == {"patient_id": "P-001"}

    def test_callable_receives_path_params(self):
        request = _make_request(path="/items/42", path_params={"item_id": "42"})
        sub = SubscriptionBuilder.build(
            request,
            resource=lambda ctx: {"id": ctx.params.get("item_id")},
            function_name="get_item",
        )
        assert sub.resource == {"id": "42"}

    def test_callable_receives_class_name(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request,
            subject=lambda ctx: f"class:{ctx.class_name}",
            function_name="get_data",
            class_name="PatientService",
        )
        assert sub.subject == "class:PatientService"

    def test_callable_receives_function_name(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request,
            action=lambda ctx: ctx.function_name,
            function_name="update_record",
        )
        assert sub.action == "update_record"


class TestGracefulDegradation:
    """Verify subscription building works with None request (service-layer)."""

    def test_build_with_none_request(self):
        sub = SubscriptionBuilder.build(
            None,
            subject="service-account",
            action="readAll",
            resource="patients",
            function_name="list_patients",
        )
        assert sub.subject == "service-account"
        assert sub.action == "readAll"
        assert sub.resource == "patients"

    def test_defaults_with_none_request(self):
        sub = SubscriptionBuilder.build(None, function_name="background_task")
        assert sub.subject == "anonymous"
        assert sub.action == {"method": "", "handler": "background_task"}
        assert sub.resource == {"path": "", "params": {}}
        assert sub.environment == {}
