from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

import pytest

from sapl_base.constraint_bundle import AccessDeniedError, StreamingConstraintHandlerBundle
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.pdp_client import PdpClient
from sapl_base.streaming import (
    WARN_ON_STREAM_DENY_FAILED,
    enforce_drop_while_denied,
    enforce_recoverable_if_denied,
    enforce_till_denied,
)
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision


def _make_subscription() -> AuthorizationSubscription:
    return AuthorizationSubscription(subject="user", action="read", resource="data")


def _make_permit() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT)


def _make_deny() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.DENY)


def _make_indeterminate() -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.INDETERMINATE)


def _noop() -> None:
    pass


def _noop_consumer(_value: Any) -> None:
    pass


def _identity(value: Any) -> Any:
    return value


def _always_true(_value: Any) -> bool:
    return True


def _noop_error_handler(_error: Exception) -> None:
    pass


def _identity_error(error: Exception) -> Exception:
    return error


def _noop_method_invocation(_context: Any) -> None:
    pass


def _make_bundle(
    on_next_mappings: Callable[[Any], Any] | None = None,
    on_cancel_handlers: Callable[[], None] | None = None,
    on_decision_handlers: Callable[[], None] | None = None,
    on_next_consumers: Callable[[Any], None] | None = None,
    filter_predicates: Callable[[Any], bool] | None = None,
) -> StreamingConstraintHandlerBundle:
    return StreamingConstraintHandlerBundle(
        on_decision_handlers=on_decision_handlers or _noop,
        method_invocation_handlers=_noop_method_invocation,
        on_next_consumers=on_next_consumers or _noop_consumer,
        on_next_mappings=on_next_mappings or _identity,
        filter_predicates=filter_predicates or _always_true,
        on_error_handlers=_noop_error_handler,
        on_error_mappings=_identity_error,
        on_complete_handlers=_noop,
        on_cancel_handlers=on_cancel_handlers or _noop,
    )


def _make_failing_on_next_bundle() -> StreamingConstraintHandlerBundle:
    """Bundle whose on_next pipeline raises AccessDeniedError."""
    def _fail(value: Any) -> Any:
        raise AccessDeniedError("obligation failed")

    return StreamingConstraintHandlerBundle(
        on_decision_handlers=_noop,
        method_invocation_handlers=_noop_method_invocation,
        on_next_consumers=_noop_consumer,
        on_next_mappings=_fail,
        filter_predicates=_always_true,
        on_error_handlers=_noop_error_handler,
        on_error_mappings=_identity_error,
        on_complete_handlers=_noop,
        on_cancel_handlers=_noop,
    )


async def _decision_stream(*decisions: AuthorizationDecision) -> AsyncIterator[AuthorizationDecision]:
    """Async generator that yields decisions with a small delay between each."""
    for decision in decisions:
        yield decision
        await asyncio.sleep(0)


async def _data_source(*items: Any) -> AsyncIterator[Any]:
    """Async generator that yields data items with a small delay between each."""
    for item in items:
        yield item
        await asyncio.sleep(0)


def _make_pdp_client(decisions: list[AuthorizationDecision]) -> PdpClient:
    """Create a mock PdpClient that yields the given decisions from decide()."""
    pdp_client = MagicMock(spec=PdpClient)

    async def decide(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
        for decision in decisions:
            yield decision
            await asyncio.sleep(0)

    pdp_client.decide = decide
    return pdp_client


def _make_constraint_service(
    bundle: StreamingConstraintHandlerBundle | None = None,
    bundles: list[StreamingConstraintHandlerBundle] | None = None,
    raise_on_resolve: bool = False,
) -> ConstraintEnforcementService:
    """Create a mock ConstraintEnforcementService.

    Args:
        bundle: A single bundle to return for all calls.
        bundles: A list of bundles to return in sequence.
        raise_on_resolve: If True, streaming_bundle_for raises AccessDeniedError.
    """
    service = MagicMock(spec=ConstraintEnforcementService)

    if raise_on_resolve:
        service.streaming_bundle_for.side_effect = AccessDeniedError("unhandled obligation")
    elif bundles is not None:
        service.streaming_bundle_for.side_effect = bundles
    else:
        service.streaming_bundle_for.return_value = bundle or _make_bundle()

    return service


async def _collect(async_iter: AsyncIterator[Any]) -> list[Any]:
    """Collect all items from an async iterator into a list."""
    result = []
    async for item in async_iter:
        result.append(item)
    return result


class TestEnforceTillDenied:
    """EnforceTillDenied: stream until first non-PERMIT, then terminate."""

    async def test_deferred_source_subscription_until_first_permit(self) -> None:
        """Source factory is not called until a PERMIT arrives (REQ-STREAM-DEFER-1)."""
        source_called = False

        async def tracked_source() -> AsyncIterator[Any]:
            nonlocal source_called
            source_called = True
            yield "item"

        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_till_denied(pdp_client, service, _make_subscription(), tracked_source),
        )

        assert source_called is True
        assert result == ["item"]

    async def test_initial_deny_no_data_yielded(self) -> None:
        """If the first decision is DENY, the generator ends without yielding data."""
        source_called = False

        async def tracked_source() -> AsyncIterator[Any]:
            nonlocal source_called
            source_called = True
            yield "never"

        pdp_client = _make_pdp_client([_make_deny()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_till_denied(pdp_client, service, _make_subscription(), tracked_source),
        )

        assert result == []
        assert source_called is False

    async def test_permit_then_deny_stops_stream(self) -> None:
        """Data yielded during PERMIT, stream terminates on DENY transition."""
        decision_event = asyncio.Event()
        deny_decision = _make_deny()

        async def decision_stream(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
            yield _make_permit()
            await asyncio.sleep(0)
            await decision_event.wait()
            yield deny_decision

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = decision_stream

        items_emitted = 0

        async def data_factory() -> AsyncIterator[Any]:
            nonlocal items_emitted
            for i in range(100):
                yield f"item-{i}"
                items_emitted += 1
                if items_emitted == 3:
                    decision_event.set()
                await asyncio.sleep(0)

        service = _make_constraint_service()

        result = await _collect(
            enforce_till_denied(pdp_client, service, _make_subscription(), data_factory),
        )

        assert len(result) >= 1
        assert all(item.startswith("item-") for item in result)

    async def test_permit_flow_data_yielded(self) -> None:
        """Items are yielded when state is PERMITTED."""
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a", "b", "c"),
            ),
        )

        assert result == ["a", "b", "c"]

    async def test_constraint_handlers_applied(self) -> None:
        """Items are transformed by the bundle on_next pipeline."""
        bundle = _make_bundle(on_next_mappings=lambda v: v.upper())
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        result = await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("hello", "world"),
            ),
        )

        assert result == ["HELLO", "WORLD"]

    async def test_on_stream_deny_callback_called(self) -> None:
        """on_stream_deny callback is invoked on initial deny."""
        deny_decision = _make_deny()
        pdp_client = _make_pdp_client([deny_decision])
        service = _make_constraint_service()
        deny_log: list[AuthorizationDecision] = []

        await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("never"),
                on_stream_deny=lambda d: deny_log.append(d),
            ),
        )

        assert deny_log == [deny_decision]

    async def test_on_stream_deny_callback_failure_logged_and_stream_still_terminates(self) -> None:
        """F20: on_stream_deny failure is logged, stream still terminates."""
        pdp_client = _make_pdp_client([_make_deny()])
        service = _make_constraint_service()

        def failing_deny(_decision: AuthorizationDecision) -> None:
            raise RuntimeError("deny callback failed")

        with patch("sapl_base.streaming.log") as mock_log:
            result = await _collect(
                enforce_till_denied(
                    pdp_client,
                    service,
                    _make_subscription(),
                    lambda: _data_source("never"),
                    on_stream_deny=failing_deny,
                ),
            )

        assert result == []
        mock_log.warning.assert_called_with(WARN_ON_STREAM_DENY_FAILED)

    async def test_on_next_handler_failure_terminates_stream(self) -> None:
        """F18: on_next obligation failure terminates the stream."""
        bundle = _make_failing_on_next_bundle()
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        with patch("sapl_base.streaming.log"):
            result = await _collect(
                enforce_till_denied(
                    pdp_client,
                    service,
                    _make_subscription(),
                    lambda: _data_source("a", "b", "c"),
                ),
            )

        assert result == []

    async def test_initial_indeterminate_treated_as_deny(self) -> None:
        """INDETERMINATE is treated the same as DENY."""
        pdp_client = _make_pdp_client([_make_indeterminate()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("never"),
            ),
        )

        assert result == []

    async def test_obligation_resolution_failure_treated_as_deny(self) -> None:
        """If constraint resolution raises AccessDeniedError, treated as deny."""
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(raise_on_resolve=True)

        result = await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("never"),
            ),
        )

        assert result == []


class TestEnforceDropWhileDenied:
    """EnforceDropWhileDenied: silently drop data during deny, resume on permit."""

    async def test_deferred_source_subscription_until_first_permit(self) -> None:
        """Source factory is not called until a PERMIT arrives."""
        source_called = False

        async def tracked_source() -> AsyncIterator[Any]:
            nonlocal source_called
            source_called = True
            yield "item"

        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_drop_while_denied(pdp_client, service, _make_subscription(), tracked_source),
        )

        assert source_called is True
        assert result == ["item"]

    async def test_permit_flow_data_yielded(self) -> None:
        """Items are yielded when state is PERMITTED."""
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_drop_while_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a", "b", "c"),
            ),
        )

        assert result == ["a", "b", "c"]

    async def test_constraint_handlers_applied(self) -> None:
        """Items are transformed by the bundle on_next pipeline."""
        bundle = _make_bundle(on_next_mappings=lambda v: v * 2)
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        result = await _collect(
            enforce_drop_while_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source(1, 2, 3),
            ),
        )

        assert result == [2, 4, 6]

    async def test_permit_deny_permit_cycle_drops_during_deny(self) -> None:
        """Data is dropped during DENY phase and resumes on re-PERMIT."""
        advance_event = asyncio.Event()

        async def decision_stream(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
            yield _make_permit()
            await asyncio.sleep(0)
            await advance_event.wait()
            advance_event.clear()
            yield _make_deny()
            await asyncio.sleep(0)
            await advance_event.wait()
            advance_event.clear()
            yield _make_permit()
            await asyncio.sleep(0)

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = decision_stream

        bundle1 = _make_bundle()
        bundle2 = _make_bundle()
        service = _make_constraint_service(bundles=[bundle1, bundle2])

        items_yielded: list[Any] = []

        async def data_factory() -> AsyncIterator[Any]:
            for i in range(6):
                yield f"item-{i}"
                if i == 1 or i == 3:
                    advance_event.set()
                await asyncio.sleep(0)

        async for item in enforce_drop_while_denied(
            pdp_client, service, _make_subscription(), data_factory,
        ):
            items_yielded.append(item)

        assert "item-0" in items_yielded
        assert "item-1" in items_yielded

    async def test_handler_re_resolution_on_re_permit(self) -> None:
        """A new bundle is created on re-PERMIT (hot-swap)."""
        bundle1 = _make_bundle(on_next_mappings=lambda v: f"{v}-v1")
        bundle2 = _make_bundle(on_next_mappings=lambda v: f"{v}-v2")

        call_count = {"n": 0}

        service = MagicMock(spec=ConstraintEnforcementService)

        def _bundle_for(_decision: AuthorizationDecision) -> StreamingConstraintHandlerBundle:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return bundle1
            return bundle2

        service.streaming_bundle_for.side_effect = _bundle_for

        advance_event = asyncio.Event()

        async def decision_stream(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
            yield _make_permit()
            await asyncio.sleep(0)
            await advance_event.wait()
            advance_event.clear()
            yield _make_deny()
            await asyncio.sleep(0)
            await advance_event.wait()
            advance_event.clear()
            yield _make_permit()
            await asyncio.sleep(0)

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = decision_stream

        items_yielded: list[Any] = []
        item_count = 0

        async def data_factory() -> AsyncIterator[Any]:
            nonlocal item_count
            for i in range(6):
                yield f"item-{i}"
                item_count += 1
                if item_count == 2 or item_count == 4:
                    advance_event.set()
                await asyncio.sleep(0)

        async for item in enforce_drop_while_denied(
            pdp_client, service, _make_subscription(), data_factory,
        ):
            items_yielded.append(item)

        assert service.streaming_bundle_for.call_count == 2

    async def test_on_next_failure_drops_single_element(self) -> None:
        """F18: on_next obligation failure drops one element, stream continues."""
        call_count = {"n": 0}

        def _mapping(value: Any) -> Any:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise AccessDeniedError("obligation failed")
            return value

        bundle = _make_bundle(on_next_mappings=_mapping)
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        with patch("sapl_base.streaming.log"):
            result = await _collect(
                enforce_drop_while_denied(
                    pdp_client,
                    service,
                    _make_subscription(),
                    lambda: _data_source("a", "b", "c"),
                ),
            )

        assert result == ["a", "c"]

    async def test_continuous_deny_all_items_dropped(self) -> None:
        """When never permitted, all items are dropped and stream ends with source."""
        advance_event = asyncio.Event()

        async def decision_stream(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
            yield _make_deny()
            await asyncio.sleep(0)
            await advance_event.wait()
            yield _make_deny()
            await asyncio.sleep(0)

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = decision_stream

        service = _make_constraint_service()

        async def data_factory() -> AsyncIterator[Any]:
            advance_event.set()
            for i in range(3):
                yield f"item-{i}"
                await asyncio.sleep(0)

        result: list[Any] = []
        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.5):
                async for item in enforce_drop_while_denied(
                    pdp_client, service, _make_subscription(), data_factory,
                ):
                    result.append(item)

        assert result == []


class TestEnforceRecoverableIfDenied:
    """EnforceRecoverableIfDenied: suspend on deny with signals, resume on re-permit."""

    async def test_deferred_source_subscription_until_first_permit(self) -> None:
        """Source factory is not called until a PERMIT arrives."""
        source_called = False

        async def tracked_source() -> AsyncIterator[Any]:
            nonlocal source_called
            source_called = True
            yield "item"

        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_recoverable_if_denied(
                pdp_client, service, _make_subscription(), tracked_source,
            ),
        )

        assert source_called is True
        assert result == ["item"]

    async def test_permit_flow_data_yielded(self) -> None:
        """Items are yielded when state is PERMITTED."""
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_recoverable_if_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a", "b", "c"),
            ),
        )

        assert result == ["a", "b", "c"]

    async def test_constraint_handlers_applied(self) -> None:
        """Items are transformed by the bundle on_next pipeline."""
        bundle = _make_bundle(on_next_mappings=lambda v: v.upper())
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        result = await _collect(
            enforce_recoverable_if_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("hello"),
            ),
        )

        assert result == ["HELLO"]

    async def test_on_stream_deny_callback_on_permit_to_deny_transition(self) -> None:
        """on_stream_deny is called on PERMIT->DENY transition."""
        advance_event = asyncio.Event()
        deny_decision = _make_deny()
        deny_log: list[AuthorizationDecision] = []

        async def decision_stream(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
            yield _make_permit()
            await asyncio.sleep(0)
            await advance_event.wait()
            yield deny_decision
            await asyncio.sleep(0)

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = decision_stream
        service = _make_constraint_service()

        item_count = 0

        async def data_factory() -> AsyncIterator[Any]:
            nonlocal item_count
            for i in range(4):
                yield f"item-{i}"
                item_count += 1
                if item_count == 2:
                    advance_event.set()
                await asyncio.sleep(0)

        await _collect(
            enforce_recoverable_if_denied(
                pdp_client,
                service,
                _make_subscription(),
                data_factory,
                on_stream_deny=lambda d: deny_log.append(d),
            ),
        )

        assert len(deny_log) >= 1
        assert deny_log[0] is deny_decision

    async def test_on_stream_recover_callback_on_deny_to_permit_transition(self) -> None:
        """on_stream_recover is called on DENY->PERMIT transition."""
        advance_event = asyncio.Event()
        advance_event_2 = asyncio.Event()
        recover_decision = _make_permit()
        recover_log: list[AuthorizationDecision] = []

        async def decision_stream(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
            yield _make_permit()
            await asyncio.sleep(0)
            await advance_event.wait()
            advance_event.clear()
            yield _make_deny()
            await asyncio.sleep(0)
            await advance_event_2.wait()
            yield recover_decision
            await asyncio.sleep(0)

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = decision_stream

        bundle1 = _make_bundle()
        bundle2 = _make_bundle()
        service = _make_constraint_service(bundles=[bundle1, bundle2])

        item_count = 0

        async def data_factory() -> AsyncIterator[Any]:
            nonlocal item_count
            for i in range(6):
                yield f"item-{i}"
                item_count += 1
                if item_count == 1:
                    advance_event.set()
                elif item_count == 3:
                    advance_event_2.set()
                await asyncio.sleep(0)

        await _collect(
            enforce_recoverable_if_denied(
                pdp_client,
                service,
                _make_subscription(),
                data_factory,
                on_stream_recover=lambda d: recover_log.append(d),
            ),
        )

        assert len(recover_log) >= 1

    async def test_signal_callback_failure_logged_state_transition_still_happens(self) -> None:
        """F20: signal callback failure is logged, state transition still happens."""
        pdp_client = _make_pdp_client([_make_deny()])
        service = _make_constraint_service()

        def failing_deny(_decision: AuthorizationDecision) -> None:
            raise RuntimeError("deny callback failed")

        with patch("sapl_base.streaming.log") as mock_log:
            result = await _collect(
                enforce_recoverable_if_denied(
                    pdp_client,
                    service,
                    _make_subscription(),
                    lambda: _data_source("never"),
                    on_stream_deny=failing_deny,
                ),
            )

        assert result == []
        mock_log.warning.assert_called_with(WARN_ON_STREAM_DENY_FAILED)

    async def test_on_next_failure_drops_element_no_state_change(self) -> None:
        """F18: on_next obligation failure drops element, no state transition."""
        call_count = {"n": 0}

        def _mapping(value: Any) -> Any:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise AccessDeniedError("obligation failed")
            return value

        bundle = _make_bundle(on_next_mappings=_mapping)
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        with patch("sapl_base.streaming.log"):
            result = await _collect(
                enforce_recoverable_if_denied(
                    pdp_client,
                    service,
                    _make_subscription(),
                    lambda: _data_source("a", "b", "c"),
                ),
            )

        assert result == ["a", "c"]

    async def test_initial_deny_calls_on_stream_deny(self) -> None:
        """Initial DENY calls on_stream_deny and generator ends."""
        deny_decision = _make_deny()
        deny_log: list[AuthorizationDecision] = []

        pdp_client = _make_pdp_client([deny_decision])
        service = _make_constraint_service()

        result = await _collect(
            enforce_recoverable_if_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("never"),
                on_stream_deny=lambda d: deny_log.append(d),
            ),
        )

        assert result == []
        assert len(deny_log) == 1
        assert deny_log[0] is deny_decision

    async def test_deny_signal_yielded_when_callback_returns_value(self) -> None:
        """When on_stream_deny returns a value, it is yielded to the consumer."""
        pdp_client = _make_pdp_client([_make_deny()])
        service = _make_constraint_service()

        result = await _collect(
            enforce_recoverable_if_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("never"),
                on_stream_deny=lambda _d: "DENIED_SIGNAL",
            ),
        )

        assert "DENIED_SIGNAL" in result

    async def test_recover_signal_yielded_when_callback_returns_value(self) -> None:
        """When on_stream_recover returns a value, it is yielded to the consumer."""
        advance_event = asyncio.Event()
        advance_event_2 = asyncio.Event()

        async def decision_stream(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
            yield _make_permit()
            await asyncio.sleep(0)
            await advance_event.wait()
            advance_event.clear()
            yield _make_deny()
            await asyncio.sleep(0)
            await advance_event_2.wait()
            yield _make_permit()
            await asyncio.sleep(0)

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = decision_stream

        bundle1 = _make_bundle()
        bundle2 = _make_bundle()
        service = _make_constraint_service(bundles=[bundle1, bundle2])

        item_count = 0

        async def data_factory() -> AsyncIterator[Any]:
            nonlocal item_count
            for i in range(6):
                yield f"item-{i}"
                item_count += 1
                if item_count == 1:
                    advance_event.set()
                elif item_count == 3:
                    advance_event_2.set()
                await asyncio.sleep(0)

        result = await _collect(
            enforce_recoverable_if_denied(
                pdp_client,
                service,
                _make_subscription(),
                data_factory,
                on_stream_deny=lambda _d: "DENY_SIGNAL",
                on_stream_recover=lambda _d: "RECOVER_SIGNAL",
            ),
        )

        assert "item-0" in result


class TestTeardown:
    """Teardown: ON_CANCEL handlers execute when generator closes."""

    async def test_on_cancel_executed_on_normal_completion(self) -> None:
        """ON_CANCEL handlers are called when the stream completes normally."""
        cancel_log: list[str] = []
        bundle = _make_bundle(on_cancel_handlers=lambda: cancel_log.append("cancelled"))
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a"),
            ),
        )

        assert cancel_log == ["cancelled"]

    async def test_on_cancel_executed_on_deny_termination(self) -> None:
        """ON_CANCEL handlers are called when stream terminates due to deny."""
        cancel_log: list[str] = []
        bundle = _make_bundle(on_cancel_handlers=lambda: cancel_log.append("cancelled"))

        async def decision_stream(_sub: AuthorizationSubscription) -> AsyncIterator[AuthorizationDecision]:
            yield _make_permit()
            await asyncio.sleep(0)
            yield _make_deny()
            await asyncio.sleep(0)

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = decision_stream
        service = _make_constraint_service(bundle=bundle)

        await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a", "b"),
            ),
        )

        assert cancel_log == ["cancelled"]

    async def test_on_cancel_executed_for_drop_while_denied(self) -> None:
        """ON_CANCEL handlers are called for DropWhileDenied on normal completion."""
        cancel_log: list[str] = []
        bundle = _make_bundle(on_cancel_handlers=lambda: cancel_log.append("cancelled"))
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        await _collect(
            enforce_drop_while_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a"),
            ),
        )

        assert cancel_log == ["cancelled"]

    async def test_on_cancel_executed_for_recoverable_if_denied(self) -> None:
        """ON_CANCEL handlers are called for RecoverableIfDenied on normal completion."""
        cancel_log: list[str] = []
        bundle = _make_bundle(on_cancel_handlers=lambda: cancel_log.append("cancelled"))
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        await _collect(
            enforce_recoverable_if_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a"),
            ),
        )

        assert cancel_log == ["cancelled"]

    async def test_on_cancel_failure_does_not_propagate(self) -> None:
        """ON_CANCEL handler failure is suppressed and does not propagate."""
        def failing_cancel() -> None:
            raise RuntimeError("cancel failed")

        bundle = _make_bundle(on_cancel_handlers=failing_cancel)
        pdp_client = _make_pdp_client([_make_permit()])
        service = _make_constraint_service(bundle=bundle)

        result = await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a"),
            ),
        )

        assert result == ["a"]

    async def test_decision_task_cancelled_on_teardown(self) -> None:
        """The PDP decision background task is cancelled during teardown."""
        stalled = asyncio.Event()

        async def stalling_decision_stream(
            _sub: AuthorizationSubscription,
        ) -> AsyncIterator[AuthorizationDecision]:
            yield _make_permit()
            await asyncio.sleep(0)
            await stalled.wait()

        pdp_client = MagicMock(spec=PdpClient)
        pdp_client.decide = stalling_decision_stream
        service = _make_constraint_service()

        result = await _collect(
            enforce_till_denied(
                pdp_client,
                service,
                _make_subscription(),
                lambda: _data_source("a"),
            ),
        )

        assert result == ["a"]
