from __future__ import annotations

from unittest.mock import MagicMock

from tornado.httputil import HTTPConnection, HTTPServerRequest

from sapl_tornado.subscription import SubscriptionBuilder


def _make_request(
    *,
    method: str = "GET",
    path: str = "/items",
    remote_ip: str | None = "127.0.0.1",
    arguments: dict[str, list[bytes]] | None = None,
) -> HTTPServerRequest:
    """Build a mock Tornado HTTPServerRequest with configurable fields."""
    request = HTTPServerRequest(
        method=method,
        uri=path,
        connection=MagicMock(spec=HTTPConnection),
    )
    if remote_ip is not None:
        request.remote_ip = remote_ip
    else:
        request.remote_ip = ""
    if arguments is not None:
        request.arguments = arguments
    return request


class TestDefaultSubject:
    """Verify subject defaults from current_user parameter."""

    def test_uses_current_user_when_present(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request,
            function_name="get_items",
            current_user={"id": "user-1", "role": "admin"},
        )
        assert sub.subject == {"id": "user-1", "role": "admin"}

    def test_falls_back_to_anonymous_when_no_user(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.subject == "anonymous"

    def test_string_user(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request,
            function_name="get_items",
            current_user="state-user",
        )
        assert sub.subject == "state-user"


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

    def test_includes_path_kwargs(self):
        request = _make_request(path="/api/items/42")
        sub = SubscriptionBuilder.build(
            request,
            function_name="get_item",
            path_kwargs={"item_id": "42"},
        )
        assert sub.resource == {"path": "/api/items/42", "params": {"item_id": "42"}}


class TestDefaultEnvironment:
    """Verify environment defaults from client info."""

    def test_includes_client_ip(self):
        request = _make_request(remote_ip="10.0.0.1")
        sub = SubscriptionBuilder.build(request, function_name="get_items")
        assert sub.environment == {"ip": "10.0.0.1"}

    def test_empty_when_no_remote_ip(self):
        request = _make_request(remote_ip=None)
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

    def test_callable_receives_path_kwargs(self):
        request = _make_request(path="/items/42")
        sub = SubscriptionBuilder.build(
            request,
            resource=lambda ctx: {"id": ctx.params.get("item_id")},
            function_name="get_item",
            path_kwargs={"item_id": "42"},
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


class TestQueryParameters:
    """Verify query parameters are extracted into the subscription context."""

    def test_query_params_available_in_context(self):
        request = _make_request(
            path="/search",
            arguments={"q": [b"test"], "limit": [b"10"]},
        )
        sub = SubscriptionBuilder.build(
            request,
            resource=lambda ctx: {"query": ctx.query},
            function_name="search",
        )
        assert sub.resource == {"query": {"q": "test", "limit": "10"}}
