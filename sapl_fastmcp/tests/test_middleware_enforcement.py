"""Tests for sapl_fastmcp.middleware enforcement logic.

Integration tests with mocked PDP and real ConstraintEnforcementService.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import NotFoundError
from fastmcp.prompts.prompt import Prompt, PromptResult
from fastmcp.resources.resource import Resource, ResourceResult
from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.auth import AccessToken
from fastmcp.tools.tool import Tool, ToolResult

from sapl_base import AuthorizationDecision, Decision, MultiAuthorizationDecision
from sapl_base.constraint_bundle import AccessDeniedError
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.constraint_types import Signal
from sapl_fastmcp.context import SaplConfig
from sapl_fastmcp.middleware import (
    SAPLMiddleware,
    _component_type,
    _get_sapl_config,
    _loggable_subject_id,
    _rewrap_result,
    _unwrap_result,
)
from tests.conftest import FilterByClassificationProvider


def _make_tool(name="test_tool", sapl_config=None, tags=None):
    """Create a mock component with optional __sapl__ config."""

    def fn():
        pass

    if sapl_config is not None:
        fn.__sapl__ = sapl_config
    tool = MagicMock(spec=Tool)
    tool.name = name
    tool.fn = fn
    tool.tags = tags or set()
    return tool


def _make_call_context(tool_name="test_tool", arguments=None, tool=None):
    """Create a mock MiddlewareContext for on_call_tool."""
    message = MagicMock()
    message.name = tool_name
    message.arguments = arguments or {}
    message.model_copy = lambda update: MagicMock(
        name=tool_name,
        arguments=update.get("arguments", arguments or {}),
        model_copy=message.model_copy,
    )

    fastmcp = AsyncMock()
    fastmcp.get_tool = AsyncMock(return_value=tool)

    fastmcp_ctx = MagicMock()
    fastmcp_ctx.fastmcp = fastmcp

    context = MagicMock()
    context.message = message
    context.fastmcp_context = fastmcp_ctx
    context.copy = lambda **kw: MagicMock(
        message=kw.get("message", message),
        fastmcp_context=fastmcp_ctx,
        copy=context.copy,
    )
    return context


def _make_list_context():
    """Create a mock MiddlewareContext for listing operations."""
    context = MagicMock()
    return context


def _make_resource(name="test_resource", sapl_config=None, tags=None):
    """Create a mock Resource component with optional __sapl__ config."""

    def fn():
        pass

    if sapl_config is not None:
        fn.__sapl__ = sapl_config
    resource = MagicMock(spec=Resource)
    resource.name = name
    resource.fn = fn
    resource.tags = tags or set()
    return resource


def _make_prompt_component(name="test_prompt", sapl_config=None, tags=None):
    """Create a mock Prompt component with optional __sapl__ config."""

    def fn():
        pass

    if sapl_config is not None:
        fn.__sapl__ = sapl_config
    prompt = MagicMock(spec=Prompt)
    prompt.name = name
    prompt.fn = fn
    prompt.tags = tags or set()
    return prompt


def _make_read_context(uri="data://test", resource=None, template=None):
    """Create a mock MiddlewareContext for on_read_resource."""
    message = MagicMock()
    message.uri = uri

    fastmcp = AsyncMock()
    if resource is not None:
        fastmcp.get_resource = AsyncMock(return_value=resource)
    else:
        fastmcp.get_resource = AsyncMock(side_effect=NotFoundError(uri))
    if template is not None:
        fastmcp.get_resource_template = AsyncMock(return_value=template)
    else:
        fastmcp.get_resource_template = AsyncMock(side_effect=NotFoundError(uri))

    fastmcp_ctx = MagicMock()
    fastmcp_ctx.fastmcp = fastmcp

    context = MagicMock()
    context.message = message
    context.fastmcp_context = fastmcp_ctx
    return context


def _make_get_context(prompt_name="test_prompt", arguments=None, prompt=None):
    """Create a mock MiddlewareContext for on_get_prompt."""
    message = MagicMock()
    message.name = prompt_name
    message.arguments = arguments or {}
    message.model_copy = lambda update: MagicMock(
        name=prompt_name,
        arguments=update.get("arguments", arguments or {}),
        model_copy=message.model_copy,
    )

    fastmcp = AsyncMock()
    if prompt is not None:
        fastmcp.get_prompt = AsyncMock(return_value=prompt)
    else:
        fastmcp.get_prompt = AsyncMock(side_effect=NotFoundError(prompt_name))

    fastmcp_ctx = MagicMock()
    fastmcp_ctx.fastmcp = fastmcp

    context = MagicMock()
    context.message = message
    context.fastmcp_context = fastmcp_ctx
    context.copy = lambda **kw: MagicMock(
        message=kw.get("message", message),
        fastmcp_context=fastmcp_ctx,
        copy=context.copy,
    )
    return context


class TestGetSaplConfig:
    """Tests for _get_sapl_config helper."""

    def test_returns_config_when_present(self):
        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        assert _get_sapl_config(tool) is config

    def test_returns_none_when_no_fn(self):
        component = MagicMock(spec=[])
        assert _get_sapl_config(component) is None

    def test_returns_none_when_no_sapl_attr(self):
        tool = _make_tool(sapl_config=None)
        assert _get_sapl_config(tool) is None

    def test_returns_none_for_none_component(self):
        assert _get_sapl_config(None) is None

    def test_returns_none_for_non_sapl_config_attr(self):
        tool = _make_tool()
        tool.fn.__sapl__ = "not a SaplConfig"
        assert _get_sapl_config(tool) is None


class TestUnwrapResult:
    """Tests for _unwrap_result -- extracting data from FastMCP wrappers."""

    def test_none_returns_none(self):
        assert _unwrap_result(None) is None

    def test_tool_result_with_dict_structured_content(self):
        tr = ToolResult(structured_content={"key": "val", "num": 42})
        assert _unwrap_result(tr) == {"key": "val", "num": 42}

    def test_tool_result_with_result_wrapper_unwraps_inner_value(self):
        tr = ToolResult(structured_content={"result": [1, 2, 3]})
        assert _unwrap_result(tr) == [1, 2, 3]

    def test_tool_result_without_structured_content_model_dumps(self):
        tr = ToolResult(content="plain text")
        result = _unwrap_result(tr)
        assert isinstance(result, dict)

    def test_resource_result_model_dumps(self):
        rr = MagicMock(spec=ResourceResult)
        rr.model_dump.return_value = {"contents": [{"text": "hello"}]}
        assert _unwrap_result(rr) == {"contents": [{"text": "hello"}]}
        rr.model_dump.assert_called_once_with(mode="json")

    def test_prompt_result_model_dumps(self):
        pr = MagicMock(spec=PromptResult)
        pr.model_dump.return_value = {"messages": [{"role": "user", "content": "hi"}]}
        assert _unwrap_result(pr) == {"messages": [{"role": "user", "content": "hi"}]}
        pr.model_dump.assert_called_once_with(mode="json")

    def test_plain_dict_passes_through(self):
        data = {"x": 1, "y": 2}
        assert _unwrap_result(data) is data

    def test_plain_list_passes_through(self):
        data = [1, 2, 3]
        assert _unwrap_result(data) is data

    def test_plain_string_passes_through(self):
        assert _unwrap_result("hello") == "hello"


class TestRewrapResult:
    """Tests for _rewrap_result -- reconstructing FastMCP wrappers after constraint handling."""

    def test_none_wrapper_returns_value_directly(self):
        assert _rewrap_result(None, {"x": 1}) == {"x": 1}

    def test_tool_result_rewraps_dict_value(self):
        wrapper = ToolResult(structured_content={"key": "original"})
        result = _rewrap_result(wrapper, {"key": "modified"})
        assert isinstance(result, ToolResult)
        assert result.structured_content == {"key": "modified"}

    def test_tool_result_rewraps_result_wrapper_convention(self):
        wrapper = ToolResult(structured_content={"result": [1, 2, 3]})
        result = _rewrap_result(wrapper, [1])
        assert isinstance(result, ToolResult)
        assert result.structured_content == {"result": [1]}

    def test_tool_result_non_dict_value_sets_structured_content_none(self):
        wrapper = ToolResult(structured_content={"data": "original"})
        result = _rewrap_result(wrapper, "plain string")
        assert isinstance(result, ToolResult)
        assert result.structured_content is None

    def test_resource_result_rewraps_string_value(self):
        wrapper = ResourceResult("original")
        result = _rewrap_result(wrapper, "modified text")
        assert isinstance(result, ResourceResult)
        assert result.contents[0].content == "modified text"

    def test_resource_result_rewraps_bytes_value(self):
        wrapper = ResourceResult("original")
        result = _rewrap_result(wrapper, b"binary data")
        assert isinstance(result, ResourceResult)
        assert result.contents[0].content == b"binary data"

    def test_resource_result_rewraps_dict_as_json(self):
        wrapper = ResourceResult("original")
        result = _rewrap_result(wrapper, {"replaced": True})
        assert isinstance(result, ResourceResult)
        assert '"replaced": true' in result.contents[0].content

    def test_resource_result_preserves_meta_on_rewrap(self):
        wrapper = ResourceResult("original", meta={"source": "test"})
        result = _rewrap_result(wrapper, "modified")
        assert isinstance(result, ResourceResult)
        assert result.meta == {"source": "test"}

    def test_prompt_result_rewraps_string_value(self):
        wrapper = PromptResult("original")
        result = _rewrap_result(wrapper, "modified prompt")
        assert isinstance(result, PromptResult)
        assert len(result.messages) == 1

    def test_prompt_result_rewraps_dict_as_json(self):
        wrapper = PromptResult("original")
        result = _rewrap_result(wrapper, {"replaced": True})
        assert isinstance(result, PromptResult)
        assert len(result.messages) == 1

    def test_prompt_result_preserves_description_on_rewrap(self):
        wrapper = PromptResult("original", description="test desc")
        result = _rewrap_result(wrapper, "modified")
        assert isinstance(result, PromptResult)
        assert result.description == "test desc"

    def test_unknown_wrapper_returns_value_directly(self):
        wrapper = MagicMock()
        assert _rewrap_result(wrapper, {"x": 1}) == {"x": 1}


class TestComponentType:
    """Tests for _component_type -- identifying FastMCP component types."""

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            (Tool, "tool"),
            (Resource, "resource"),
            (Prompt, "prompt"),
            (ResourceTemplate, "template"),
        ],
        ids=["tool", "resource", "prompt", "template"],
    )
    def test_identifies_fastmcp_component_type(self, spec, expected):
        component = MagicMock(spec=spec)
        assert _component_type(component) == expected

    def test_unknown_type_returns_unknown(self):
        assert _component_type(MagicMock()) == "unknown"


class TestLoggableSubjectId:
    """Tests for _loggable_subject_id -- extracting subject for logging."""

    def test_none_token_returns_anonymous(self):
        assert _loggable_subject_id(None) == "anonymous"

    def test_claims_with_sub_returns_sub(self):
        token = MagicMock(spec=AccessToken)
        token.claims = {"sub": "alice", "org": "acme"}
        assert _loggable_subject_id(token) == "alice"

    def test_claims_with_preferred_username_returns_that(self):
        token = MagicMock(spec=AccessToken)
        token.claims = {"preferred_username": "bob"}
        assert _loggable_subject_id(token) == "bob"

    def test_client_id_only_returns_client_id(self):
        token = MagicMock(spec=AccessToken)
        token.claims = {}
        token.client_id = "service-a"
        assert _loggable_subject_id(token) == "service-a"

    def test_no_claims_no_client_id_returns_unknown(self):
        token = MagicMock(spec=AccessToken)
        token.claims = {}
        token.client_id = None
        assert _loggable_subject_id(token) == "unknown"

    def test_non_access_token_returns_unknown(self):
        assert _loggable_subject_id(MagicMock()) == "unknown"


@pytest.mark.asyncio
class TestPreEnforceTool:
    """Pre-enforce tests for on_call_tool."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_permit_executes_tool_and_returns_result(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"x": 42})
        call_next = AsyncMock(return_value={"result": 42})

        result = await middleware.on_call_tool(context, call_next)

        assert result == {"result": 42}
        call_next.assert_awaited_once()

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_deny_blocks_tool_execution(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"x": 42})
        call_next = AsyncMock(return_value={"result": 42})

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)

        call_next.assert_not_awaited()

    @pytest.mark.parametrize(
        "decision_factory",
        [AuthorizationDecision.indeterminate, AuthorizationDecision.deny],
        ids=["indeterminate", "deny"],
    )
    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_non_permit_denies_fail_closed(self, _mock_token, decision_factory):
        pdp = AsyncMock()
        pdp.decide_once.return_value = decision_factory()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock()

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_pdp_unreachable_denies(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.side_effect = ConnectionError("unreachable")
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock()

        with pytest.raises(ConnectionError):
            await middleware.on_call_tool(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_unhandled_obligation_denies_despite_permit(self, _mock_token):
        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "unhandled_obligation"},),
        )
        pdp = AsyncMock()
        pdp.decide_once.return_value = decision
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock()

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_finalize_called_with_permit_on_success(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()

        finalize = AsyncMock()
        config = SaplConfig(mode="pre", finalize=finalize)
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock(return_value="ok")
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        await middleware.on_call_tool(context, call_next)

        finalize.assert_awaited_once()
        decision_arg = finalize.call_args[0][0]
        assert decision_arg.decision == Decision.PERMIT

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_finalize_called_with_deny_on_failure(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()

        finalize = AsyncMock()
        config = SaplConfig(mode="pre", finalize=finalize)
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)

        finalize.assert_awaited_once()
        decision_arg = finalize.call_args[0][0]
        assert decision_arg.decision == Decision.DENY

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_finalize_exception_does_not_mask_original_error(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()

        finalize = AsyncMock(side_effect=RuntimeError("finalize boom"))
        config = SaplConfig(mode="pre", finalize=finalize)
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)


@pytest.mark.asyncio
class TestPostEnforceTool:
    """Post-enforce tests for on_call_tool."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_tool_always_executes(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="post")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"x": 1})
        call_next = AsyncMock(return_value={"result": 1})

        result = await middleware.on_call_tool(context, call_next)

        assert result == {"result": 1}
        call_next.assert_awaited_once()

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_deny_suppresses_result(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="post")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"x": 1})
        call_next = AsyncMock(return_value={"sensitive": "data"})

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)

        call_next.assert_awaited_once()

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_subscription_includes_return_value(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(
            mode="post",
            resource=lambda ctx: {"result": ctx.return_value},
        )
        tool = _make_tool(name="run_model", sapl_config=config)
        context = _make_call_context(
            tool_name="run_model",
            tool=tool,
            arguments={"model_id": "v3"},
        )
        call_next = AsyncMock(return_value={"accuracy": 0.95})

        await middleware.on_call_tool(context, call_next)

        sub = pdp.decide_once.call_args[0][0]
        assert sub.resource == {"result": {"accuracy": 0.95}}

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_tool_result_unwrapped_in_subscription(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(
            mode="post",
            resource=lambda ctx: {"summary": ctx.return_value},
        )
        tool = _make_tool(name="run_model", sapl_config=config)
        context = _make_call_context(
            tool_name="run_model",
            tool=tool,
            arguments={"model_id": "v3"},
        )
        tool_result = ToolResult(
            structured_content={"accuracy": 0.95, "model": "v3"},
        )
        call_next = AsyncMock(return_value=tool_result)

        await middleware.on_call_tool(context, call_next)

        sub = pdp.decide_once.call_args[0][0]
        assert sub.resource == {"summary": {"accuracy": 0.95, "model": "v3"}}


def _make_on_decision_provider(constraint_type, handler_fn=None):
    """Create a mock RunnableConstraintHandlerProvider for ON_DECISION."""
    provider = MagicMock()
    provider.is_responsible = lambda c: c.get("type") == constraint_type
    provider.get_signal.return_value = Signal.ON_DECISION
    if handler_fn is None:
        handler_fn = MagicMock()
    provider.get_handler = MagicMock(return_value=handler_fn)
    return provider


def _multi_decision(**decisions):
    """Build a MultiAuthorizationDecision from keyword args of id->AuthorizationDecision."""
    return MultiAuthorizationDecision(decisions=decisions)


@pytest.mark.asyncio
class TestListingFilter:
    """Tests for listing hooks with multi-decide-all-once and constraint handling."""

    class TestPerComponentDecisions:
        """Per-component filtering for stealth components."""

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_stealth_permit_included(self, _mock_token):
            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            pdp = AsyncMock()
            pdp.multi_decide_all_once.return_value = _multi_decision(
                **{
                    "tool:secret": AuthorizationDecision.permit(),
                },
            )
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth])

            result = await middleware.on_list_tools(context, call_next)

            assert stealth in result

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_stealth_deny_excluded(self, _mock_token):
            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            pdp = AsyncMock()
            pdp.multi_decide_all_once.return_value = _multi_decision(
                **{
                    "tool:secret": AuthorizationDecision.deny(),
                },
            )
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth])

            result = await middleware.on_list_tools(context, call_next)

            assert stealth not in result

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_stealth_permit_with_unhandled_obligation_excluded(self, _mock_token):
            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            comp_decision = AuthorizationDecision(
                decision=Decision.PERMIT,
                obligations=({"type": "unknown_obligation"},),
            )
            pdp = AsyncMock()
            pdp.multi_decide_all_once.return_value = _multi_decision(
                **{
                    "tool:secret": comp_decision,
                },
            )
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth])

            result = await middleware.on_list_tools(context, call_next)

            assert stealth not in result

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_stealth_permit_with_resource_excluded(self, _mock_token):
            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            comp_decision = AuthorizationDecision(
                decision=Decision.PERMIT,
                resource={"replaced": True},
            )
            pdp = AsyncMock()
            pdp.multi_decide_all_once.return_value = _multi_decision(
                **{
                    "tool:secret": comp_decision,
                },
            )
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth])

            result = await middleware.on_list_tools(context, call_next)

            assert stealth not in result

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_stealth_on_decision_handler_invoked_per_component(self, _mock_token):
            handler_fn = MagicMock()
            provider = _make_on_decision_provider("log_component", handler_fn)
            constraint_service = ConstraintEnforcementService()
            constraint_service.register_runnable(provider)

            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            comp_decision = AuthorizationDecision(
                decision=Decision.PERMIT,
                obligations=({"type": "log_component"},),
            )
            pdp = AsyncMock()
            pdp.multi_decide_all_once.return_value = _multi_decision(
                **{
                    "tool:secret": comp_decision,
                },
            )
            middleware = SAPLMiddleware(pdp, constraint_service)
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth])

            result = await middleware.on_list_tools(context, call_next)

            assert stealth in result
            handler_fn.assert_called_once()

    class TestComponentPartitioning:
        """Tests for correct three-way partitioning of components."""

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_non_stealth_decorated_always_included(self, _mock_token):
            non_stealth = _make_tool(name="visible", sapl_config=SaplConfig(mode="pre", stealth=False))
            pdp = AsyncMock()
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[non_stealth])

            result = await middleware.on_list_tools(context, call_next)

            assert non_stealth in result
            pdp.multi_decide_all_once.assert_not_awaited()

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_undecorated_always_included(self, _mock_token):
            undecorated = _make_tool(name="open", sapl_config=None)
            pdp = AsyncMock()
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[undecorated])

            result = await middleware.on_list_tools(context, call_next)

            assert undecorated in result
            pdp.multi_decide_all_once.assert_not_awaited()

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_no_stealth_components_skips_pdp_call(self, _mock_token):
            non_stealth = _make_tool(name="visible", sapl_config=SaplConfig(mode="pre", stealth=False))
            undecorated = _make_tool(name="open", sapl_config=None)
            pdp = AsyncMock()
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[non_stealth, undecorated])

            result = await middleware.on_list_tools(context, call_next)

            assert len(result) == 2
            pdp.multi_decide_all_once.assert_not_awaited()

    class TestPdpInteraction:
        """Tests for PDP call behavior."""

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_uses_multi_decide_all_once(self, _mock_token):
            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            pdp = AsyncMock()
            pdp.multi_decide_all_once.return_value = _multi_decision(
                **{
                    "tool:secret": AuthorizationDecision.permit(),
                },
            )
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth])

            await middleware.on_list_tools(context, call_next)

            pdp.multi_decide_all_once.assert_awaited_once()
            pdp.decide_once.assert_not_awaited()

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_missing_component_decision_excludes_it(self, _mock_token):
            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            pdp = AsyncMock()
            pdp.multi_decide_all_once.return_value = _multi_decision()
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth])

            result = await middleware.on_list_tools(context, call_next)

            assert stealth not in result

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_subscription_build_failure_excludes_component_fail_closed(self, _mock_token):
            broken_config = SaplConfig(
                mode="pre",
                stealth=True,
                resource=lambda ctx: ctx.arguments["missing_key"],
            )
            broken = _make_tool(name="broken", sapl_config=broken_config)
            healthy = _make_tool(name="healthy", sapl_config=SaplConfig(mode="pre", stealth=True))
            pdp = AsyncMock()
            pdp.multi_decide_all_once.return_value = _multi_decision(
                **{
                    "tool:healthy": AuthorizationDecision.permit(),
                },
            )
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
            context = _make_list_context()
            call_next = AsyncMock(return_value=[broken, healthy])

            result = await middleware.on_list_tools(context, call_next)

            assert broken not in result
            assert healthy in result

    class TestEnforceListingFlag:
        """Tests for the enforce_listing constructor flag."""

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_enforce_listing_false_skips_pdp_call(self, _mock_token):
            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            pdp = AsyncMock()
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService(), enforce_listing=False)
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth])

            await middleware.on_list_tools(context, call_next)

            pdp.multi_decide_all_once.assert_not_awaited()

        @patch("sapl_fastmcp.middleware._get_token", return_value=None)
        async def test_enforce_listing_false_returns_all_components(self, _mock_token):
            stealth = _make_tool(name="secret", sapl_config=SaplConfig(mode="pre", stealth=True))
            non_stealth = _make_tool(name="visible", sapl_config=SaplConfig(mode="pre", stealth=False))
            undecorated = _make_tool(name="open", sapl_config=None)
            pdp = AsyncMock()
            middleware = SAPLMiddleware(pdp, ConstraintEnforcementService(), enforce_listing=False)
            context = _make_list_context()
            call_next = AsyncMock(return_value=[stealth, non_stealth, undecorated])

            result = await middleware.on_list_tools(context, call_next)

            assert len(result) == 3
            assert stealth in result
            assert non_stealth in result
            assert undecorated in result


@pytest.mark.asyncio
class TestNoDecoratorPassthrough:
    """Tests that undecorated components pass through without PDP calls."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_undecorated_tool_passes_through(self, _mock_token):
        pdp = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        tool = _make_tool(sapl_config=None)
        context = _make_call_context(tool=tool, arguments={"x": 1})
        call_next = AsyncMock(return_value={"result": 1})

        result = await middleware.on_call_tool(context, call_next)

        assert result == {"result": 1}
        pdp.decide_once.assert_not_awaited()


@pytest.mark.asyncio
class TestNonExistentComponent:
    """Tests that non-existent components raise NotFoundError without PDP calls."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_non_existent_tool_raises_not_found_error(self, _mock_token):
        pdp = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        context = _make_call_context(tool=None)
        call_next = AsyncMock()

        with pytest.raises(NotFoundError):
            await middleware.on_call_tool(context, call_next)

        pdp.decide_once.assert_not_awaited()
        call_next.assert_not_awaited()


@pytest.mark.asyncio
class TestStealthMode:
    """Tests for stealth mode (deny raises NotFoundError instead of AccessDeniedError)."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_stealth_deny_raises_not_found_error(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre", stealth=True)
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock()

        with pytest.raises(NotFoundError):
            await middleware.on_call_tool(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_non_stealth_deny_raises_access_denied_error(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre", stealth=False)
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock()

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_stealth_permit_returns_normally(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre", stealth=True)
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"x": 1})
        call_next = AsyncMock(return_value={"result": 1})

        result = await middleware.on_call_tool(context, call_next)

        assert result == {"result": 1}

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_stealth_not_found_error_includes_component_name(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre", stealth=True)
        tool = _make_tool(name="secret_tool", sapl_config=config)
        context = _make_call_context(tool_name="secret_tool", tool=tool)
        call_next = AsyncMock()

        with pytest.raises(NotFoundError, match="secret_tool"):
            await middleware.on_call_tool(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_stealth_finalize_still_called_on_deny(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()

        finalize = AsyncMock()
        config = SaplConfig(mode="pre", stealth=True, finalize=finalize)
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool)
        call_next = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        with pytest.raises(NotFoundError):
            await middleware.on_call_tool(context, call_next)

        finalize.assert_awaited_once()
        decision_arg = finalize.call_args[0][0]
        assert decision_arg.decision == Decision.DENY

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_stealth_post_enforce_deny_raises_not_found_error(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="post", stealth=True)
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"x": 1})
        call_next = AsyncMock(return_value={"sensitive": "data"})

        with pytest.raises(NotFoundError):
            await middleware.on_call_tool(context, call_next)


def _make_method_invocation_provider(constraint_type, handler_fn):
    """Create a mock MethodInvocationConstraintHandlerProvider."""
    provider = MagicMock()
    provider.is_responsible = lambda c: isinstance(c, dict) and c.get("type") == constraint_type
    provider.get_handler = MagicMock(return_value=handler_fn)
    return provider


@pytest.mark.asyncio
class TestPreEnforceMethodInvocation:
    """Tests for method-invocation handlers modifying kwargs via pre-enforce."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_obligation_limits_kwargs(self, _mock_token):
        captured_kwargs = {}

        async def fake_call_next(ctx):
            captured_kwargs.update(ctx.message.arguments)
            return {"result": "ok"}

        def limit_handler(context):
            current = context.kwargs.get("limit")
            if current is not None and current > 5:
                context.kwargs["limit"] = 5

        constraint_service = ConstraintEnforcementService()
        constraint_service.register_method_invocation(
            _make_method_invocation_provider("limitResults", limit_handler),
        )

        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "limitResults", "maxLimit": 5},),
        )
        pdp = AsyncMock()
        pdp.decide_once.return_value = decision
        middleware = SAPLMiddleware(pdp, constraint_service)

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"limit": 100})

        await middleware.on_call_tool(context, fake_call_next)

        assert captured_kwargs["limit"] == 5

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_no_obligation_keeps_original_kwargs(self, _mock_token):
        captured_kwargs = {}

        async def fake_call_next(ctx):
            captured_kwargs.update(ctx.message.arguments)
            return {"result": "ok"}

        def limit_handler(context):
            current = context.kwargs.get("limit")
            if current is not None and current > 5:
                context.kwargs["limit"] = 5

        constraint_service = ConstraintEnforcementService()
        constraint_service.register_method_invocation(
            _make_method_invocation_provider("limitResults", limit_handler),
        )

        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, constraint_service)

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"limit": 100})

        await middleware.on_call_tool(context, fake_call_next)

        assert captured_kwargs["limit"] == 100


@pytest.mark.asyncio
class TestPreEnforceFilterPredicate:
    """Tests for filter predicates filtering list results via pre-enforce."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_obligation_filters_list_result(self, _mock_token):
        constraint_service = ConstraintEnforcementService()
        constraint_service.register_filter_predicate(FilterByClassificationProvider())

        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "filterByClassification", "allowedLevels": ["public"]},),
        )
        pdp = AsyncMock()
        pdp.decide_once.return_value = decision
        middleware = SAPLMiddleware(pdp, constraint_service)

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={})
        call_next = AsyncMock(return_value=[
            {"classification": "public", "name": "a"},
            {"classification": "confidential", "name": "b"},
        ])

        result = await middleware.on_call_tool(context, call_next)

        assert len(result) == 1
        assert result[0]["classification"] == "public"

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_no_obligation_keeps_all_elements(self, _mock_token):
        constraint_service = ConstraintEnforcementService()
        constraint_service.register_filter_predicate(FilterByClassificationProvider())

        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, constraint_service)

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={})
        full_list = [
            {"classification": "public", "name": "a"},
            {"classification": "confidential", "name": "b"},
        ]
        call_next = AsyncMock(return_value=full_list)

        result = await middleware.on_call_tool(context, call_next)

        assert len(result) == 2

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_multiple_allowed_levels_keeps_matching(self, _mock_token):
        constraint_service = ConstraintEnforcementService()
        constraint_service.register_filter_predicate(FilterByClassificationProvider())

        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "filterByClassification", "allowedLevels": ["public", "internal"]},),
        )
        pdp = AsyncMock()
        pdp.decide_once.return_value = decision
        middleware = SAPLMiddleware(pdp, constraint_service)

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={})
        call_next = AsyncMock(return_value=[
            {"classification": "public", "name": "a"},
            {"classification": "confidential", "name": "b"},
            {"classification": "internal", "name": "c"},
        ])

        result = await middleware.on_call_tool(context, call_next)

        assert len(result) == 2
        assert {r["name"] for r in result} == {"a", "c"}


@pytest.mark.asyncio
class TestPostEnforceConstraintHandlers:
    """Tests for post-enforce constraint handler behavior."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_filter_predicate_transforms_result(self, _mock_token):
        constraint_service = ConstraintEnforcementService()
        constraint_service.register_filter_predicate(FilterByClassificationProvider())

        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "filterByClassification", "allowedLevels": ["public"]},),
        )
        pdp = AsyncMock()
        pdp.decide_once.return_value = decision
        middleware = SAPLMiddleware(pdp, constraint_service)

        config = SaplConfig(mode="post")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={})
        call_next = AsyncMock(return_value=[
            {"classification": "public", "name": "a"},
            {"classification": "confidential", "name": "b"},
        ])

        result = await middleware.on_call_tool(context, call_next)

        assert len(result) == 1
        assert result[0]["name"] == "a"

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_method_invocation_only_obligation_denies_in_post_enforce(self, _mock_token):
        """An obligation with only a method-invocation handler is unenforceable
        in post-enforce (no method-invocation handlers in post path), so it
        correctly results in denial due to unhandled obligation.
        """
        def invocation_handler(context):
            context.kwargs["limit"] = 1

        constraint_service = ConstraintEnforcementService()
        constraint_service.register_method_invocation(
            _make_method_invocation_provider("limitResults", invocation_handler),
        )

        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "limitResults"},),
        )
        pdp = AsyncMock()
        pdp.decide_once.return_value = decision
        middleware = SAPLMiddleware(pdp, constraint_service)

        config = SaplConfig(mode="post")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"limit": 100})
        call_next = AsyncMock(return_value={"result": "ok"})

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)


@pytest.mark.asyncio
class TestResourceHook:
    """Tests for on_read_resource enforcement."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_permit_returns_resource_content(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        resource = _make_resource(sapl_config=config)
        context = _make_read_context(uri="data://public/summary", resource=resource)
        call_next = AsyncMock(return_value="resource content")

        result = await middleware.on_read_resource(context, call_next)

        assert result == "resource content"
        call_next.assert_awaited_once()

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_deny_blocks_resource_read(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        resource = _make_resource(sapl_config=config)
        context = _make_read_context(uri="data://secret/keys", resource=resource)
        call_next = AsyncMock()

        with pytest.raises(AccessDeniedError):
            await middleware.on_read_resource(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_non_existent_resource_raises_not_found(self, _mock_token):
        pdp = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        context = _make_read_context(uri="data://missing")
        call_next = AsyncMock()

        with pytest.raises(NotFoundError):
            await middleware.on_read_resource(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_undecorated_resource_passes_through(self, _mock_token):
        pdp = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        resource = _make_resource(sapl_config=None)
        context = _make_read_context(uri="data://open", resource=resource)
        call_next = AsyncMock(return_value="open data")

        result = await middleware.on_read_resource(context, call_next)

        assert result == "open data"
        pdp.decide_once.assert_not_awaited()


@pytest.mark.asyncio
class TestPromptHook:
    """Tests for on_get_prompt enforcement."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_permit_returns_prompt_messages(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        prompt = _make_prompt_component(sapl_config=config)
        context = _make_get_context(prompt=prompt, arguments={"topic": "sales"})
        call_next = AsyncMock(return_value="prompt messages")

        result = await middleware.on_get_prompt(context, call_next)

        assert result == "prompt messages"
        call_next.assert_awaited_once()

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_deny_blocks_prompt_access(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        prompt = _make_prompt_component(sapl_config=config)
        context = _make_get_context(prompt=prompt)
        call_next = AsyncMock()

        with pytest.raises(AccessDeniedError):
            await middleware.on_get_prompt(context, call_next)

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_non_existent_prompt_raises_not_found(self, _mock_token):
        pdp = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        context = _make_get_context(prompt=None)
        call_next = AsyncMock()

        with pytest.raises(NotFoundError):
            await middleware.on_get_prompt(context, call_next)


@pytest.mark.asyncio
class TestResourceTemplateFallback:
    """Tests for resource template fallback in on_read_resource."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_template_used_when_resource_not_found(self, _mock_token):
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        template = MagicMock(spec=ResourceTemplate)

        def fn():
            pass

        fn.__sapl__ = config
        template.fn = fn
        template.name = "user_{id}"
        template.tags = set()

        context = _make_read_context(
            uri="data://users/42",
            resource=None,
            template=template,
        )
        call_next = AsyncMock(return_value="template content")

        result = await middleware.on_read_resource(context, call_next)

        assert result == "template content"


@pytest.mark.asyncio
class TestMixedStealthListing:
    """Tests for listing with mixed permitted and denied stealth components."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_mixed_decisions_filter_correctly(self, _mock_token):
        permitted = _make_tool(
            name="allowed", sapl_config=SaplConfig(stealth=True),
        )
        denied = _make_tool(
            name="forbidden", sapl_config=SaplConfig(stealth=True),
        )
        undecorated = _make_tool(name="open", sapl_config=None)

        pdp = AsyncMock()
        pdp.multi_decide_all_once.return_value = _multi_decision(
            **{
                "tool:allowed": AuthorizationDecision.permit(),
                "tool:forbidden": AuthorizationDecision.deny(),
            },
        )
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
        context = _make_list_context()
        call_next = AsyncMock(return_value=[permitted, denied, undecorated])

        result = await middleware.on_list_tools(context, call_next)

        assert permitted in result
        assert denied not in result
        assert undecorated in result
        assert len(result) == 2


@pytest.mark.asyncio
class TestToolResultConstraintRoundTrip:
    """Tests that ToolResult wrappers survive the unwrap-constrain-rewrap cycle."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_filter_predicate_on_tool_result_preserves_wrapper(self, _mock_token):
        """A tool returns classified data wrapped in ToolResult.
        The filterByClassification obligation filters the list.
        The result must be a properly rewrapped ToolResult.
        """
        constraint_service = ConstraintEnforcementService()
        constraint_service.register_filter_predicate(FilterByClassificationProvider())

        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "filterByClassification", "allowedLevels": ["public"]},),
        )
        pdp = AsyncMock()
        pdp.decide_once.return_value = decision
        middleware = SAPLMiddleware(pdp, constraint_service)

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={})
        data = [
            {"classification": "public", "name": "a"},
            {"classification": "confidential", "name": "b"},
        ]
        call_next = AsyncMock(
            return_value=ToolResult(structured_content={"result": data}),
        )

        result = await middleware.on_call_tool(context, call_next)

        assert isinstance(result, ToolResult)
        assert result.structured_content == {
            "result": [{"classification": "public", "name": "a"}],
        }

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_dict_tool_result_survives_permit_unmodified(self, _mock_token):
        """A tool returns a dict wrapped in ToolResult.
        With no constraint modifications, the result must be a ToolResult.
        """
        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        config = SaplConfig(mode="pre")
        tool = _make_tool(sapl_config=config)
        context = _make_call_context(tool=tool, arguments={"x": 1})
        call_next = AsyncMock(
            return_value=ToolResult(structured_content={"key": "value"}),
        )

        result = await middleware.on_call_tool(context, call_next)

        assert isinstance(result, ToolResult)
        assert result.structured_content == {"key": "value"}


class TestStdioBypass:
    """STDIO transport bypasses all SAPL authorization."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "hook,make_context",
        [
            ("on_call_tool", lambda: _make_call_context(tool=_make_tool(sapl_config=SaplConfig(mode="pre")))),
            ("on_read_resource", lambda: _make_read_context(resource=_make_resource(sapl_config=SaplConfig(mode="pre")))),
            ("on_get_prompt", lambda: _make_get_context(prompt=_make_prompt_component(sapl_config=SaplConfig(mode="pre")))),
        ],
        ids=["call_tool", "read_resource", "get_prompt"],
    )
    @patch("sapl_fastmcp.middleware._is_stdio", return_value=True)
    async def test_access_hooks_bypasses_authorization_on_stdio(self, _mock_stdio, hook, make_context):
        pdp = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
        context = make_context()
        sentinel = object()
        call_next = AsyncMock(return_value=sentinel)

        result = await getattr(middleware, hook)(context, call_next)

        assert result is sentinel
        pdp.decide_once.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "hook",
        ["on_list_tools", "on_list_resources", "on_list_resource_templates", "on_list_prompts"],
        ids=["list_tools", "list_resources", "list_templates", "list_prompts"],
    )
    @patch("sapl_fastmcp.middleware._is_stdio", return_value=True)
    async def test_listing_hooks_bypasses_authorization_on_stdio(self, _mock_stdio, hook):
        pdp = AsyncMock()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
        context = _make_list_context()
        sentinel = [object()]
        call_next = AsyncMock(return_value=sentinel)

        result = await getattr(middleware, hook)(context, call_next)

        assert result is sentinel
        pdp.multi_decide_all_once.assert_not_called()


class TestListingHookVariants:
    """on_list_resources, on_list_resource_templates, on_list_prompts delegate to _authorize_listing."""

    @pytest.mark.asyncio
    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_list_resources_filters_stealth_resources(self, _mock_token):
        stealth = _make_resource(name="secret_res", sapl_config=SaplConfig(mode="pre", stealth=True))
        visible = _make_resource(name="public_res")
        pdp = AsyncMock()
        pdp.multi_decide_all_once.return_value = _multi_decision(
            **{"resource:secret_res": AuthorizationDecision.deny()},
        )
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
        context = _make_list_context()
        call_next = AsyncMock(return_value=[visible, stealth])

        result = await middleware.on_list_resources(context, call_next)

        assert visible in result
        assert stealth not in result

    @pytest.mark.asyncio
    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_list_resource_templates_filters_stealth_templates(self, _mock_token):
        def fn():
            pass
        fn.__sapl__ = SaplConfig(mode="pre", stealth=True)
        stealth = MagicMock(spec=ResourceTemplate)
        stealth.name = "secret_tmpl"
        stealth.fn = fn
        stealth.tags = set()

        pdp = AsyncMock()
        pdp.multi_decide_all_once.return_value = _multi_decision(
            **{"template:secret_tmpl": AuthorizationDecision.deny()},
        )
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
        context = _make_list_context()
        call_next = AsyncMock(return_value=[stealth])

        result = await middleware.on_list_resource_templates(context, call_next)

        assert stealth not in result

    @pytest.mark.asyncio
    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_list_prompts_filters_stealth_prompts(self, _mock_token):
        stealth = _make_prompt_component(name="secret_prompt", sapl_config=SaplConfig(mode="pre", stealth=True))
        visible = _make_prompt_component(name="public_prompt")
        pdp = AsyncMock()
        pdp.multi_decide_all_once.return_value = _multi_decision(
            **{"prompt:secret_prompt": AuthorizationDecision.deny()},
        )
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
        context = _make_list_context()
        call_next = AsyncMock(return_value=[visible, stealth])

        result = await middleware.on_list_prompts(context, call_next)

        assert visible in result
        assert stealth not in result

    @pytest.mark.asyncio
    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_list_resources_permit_includes_stealth_resource(self, _mock_token):
        stealth = _make_resource(name="secret_res", sapl_config=SaplConfig(mode="pre", stealth=True))
        pdp = AsyncMock()
        pdp.multi_decide_all_once.return_value = _multi_decision(
            **{"resource:secret_res": AuthorizationDecision.permit()},
        )
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())
        context = _make_list_context()
        call_next = AsyncMock(return_value=[stealth])

        result = await middleware.on_list_resources(context, call_next)

        assert stealth in result
