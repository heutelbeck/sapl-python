from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.http import HttpRequest

from sapl_django.subscription import SubscriptionBuilder


def _make_request(
    *,
    method: str = "GET",
    path: str = "/api/test",
    username: str | None = None,
    remote_addr: str = "127.0.0.1",
    resolver_kwargs: dict | None = None,
) -> HttpRequest:
    """Create a mock Django HttpRequest with common attributes."""
    request = HttpRequest()
    request.method = method
    request.path = path
    request.META["REMOTE_ADDR"] = remote_addr

    if username is not None:
        request.user = SimpleNamespace(username=username)
    else:
        # Simulate AnonymousUser (no username attribute or empty)
        request.user = SimpleNamespace(username="")

    if resolver_kwargs is not None:
        request.resolver_match = SimpleNamespace(kwargs=resolver_kwargs)

    return request


class TestDefaultSubject:
    """Tests for default subject extraction from request.user."""

    def test_authenticated_user(self):
        request = _make_request(username="alice")
        sub = SubscriptionBuilder.build(request, function_name="test_view")

        assert sub.subject == "alice"

    def test_anonymous_user_with_empty_username(self):
        request = _make_request(username="")
        sub = SubscriptionBuilder.build(request, function_name="test_view")

        assert sub.subject == "anonymous"

    def test_anonymous_user_without_user_attribute(self):
        request = HttpRequest()
        request.method = "GET"
        request.path = "/test"
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        # No user attribute at all
        sub = SubscriptionBuilder.build(request, function_name="test_view")

        assert sub.subject == "anonymous"


class TestDefaultAction:
    """Tests for default action extraction from request method and view name."""

    def test_includes_method_and_view(self):
        request = _make_request(method="POST")
        sub = SubscriptionBuilder.build(request, function_name="create_patient")

        assert sub.action == {"method": "POST", "view": "create_patient"}

    def test_different_methods(self):
        for method in ("GET", "PUT", "DELETE", "PATCH"):
            request = _make_request(method=method)
            sub = SubscriptionBuilder.build(request, function_name="my_view")

            assert sub.action["method"] == method


class TestDefaultResource:
    """Tests for default resource extraction from request path."""

    def test_includes_path(self):
        request = _make_request(path="/api/patients/42")
        sub = SubscriptionBuilder.build(request, function_name="test_view")

        assert sub.resource["path"] == "/api/patients/42"

    def test_includes_resolver_kwargs(self):
        request = _make_request(
            path="/api/patients/42",
            resolver_kwargs={"patient_id": "42"},
        )
        sub = SubscriptionBuilder.build(request, function_name="test_view")

        assert sub.resource["kwargs"] == {"patient_id": "42"}

    def test_empty_kwargs_without_resolver_match(self):
        request = _make_request(path="/api/test")
        # No resolver_match set
        sub = SubscriptionBuilder.build(request, function_name="test_view")

        assert sub.resource["kwargs"] == {}


class TestDefaultEnvironment:
    """Tests for default environment extraction from request metadata."""

    def test_includes_remote_addr(self):
        request = _make_request(remote_addr="192.168.1.100")
        sub = SubscriptionBuilder.build(request, function_name="test_view")

        assert sub.environment == {"ip": "192.168.1.100"}

    def test_empty_when_no_remote_addr(self):
        request = HttpRequest()
        request.method = "GET"
        request.path = "/test"
        # No REMOTE_ADDR in META
        sub = SubscriptionBuilder.build(request, function_name="test_view")

        assert sub.environment == {}


class TestCustomFieldOverrides:
    """Tests for static and callable field overrides."""

    def test_static_subject_override(self):
        request = _make_request(username="alice")
        sub = SubscriptionBuilder.build(
            request, subject="admin_service", function_name="test_view",
        )

        assert sub.subject == "admin_service"

    def test_callable_subject_override(self):
        request = _make_request(username="alice")
        sub = SubscriptionBuilder.build(
            request,
            subject=lambda ctx: f"user:{ctx.request.user.username}",
            function_name="test_view",
        )

        assert sub.subject == "user:alice"

    def test_static_action_override(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, action="read_all", function_name="test_view",
        )

        assert sub.action == "read_all"

    def test_callable_resource_with_return_value(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request,
            resource=lambda ctx: {"data": ctx.return_value, "path": ctx.request.path},
            function_name="test_view",
            return_value={"id": 42},
        )

        assert sub.resource == {"data": {"id": 42}, "path": "/api/test"}

    def test_static_environment_override(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, environment={"region": "eu-west-1"}, function_name="test_view",
        )

        assert sub.environment == {"region": "eu-west-1"}

    def test_secrets_field(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, secrets={"api_key": "secret123"}, function_name="test_view",
        )

        assert sub.secrets == {"api_key": "secret123"}

    def test_secrets_excluded_from_loggable_dict(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request, secrets={"api_key": "secret123"}, function_name="test_view",
        )

        loggable = sub.to_loggable_dict()
        assert "secrets" not in loggable


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

    def test_callable_receives_class_name(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request,
            subject=lambda ctx: f"class:{ctx.class_name}",
            function_name="get_data",
            class_name="PatientService",
        )

        assert sub.subject == "class:PatientService"

    def test_callable_receives_query_params(self):
        request = _make_request()
        request.GET = {"q": "search", "page": "2"}
        sub = SubscriptionBuilder.build(
            request,
            resource=lambda ctx: {"query": ctx.query},
            function_name="search",
        )

        assert sub.resource == {"query": {"q": "search", "page": "2"}}

    def test_callable_receives_return_value(self):
        request = _make_request()
        sub = SubscriptionBuilder.build(
            request,
            resource=lambda ctx: {"data": ctx.return_value},
            function_name="get_record",
            return_value={"id": 42},
        )

        assert sub.resource == {"data": {"id": 42}}


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
        assert sub.action == {"method": "", "view": "background_task"}
        assert sub.resource == {"path": "", "kwargs": {}}
        assert sub.environment == {}
