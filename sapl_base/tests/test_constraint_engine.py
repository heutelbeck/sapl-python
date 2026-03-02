from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from sapl_base.constraint_bundle import (
    AccessDeniedError,
    ConstraintHandlerBundle,
    StreamingConstraintHandlerBundle,
    UnhandledObligationError,
)
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.constraint_types import (
    MethodInvocationContext,
    Signal,
)
from sapl_base.types import AuthorizationDecision, Decision


def _decision_with_obligations(*obligations: Any) -> AuthorizationDecision:
    return AuthorizationDecision(
        decision=Decision.PERMIT,
        obligations=tuple(obligations),
    )


def _decision_with_advice(*advice: Any) -> AuthorizationDecision:
    return AuthorizationDecision(
        decision=Decision.PERMIT,
        advice=tuple(advice),
    )


class _LoggingRunnableProvider:
    def __init__(self, constraint_type: str, signal: Signal, log: list[str]) -> None:
        self._constraint_type = constraint_type
        self._signal = signal
        self._log = log

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_signal(self) -> Signal:
        return self._signal

    def get_handler(self, constraint: Any) -> Callable[[], None]:
        tag = constraint.get("tag", self._constraint_type)
        def handler() -> None:
            self._log.append(f"runnable:{tag}")
        return handler


class _LoggingConsumerProvider:
    def __init__(self, constraint_type: str, log: list[str]) -> None:
        self._constraint_type = constraint_type
        self._log = log

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_handler(self, constraint: Any) -> Callable[[Any], None]:
        tag = constraint.get("tag", self._constraint_type)
        def handler(value: Any) -> None:
            self._log.append(f"consumer:{tag}:{value}")
        return handler


class _LoggingMappingProvider:
    def __init__(
        self,
        constraint_type: str,
        priority: int,
        suffix: str,
        log: list[str],
    ) -> None:
        self._constraint_type = constraint_type
        self._priority = priority
        self._suffix = suffix
        self._log = log

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_priority(self) -> int:
        return self._priority

    def get_handler(self, constraint: Any) -> Callable[[Any], Any]:
        suffix = self._suffix
        log_ref = self._log
        def handler(value: Any) -> Any:
            result = f"{value}{suffix}"
            log_ref.append(f"mapping:{result}")
            return result
        return handler


class _LoggingFilterPredicateProvider:
    def __init__(self, constraint_type: str, predicate: Callable[[Any], bool]) -> None:
        self._constraint_type = constraint_type
        self._predicate = predicate

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_handler(self, constraint: Any) -> Callable[[Any], bool]:
        return self._predicate


class _LoggingErrorHandlerProvider:
    def __init__(self, constraint_type: str, log: list[str]) -> None:
        self._constraint_type = constraint_type
        self._log = log

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_handler(self, constraint: Any) -> Callable[[Exception], None]:
        log_ref = self._log
        def handler(error: Exception) -> None:
            log_ref.append(f"error_handler:{error}")
        return handler


class _LoggingErrorMappingProvider:
    def __init__(self, constraint_type: str, priority: int, wrapper_type: type) -> None:
        self._constraint_type = constraint_type
        self._priority = priority
        self._wrapper_type = wrapper_type

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_priority(self) -> int:
        return self._priority

    def get_handler(self, constraint: Any) -> Callable[[Exception], Exception]:
        wrapper = self._wrapper_type
        def handler(error: Exception) -> Exception:
            return wrapper(str(error))
        return handler


class _LoggingMethodInvocationProvider:
    def __init__(self, constraint_type: str, log: list[str]) -> None:
        self._constraint_type = constraint_type
        self._log = log

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_handler(self, constraint: Any) -> Callable[[MethodInvocationContext], None]:
        log_ref = self._log
        def handler(context: MethodInvocationContext) -> None:
            log_ref.append(f"method_invocation:{context.function_name}")
            context.args.append("injected")
        return handler


class TestRegistration:
    """Handler provider registration for all 7 types."""

    def test_register_runnable_provider(self) -> None:
        service = ConstraintEnforcementService()
        provider = _LoggingRunnableProvider("log", Signal.ON_DECISION, [])
        service.register_runnable(provider)
        assert provider in service._runnable_providers

    def test_register_consumer_provider(self) -> None:
        service = ConstraintEnforcementService()
        provider = _LoggingConsumerProvider("log", [])
        service.register_consumer(provider)
        assert provider in service._consumer_providers

    def test_register_mapping_provider(self) -> None:
        service = ConstraintEnforcementService()
        provider = _LoggingMappingProvider("map", 0, "_mapped", [])
        service.register_mapping(provider)
        assert provider in service._mapping_providers

    def test_register_filter_predicate_provider(self) -> None:
        service = ConstraintEnforcementService()
        provider = _LoggingFilterPredicateProvider("filter", lambda v: True)
        service.register_filter_predicate(provider)
        assert provider in service._filter_predicate_providers

    def test_register_error_handler_provider(self) -> None:
        service = ConstraintEnforcementService()
        provider = _LoggingErrorHandlerProvider("error", [])
        service.register_error_handler(provider)
        assert provider in service._error_handler_providers

    def test_register_error_mapping_provider(self) -> None:
        service = ConstraintEnforcementService()
        provider = _LoggingErrorMappingProvider("error_map", 0, RuntimeError)
        service.register_error_mapping(provider)
        assert provider in service._error_mapping_providers

    def test_register_method_invocation_provider(self) -> None:
        service = ConstraintEnforcementService()
        provider = _LoggingMethodInvocationProvider("invoke", [])
        service.register_method_invocation(provider)
        assert provider in service._method_invocation_providers


class TestMultiProtocolRegistration:
    """A single provider registered for multiple roles via typed methods."""

    def test_provider_registered_for_multiple_roles(self) -> None:
        class MultiProvider:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_signal(self) -> Signal:
                return Signal.ON_DECISION

            def get_priority(self) -> int:
                return 0

            def get_handler(self, constraint: Any) -> Any:
                return lambda: None

        service = ConstraintEnforcementService()
        provider = MultiProvider()
        service.register_runnable(provider)
        service.register_consumer(provider)

        assert provider in service._runnable_providers
        assert provider in service._consumer_providers


class TestObligationResolution:
    """Unhandled obligations raise UnhandledObligationError."""

    def test_unhandled_obligation_raises(self) -> None:
        service = ConstraintEnforcementService()
        decision = _decision_with_obligations({"type": "unknown"})
        with pytest.raises(UnhandledObligationError) as exc_info:
            service.pre_enforce_bundle_for(decision)
        assert {"type": "unknown"} in exc_info.value.constraints

    def test_handled_obligation_does_not_raise(self) -> None:
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_DECISION, []),
        )
        decision = _decision_with_obligations({"type": "log"})
        bundle = service.pre_enforce_bundle_for(decision)
        assert isinstance(bundle, ConstraintHandlerBundle)

    def test_multiple_obligations_one_unhandled_raises(self) -> None:
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_DECISION, []),
        )
        decision = _decision_with_obligations({"type": "log"}, {"type": "unknown"})
        with pytest.raises(UnhandledObligationError):
            service.pre_enforce_bundle_for(decision)

    def test_post_enforce_unhandled_obligation_raises(self) -> None:
        service = ConstraintEnforcementService()
        decision = _decision_with_obligations({"type": "unknown"})
        with pytest.raises(UnhandledObligationError):
            service.post_enforce_bundle_for(decision)

    def test_streaming_unhandled_obligation_raises(self) -> None:
        service = ConstraintEnforcementService()
        decision = _decision_with_obligations({"type": "unknown"})
        with pytest.raises(UnhandledObligationError):
            service.streaming_bundle_for(decision)


class TestAdviceResolution:
    """Unhandled advice is silently skipped."""

    def test_unhandled_advice_does_not_raise(self) -> None:
        service = ConstraintEnforcementService()
        decision = _decision_with_advice({"type": "unknown"})
        bundle = service.pre_enforce_bundle_for(decision)
        assert isinstance(bundle, ConstraintHandlerBundle)

    def test_handled_advice_is_included(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_DECISION, action_log),
        )
        decision = _decision_with_advice({"type": "log", "tag": "advice_tag"})
        bundle = service.pre_enforce_bundle_for(decision)
        bundle.handle_on_decision_constraints()
        assert "runnable:advice_tag" in action_log


class TestHandlerComposition:
    """Handler composition: execution order and priority sorting."""

    def test_runnables_execute_sequentially(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("a", Signal.ON_DECISION, action_log),
        )
        service.register_runnable(
            _LoggingRunnableProvider("b", Signal.ON_DECISION, action_log),
        )
        decision = _decision_with_obligations(
            {"type": "a", "tag": "first"},
            {"type": "b", "tag": "second"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        bundle.handle_on_decision_constraints()
        assert action_log == ["runnable:first", "runnable:second"]

    def test_consumers_receive_same_value(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_consumer(_LoggingConsumerProvider("a", action_log))
        service.register_consumer(_LoggingConsumerProvider("b", action_log))
        decision = _decision_with_obligations(
            {"type": "a", "tag": "c1"},
            {"type": "b", "tag": "c2"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        bundle.handle_all_on_next_constraints("hello")
        assert "consumer:c1:hello" in action_log
        assert "consumer:c2:hello" in action_log

    def test_mappings_sorted_by_priority_highest_first(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_mapping(_LoggingMappingProvider("low", 1, "_low", action_log))
        service.register_mapping(_LoggingMappingProvider("high", 10, "_high", action_log))
        decision = _decision_with_obligations(
            {"type": "low"},
            {"type": "high"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        result = bundle.handle_all_on_next_constraints("start")
        assert result == "start_high_low"

    def test_filter_predicates_combined_with_and(self) -> None:
        service = ConstraintEnforcementService()
        service.register_filter_predicate(
            _LoggingFilterPredicateProvider("even", lambda v: v % 2 == 0),
        )
        service.register_filter_predicate(
            _LoggingFilterPredicateProvider("positive", lambda v: v > 0),
        )
        decision = _decision_with_obligations(
            {"type": "even"},
            {"type": "positive"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        result = bundle.handle_all_on_next_constraints([2, -2, 3, 4, -1, 0])
        assert result == [2, 4]

    def test_multiple_providers_handle_same_constraint(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("shared", Signal.ON_DECISION, action_log),
        )
        service.register_consumer(_LoggingConsumerProvider("shared", action_log))
        decision = _decision_with_obligations({"type": "shared", "tag": "x"})
        bundle = service.pre_enforce_bundle_for(decision)
        bundle.handle_on_decision_constraints()
        bundle.handle_all_on_next_constraints("val")
        assert "runnable:x" in action_log
        assert "consumer:x:val" in action_log

    def test_error_handlers_both_called(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_error_handler(_LoggingErrorHandlerProvider("a", action_log))
        service.register_error_handler(_LoggingErrorHandlerProvider("b", action_log))
        decision = _decision_with_obligations(
            {"type": "a"},
            {"type": "b"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        error = ValueError("test")
        bundle.handle_all_on_error_constraints(error)
        assert len(action_log) == 2

    def test_error_mappings_chained_by_priority(self) -> None:
        service = ConstraintEnforcementService()
        service.register_error_mapping(
            _LoggingErrorMappingProvider("wrap", 10, RuntimeError),
        )
        service.register_error_mapping(
            _LoggingErrorMappingProvider("wrap2", 1, TypeError),
        )
        decision = _decision_with_obligations(
            {"type": "wrap"},
            {"type": "wrap2"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        original = ValueError("original")
        result = bundle.handle_all_on_error_constraints(original)
        assert isinstance(result, TypeError)

    def test_method_invocation_handlers_mutate_context(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_method_invocation(
            _LoggingMethodInvocationProvider("invoke", action_log),
        )
        decision = _decision_with_obligations({"type": "invoke"})
        bundle = service.pre_enforce_bundle_for(decision)
        context = MethodInvocationContext(args=[], kwargs={}, function_name="my_func")
        bundle.handle_method_invocation_handlers(context)
        assert "method_invocation:my_func" in action_log
        assert "injected" in context.args


class TestBestEffortBundle:
    """Best-effort bundles do not raise for unhandled obligations or handler failures."""

    def test_unhandled_obligation_does_not_raise(self) -> None:
        service = ConstraintEnforcementService()
        decision = _decision_with_obligations({"type": "unknown"})
        bundle = service.best_effort_bundle_for(decision)
        assert isinstance(bundle, ConstraintHandlerBundle)

    def test_failing_handler_does_not_raise(self) -> None:
        class FailingRunnable:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_signal(self) -> Signal:
                return Signal.ON_DECISION

            def get_handler(self, constraint: Any) -> Callable[[], None]:
                def handler() -> None:
                    raise RuntimeError("boom")
                return handler

        service = ConstraintEnforcementService()
        service.register_runnable(FailingRunnable())
        decision = _decision_with_obligations({"type": "anything"})
        bundle = service.best_effort_bundle_for(decision)
        bundle.handle_on_decision_constraints()

    def test_streaming_best_effort_unhandled_does_not_raise(self) -> None:
        service = ConstraintEnforcementService()
        decision = _decision_with_obligations({"type": "unknown"})
        bundle = service.streaming_best_effort_bundle_for(decision)
        assert isinstance(bundle, StreamingConstraintHandlerBundle)


class TestObligationHandlerFailure:
    """When an obligation handler fails, AccessDeniedError is raised."""

    def test_failing_obligation_runnable_raises_access_denied(self) -> None:
        class FailingRunnable:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_signal(self) -> Signal:
                return Signal.ON_DECISION

            def get_handler(self, constraint: Any) -> Callable[[], None]:
                def handler() -> None:
                    raise RuntimeError("boom")
                return handler

        service = ConstraintEnforcementService()
        service.register_runnable(FailingRunnable())
        decision = _decision_with_obligations({"type": "x"})
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_on_decision_constraints()

    def test_failing_obligation_consumer_raises_access_denied(self) -> None:
        class FailingConsumer:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_handler(self, constraint: Any) -> Callable[[Any], None]:
                def handler(value: Any) -> None:
                    raise RuntimeError("boom")
                return handler

        service = ConstraintEnforcementService()
        service.register_consumer(FailingConsumer())
        decision = _decision_with_obligations({"type": "x"})
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_all_on_next_constraints("val")

    def test_failing_obligation_mapping_raises_access_denied(self) -> None:
        class FailingMapping:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_priority(self) -> int:
                return 0

            def get_handler(self, constraint: Any) -> Callable[[Any], Any]:
                def handler(value: Any) -> Any:
                    raise RuntimeError("boom")
                return handler

        service = ConstraintEnforcementService()
        service.register_mapping(FailingMapping())
        decision = _decision_with_obligations({"type": "x"})
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_all_on_next_constraints("val")


class TestAdviceHandlerFailure:
    """When an advice handler fails, execution continues without raising."""

    def test_failing_advice_runnable_does_not_raise(self) -> None:
        class FailingRunnable:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_signal(self) -> Signal:
                return Signal.ON_DECISION

            def get_handler(self, constraint: Any) -> Callable[[], None]:
                def handler() -> None:
                    raise RuntimeError("boom")
                return handler

        service = ConstraintEnforcementService()
        service.register_runnable(FailingRunnable())
        decision = _decision_with_advice({"type": "x"})
        bundle = service.pre_enforce_bundle_for(decision)
        bundle.handle_on_decision_constraints()

    def test_failing_advice_mapping_returns_original_value(self) -> None:
        class FailingMapping:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_priority(self) -> int:
                return 0

            def get_handler(self, constraint: Any) -> Callable[[Any], Any]:
                def handler(value: Any) -> Any:
                    raise RuntimeError("boom")
                return handler

        service = ConstraintEnforcementService()
        service.register_mapping(FailingMapping())
        decision = _decision_with_advice({"type": "x"})
        bundle = service.pre_enforce_bundle_for(decision)
        result = bundle.handle_all_on_next_constraints("original")
        assert result == "original"


class TestBundleExecutionPipeline:
    """Full pipeline: on_decision -> method_invocation -> on_next."""

    def test_full_pipeline_order(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_DECISION, action_log),
        )
        service.register_consumer(_LoggingConsumerProvider("log", action_log))
        service.register_mapping(_LoggingMappingProvider("log", 0, "_mapped", action_log))
        service.register_method_invocation(
            _LoggingMethodInvocationProvider("log", action_log),
        )

        decision = _decision_with_obligations({"type": "log", "tag": "step"})
        bundle = service.pre_enforce_bundle_for(decision)

        bundle.handle_on_decision_constraints()
        context = MethodInvocationContext(args=[], kwargs={}, function_name="test_fn")
        bundle.handle_method_invocation_handlers(context)
        result = bundle.handle_all_on_next_constraints("input")

        assert action_log[0] == "runnable:step"
        assert action_log[1] == "method_invocation:test_fn"
        assert "consumer:step:input" in action_log
        assert result == "input_mapped"

    def test_empty_decision_produces_noop_bundle(self) -> None:
        service = ConstraintEnforcementService()
        decision = AuthorizationDecision(decision=Decision.PERMIT)
        bundle = service.pre_enforce_bundle_for(decision)
        bundle.handle_on_decision_constraints()
        result = bundle.handle_all_on_next_constraints("passthrough")
        assert result == "passthrough"


class TestStreamingBundle:
    """Streaming bundle lifecycle signals: ON_COMPLETE, ON_CANCEL."""

    def test_on_complete_signal(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_COMPLETE, action_log),
        )
        decision = _decision_with_obligations({"type": "log", "tag": "complete"})
        bundle = service.streaming_bundle_for(decision)
        bundle.handle_on_complete_constraints()
        assert "runnable:complete" in action_log

    def test_on_cancel_signal(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_CANCEL, action_log),
        )
        decision = _decision_with_obligations({"type": "log", "tag": "cancel"})
        bundle = service.streaming_bundle_for(decision)
        bundle.handle_on_cancel_constraints()
        assert "runnable:cancel" in action_log

    def test_on_decision_still_works_in_streaming_bundle(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_DECISION, action_log),
        )
        decision = _decision_with_obligations({"type": "log", "tag": "decision"})
        bundle = service.streaming_bundle_for(decision)
        bundle.handle_on_decision_constraints()
        assert "runnable:decision" in action_log

    def test_streaming_bundle_is_constraint_handler_bundle(self) -> None:
        service = ConstraintEnforcementService()
        decision = AuthorizationDecision(decision=Decision.PERMIT)
        bundle = service.streaming_bundle_for(decision)
        assert isinstance(bundle, ConstraintHandlerBundle)
        assert isinstance(bundle, StreamingConstraintHandlerBundle)


class TestPostEnforce:
    """Post-enforce bundles do not include method invocation handlers."""

    def test_post_enforce_has_no_method_invocation(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_method_invocation(
            _LoggingMethodInvocationProvider("invoke", action_log),
        )
        service.register_runnable(
            _LoggingRunnableProvider("invoke", Signal.ON_DECISION, action_log),
        )
        decision = _decision_with_obligations({"type": "invoke"})
        bundle = service.post_enforce_bundle_for(decision)
        context = MethodInvocationContext(args=[], kwargs={}, function_name="fn")
        bundle.handle_method_invocation_handlers(context)
        assert "injected" not in context.args


class _FailingRunnableProvider:
    def __init__(self, constraint_type: str, signal: Signal) -> None:
        self._constraint_type = constraint_type
        self._signal = signal

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_signal(self) -> Signal:
        return self._signal

    def get_handler(self, constraint: Any) -> Callable[[], None]:
        def handler() -> None:
            raise RuntimeError("boom")
        return handler


class _FailingConsumerProvider:
    def __init__(self, constraint_type: str) -> None:
        self._constraint_type = constraint_type

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_handler(self, constraint: Any) -> Callable[[Any], None]:
        def handler(value: Any) -> None:
            raise RuntimeError("boom")
        return handler


class _FailingMappingProvider:
    def __init__(self, constraint_type: str, priority: int) -> None:
        self._constraint_type = constraint_type
        self._priority = priority

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_priority(self) -> int:
        return self._priority

    def get_handler(self, constraint: Any) -> Callable[[Any], Any]:
        def handler(value: Any) -> Any:
            raise RuntimeError("boom")
        return handler


class _FailingFilterPredicateProvider:
    def __init__(self, constraint_type: str) -> None:
        self._constraint_type = constraint_type

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_handler(self, constraint: Any) -> Callable[[Any], bool]:
        def handler(value: Any) -> bool:
            raise RuntimeError("boom")
        return handler


class _FailingErrorHandlerProvider:
    def __init__(self, constraint_type: str) -> None:
        self._constraint_type = constraint_type

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_handler(self, constraint: Any) -> Callable[[Exception], None]:
        def handler(error: Exception) -> None:
            raise RuntimeError("boom")
        return handler


class _FailingErrorMappingProvider:
    def __init__(self, constraint_type: str, priority: int) -> None:
        self._constraint_type = constraint_type
        self._priority = priority

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_priority(self) -> int:
        return self._priority

    def get_handler(self, constraint: Any) -> Callable[[Exception], Exception]:
        def handler(error: Exception) -> Exception:
            raise RuntimeError("boom")
        return handler


class _FailingMethodInvocationProvider:
    def __init__(self, constraint_type: str) -> None:
        self._constraint_type = constraint_type

    def is_responsible(self, constraint: Any) -> bool:
        return constraint.get("type") == self._constraint_type

    def get_handler(self, constraint: Any) -> Callable[[MethodInvocationContext], None]:
        def handler(context: MethodInvocationContext) -> None:
            raise RuntimeError("boom")
        return handler


class TestObligationNoShortCircuit:
    """REQ-OBLIGATION-3: All obligation/advice handlers must be attempted.

    When an obligation handler fails, execution must not short-circuit.
    All remaining handlers in the stage must still run. AccessDeniedError
    is raised only after all handlers have been attempted.
    """

    def test_failing_obligation_runnable_does_not_prevent_second_from_running(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _FailingRunnableProvider("fail", Signal.ON_DECISION),
        )
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_DECISION, action_log),
        )
        decision = _decision_with_obligations(
            {"type": "fail"},
            {"type": "log", "tag": "second"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_on_decision_constraints()
        assert "runnable:second" in action_log

    def test_failing_obligation_consumer_does_not_prevent_second_from_running(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_consumer(_FailingConsumerProvider("fail"))
        service.register_consumer(_LoggingConsumerProvider("log", action_log))
        decision = _decision_with_obligations(
            {"type": "fail"},
            {"type": "log", "tag": "second"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_all_on_next_constraints("val")
        assert "consumer:second:val" in action_log

    def test_failing_obligation_mapping_does_not_prevent_second_from_running(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_mapping(_FailingMappingProvider("fail", 10))
        service.register_mapping(_LoggingMappingProvider("log", 1, "_ok", action_log))
        decision = _decision_with_obligations(
            {"type": "fail"},
            {"type": "log"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_all_on_next_constraints("start")
        assert len(action_log) == 1
        assert action_log[0].startswith("mapping:")

    def test_failing_obligation_filter_does_not_prevent_second_from_running(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_filter_predicate(_FailingFilterPredicateProvider("fail"))
        service.register_consumer(_LoggingConsumerProvider("log", action_log))
        decision = _decision_with_obligations(
            {"type": "fail"},
            {"type": "log", "tag": "second"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_all_on_next_constraints("val")
        assert "consumer:second:val" in action_log

    def test_failing_obligation_error_handler_does_not_prevent_second_from_running(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_error_handler(_FailingErrorHandlerProvider("fail"))
        service.register_error_handler(_LoggingErrorHandlerProvider("log", action_log))
        decision = _decision_with_obligations(
            {"type": "fail"},
            {"type": "log"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_all_on_error_constraints(ValueError("test"))
        assert len(action_log) == 1

    def test_failing_obligation_error_mapping_does_not_prevent_second_from_running(self) -> None:
        service = ConstraintEnforcementService()
        service.register_error_mapping(_FailingErrorMappingProvider("fail", 10))
        service.register_error_mapping(
            _LoggingErrorMappingProvider("wrap", 1, TypeError),
        )
        decision = _decision_with_obligations(
            {"type": "fail"},
            {"type": "wrap"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_all_on_error_constraints(ValueError("original"))

    def test_failing_obligation_method_invocation_does_not_prevent_second_from_running(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_method_invocation(_FailingMethodInvocationProvider("fail"))
        service.register_method_invocation(
            _LoggingMethodInvocationProvider("log", action_log),
        )
        decision = _decision_with_obligations(
            {"type": "fail"},
            {"type": "log"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        context = MethodInvocationContext(args=[], kwargs={}, function_name="fn")
        with pytest.raises(AccessDeniedError):
            bundle.handle_method_invocation_handlers(context)
        assert "method_invocation:fn" in action_log

    def test_advice_still_runs_after_obligation_failure(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _FailingRunnableProvider("fail", Signal.ON_DECISION),
        )
        service.register_runnable(
            _LoggingRunnableProvider("advice", Signal.ON_DECISION, action_log),
        )
        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "fail"},),
            advice=({"type": "advice", "tag": "advice_ran"},),
        )
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_on_decision_constraints()
        assert "runnable:advice_ran" in action_log

    def test_all_failures_collected_before_deny(self) -> None:
        action_log: list[str] = []
        service = ConstraintEnforcementService()
        service.register_runnable(
            _FailingRunnableProvider("fail", Signal.ON_DECISION),
        )
        service.register_runnable(
            _LoggingRunnableProvider("log", Signal.ON_DECISION, action_log),
        )
        decision = _decision_with_obligations(
            {"type": "fail", "tag": "first_fail"},
            {"type": "log", "tag": "middle"},
            {"type": "fail", "tag": "third_fail"},
        )
        bundle = service.pre_enforce_bundle_for(decision)
        with pytest.raises(AccessDeniedError):
            bundle.handle_on_decision_constraints()
        assert "runnable:middle" in action_log
