from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

import structlog

from sapl_base.constraint_bundle import AccessDeniedError, StreamingConstraintHandlerBundle
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision

if TYPE_CHECKING:
    from sapl_base.constraint_engine import ConstraintEnforcementService
    from sapl_base.pdp_client import PdpClient

log = structlog.get_logger()

ERROR_ACCESS_DENIED_STREAMING = "Access denied in streaming enforcement"
ERROR_OBLIGATION_FAILED_STREAMING = "Obligation handler failed during streaming enforcement"
ERROR_STREAM_TERMINATED = "Stream terminated due to access denial"
WARN_BEST_EFFORT_FAILED = "Best-effort handlers failed on streaming deny path"
WARN_ON_NEXT_HANDLER_FAILED = "On-next handler failed for stream element"
WARN_ON_STREAM_DENY_FAILED = "onStreamDeny callback raised an exception"
WARN_ON_STREAM_RECOVER_FAILED = "onStreamRecover callback raised an exception"


DataSourceFactory = Callable[[], AsyncIterator[Any]]


async def _open_data_source(factory: DataSourceFactory) -> AsyncIterator[Any]:
    """Open a data source, awaiting if the factory returns a coroutine.

    Framework decorators wrap view functions in ``async def data_source()``
    closures. Calling such a closure returns a coroutine that must be awaited
    to obtain the underlying async iterator. Plain factories (e.g. lambdas
    in tests) return async iterators directly.
    """
    result = factory()
    if asyncio.iscoroutine(result):
        result = await result
    return result


class _StreamState(Enum):
    INITIAL = auto()
    PERMITTED = auto()
    DENIED = auto()
    TERMINATED = auto()


def _run_best_effort_on_deny(
    constraint_service: ConstraintEnforcementService,
    decision: AuthorizationDecision,
) -> None:
    """Run best-effort constraint handlers on a streaming deny path."""
    try:
        best_effort_bundle = constraint_service.streaming_best_effort_bundle_for(decision)
        best_effort_bundle.handle_on_decision_constraints()
    except Exception:
        log.warning(WARN_BEST_EFFORT_FAILED)


def _safe_call_deny(
    callback: Callable[[AuthorizationDecision], Any],
    decision: AuthorizationDecision,
) -> Any:
    """Call an on_stream_deny callback, logging and suppressing exceptions."""
    try:
        return callback(decision)
    except Exception:
        log.warning(WARN_ON_STREAM_DENY_FAILED)
        return None


def _safe_call_recover(
    callback: Callable[[AuthorizationDecision], Any],
    decision: AuthorizationDecision,
) -> Any:
    """Call an on_stream_recover callback, logging and suppressing exceptions."""
    try:
        return callback(decision)
    except Exception:
        log.warning(WARN_ON_STREAM_RECOVER_FAILED)
        return None


async def enforce_till_denied(
    pdp_client: PdpClient,
    constraint_service: ConstraintEnforcementService,
    subscription: AuthorizationSubscription,
    data_source: DataSourceFactory,
    on_stream_deny: Callable[[AuthorizationDecision], Any] | None = None,
) -> AsyncIterator[Any]:
    """EnforceTillDenied: stream until first non-PERMIT, then terminate.

    Section 7.3:
    - Deferred: source not subscribed until first PERMIT (REQ-STREAM-DEFER-1)
    - On PERMIT: resolve handlers, forward filtered/mapped data
    - On non-PERMIT: execute on_stream_deny callback, terminate stream
    - On-next obligation failure (F18): terminate with error (REQ-ERROR-5)
    - Teardown: ON_CANCEL -> unsubscribe PDP -> unsubscribe source
    """
    state = _StreamState.INITIAL
    bundle: StreamingConstraintHandlerBundle | None = None
    current_decision: AuthorizationDecision | None = None
    decision_event = asyncio.Event()

    async def _consume_decisions() -> None:
        nonlocal state, bundle, current_decision
        async for decision in pdp_client.decide(subscription):
            current_decision = decision
            if decision.decision == Decision.PERMIT:
                try:
                    bundle = constraint_service.streaming_bundle_for(decision)
                    bundle.handle_on_decision_constraints()
                    if state == _StreamState.INITIAL:
                        state = _StreamState.PERMITTED
                except AccessDeniedError:
                    _run_best_effort_on_deny(constraint_service, decision)
                    state = _StreamState.TERMINATED
                    decision_event.set()
                    return
            else:
                _run_best_effort_on_deny(constraint_service, decision)
                state = _StreamState.TERMINATED
            decision_event.set()
            if state == _StreamState.TERMINATED:
                return

    decision_task: asyncio.Task[None] | None = None
    source_iterator: AsyncIterator[Any] | None = None

    try:
        decision_task = asyncio.create_task(_consume_decisions())

        await decision_event.wait()
        decision_event.clear()

        if state != _StreamState.PERMITTED:
            if on_stream_deny and current_decision:
                _safe_call_deny(on_stream_deny, current_decision)
            return

        source_iterator = (await _open_data_source(data_source)).__aiter__()

        async for item in source_iterator:
            if decision_event.is_set():
                decision_event.clear()

            if state == _StreamState.TERMINATED:
                if on_stream_deny and current_decision:
                    _safe_call_deny(on_stream_deny, current_decision)
                return

            try:
                if bundle:
                    transformed = bundle.handle_all_on_next_constraints(item)
                    yield transformed
            except AccessDeniedError:
                log.warning(WARN_ON_NEXT_HANDLER_FAILED)
                return

        if decision_event.is_set():
            decision_event.clear()
            if state == _StreamState.TERMINATED and on_stream_deny and current_decision:
                _safe_call_deny(on_stream_deny, current_decision)

    finally:
        if bundle:
            with contextlib.suppress(Exception):
                bundle.handle_on_cancel_constraints()
        if decision_task and not decision_task.done():
            decision_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await decision_task


async def enforce_drop_while_denied(
    pdp_client: PdpClient,
    constraint_service: ConstraintEnforcementService,
    subscription: AuthorizationSubscription,
    data_source: DataSourceFactory,
) -> AsyncIterator[Any]:
    """EnforceDropWhileDenied: silently drop data during deny, resume on permit.

    Section 7.4:
    - Deferred: source not subscribed until first PERMIT
    - On PERMIT: resolve handlers, forward data
    - On non-PERMIT: silently drop data items (no callback, no error)
    - On-next obligation failure (F18): drop single element, continue
    - Re-PERMIT: re-resolve handlers, resume forwarding
    """
    state = _StreamState.INITIAL
    bundle: StreamingConstraintHandlerBundle | None = None
    decision_event = asyncio.Event()

    async def _consume_decisions() -> None:
        nonlocal state, bundle
        async for decision in pdp_client.decide(subscription):
            if decision.decision == Decision.PERMIT:
                try:
                    bundle = constraint_service.streaming_bundle_for(decision)
                    bundle.handle_on_decision_constraints()
                    state = _StreamState.PERMITTED
                except AccessDeniedError:
                    _run_best_effort_on_deny(constraint_service, decision)
                    state = _StreamState.DENIED
                    bundle = None
            else:
                _run_best_effort_on_deny(constraint_service, decision)
                state = _StreamState.DENIED
                bundle = None
            decision_event.set()

    decision_task: asyncio.Task[None] | None = None
    source_iterator: AsyncIterator[Any] | None = None

    try:
        decision_task = asyncio.create_task(_consume_decisions())

        await decision_event.wait()
        decision_event.clear()

        if state != _StreamState.PERMITTED:
            await decision_event.wait()
            decision_event.clear()
            if state != _StreamState.PERMITTED:
                return

        source_iterator = (await _open_data_source(data_source)).__aiter__()

        async for item in source_iterator:
            if decision_event.is_set():
                decision_event.clear()

            if state != _StreamState.PERMITTED:
                continue

            try:
                if bundle:
                    transformed = bundle.handle_all_on_next_constraints(item)
                    yield transformed
            except AccessDeniedError:
                log.warning(WARN_ON_NEXT_HANDLER_FAILED)
                continue

    finally:
        if bundle:
            with contextlib.suppress(Exception):
                bundle.handle_on_cancel_constraints()
        if decision_task and not decision_task.done():
            decision_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await decision_task


async def enforce_recoverable_if_denied(
    pdp_client: PdpClient,
    constraint_service: ConstraintEnforcementService,
    subscription: AuthorizationSubscription,
    data_source: DataSourceFactory,
    on_stream_deny: Callable[[AuthorizationDecision], Any] | None = None,
    on_stream_recover: Callable[[AuthorizationDecision], Any] | None = None,
) -> AsyncIterator[Any]:
    """EnforceRecoverableIfDenied: suspend on deny with signals, resume on re-permit.

    Section 7.5:
    - Deferred: source not subscribed until first PERMIT
    - On PERMIT: resolve handlers, forward data
    - On PERMIT->DENY transition: call on_stream_deny (REQ-ACCESS-VISIBILITY-1)
    - On DENY->PERMIT transition: call on_stream_recover
    - On-next obligation failure (F18): drop element, no deny transition
    - Signals emitted immediately (not deferred)
    """
    state = _StreamState.INITIAL
    bundle: StreamingConstraintHandlerBundle | None = None
    current_decision: AuthorizationDecision | None = None
    decision_event = asyncio.Event()
    signal_queue: asyncio.Queue[tuple[str, AuthorizationDecision]] = asyncio.Queue()

    async def _consume_decisions() -> None:
        nonlocal state, bundle, current_decision
        async for decision in pdp_client.decide(subscription):
            current_decision = decision
            previous_state = state
            if decision.decision == Decision.PERMIT:
                try:
                    bundle = constraint_service.streaming_bundle_for(decision)
                    bundle.handle_on_decision_constraints()
                    state = _StreamState.PERMITTED
                    if previous_state == _StreamState.DENIED:
                        signal_queue.put_nowait(("recover", decision))
                except AccessDeniedError:
                    _run_best_effort_on_deny(constraint_service, decision)
                    if previous_state == _StreamState.PERMITTED:
                        signal_queue.put_nowait(("deny", decision))
                    state = _StreamState.DENIED
                    bundle = None
            else:
                _run_best_effort_on_deny(constraint_service, decision)
                if previous_state == _StreamState.PERMITTED:
                    signal_queue.put_nowait(("deny", decision))
                state = _StreamState.DENIED
                bundle = None
            decision_event.set()

    decision_task: asyncio.Task[None] | None = None
    source_iterator: AsyncIterator[Any] | None = None

    try:
        decision_task = asyncio.create_task(_consume_decisions())

        await decision_event.wait()
        decision_event.clear()

        while not signal_queue.empty():
            signal_type, signal_decision = signal_queue.get_nowait()
            if signal_type == "deny" and on_stream_deny:
                result = _safe_call_deny(on_stream_deny, signal_decision)
                if result is not None:
                    yield result
            elif signal_type == "recover" and on_stream_recover:
                result = _safe_call_recover(on_stream_recover, signal_decision)
                if result is not None:
                    yield result

        if state != _StreamState.PERMITTED:
            if on_stream_deny and current_decision:
                result = _safe_call_deny(on_stream_deny, current_decision)
                if result is not None:
                    yield result
            return

        source_iterator = (await _open_data_source(data_source)).__aiter__()

        async for item in source_iterator:
            if decision_event.is_set():
                decision_event.clear()

            while not signal_queue.empty():
                signal_type, signal_decision = signal_queue.get_nowait()
                if signal_type == "deny" and on_stream_deny:
                    result = _safe_call_deny(on_stream_deny, signal_decision)
                    if result is not None:
                        yield result
                elif signal_type == "recover" and on_stream_recover:
                    result = _safe_call_recover(on_stream_recover, signal_decision)
                    if result is not None:
                        yield result

            if state != _StreamState.PERMITTED:
                continue

            try:
                if bundle:
                    transformed = bundle.handle_all_on_next_constraints(item)
                    yield transformed
            except AccessDeniedError:
                log.warning(WARN_ON_NEXT_HANDLER_FAILED)
                continue

    finally:
        if bundle:
            with contextlib.suppress(Exception):
                bundle.handle_on_cancel_constraints()
        if decision_task and not decision_task.done():
            decision_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await decision_task
