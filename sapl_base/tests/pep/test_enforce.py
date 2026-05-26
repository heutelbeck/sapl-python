from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from sapl_base.pep import (
    DECISION,
    ERROR,
    INPUT,
    OUTPUT,
    AccessDeniedError,
    EnforcementPlanner,
    ScopedHandler,
)
from sapl_base.pep.enforce import post_enforce, pre_enforce
from sapl_base.types import (
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
    IdentifiableAuthorizationDecision,
)


class _ScriptedPdpClient:
    """Test double: returns a canned decision on `decide_once`."""

    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision

    async def multi_decide_all_once(self, _: Any) -> MultiAuthorizationDecision:
        return MultiAuthorizationDecision()

    def decide(self, _: Any) -> AsyncIterator[AuthorizationDecision]:
        async def _gen() -> AsyncIterator[AuthorizationDecision]:
            yield self._decision
        return _gen()

    def multi_decide(self, _: Any) -> AsyncIterator[IdentifiableAuthorizationDecision]:
        async def _gen() -> AsyncIterator[IdentifiableAuthorizationDecision]:
            return
            yield  # pragma: no cover
        return _gen()

    def multi_decide_all(self, _: Any) -> AsyncIterator[MultiAuthorizationDecision]:
        async def _gen() -> AsyncIterator[MultiAuthorizationDecision]:
            return
            yield  # pragma: no cover
        return _gen()

    async def close(self) -> None:
        return None


class _UppercaseProvider:
    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "uppercase":
            return ()
        return (
            ScopedHandler(
                signal=OUTPUT,
                priority=0,
                shape="mapper",
                handler=lambda value: value.upper() if isinstance(value, str) else value,
            ),
        )


class _AuditProvider:
    def __init__(self) -> None:
        self.invocations: list[Any] = []

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "audit":
            return ()
        return (
            ScopedHandler(
                signal=DECISION,
                priority=0,
                shape="runner",
                handler=lambda: self.invocations.append(constraint),
            ),
        )


class _RejectFirstArgProvider:
    """Drop the first positional argument before calling the method."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "drop-first":
            return ()
        return (
            ScopedHandler(
                signal=INPUT,
                priority=0,
                shape="mapper",
                handler=lambda value: (value[0][1:], value[1]),
            ),
        )


async def _identity(*args: Any, **kwargs: Any) -> Any:
    return args[0] if args else kwargs


async def _raises_runtime() -> None:
    raise RuntimeError("boom")


def _subscription() -> AuthorizationSubscription:
    return AuthorizationSubscription(subject="alice", action="read", resource="doc-1")


@pytest.mark.asyncio
class TestPreEnforce:
    async def test_permit_no_constraints_returns_method_result(self) -> None:
        pdp = _ScriptedPdpClient(AuthorizationDecision(decision=Decision.PERMIT))
        result = await pre_enforce(
            _identity,
            pdp_client=pdp,
            planner=EnforcementPlanner(),
            subscription=_subscription(),
            args=("hello",),
        )
        assert result == "hello"

    async def test_deny_raises_access_denied_error(self) -> None:
        pdp = _ScriptedPdpClient(AuthorizationDecision(decision=Decision.DENY))
        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                _identity,
                pdp_client=pdp,
                planner=EnforcementPlanner(),
                subscription=_subscription(),
            )

    async def test_indeterminate_raises_access_denied(self) -> None:
        pdp = _ScriptedPdpClient(AuthorizationDecision(decision=Decision.INDETERMINATE))
        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                _identity, pdp_client=pdp, planner=EnforcementPlanner(),
                subscription=_subscription()
            )

    async def test_output_mapper_transforms_return_value(self) -> None:
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "uppercase"},))
        )
        result = await pre_enforce(
            _identity,
            pdp_client=pdp,
            planner=EnforcementPlanner(providers=[_UppercaseProvider()]),
            subscription=_subscription(),
            args=("hello",),
        )
        assert result == "HELLO"

    async def test_input_mapper_transforms_args_before_invocation(self) -> None:
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "drop-first"},))
        )
        result = await pre_enforce(
            _identity,
            pdp_client=pdp,
            planner=EnforcementPlanner(providers=[_RejectFirstArgProvider()]),
            subscription=_subscription(),
            args=("admin", "real-payload"),
        )
        assert result == "real-payload"

    async def test_decision_obligation_failure_denies(self) -> None:
        def _fails() -> None:
            raise RuntimeError("audit dropped")

        class _FailingAudit:
            def get_handlers(self, c: Any) -> Sequence[ScopedHandler]:
                if not isinstance(c, dict) or c.get("type") != "audit":
                    return ()
                return (ScopedHandler(DECISION, 0, "runner", _fails),)

        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "audit"},))
        )
        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                _identity,
                pdp_client=pdp,
                planner=EnforcementPlanner(providers=[_FailingAudit()]),
                subscription=_subscription(),
                args=("x",),
            )

    async def test_method_exception_runs_error_signal_handlers_then_propagates(self) -> None:
        seen: list[BaseException] = []

        class _ErrorObserver:
            def get_handlers(self, c: Any) -> Sequence[ScopedHandler]:
                if not isinstance(c, dict) or c.get("type") != "error-log":
                    return ()
                return (
                    ScopedHandler(
                        signal=ERROR,
                        priority=0,
                        shape="consumer",
                        handler=lambda e: seen.append(e),
                    ),
                )

        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "error-log"},))
        )
        with pytest.raises(RuntimeError, match="boom"):
            await pre_enforce(
                _raises_runtime,
                pdp_client=pdp,
                planner=EnforcementPlanner(providers=[_ErrorObserver()]),
                subscription=_subscription(),
            )
        assert len(seen) == 1
        assert isinstance(seen[0], RuntimeError)

    async def test_decision_runner_runs_before_method(self) -> None:
        audit = _AuditProvider()
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "audit"},))
        )
        await pre_enforce(
            _identity,
            pdp_client=pdp,
            planner=EnforcementPlanner(providers=[audit]),
            subscription=_subscription(),
            args=("hi",),
        )
        assert len(audit.invocations) == 1


@pytest.mark.asyncio
class TestPostEnforce:
    async def test_method_runs_before_pdp_decision_in_post(self) -> None:
        invoked = []

        async def _producer() -> str:
            invoked.append("ran")
            return "data"

        pdp = _ScriptedPdpClient(AuthorizationDecision(decision=Decision.PERMIT))
        result = await post_enforce(
            _producer,
            pdp_client=pdp,
            planner=EnforcementPlanner(),
            subscription_builder=lambda _: _subscription(),
        )
        assert invoked == ["ran"]
        assert result == "data"

    async def test_post_enforce_deny_raises(self) -> None:
        async def _producer() -> str:
            return "data"

        pdp = _ScriptedPdpClient(AuthorizationDecision(decision=Decision.DENY))
        with pytest.raises(AccessDeniedError):
            await post_enforce(
                _producer,
                pdp_client=pdp,
                planner=EnforcementPlanner(),
                subscription_builder=lambda _: _subscription(),
            )

    async def test_post_enforce_output_mapper_transforms_result(self) -> None:
        async def _producer() -> str:
            return "secret"

        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "uppercase"},))
        )
        result = await post_enforce(
            _producer,
            pdp_client=pdp,
            planner=EnforcementPlanner(providers=[_UppercaseProvider()]),
            subscription_builder=lambda r: AuthorizationSubscription(
                subject="alice", action="read", resource=r
            ),
        )
        assert result == "SECRET"

    async def test_post_enforce_subscription_builder_receives_method_result(self) -> None:
        captured: list[Any] = []

        async def _producer() -> int:
            return 42

        pdp = _ScriptedPdpClient(AuthorizationDecision(decision=Decision.PERMIT))

        def _builder(r: Any) -> AuthorizationSubscription:
            captured.append(r)
            return _subscription()

        await post_enforce(
            _producer,
            pdp_client=pdp,
            planner=EnforcementPlanner(),
            subscription_builder=_builder,
        )
        assert captured == [42]
