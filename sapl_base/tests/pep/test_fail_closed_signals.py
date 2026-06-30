"""Fail-closed obligation enforcement on the error path and unconditional
input-signal handling during pre-invocation enforcement.

These scenarios pin the Spring PEP contract (EnforcementPlan.java):

- The error path is itself fail-closed. When the protected method raises,
  the error-signal handlers run and a failing error-signal OBLIGATION
  escalates to a fresh AccessDeniedError, while an error MAPPER that returns
  a replacement exception sanitises the throwable before it reaches the
  caller (BP-12 / R19 / A18).
- Pre-invocation enforcement fires the decision signal AND the input signal
  unconditionally, and only afterwards denies. Input-level handlers therefore
  run even when the decision denies or a decision-signal obligation already
  failed (BP-09 / R16 / A11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sapl_base.pep import (
    DECISION,
    ERROR,
    INPUT,
    AccessDeniedError,
    EnforcementPlanner,
    ScopedHandler,
)
from sapl_base.pep.enforce import pre_enforce, pre_enforce_blocking
from sapl_base.types import (
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence


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


class SanitizedError(Exception):
    """Replacement exception a policy mandates to hide internal error detail."""


class _FailingErrorObligationProvider:
    """An ERROR-signal obligation whose audit handler itself fails."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "error-audit":
            return ()

        def _fail(_error: BaseException) -> None:
            raise RuntimeError("audit-on-error failed")

        return (ScopedHandler(signal=ERROR, priority=0, shape="consumer", handler=_fail),)


class _SanitizingErrorMapperProvider:
    """An ERROR-signal obligation that replaces the raised exception."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "sanitize-error":
            return ()
        return (
            ScopedHandler(
                signal=ERROR,
                priority=0,
                shape="mapper",
                handler=lambda _error: SanitizedError("sanitized"),
            ),
        )


class _FailingDecisionObligationProvider:
    """A DECISION-signal obligation runner that fails."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "decision-fail":
            return ()

        def _fail() -> None:
            raise RuntimeError("decision audit failed")

        return (ScopedHandler(signal=DECISION, priority=0, shape="runner", handler=_fail),)


class _RecordingInputConsumerProvider:
    """An INPUT-signal obligation consumer that records the attempted call."""

    def __init__(self) -> None:
        self.seen: list[Any] = []

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "input-audit":
            return ()
        return (
            ScopedHandler(
                signal=INPUT,
                priority=0,
                shape="consumer",
                handler=lambda value: self.seen.append(value),
            ),
        )


async def _identity(*args: Any, **kwargs: Any) -> Any:
    return args[0] if args else kwargs


def _identity_sync(*args: Any, **kwargs: Any) -> Any:
    return args[0] if args else kwargs


async def _raises_boom() -> None:
    raise RuntimeError("boom")


def _raises_boom_sync() -> None:
    raise RuntimeError("boom")


def _subscription() -> AuthorizationSubscription:
    return AuthorizationSubscription(subject="alice", action="read", resource="doc-1")


@pytest.mark.asyncio
class TestErrorSignalIsFailClosed:
    async def test_failing_error_obligation_escalates_to_access_denied(self) -> None:
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "error-audit"},))
        )
        decided = pre_enforce(
            _raises_boom,
            pdp_client=pdp,
            planner=EnforcementPlanner(providers=[_FailingErrorObligationProvider()]),
            subscription=_subscription(),
        )
        await self._assert_access_denied(decided)

    async def test_error_mapper_replaces_exception_to_sanitize_detail(self) -> None:
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "sanitize-error"},))
        )
        decided = pre_enforce(
            _raises_boom,
            pdp_client=pdp,
            planner=EnforcementPlanner(providers=[_SanitizingErrorMapperProvider()]),
            subscription=_subscription(),
        )
        with pytest.raises(SanitizedError, match="sanitized"):
            await decided

    @staticmethod
    async def _assert_access_denied(awaitable: Any) -> None:
        with pytest.raises(AccessDeniedError):
            await awaitable


class TestErrorSignalIsFailClosedBlocking:
    def test_failing_error_obligation_escalates_to_access_denied(self) -> None:
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "error-audit"},))
        )
        with pytest.raises(AccessDeniedError):
            pre_enforce_blocking(
                _raises_boom_sync,
                pdp_client=pdp,
                planner=EnforcementPlanner(providers=[_FailingErrorObligationProvider()]),
                subscription=_subscription(),
            )

    def test_error_mapper_replaces_exception_to_sanitize_detail(self) -> None:
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.PERMIT, obligations=({"type": "sanitize-error"},))
        )
        with pytest.raises(SanitizedError, match="sanitized"):
            pre_enforce_blocking(
                _raises_boom_sync,
                pdp_client=pdp,
                planner=EnforcementPlanner(providers=[_SanitizingErrorMapperProvider()]),
                subscription=_subscription(),
            )


@pytest.mark.asyncio
class TestPreInvocationRunsInputBeforeDenying:
    async def test_input_handlers_run_when_decision_obligation_fails(self) -> None:
        recorder = _RecordingInputConsumerProvider()
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(
                decision=Decision.PERMIT,
                obligations=({"type": "decision-fail"}, {"type": "input-audit"}),
            )
        )
        decided = pre_enforce(
            _identity,
            pdp_client=pdp,
            planner=EnforcementPlanner(
                providers=[_FailingDecisionObligationProvider(), recorder]
            ),
            subscription=_subscription(),
            args=("payload",),
        )
        with pytest.raises(AccessDeniedError):
            await decided
        assert len(recorder.seen) == 1

    async def test_input_handlers_run_when_decision_denies(self) -> None:
        recorder = _RecordingInputConsumerProvider()
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.DENY, obligations=({"type": "input-audit"},))
        )
        decided = pre_enforce(
            _identity,
            pdp_client=pdp,
            planner=EnforcementPlanner(providers=[recorder]),
            subscription=_subscription(),
            args=("payload",),
        )
        with pytest.raises(AccessDeniedError):
            await decided
        assert len(recorder.seen) == 1


class TestPreInvocationRunsInputBeforeDenyingBlocking:
    def test_input_handlers_run_when_decision_obligation_fails(self) -> None:
        recorder = _RecordingInputConsumerProvider()
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(
                decision=Decision.PERMIT,
                obligations=({"type": "decision-fail"}, {"type": "input-audit"}),
            )
        )
        with pytest.raises(AccessDeniedError):
            pre_enforce_blocking(
                _identity_sync,
                pdp_client=pdp,
                planner=EnforcementPlanner(
                    providers=[_FailingDecisionObligationProvider(), recorder]
                ),
                subscription=_subscription(),
                args=("payload",),
            )
        assert len(recorder.seen) == 1

    def test_input_handlers_run_when_decision_denies(self) -> None:
        recorder = _RecordingInputConsumerProvider()
        pdp = _ScriptedPdpClient(
            AuthorizationDecision(decision=Decision.DENY, obligations=({"type": "input-audit"},))
        )
        with pytest.raises(AccessDeniedError):
            pre_enforce_blocking(
                _identity_sync,
                pdp_client=pdp,
                planner=EnforcementPlanner(providers=[recorder]),
                subscription=_subscription(),
                args=("payload",),
            )
        assert len(recorder.seen) == 1
