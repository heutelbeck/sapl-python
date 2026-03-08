"""Tests for sapl_fastmcp.subscription module."""

from unittest.mock import MagicMock

import pytest

from sapl_fastmcp.context import SaplConfig, SubscriptionContext
from sapl_fastmcp.subscription import (
    _default_auth_action,
    _default_auth_resource,
    _default_middleware_action,
    _default_middleware_resource,
    _default_subject,
    _resolve,
    build_middleware_subscription,
    build_subscription,
)
from tests.conftest import make_auth_ctx as _make_ctx
from tests.conftest import make_token as _make_token


def _make_component(name="test_tool", tags=None):
    component = MagicMock()
    component.name = name
    component.tags = tags or set()
    return component


class TestResolve:
    """Tests for _resolve field resolution."""

    def test_returns_default_when_override_is_none(self):
        ctx = _make_ctx()
        result = _resolve(None, ctx, lambda c: "default-val")
        assert result == "default-val"

    def test_returns_static_override(self):
        ctx = _make_ctx()
        result = _resolve("custom", ctx, lambda c: "default-val")
        assert result == "custom"

    def test_calls_callable_override_with_ctx(self):
        ctx = _make_ctx()
        result = _resolve(lambda c: f"from-{c.component.name}", ctx, lambda c: "x")
        assert result == "from-test_tool"


class TestDefaultSubject:
    """Tests for _default_subject."""

    def test_returns_claims_when_present(self):
        ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
        assert _default_subject(ctx) == {"sub": "alice"}

    def test_returns_client_id_when_no_claims(self):
        ctx = _make_ctx(token=_make_token(claims=None, client_id="my-client"))
        assert _default_subject(ctx) == "my-client"

    def test_returns_client_id_when_claims_empty(self):
        ctx = _make_ctx(token=_make_token(claims={}, client_id="my-client"))
        assert _default_subject(ctx) == "my-client"

    def test_returns_anonymous_when_no_token(self):
        ctx = _make_ctx(token=None)
        assert _default_subject(ctx) == "anonymous"


class TestDefaultAuthAction:
    """Tests for _default_auth_action."""

    def test_returns_component_name(self):
        ctx = _make_ctx(component_name="my_tool")
        assert _default_auth_action(ctx) == "my_tool"


class TestDefaultAuthResource:
    """Tests for _default_auth_resource."""

    def test_returns_mcp(self):
        ctx = _make_ctx()
        assert _default_auth_resource(ctx) == "mcp"


class TestBuildSubscription:
    """Tests for build_subscription."""

    def test_builds_with_defaults(self):
        ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}), component_name="my_tool")
        sub = build_subscription(ctx)

        assert sub.subject == {"sub": "alice"}
        assert sub.action == "my_tool"
        assert sub.resource == "mcp"
        assert sub.environment is None

    def test_builds_with_static_overrides(self):
        ctx = _make_ctx()
        sub = build_subscription(ctx, subject="bob", action="read", resource="patients")

        assert sub.subject == "bob"
        assert sub.action == "read"
        assert sub.resource == "patients"

    def test_builds_with_callable_overrides(self):
        ctx = _make_ctx(component_name="my_tool")
        sub = build_subscription(ctx, action=lambda c: f"custom_{c.component.name}")

        assert sub.action == "custom_my_tool"

    def test_environment_and_secrets_passed_through(self):
        ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
        sub = build_subscription(ctx, environment={"key": "val"}, secrets={"s": "v"})

        assert sub.environment == {"key": "val"}
        assert sub.secrets == {"s": "v"}

    @pytest.mark.parametrize(
        "field",
        ["subject", "action", "resource"],
        ids=["subject-none", "action-none", "resource-none"],
    )
    def test_raises_when_mandatory_field_resolves_to_none(self, field):
        ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
        with pytest.raises(ValueError, match=field):
            build_subscription(ctx, **{field: lambda _: None})

    def test_environment_none_is_valid(self):
        ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
        sub = build_subscription(ctx, environment=lambda _: None)

        assert sub.environment is None


# -- Middleware subscription tests --


class TestDefaultMiddlewareAction:
    """Tests for _default_middleware_action."""

    def test_returns_operation_verb(self):
        ctx = SubscriptionContext(operation="call")
        assert _default_middleware_action(ctx) == "call"

    def test_returns_none_when_no_operation(self):
        ctx = SubscriptionContext(operation=None)
        assert _default_middleware_action(ctx) is None


class TestDefaultMiddlewareResource:
    """Tests for _default_middleware_resource."""

    def test_returns_name_and_arguments_for_call(self):
        component = _make_component("my_tool")
        ctx = SubscriptionContext(operation="call", component=component, arguments={"x": 1})
        assert _default_middleware_resource(ctx) == {"name": "my_tool", "arguments": {"x": 1}}

    def test_returns_name_only_for_call_with_no_arguments(self):
        component = _make_component("my_tool")
        ctx = SubscriptionContext(operation="call", component=component, arguments={})
        assert _default_middleware_resource(ctx) == {"name": "my_tool"}

    def test_returns_mcp_for_call_with_no_component_no_arguments(self):
        ctx = SubscriptionContext(operation="call", arguments={})
        assert _default_middleware_resource(ctx) == "mcp"

    def test_returns_name_and_uri_for_read(self):
        component = _make_component("my_resource")
        ctx = SubscriptionContext(operation="read", component=component, uri="data://public/summary")
        assert _default_middleware_resource(ctx) == {"name": "my_resource", "uri": "data://public/summary"}

    def test_returns_name_only_for_read_with_no_uri(self):
        component = _make_component("my_resource")
        ctx = SubscriptionContext(operation="read", component=component, uri=None)
        assert _default_middleware_resource(ctx) == {"name": "my_resource"}

    def test_returns_name_and_tags_for_component(self):
        component = _make_component("my_tool", tags={"pii", "export"})
        ctx = SubscriptionContext(operation="call", component=component)
        result = _default_middleware_resource(ctx)
        assert result["name"] == "my_tool"
        assert sorted(result["tags"]) == ["export", "pii"]

    def test_returns_name_only_for_component_without_tags(self):
        component = _make_component("my_tool", tags=set())
        ctx = SubscriptionContext(operation="call", component=component)
        assert _default_middleware_resource(ctx) == {"name": "my_tool"}

    def test_returns_name_and_arguments_for_get(self):
        component = _make_component("my_prompt")
        ctx = SubscriptionContext(operation="get", component=component, arguments={"name": "report"})
        assert _default_middleware_resource(ctx) == {"name": "my_prompt", "arguments": {"name": "report"}}

    def test_returns_mcp_for_unknown_operation(self):
        ctx = SubscriptionContext(operation=None)
        assert _default_middleware_resource(ctx) == "mcp"


class TestBuildMiddlewareSubscription:
    """Tests for build_middleware_subscription."""

    def test_builds_with_defaults(self):
        ctx = SubscriptionContext(
            token=_make_token(claims={"sub": "alice"}),
            component=_make_component("my_tool"),
            operation="call",
            arguments={"x": 1},
        )
        config = SaplConfig(mode="pre")
        sub = build_middleware_subscription(ctx, config)

        assert sub.subject == {"sub": "alice"}
        assert sub.action == "call"
        assert sub.resource == {"name": "my_tool", "arguments": {"x": 1}}
        assert sub.environment is None

    def test_builds_with_static_overrides(self):
        ctx = SubscriptionContext(
            token=_make_token(claims={"sub": "alice"}),
            component=_make_component("my_tool"),
            operation="call",
        )
        config = SaplConfig(
            mode="pre",
            subject="bob",
            action="read",
            resource="patients",
        )
        sub = build_middleware_subscription(ctx, config)

        assert sub.subject == "bob"
        assert sub.action == "read"
        assert sub.resource == "patients"

    def test_builds_with_callable_overrides(self):
        ctx = SubscriptionContext(
            component=_make_component("my_tool"),
            operation="call",
            arguments={"segment": "high_value"},
            token=_make_token(claims={"sub": "alice"}),
        )
        config = SaplConfig(
            mode="pre",
            resource=lambda c: {"segment": c.arguments["segment"]},
        )
        sub = build_middleware_subscription(ctx, config)

        assert sub.resource == {"segment": "high_value"}

    def test_environment_and_secrets_passed_through(self):
        ctx = SubscriptionContext(
            token=_make_token(claims={"sub": "alice"}),
            component=_make_component("my_tool"),
            operation="call",
            arguments={"x": 1},
        )
        config = SaplConfig(
            mode="pre",
            environment={"key": "val"},
            secrets={"s": "v"},
        )
        sub = build_middleware_subscription(ctx, config)

        assert sub.environment == {"key": "val"}
        assert sub.secrets == {"s": "v"}

    @pytest.mark.parametrize(
        "field",
        ["subject", "action", "resource"],
        ids=["subject-none", "action-none", "resource-none"],
    )
    def test_raises_when_mandatory_field_resolves_to_none(self, field):
        ctx = SubscriptionContext(
            token=_make_token(claims={"sub": "alice"}),
            component=_make_component("my_tool"),
            operation="call",
            arguments={"x": 1},
        )
        config = SaplConfig(mode="pre", **{field: lambda _: None})
        with pytest.raises(ValueError, match=field):
            build_middleware_subscription(ctx, config)

    def test_post_enforce_includes_return_value(self):
        ctx = SubscriptionContext(
            token=_make_token(claims={"sub": "alice"}),
            component=_make_component("run_model"),
            operation="call",
            arguments={"model_id": "v3"},
            return_value={"accuracy": 0.95},
        )
        config = SaplConfig(
            mode="post",
            resource=lambda c: {"model": c.arguments["model_id"], "result": c.return_value},
        )
        sub = build_middleware_subscription(ctx, config)

        assert sub.resource == {"model": "v3", "result": {"accuracy": 0.95}}
