"""Tests for sapl_fastmcp.auth_check module."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sapl_base import AuthorizationDecision, Decision
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_fastmcp.auth_check import WARN_STEALTH_IGNORED, sapl
from sapl_fastmcp.context import SaplConfig
from tests.conftest import make_auth_ctx as _make_ctx
from tests.conftest import make_token as _make_token


def _make_decision(
    decision=Decision.PERMIT,
    obligations=(),
    advice=(),
    has_resource=False,
):
    d = MagicMock(spec=AuthorizationDecision)
    d.decision = decision
    d.obligations = list(obligations)
    d.advice = list(advice)
    d.has_resource = has_resource
    return d


def _patched_sapl(decision):
    """Context manager that patches PDP client and constraint service."""
    pdp = AsyncMock()
    pdp.decide_once.return_value = decision
    service = ConstraintEnforcementService()

    class _PatchedSaplCtx:
        def __init__(self):
            self.pdp = pdp

        def __enter__(self):
            self._p1 = patch("sapl_fastmcp.get_pdp_client", return_value=pdp)
            self._p2 = patch("sapl_fastmcp.get_constraint_service", return_value=service)
            self._p1.__enter__()
            self._p2.__enter__()
            return self

        def __exit__(self, *args):
            self._p2.__exit__(*args)
            self._p1.__exit__(*args)

    return _PatchedSaplCtx()


class TestSaplAuthCheck:
    """Tests for the sapl() auth check."""

    @pytest.mark.asyncio
    async def test_permit_returns_true(self):
        with _patched_sapl(_make_decision()):
            result = await sapl()(_make_ctx(token=_make_token(claims={"sub": "alice"})))
        assert result is True

    @pytest.mark.asyncio
    async def test_deny_returns_false(self):
        with _patched_sapl(_make_decision(decision=Decision.DENY)):
            result = await sapl()(_make_ctx(token=_make_token(claims={"sub": "alice"})))
        assert result is False

    @pytest.mark.asyncio
    async def test_overrides_passed_to_subscription(self):
        with _patched_sapl(_make_decision()) as env:
            await sapl(subject="bob", action="read", resource="patients")(_make_ctx())

        sub = env.pdp.decide_once.call_args[0][0]
        assert sub.subject == "bob"
        assert sub.action == "read"
        assert sub.resource == "patients"

    @pytest.mark.asyncio
    async def test_callable_overrides(self):
        with _patched_sapl(_make_decision()) as env:
            ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
            await sapl(action=lambda ctx: "custom_action")(ctx)

        assert env.pdp.decide_once.call_args[0][0].action == "custom_action"

    @pytest.mark.asyncio
    async def test_permit_with_failed_constraints_returns_false(self):
        decision = _make_decision(obligations=[{"type": "unhandled"}])
        with _patched_sapl(decision):
            ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
            result = await sapl()(ctx)
        assert result is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "decision_value",
        [Decision.INDETERMINATE, Decision.NOT_APPLICABLE],
        ids=["indeterminate", "not-applicable"],
    )
    async def test_non_permit_non_deny_returns_false_with_warning(
        self, decision_value, caplog
    ):
        with _patched_sapl(_make_decision(decision=decision_value)):
            ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
            with caplog.at_level(logging.WARNING, logger="sapl.mcp"):
                result = await sapl()(ctx)
        assert result is False
        assert "no matching policy" in caplog.text

    @pytest.mark.asyncio
    async def test_raises_when_not_configured(self):
        check = sapl()
        ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
        with pytest.raises(RuntimeError, match="SAPL not configured"):
            await check(ctx)

    @pytest.mark.asyncio
    async def test_warns_when_stealth_set_on_component(self, caplog):
        ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
        ctx.component.fn.__sapl__ = SaplConfig(mode="pre", stealth=True)
        with _patched_sapl(_make_decision()), caplog.at_level(logging.WARNING, logger="sapl.mcp"):
            await sapl()(ctx)
        assert WARN_STEALTH_IGNORED % "test_tool" in caplog.text

    @pytest.mark.asyncio
    async def test_no_stealth_warning_when_stealth_false(self, caplog):
        ctx = _make_ctx(token=_make_token(claims={"sub": "alice"}))
        ctx.component.fn.__sapl__ = SaplConfig(mode="pre", stealth=False)
        with _patched_sapl(_make_decision()), caplog.at_level(logging.WARNING, logger="sapl.mcp"):
            await sapl()(ctx)
        assert "stealth" not in caplog.text
