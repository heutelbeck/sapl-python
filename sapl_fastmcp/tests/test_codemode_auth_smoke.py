"""Smoke test: verify that CodeMode sandbox call_tool() triggers auth= checks.

Monty (pydantic-monty) is a sandboxed Python interpreter compiled in Rust.
Code inside the sandbox can ONLY call functions explicitly passed via
external_functions. CodeMode passes exactly one: call_tool(). This test
verifies that call_tool() inside the sandbox goes through the full FastMCP
dispatch path including auth= checks.

NOTE: On STDIO transport, FastMCP skips auth by design (_get_auth_context
returns skip_auth=True). These tests use server.call_tool() directly which
also runs in a no-transport context. To verify auth enforcement, we
monkeypatch _get_auth_context to simulate HTTP transport behavior.
"""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.experimental.transforms.code_mode import CodeMode

try:
    import pydantic_monty as _pydantic_monty  # noqa: F401

    _has_monty = True
except ImportError:
    _has_monty = False

_requires_monty = pytest.mark.skipif(
    not _has_monty,
    reason="pydantic-monty not installed (install fastmcp[code-mode])",
)


@_requires_monty
@pytest.mark.asyncio
async def test_codemode_calls_auth_on_inner_tool():
    """Auth function is invoked when call_tool() runs inside sandbox."""
    auth_calls = []

    async def tracking_auth(ctx):
        auth_calls.append(ctx.component.name)
        return True

    mcp = FastMCP("test", transforms=[CodeMode()])

    @mcp.tool(auth=tracking_auth)
    def add(x: int, y: int) -> int:
        """Add two numbers."""
        return x + y

    with patch(
        "fastmcp.server.server._get_auth_context",
        return_value=(False, None),
    ):
        await mcp.call_tool(
            "execute",
            {"code": 'result = await call_tool("add", {"x": 1, "y": 2})'},
        )

    assert "add" in auth_calls


@_requires_monty
@pytest.mark.asyncio
async def test_codemode_denied_tool_raises_in_sandbox():
    """When auth denies a tool, call_tool() inside sandbox fails."""

    async def deny_all(ctx):
        return False

    mcp = FastMCP("test", transforms=[CodeMode()])

    @mcp.tool(auth=deny_all)
    def add(x: int, y: int) -> int:
        """Add two numbers."""
        return x + y

    with (
        patch(
            "fastmcp.server.server._get_auth_context",
            return_value=(False, None),
        ),
        pytest.raises(ToolError, match="execute"),
    ):
        await mcp.call_tool(
            "execute",
            {"code": 'result = await call_tool("add", {"x": 1, "y": 2})'},
        )
