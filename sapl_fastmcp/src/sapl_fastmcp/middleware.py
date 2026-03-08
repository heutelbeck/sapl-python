"""SAPL authorization middleware for FastMCP.

Replaces per-component auth= checks with a single middleware that
intercepts all MCP operations. Delegates to ``sapl_base.enforcement``
for the actual pre/post enforcement logic; the middleware adds
MCP-specific concerns: subscription building, ``call_next`` wrapping,
``finalize`` orchestration, and listing filters.

Components without a ``@pre_enforce`` / ``@post_enforce`` decorator
pass through with no PDP call (gradual adoption).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastmcp.exceptions import NotFoundError
from fastmcp.prompts.prompt import Prompt, PromptResult
from fastmcp.resources.resource import Resource, ResourceResult
from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.auth import AccessToken
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware.middleware import (
    CallNext,
    Middleware,
    MiddlewareContext,
)
from fastmcp.tools.tool import Tool, ToolResult

from sapl_base import (
    AuthorizationDecision,
    MultiAuthorizationSubscription,
    PdpClient,
)
from sapl_base.constraint_bundle import AccessDeniedError
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.enforcement import (
    post_enforce as base_post_enforce,
)
from sapl_base.enforcement import (
    pre_enforce as base_pre_enforce,
)
from sapl_fastmcp.context import FinalizeCallback, SaplConfig, SubscriptionContext
from sapl_fastmcp.enforcement import enforce_decision_gate
from sapl_fastmcp.subscription import build_middleware_subscription

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger("sapl.mcp.middleware")


def _is_stdio() -> bool:
    """Check whether the current request is served over the STDIO transport.

    SAPL authorization is scoped to HTTP-based MCP servers. STDIO is a local
    subprocess transport with no network boundary and no authentication
    context (no tokens, no headers). The MCP specification does not define
    an auth model for STDIO.

    From an AI safety perspective, constraining agent actions over STDIO is
    a valid concern, but it requires a different trust and identity model
    that is outside the scope of the current SAPL MCP integration. This
    should be revisited when the MCP specification addresses agent-level
    authorization for local transports.

    Follows the same pattern as FastMCP's built-in AuthorizationMiddleware.
    """
    from fastmcp.server.context import _current_transport

    return _current_transport.get() == "stdio"


class SAPLMiddleware(Middleware):
    """Attribute-based authorization middleware backed by SAPL PDP.

    Sits in the FastMCP middleware chain and intercepts every list, call,
    read, and get operation. Has access to the full request context
    including tool arguments and resource URIs, which component-level
    auth= checks cannot see.

    The PDP client and constraint service are injected at construction time
    so the middleware does not depend on module-level globals.

    STDIO transport is not enforced. All middleware hooks pass through
    without PDP calls when the transport is STDIO. See ``_is_stdio``.
    """

    def __init__(
        self,
        pdp: PdpClient,
        constraint_service: ConstraintEnforcementService | None = None,
        enforce_listing: bool = True,
    ) -> None:
        self._pdp = pdp
        self._constraint_service = constraint_service or ConstraintEnforcementService()
        self._enforce_listing = enforce_listing

    # -- Listing flow --

    async def on_list_tools(self, context, call_next):
        return await self._authorize_listing(context, call_next, "call")

    async def on_list_resources(self, context, call_next):
        return await self._authorize_listing(context, call_next, "read")

    async def on_list_resource_templates(self, context, call_next):
        return await self._authorize_listing(context, call_next, "read")

    async def on_list_prompts(self, context, call_next):
        return await self._authorize_listing(context, call_next, "get")

    async def _authorize_listing(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Sequence[Any]],
        operation: str,
    ) -> Sequence[Any]:
        if _is_stdio():
            return await call_next(context)
        components = await call_next(context)
        if not self._enforce_listing:
            return components
        return await self._hide_unauthorized_stealth_components(components, operation)

    async def _hide_unauthorized_stealth_components(
        self,
        components: Sequence[Any],
        operation: str,
    ) -> list[Any]:
        """Filter a component list by hiding stealth components the subject may not access.

        Listing is always a gate-level visibility filter, not access enforcement.
        Only ON_DECISION constraint handlers run here (via ``enforce_decision_gate``).
        The pre/post distinction is irrelevant for listing because there is no
        "execution" during a list operation -- post-enforce (which includes the
        return value in the subscription) has no meaning in this context.

        No gate-level denial: the MCP SDK internally triggers listing during
        tool calls for schema cache population. A gate denial would prevent
        cache population, creating a permanent cache-miss loop. Actual access
        control is enforced per-request by the on_call/read/get hooks.
        """
        token = _get_token()
        always_visible: list[Any] = []
        stealth: list[tuple[Any, SaplConfig]] = []

        for component in components:
            config = _get_sapl_config(component)
            if config is None or not config.stealth:
                always_visible.append(component)
            else:
                stealth.append((component, config))

        if not stealth:
            return always_visible

        subscriptions: dict[str, Any] = {}
        component_ids: dict[str, tuple[Any, SaplConfig]] = {}
        for component, config in stealth:
            sub_ctx = SubscriptionContext(
                token=token, component=component, operation=operation,
            )
            comp_id = f"{_component_type(component)}:{getattr(component, 'name', '?')}"
            try:
                subscriptions[comp_id] = build_middleware_subscription(sub_ctx, config)
            except Exception:
                logger.warning(
                    "%s: subscription build failed for %s, excluding (fail-closed)",
                    operation, getattr(component, "name", "?"),
                    exc_info=True,
                )
                continue
            component_ids[comp_id] = (component, config)

        if not subscriptions:
            return always_visible

        multi_sub = MultiAuthorizationSubscription(subscriptions=subscriptions)
        _log_subscription(operation, "list", multi_sub)
        multi_decision = await self._pdp.multi_decide_all_once(multi_sub)
        _log_multi_decisions(operation, multi_decision)

        included_stealth: list[Any] = []
        for comp_id, (component, _config) in component_ids.items():
            comp_decision = multi_decision.decisions.get(comp_id)
            if comp_decision is not None and enforce_decision_gate(self._constraint_service, comp_decision):
                included_stealth.append(component)
            else:
                logger.debug(
                    "%s: hiding %s, subject=%s",
                    operation, getattr(component, "name", "?"), _loggable_subject_id(token),
                )

        visible = always_visible + included_stealth
        logger.debug(
            "%s: %d/%d visible, subject=%s",
            operation, len(visible), len(components), _loggable_subject_id(token),
        )
        return visible

    # -- Access flow --

    async def on_call_tool(self, context, call_next):
        if _is_stdio():
            return await call_next(context)
        name = context.message.name
        tool = await self._lookup_component(context, "get_tool", name)
        return await self._authorize_component(
            context, call_next, tool, name, "call",
            kwargs=dict(context.message.arguments or {}),
        )

    async def on_read_resource(self, context, call_next):
        if _is_stdio():
            return await call_next(context)
        uri = str(context.message.uri)
        resource = await self._lookup_component(context, "get_resource", uri)
        if resource is None:
            resource = await self._lookup_component(context, "get_resource_template", uri)
        return await self._authorize_component(
            context, call_next, resource, uri, "read", uri=uri,
        )

    async def on_get_prompt(self, context, call_next):
        if _is_stdio():
            return await call_next(context)
        name = context.message.name
        prompt = await self._lookup_component(context, "get_prompt", name)
        return await self._authorize_component(
            context, call_next, prompt, name, "get",
            kwargs=dict(context.message.arguments or {}),
        )

    @staticmethod
    async def _lookup_component(
        context: MiddlewareContext[Any],
        method_name: str,
        key: str,
    ) -> Any:
        """Look up a component from the FastMCP server instance."""
        try:
            fastmcp = context.fastmcp_context.fastmcp
            getter = getattr(fastmcp, method_name, None)
            if getter is not None:
                return await getter(key)
        except NotFoundError:
            logger.debug("component not found: %s(%s)", method_name, key)
        return None

    async def _authorize_component(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
        component: Any,
        identifier: str,
        operation: str,
        *,
        kwargs: dict[str, Any] | None = None,
        uri: str | None = None,
    ) -> Any:
        """Shared enforcement for call/read/get hooks.

        When ``kwargs`` is provided, arguments are forwarded to the protected
        function and constraint handlers may modify them. When absent (resources),
        the protected function ignores arguments.
        """
        if component is None:
            raise NotFoundError(identifier)

        config = _get_sapl_config(component)

        if config is None:
            logger.debug("%s: %s -- no decorator, pass through", operation, identifier)
            return await call_next(context)

        sub_ctx = SubscriptionContext(
            token=_get_token(),
            component=component,
            operation=operation,
            arguments=kwargs or {},
            uri=uri,
        )

        _fastmcp_wrapper: list[Any] = [None]
        _unwrapped_ref: list[Any] = [None]

        if kwargs is not None:
            async def protected(**updated_kwargs: Any) -> Any:
                new_msg = context.message.model_copy(update={"arguments": updated_kwargs})
                wrapper = await call_next(context.copy(message=new_msg))
                _fastmcp_wrapper[0] = wrapper
                unwrapped = _unwrap_result(wrapper)
                _unwrapped_ref[0] = unwrapped
                return unwrapped
        else:
            async def protected(**_kw: Any) -> Any:
                wrapper = await call_next(context)
                _fastmcp_wrapper[0] = wrapper
                unwrapped = _unwrap_result(wrapper)
                _unwrapped_ref[0] = unwrapped
                return unwrapped

        result = await self._enforce_component_access(
            config=config,
            sub_ctx=sub_ctx,
            protected=protected,
            kwargs=kwargs or {},
            function_name=identifier,
        )
        if result is _unwrapped_ref[0]:
            return _fastmcp_wrapper[0]
        return _rewrap_result(_fastmcp_wrapper[0], result)

    async def _enforce_component_access(
        self,
        config: SaplConfig,
        sub_ctx: SubscriptionContext,
        protected: Any,
        kwargs: dict[str, Any],
        function_name: str,
    ) -> Any:
        """Delegate to sapl_base enforcement with finalize orchestration."""
        outcome = AuthorizationDecision.deny()
        try:
            if config.mode == "pre":
                subscription = build_middleware_subscription(sub_ctx, config)
                _log_subscription(function_name, config.mode, subscription)
                result = await base_pre_enforce(
                    pdp_client=self._pdp,
                    constraint_service=self._constraint_service,
                    subscription=subscription,
                    protected_function=protected,
                    args=[],
                    kwargs=kwargs,
                    function_name=function_name,
                )
            else:
                def sub_builder(return_value: Any) -> Any:
                    enriched = SubscriptionContext(
                        token=sub_ctx.token,
                        component=sub_ctx.component,
                        operation=sub_ctx.operation,
                        arguments=sub_ctx.arguments,
                        uri=sub_ctx.uri,
                        return_value=_unwrap_result(return_value),
                    )
                    sub = build_middleware_subscription(enriched, config)
                    _log_subscription(function_name, config.mode, sub)
                    return sub

                result = await base_post_enforce(
                    pdp_client=self._pdp,
                    constraint_service=self._constraint_service,
                    subscription_builder=sub_builder,
                    protected_function=protected,
                    args=[],
                    kwargs=kwargs,
                    function_name=function_name,
                )
            outcome = AuthorizationDecision.permit()
            _log_decision(function_name, config.mode, "PERMIT")
            return result
        except AccessDeniedError:
            outcome = AuthorizationDecision.deny()
            _log_decision(function_name, config.mode, "DENY (access denied)")
            if config.stealth:
                raise NotFoundError(function_name) from None
            raise
        except Exception:
            outcome = AuthorizationDecision.deny()
            _log_decision(function_name, config.mode, "DENY (error)")
            raise
        finally:
            if config.finalize is not None:
                await _invoke_finalize_safely(config.finalize, outcome, sub_ctx)


# -- Shared helpers --


def _get_token() -> AccessToken | None:
    """Retrieve the access token from the current request context.

    Returns None when no token is present (unauthenticated request).
    Exceptions propagate intentionally: an unexpected failure in the
    auth infrastructure must fail closed (deny), not silently downgrade
    the request to anonymous.
    """
    return get_access_token()


def _get_sapl_config(component: Any) -> SaplConfig | None:
    """Extract ``__sapl__`` config from a component's underlying function.

    Returns None if the component has no function or no decorator.
    """
    if component is None:
        return None
    fn = getattr(component, "fn", None)
    if fn is None:
        return None
    config = getattr(fn, "__sapl__", None)
    if isinstance(config, SaplConfig):
        return config
    return None


def _component_type(component: Any) -> str:
    """Return a short type label for a component (tool, resource, prompt, template)."""
    if isinstance(component, ResourceTemplate):
        return "template"
    if isinstance(component, Resource):
        return "resource"
    if isinstance(component, Prompt):
        return "prompt"
    if isinstance(component, Tool):
        return "tool"
    return "unknown"


def _loggable_subject_id(token: AccessToken | None) -> str:
    """Extract a loggable subject identifier from a token."""
    if token is None:
        return "anonymous"
    if not isinstance(token, AccessToken):
        return "unknown"
    if token.claims:
        return token.claims.get("sub", token.claims.get("preferred_username", "unknown"))
    if token.client_id:
        return token.client_id
    return "unknown"


def _unwrap_result(result: Any) -> Any:
    """Extract JSON-serializable content from FastMCP result wrappers.

    FastMCP wraps tool/resource/prompt return values in Pydantic models
    (ToolResult, ResourceResult, PromptResult) that are not directly
    JSON-serializable by the PDP client. This extracts the plain data.

    When a tool returns a non-dict value (e.g. a list), FastMCP may wrap it
    as ``{"result": value}`` in structured_content. This function detects
    that wrapper and returns the inner value so constraint handlers operate
    on the original data shape.
    """
    if result is None:
        return None
    if isinstance(result, ToolResult):
        sc = result.structured_content
        if sc is not None:
            if isinstance(sc, dict) and len(sc) == 1 and "result" in sc:
                return sc["result"]
            return sc
        return result.model_dump(mode="json")
    if isinstance(result, (ResourceResult, PromptResult)):
        return result.model_dump(mode="json")
    return result


def _rewrap_result(wrapper: Any, value: Any) -> Any:
    """Re-wrap a constraint-modified value into a valid FastMCP wrapper.

    Only called when a constraint handler actually modified the value
    (identity check in ``_authorize_component`` short-circuits the common
    unmodified case). The modified value is arbitrary JSON-serializable data
    from resource replacement, mapping handlers, or filter predicates.

    For ``ToolResult``, the constructor accepts raw content and rebuilds
    content blocks automatically. For ``ResourceResult`` and ``PromptResult``,
    the modified value is wrapped as a single text content item since the
    constructors accept plain strings.

    Limitation: if the original wrapper contained multiple content items
    (ResourceResult with multiple BlobContent/TextContent entries) or
    multiple messages (PromptResult), only a single item is produced.
    This is acceptable because sapl_base constraint handlers currently
    operate on the unwrapped JSON value as a whole, not on individual
    content items. If per-item modification is needed in the future,
    this function must be extended to reconstruct multi-item wrappers.
    """
    if wrapper is None:
        return value
    if isinstance(wrapper, ToolResult):
        sc = wrapper.structured_content
        if sc is not None and isinstance(sc, dict) and len(sc) == 1 and "result" in sc:
            return ToolResult(content=value, structured_content={"result": value})
        return ToolResult(
            content=value,
            structured_content=value if isinstance(value, dict) else None,
        )
    if isinstance(wrapper, ResourceResult):
        if isinstance(value, (str, bytes)):
            return ResourceResult(value, meta=wrapper.meta)
        return ResourceResult(json.dumps(value, default=str), meta=wrapper.meta)
    if isinstance(wrapper, PromptResult):
        if isinstance(value, str):
            return PromptResult(value, description=wrapper.description, meta=wrapper.meta)
        return PromptResult(
            json.dumps(value, default=str),
            description=wrapper.description,
            meta=wrapper.meta,
        )
    return value


async def _invoke_finalize_safely(
    finalize: FinalizeCallback,
    decision: AuthorizationDecision,
    ctx: SubscriptionContext,
) -> None:
    """Call the finalize callback, logging and swallowing any exception."""
    try:
        await finalize(decision, ctx)
    except Exception:
        logger.warning(
            "finalize callback raised an exception",
            exc_info=True,
        )


# -- Logging helpers --


def _log_subscription(name: str, mode: str, subscription: Any) -> None:
    logger.debug(
        "%s [%s]: subscription:\n%s",
        name, mode, json.dumps(subscription.to_loggable_dict(), indent=2, default=str),
    )


def _log_decision(name: str, mode: str, outcome: str) -> None:
    logger.debug("%s [%s]: %s", name, mode, outcome)


def _log_multi_decisions(operation: str, multi_decision: Any) -> None:
    summary = {
        k: {
            "decision": v.decision.value,
            "obligations": v.obligations,
            "advice": v.advice,
            "has_resource": v.has_resource,
        }
        for k, v in multi_decision.decisions.items()
    }
    logger.debug(
        "%s: received decisions:\n%s",
        operation, json.dumps(summary, indent=2, default=str),
    )
