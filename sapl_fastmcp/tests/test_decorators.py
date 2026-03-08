"""Tests for sapl_fastmcp.decorators module."""

import pytest

from sapl_fastmcp.context import SaplConfig
from sapl_fastmcp.decorators import post_enforce, pre_enforce


class TestPreEnforce:
    """Tests for the @pre_enforce decorator factory."""

    def test_attaches_sapl_config_with_pre_mode(self):
        @pre_enforce()
        def my_tool():
            pass

        assert hasattr(my_tool, "__sapl__")
        assert isinstance(my_tool.__sapl__, SaplConfig)
        assert my_tool.__sapl__.mode == "pre"

    def test_stores_static_fields(self):
        @pre_enforce(subject="bob", action="read", resource="data")
        def my_tool():
            pass

        config = my_tool.__sapl__
        assert config.subject == "bob"
        assert config.action == "read"
        assert config.resource == "data"

    def test_stores_callable_fields(self):
        def subject_fn(ctx):
            return ctx.token
        def action_fn(ctx):
            return "custom"

        @pre_enforce(subject=subject_fn, action=action_fn)
        def my_tool():
            pass

        config = my_tool.__sapl__
        assert config.subject is subject_fn
        assert config.action is action_fn

    def test_stores_environment_and_secrets(self):
        @pre_enforce(environment={"key": "val"}, secrets={"s": "v"})
        def my_tool():
            pass

        config = my_tool.__sapl__
        assert config.environment == {"key": "val"}
        assert config.secrets == {"s": "v"}

    def test_stores_finalize(self):
        async def my_finalize(decision, ctx):
            pass

        @pre_enforce(finalize=my_finalize)
        def my_tool():
            pass

        assert my_tool.__sapl__.finalize is my_finalize

    def test_preserves_function_identity(self):
        def my_tool():
            pass

        original_id = id(my_tool)
        decorated = pre_enforce()(my_tool)

        assert decorated is my_tool
        assert id(decorated) == original_id

    def test_stores_stealth_true(self):
        @pre_enforce(stealth=True)
        def my_tool():
            pass

        assert my_tool.__sapl__.stealth is True

    def test_default_fields_are_none(self):
        @pre_enforce()
        def my_tool():
            pass

        config = my_tool.__sapl__
        assert config.subject is None
        assert config.action is None
        assert config.resource is None
        assert config.environment is None
        assert config.secrets is None
        assert config.finalize is None
        assert config.stealth is False


class TestPostEnforce:
    """Tests for the @post_enforce decorator factory."""

    def test_attaches_sapl_config_with_post_mode(self):
        @post_enforce()
        def my_tool():
            pass

        assert hasattr(my_tool, "__sapl__")
        assert isinstance(my_tool.__sapl__, SaplConfig)
        assert my_tool.__sapl__.mode == "post"

    def test_stores_fields_correctly(self):
        def resource_fn(ctx):
            return {"model": ctx.arguments["model_id"], "result": ctx.return_value}

        @post_enforce(resource=resource_fn, action="run_model")
        def my_tool():
            pass

        config = my_tool.__sapl__
        assert config.resource is resource_fn
        assert config.action == "run_model"

    def test_preserves_function_identity(self):
        def my_tool():
            pass

        original_id = id(my_tool)
        decorated = post_enforce()(my_tool)

        assert decorated is my_tool
        assert id(decorated) == original_id

    def test_stores_finalize(self):
        async def my_finalize(decision, ctx):
            pass

        @post_enforce(finalize=my_finalize)
        def my_tool():
            pass

        assert my_tool.__sapl__.finalize is my_finalize

    def test_stores_stealth_true(self):
        @post_enforce(stealth=True)
        def my_tool():
            pass

        assert my_tool.__sapl__.stealth is True

    def test_default_stealth_is_false(self):
        @post_enforce()
        def my_tool():
            pass

        assert my_tool.__sapl__.stealth is False


class TestDecoratorStacking:
    """Tests that stacking @pre_enforce and @post_enforce is rejected."""

    def test_pre_after_post_raises_type_error(self):
        @post_enforce()
        def my_tool():
            pass

        with pytest.raises(TypeError, match="Cannot apply both"):
            pre_enforce()(my_tool)

    def test_post_after_pre_raises_type_error(self):
        @pre_enforce()
        def my_tool():
            pass

        with pytest.raises(TypeError, match="Cannot apply both"):
            post_enforce()(my_tool)

    def test_duplicate_pre_raises_type_error(self):
        @pre_enforce()
        def my_tool():
            pass

        with pytest.raises(TypeError, match="Cannot apply both"):
            pre_enforce()(my_tool)

    def test_single_decorator_succeeds(self):
        @pre_enforce()
        def my_tool():
            pass

        assert hasattr(my_tool, "__sapl__")
        assert my_tool.__sapl__.mode == "pre"
