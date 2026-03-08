"""Integration tests for finalize callback with database transactions.

Uses SQLAlchemy async with aiosqlite in-memory database to test
commit/rollback semantics controlled by the finalize callback.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from sapl_base import AuthorizationDecision, Decision
from sapl_base.constraint_bundle import AccessDeniedError
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_fastmcp.context import SaplConfig
from sapl_fastmcp.middleware import SAPLMiddleware

try:
    import greenlet as _greenlet  # noqa: F401

    _has_greenlet = True
except (ImportError, OSError, ValueError):
    _has_greenlet = False

_requires_sqlalchemy = pytest.mark.skipif(
    not _has_greenlet,
    reason="greenlet native library not available in this environment",
)


async def _create_engine_and_table():
    """Create an in-memory SQLite engine with an items table."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"))
    return engine


def _make_tool_with_finalize(finalize_fn):
    """Create a mock tool with a pre_enforce config including finalize."""

    def fn():
        pass

    fn.__sapl__ = SaplConfig(mode="pre", finalize=finalize_fn)

    tool = MagicMock()
    tool.name = "insert_item"
    tool.fn = fn
    tool.tags = set()
    return tool


def _make_call_context(tool, arguments=None):
    """Create a mock MiddlewareContext for on_call_tool."""
    message = MagicMock()
    message.name = tool.name
    message.arguments = arguments or {}
    message.model_copy = lambda update: MagicMock(
        name=tool.name,
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


@_requires_sqlalchemy
@pytest.mark.asyncio
class TestFinalizeWithDatabase:
    """Tests for finalize callback controlling database transactions."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_permit_commits_data(self, _mock_token):
        engine = await _create_engine_and_table()
        session = AsyncSession(engine)

        async def finalize(decision, ctx):
            if decision.decision == Decision.PERMIT:
                await session.commit()
            else:
                await session.rollback()
            await session.close()

        tool = _make_tool_with_finalize(finalize)
        context = _make_call_context(tool, {"name": "widget"})

        async def call_next(_ctx):
            session.add_all([])
            await session.execute(text("INSERT INTO items (name) VALUES ('widget')"))
            return {"inserted": True}

        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.permit()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        await middleware.on_call_tool(context, call_next)

        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT name FROM items"))
            rows = result.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "widget"
        await engine.dispose()

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_deny_rollbacks_data(self, _mock_token):
        engine = await _create_engine_and_table()
        session = AsyncSession(engine)

        async def finalize(decision, ctx):
            if decision.decision == Decision.PERMIT:
                await session.commit()
            else:
                await session.rollback()
            await session.close()

        tool = _make_tool_with_finalize(finalize)
        context = _make_call_context(tool, {"name": "widget"})

        call_next = AsyncMock(return_value={"inserted": True})

        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)

        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT name FROM items"))
            rows = result.fetchall()

        assert len(rows) == 0
        await engine.dispose()

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_pdp_unreachable_rollbacks(self, _mock_token):
        engine = await _create_engine_and_table()
        session = AsyncSession(engine)

        async def finalize(decision, ctx):
            if decision.decision == Decision.PERMIT:
                await session.commit()
            else:
                await session.rollback()
            await session.close()

        tool = _make_tool_with_finalize(finalize)
        context = _make_call_context(tool, {"name": "widget"})
        call_next = AsyncMock()

        pdp = AsyncMock()
        pdp.decide_once.side_effect = ConnectionError("unreachable")
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        with pytest.raises(ConnectionError):
            await middleware.on_call_tool(context, call_next)

        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT name FROM items"))
            rows = result.fetchall()

        assert len(rows) == 0
        await engine.dispose()


@pytest.mark.asyncio
class TestFinalizeCallbackBehavior:
    """Tests for finalize callback semantics (no DB needed)."""

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_finalize_always_called_even_on_exception(self, _mock_token):
        finalize = AsyncMock()
        tool = _make_tool_with_finalize(finalize)
        context = _make_call_context(tool)

        pdp = AsyncMock()
        pdp.decide_once.side_effect = RuntimeError("unexpected")
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        with pytest.raises(RuntimeError, match="unexpected"):
            await middleware.on_call_tool(context, AsyncMock())

        finalize.assert_awaited_once()

    @patch("sapl_fastmcp.middleware._get_token", return_value=None)
    async def test_finalize_exception_logged_original_preserved(self, _mock_token):
        finalize = AsyncMock(side_effect=RuntimeError("finalize boom"))
        tool = _make_tool_with_finalize(finalize)
        context = _make_call_context(tool)
        call_next = AsyncMock()

        pdp = AsyncMock()
        pdp.decide_once.return_value = AuthorizationDecision.deny()
        middleware = SAPLMiddleware(pdp, ConstraintEnforcementService())

        with pytest.raises(AccessDeniedError):
            await middleware.on_call_tool(context, call_next)

        finalize.assert_awaited_once()
