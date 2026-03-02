from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

from sapl_base.constraint_bundle import (
    ConstraintHandlerBundle,
    StreamingConstraintHandlerBundle,
    UnhandledObligationError,
    _FailureCollector,
)
from sapl_base.constraint_types import (
    ConsumerConstraintHandlerProvider,
    ErrorHandlerProvider,
    ErrorMappingConstraintHandlerProvider,
    FilterPredicateConstraintHandlerProvider,
    MappingConstraintHandlerProvider,
    MethodInvocationConstraintHandlerProvider,
    MethodInvocationContext,
    RunnableConstraintHandlerProvider,
    Signal,
)
from sapl_base.types import RESOURCE_ABSENT, AuthorizationDecision

log = structlog.get_logger()

ERROR_OBLIGATION_HANDLER_FAILED = "Obligation handler failed"
ERROR_UNHANDLED_OBLIGATION = "No registered handler for obligation"


def _noop() -> None:
    """No-op runnable."""


def _noop_consumer(_value: Any) -> None:
    """No-op consumer."""


def _identity(value: Any) -> Any:
    """Identity mapping."""
    return value


def _always_true(_value: Any) -> bool:
    """Always-true predicate."""
    return True


def _noop_error_handler(_error: Exception) -> None:
    """No-op error handler."""


def _identity_error(error: Exception) -> Exception:
    """Identity error mapping."""
    return error


def _noop_method_invocation(_context: MethodInvocationContext) -> None:
    """No-op method invocation handler."""


def _run_both(first: Callable[[], None], second: Callable[[], None]) -> Callable[[], None]:
    """Compose two runnables to execute sequentially."""
    def combined() -> None:
        first()
        second()
    return combined


def _consume_with_both(
    first: Callable[[Any], None],
    second: Callable[[Any], None],
) -> Callable[[Any], None]:
    """Compose two consumers to both receive the same value."""
    def combined(value: Any) -> None:
        first(value)
        second(value)
    return combined


def _map_both(
    first: Callable[[Any], Any],
    second: Callable[[Any], Any],
) -> Callable[[Any], Any]:
    """Chain two mappings: second(first(value))."""
    def combined(value: Any) -> Any:
        return second(first(value))
    return combined


def _filter_both(
    first: Callable[[Any], bool],
    second: Callable[[Any], bool],
) -> Callable[[Any], bool]:
    """Compose two predicates with AND logic."""
    def combined(value: Any) -> bool:
        return first(value) and second(value)
    return combined


def _error_handle_both(
    first: Callable[[Exception], None],
    second: Callable[[Exception], None],
) -> Callable[[Exception], None]:
    """Compose two error handlers to both receive the same error."""
    def combined(error: Exception) -> None:
        first(error)
        second(error)
    return combined


def _error_map_both(
    first: Callable[[Exception], Exception],
    second: Callable[[Exception], Exception],
) -> Callable[[Exception], Exception]:
    """Chain two error mappings: second(first(error))."""
    def combined(error: Exception) -> Exception:
        return second(first(error))
    return combined


def _method_invocation_both(
    first: Callable[[MethodInvocationContext], None],
    second: Callable[[MethodInvocationContext], None],
) -> Callable[[MethodInvocationContext], None]:
    """Compose two method invocation handlers to both mutate the context."""
    def combined(context: MethodInvocationContext) -> None:
        first(context)
        second(context)
    return combined


def _wrap_obligation_runnable(
    handler: Callable[[], None], collector: _FailureCollector,
) -> Callable[[], None]:
    """Wrap a runnable so that failures are recorded for deferred denial."""
    def wrapped() -> None:
        try:
            handler()
        except Exception as error:
            log.error(ERROR_OBLIGATION_HANDLER_FAILED, error=str(error))
            collector.record(error)
    return wrapped


def _wrap_obligation_consumer(
    handler: Callable[[Any], None], collector: _FailureCollector,
) -> Callable[[Any], None]:
    """Wrap a consumer so that failures are recorded for deferred denial."""
    def wrapped(value: Any) -> None:
        try:
            handler(value)
        except Exception as error:
            log.error(ERROR_OBLIGATION_HANDLER_FAILED, error=str(error))
            collector.record(error)
    return wrapped


def _wrap_obligation_mapping(
    handler: Callable[[Any], Any], collector: _FailureCollector,
) -> Callable[[Any], Any]:
    """Wrap a mapping so that failures are recorded and identity is returned."""
    def wrapped(value: Any) -> Any:
        try:
            return handler(value)
        except Exception as error:
            log.error(ERROR_OBLIGATION_HANDLER_FAILED, error=str(error))
            collector.record(error)
            return value
    return wrapped


def _wrap_obligation_filter(
    handler: Callable[[Any], bool], collector: _FailureCollector,
) -> Callable[[Any], bool]:
    """Wrap a filter predicate so that failures are recorded and element is kept."""
    def wrapped(value: Any) -> bool:
        try:
            return handler(value)
        except Exception as error:
            log.error(ERROR_OBLIGATION_HANDLER_FAILED, error=str(error))
            collector.record(error)
            return True
    return wrapped


def _wrap_obligation_error_handler(
    handler: Callable[[Exception], None], collector: _FailureCollector,
) -> Callable[[Exception], None]:
    """Wrap an error handler so that failures are recorded for deferred denial."""
    def wrapped(error: Exception) -> None:
        try:
            handler(error)
        except Exception as wrapper_error:
            log.error(ERROR_OBLIGATION_HANDLER_FAILED, error=str(wrapper_error))
            collector.record(wrapper_error)
    return wrapped


def _wrap_obligation_error_mapping(
    handler: Callable[[Exception], Exception], collector: _FailureCollector,
) -> Callable[[Exception], Exception]:
    """Wrap an error mapping so that failures are recorded and original error returned."""
    def wrapped(error: Exception) -> Exception:
        try:
            return handler(error)
        except Exception as wrapper_error:
            log.error(ERROR_OBLIGATION_HANDLER_FAILED, error=str(wrapper_error))
            collector.record(wrapper_error)
            return error
    return wrapped


def _wrap_obligation_method_invocation(
    handler: Callable[[MethodInvocationContext], None], collector: _FailureCollector,
) -> Callable[[MethodInvocationContext], None]:
    """Wrap a method invocation handler so that failures are recorded for deferred denial."""
    def wrapped(context: MethodInvocationContext) -> None:
        try:
            handler(context)
        except Exception as error:
            log.error(ERROR_OBLIGATION_HANDLER_FAILED, error=str(error))
            collector.record(error)
    return wrapped


def _wrap_advice_runnable(handler: Callable[[], None]) -> Callable[[], None]:
    """Wrap a runnable so that failures are silently logged."""
    def wrapped() -> None:
        try:
            handler()
        except Exception:
            log.warning("Advice handler failed, ignoring")
    return wrapped


def _wrap_advice_consumer(handler: Callable[[Any], None]) -> Callable[[Any], None]:
    """Wrap a consumer so that failures are silently logged."""
    def wrapped(value: Any) -> None:
        try:
            handler(value)
        except Exception:
            log.warning("Advice handler failed, ignoring")
    return wrapped


def _wrap_advice_mapping(handler: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Wrap a mapping so that failures return the original value."""
    def wrapped(value: Any) -> Any:
        try:
            return handler(value)
        except Exception:
            log.warning("Advice mapping handler failed, returning original value")
            return value
    return wrapped


def _wrap_advice_filter(handler: Callable[[Any], bool]) -> Callable[[Any], bool]:
    """Wrap a filter predicate so that failures return True (keep element)."""
    def wrapped(value: Any) -> bool:
        try:
            return handler(value)
        except Exception:
            log.warning("Advice filter handler failed, keeping element")
            return True
    return wrapped


def _wrap_advice_error_handler(
    handler: Callable[[Exception], None],
) -> Callable[[Exception], None]:
    """Wrap an error handler so that failures are silently logged."""
    def wrapped(error: Exception) -> None:
        try:
            handler(error)
        except Exception:
            log.warning("Advice error handler failed, ignoring")
    return wrapped


def _wrap_advice_error_mapping(
    handler: Callable[[Exception], Exception],
) -> Callable[[Exception], Exception]:
    """Wrap an error mapping so that failures return the original error."""
    def wrapped(error: Exception) -> Exception:
        try:
            return handler(error)
        except Exception:
            log.warning("Advice error mapping handler failed, returning original error")
            return error
    return wrapped


def _wrap_advice_method_invocation(
    handler: Callable[[MethodInvocationContext], None],
) -> Callable[[MethodInvocationContext], None]:
    """Wrap a method invocation handler so that failures are silently logged."""
    def wrapped(context: MethodInvocationContext) -> None:
        try:
            handler(context)
        except Exception:
            log.warning("Advice method invocation handler failed, ignoring")
    return wrapped


def _wrap_best_effort_runnable(handler: Callable[[], None]) -> Callable[[], None]:
    """Wrap a runnable for best-effort execution (failures silently logged)."""
    def wrapped() -> None:
        try:
            handler()
        except Exception:
            log.debug("Best-effort handler failed, ignoring")
    return wrapped


def _wrap_best_effort_consumer(handler: Callable[[Any], None]) -> Callable[[Any], None]:
    """Wrap a consumer for best-effort execution."""
    def wrapped(value: Any) -> None:
        try:
            handler(value)
        except Exception:
            log.debug("Best-effort consumer handler failed, ignoring")
    return wrapped


def _wrap_best_effort_mapping(handler: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Wrap a mapping for best-effort execution."""
    def wrapped(value: Any) -> Any:
        try:
            return handler(value)
        except Exception:
            log.debug("Best-effort mapping handler failed, returning original value")
            return value
    return wrapped


def _wrap_best_effort_filter(handler: Callable[[Any], bool]) -> Callable[[Any], bool]:
    """Wrap a filter predicate for best-effort execution."""
    def wrapped(value: Any) -> bool:
        try:
            return handler(value)
        except Exception:
            log.debug("Best-effort filter handler failed, keeping element")
            return True
    return wrapped


def _wrap_best_effort_error_handler(
    handler: Callable[[Exception], None],
) -> Callable[[Exception], None]:
    """Wrap an error handler for best-effort execution."""
    def wrapped(error: Exception) -> None:
        try:
            handler(error)
        except Exception:
            log.debug("Best-effort error handler failed, ignoring")
    return wrapped


def _wrap_best_effort_error_mapping(
    handler: Callable[[Exception], Exception],
) -> Callable[[Exception], Exception]:
    """Wrap an error mapping for best-effort execution."""
    def wrapped(error: Exception) -> Exception:
        try:
            return handler(error)
        except Exception:
            log.debug("Best-effort error mapping handler failed, returning original")
            return error
    return wrapped


def _wrap_best_effort_method_invocation(
    handler: Callable[[MethodInvocationContext], None],
) -> Callable[[MethodInvocationContext], None]:
    """Wrap a method invocation handler for best-effort execution."""
    def wrapped(context: MethodInvocationContext) -> None:
        try:
            handler(context)
        except Exception:
            log.debug("Best-effort method invocation handler failed, ignoring")
    return wrapped


class ConstraintEnforcementService:
    """Discovers and manages constraint handler providers.

    Builds handler bundles by matching constraints against registered providers
    using the ``is_responsible`` protocol.
    """

    def __init__(self) -> None:
        self._runnable_providers: list[RunnableConstraintHandlerProvider] = []
        self._consumer_providers: list[ConsumerConstraintHandlerProvider] = []
        self._mapping_providers: list[MappingConstraintHandlerProvider] = []
        self._filter_predicate_providers: list[FilterPredicateConstraintHandlerProvider] = []
        self._error_handler_providers: list[ErrorHandlerProvider] = []
        self._error_mapping_providers: list[ErrorMappingConstraintHandlerProvider] = []
        self._method_invocation_providers: list[MethodInvocationConstraintHandlerProvider] = []

    def register_runnable(self, provider: RunnableConstraintHandlerProvider) -> None:
        """Register a runnable constraint handler provider.

        Args:
            provider: A provider implementing the RunnableConstraintHandlerProvider protocol.
        """
        self._runnable_providers.append(provider)

    def register_consumer(self, provider: ConsumerConstraintHandlerProvider) -> None:
        """Register a consumer constraint handler provider.

        Args:
            provider: A provider implementing the ConsumerConstraintHandlerProvider protocol.
        """
        self._consumer_providers.append(provider)

    def register_mapping(self, provider: MappingConstraintHandlerProvider) -> None:
        """Register a mapping constraint handler provider.

        Args:
            provider: A provider implementing the MappingConstraintHandlerProvider protocol.
        """
        self._mapping_providers.append(provider)

    def register_filter_predicate(
        self,
        provider: FilterPredicateConstraintHandlerProvider,
    ) -> None:
        """Register a filter predicate constraint handler provider.

        Args:
            provider: A provider implementing the FilterPredicateConstraintHandlerProvider
                protocol.
        """
        self._filter_predicate_providers.append(provider)

    def register_error_handler(self, provider: ErrorHandlerProvider) -> None:
        """Register an error handler provider.

        Args:
            provider: A provider implementing the ErrorHandlerProvider protocol.
        """
        self._error_handler_providers.append(provider)

    def register_error_mapping(
        self,
        provider: ErrorMappingConstraintHandlerProvider,
    ) -> None:
        """Register an error mapping constraint handler provider.

        Args:
            provider: A provider implementing the ErrorMappingConstraintHandlerProvider
                protocol.
        """
        self._error_mapping_providers.append(provider)

    def register_method_invocation(
        self,
        provider: MethodInvocationConstraintHandlerProvider,
    ) -> None:
        """Register a method invocation constraint handler provider.

        Args:
            provider: A provider implementing the MethodInvocationConstraintHandlerProvider
                protocol.
        """
        self._method_invocation_providers.append(provider)

    def pre_enforce_bundle_for(self, decision: AuthorizationDecision) -> ConstraintHandlerBundle:
        """Build a bundle for pre-enforcement.

        All obligations must have at least one registered handler. Unhandled
        obligations raise ``UnhandledObligationError``. Advice handler failures
        are non-fatal.

        Args:
            decision: The authorization decision containing constraints.

        Returns:
            A fully composed constraint handler bundle.

        Raises:
            UnhandledObligationError: If any obligation has no registered handler.
        """
        return self._build_bundle(decision, best_effort=False, include_method_invocation=True)

    def post_enforce_bundle_for(self, decision: AuthorizationDecision) -> ConstraintHandlerBundle:
        """Build a bundle for post-enforcement.

        All obligations must have at least one registered handler.

        Args:
            decision: The authorization decision containing constraints.

        Returns:
            A fully composed constraint handler bundle.

        Raises:
            UnhandledObligationError: If any obligation has no registered handler.
        """
        return self._build_bundle(decision, best_effort=False, include_method_invocation=False)

    def best_effort_bundle_for(self, decision: AuthorizationDecision) -> ConstraintHandlerBundle:
        """Build a best-effort bundle, typically for the deny path.

        All handlers execute best-effort: failures are logged but never raise.
        Unhandled obligations do not raise.

        Args:
            decision: The authorization decision containing constraints.

        Returns:
            A best-effort constraint handler bundle.
        """
        return self._build_bundle(decision, best_effort=True, include_method_invocation=False)

    def streaming_bundle_for(
        self,
        decision: AuthorizationDecision,
    ) -> StreamingConstraintHandlerBundle:
        """Build a streaming bundle with lifecycle signal support.

        All obligations must have at least one registered handler.

        Args:
            decision: The authorization decision containing constraints.

        Returns:
            A streaming constraint handler bundle with ON_COMPLETE and ON_CANCEL support.

        Raises:
            UnhandledObligationError: If any obligation has no registered handler.
        """
        return self._build_streaming_bundle(decision, best_effort=False)

    def streaming_best_effort_bundle_for(
        self,
        decision: AuthorizationDecision,
    ) -> StreamingConstraintHandlerBundle:
        """Build a best-effort streaming bundle.

        All handlers execute best-effort. Unhandled obligations do not raise.

        Args:
            decision: The authorization decision containing constraints.

        Returns:
            A best-effort streaming constraint handler bundle.
        """
        return self._build_streaming_bundle(decision, best_effort=True)

    def _build_bundle(
        self,
        decision: AuthorizationDecision,
        *,
        best_effort: bool,
        include_method_invocation: bool,
    ) -> ConstraintHandlerBundle:
        """Build a non-streaming constraint handler bundle.

        Args:
            decision: The authorization decision.
            best_effort: If True, skip unhandled obligation checks and wrap all handlers.
            include_method_invocation: If True, include method invocation handlers.

        Returns:
            A composed ConstraintHandlerBundle.
        """
        collector = _FailureCollector()
        unhandled_obligations: set[int] = set(range(len(decision.obligations)))

        on_decision = self._build_runnables(
            Signal.ON_DECISION, decision, unhandled_obligations, best_effort, collector,
        )
        method_invocation = (
            self._build_method_invocation_handlers(
                decision, unhandled_obligations, best_effort, collector,
            )
            if include_method_invocation
            else _noop_method_invocation
        )
        consumers = self._build_consumers(
            decision, unhandled_obligations, best_effort, collector,
        )
        mappings = self._build_mappings(
            decision, unhandled_obligations, best_effort, collector,
        )
        filters = self._build_filter_predicates(
            decision, unhandled_obligations, best_effort, collector,
        )
        error_handlers = self._build_error_handlers(
            decision, unhandled_obligations, best_effort, collector,
        )
        error_mappings = self._build_error_mappings(
            decision, unhandled_obligations, best_effort, collector,
        )

        if not best_effort and unhandled_obligations:
            unhandled = [decision.obligations[i] for i in sorted(unhandled_obligations)]
            raise UnhandledObligationError(unhandled)

        resource = decision.resource if decision.has_resource else RESOURCE_ABSENT

        return ConstraintHandlerBundle(
            on_decision_handlers=on_decision,
            method_invocation_handlers=method_invocation,
            on_next_consumers=consumers,
            on_next_mappings=mappings,
            filter_predicates=filters,
            on_error_handlers=error_handlers,
            on_error_mappings=error_mappings,
            resource_replacement=resource,
            failure_collector=collector,
        )

    def _build_streaming_bundle(
        self,
        decision: AuthorizationDecision,
        *,
        best_effort: bool,
    ) -> StreamingConstraintHandlerBundle:
        """Build a streaming constraint handler bundle with lifecycle signals.

        Args:
            decision: The authorization decision.
            best_effort: If True, skip unhandled obligation checks.

        Returns:
            A composed StreamingConstraintHandlerBundle.
        """
        collector = _FailureCollector()
        unhandled_obligations: set[int] = set(range(len(decision.obligations)))

        on_decision = self._build_runnables(
            Signal.ON_DECISION, decision, unhandled_obligations, best_effort, collector,
        )
        on_complete = self._build_runnables(
            Signal.ON_COMPLETE, decision, unhandled_obligations, best_effort, collector,
        )
        on_cancel = self._build_runnables(
            Signal.ON_CANCEL, decision, unhandled_obligations, best_effort, collector,
        )
        method_invocation = self._build_method_invocation_handlers(
            decision, unhandled_obligations, best_effort, collector,
        )
        consumers = self._build_consumers(
            decision, unhandled_obligations, best_effort, collector,
        )
        mappings = self._build_mappings(
            decision, unhandled_obligations, best_effort, collector,
        )
        filters = self._build_filter_predicates(
            decision, unhandled_obligations, best_effort, collector,
        )
        error_handlers = self._build_error_handlers(
            decision, unhandled_obligations, best_effort, collector,
        )
        error_mappings = self._build_error_mappings(
            decision, unhandled_obligations, best_effort, collector,
        )

        if not best_effort and unhandled_obligations:
            unhandled = [decision.obligations[i] for i in sorted(unhandled_obligations)]
            raise UnhandledObligationError(unhandled)

        resource = decision.resource if decision.has_resource else RESOURCE_ABSENT

        return StreamingConstraintHandlerBundle(
            on_decision_handlers=on_decision,
            method_invocation_handlers=method_invocation,
            on_next_consumers=consumers,
            on_next_mappings=mappings,
            filter_predicates=filters,
            on_error_handlers=error_handlers,
            on_error_mappings=error_mappings,
            resource_replacement=resource,
            on_complete_handlers=on_complete,
            on_cancel_handlers=on_cancel,
            failure_collector=collector,
        )

    def _build_runnables(
        self,
        signal: Signal,
        decision: AuthorizationDecision,
        unhandled_obligations: set[int],
        best_effort: bool,
        collector: _FailureCollector,
    ) -> Callable[[], None]:
        """Build composed runnable handlers for a specific signal.

        Args:
            signal: The lifecycle signal to match.
            decision: The authorization decision.
            unhandled_obligations: Indices of obligations not yet handled (mutated).
            best_effort: If True, wrap all handlers for best-effort execution.
            collector: Failure collector for deferred obligation denial.

        Returns:
            A composed runnable.
        """
        handler: Callable[[], None] = _noop

        for index, constraint in enumerate(decision.obligations):
            for provider in self._runnable_providers:
                if provider.get_signal() == signal and provider.is_responsible(constraint):
                    unhandled_obligations.discard(index)
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_runnable(raw)
                        if best_effort
                        else _wrap_obligation_runnable(raw, collector)
                    )
                    handler = _run_both(handler, wrapped)

        for constraint in decision.advice:
            for provider in self._runnable_providers:
                if provider.get_signal() == signal and provider.is_responsible(constraint):
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_runnable(raw)
                        if best_effort
                        else _wrap_advice_runnable(raw)
                    )
                    handler = _run_both(handler, wrapped)

        return handler

    def _build_consumers(
        self,
        decision: AuthorizationDecision,
        unhandled_obligations: set[int],
        best_effort: bool,
        collector: _FailureCollector,
    ) -> Callable[[Any], None]:
        """Build composed consumer handlers.

        Args:
            decision: The authorization decision.
            unhandled_obligations: Indices of obligations not yet handled (mutated).
            best_effort: If True, wrap all handlers for best-effort execution.
            collector: Failure collector for deferred obligation denial.

        Returns:
            A composed consumer.
        """
        handler: Callable[[Any], None] = _noop_consumer

        for index, constraint in enumerate(decision.obligations):
            for provider in self._consumer_providers:
                if provider.is_responsible(constraint):
                    unhandled_obligations.discard(index)
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_consumer(raw)
                        if best_effort
                        else _wrap_obligation_consumer(raw, collector)
                    )
                    handler = _consume_with_both(handler, wrapped)

        for constraint in decision.advice:
            for provider in self._consumer_providers:
                if provider.is_responsible(constraint):
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_consumer(raw)
                        if best_effort
                        else _wrap_advice_consumer(raw)
                    )
                    handler = _consume_with_both(handler, wrapped)

        return handler

    def _build_mappings(
        self,
        decision: AuthorizationDecision,
        unhandled_obligations: set[int],
        best_effort: bool,
        collector: _FailureCollector,
    ) -> Callable[[Any], Any]:
        """Build composed mapping handlers sorted by priority.

        Args:
            decision: The authorization decision.
            unhandled_obligations: Indices of obligations not yet handled (mutated).
            best_effort: If True, wrap all handlers for best-effort execution.
            collector: Failure collector for deferred obligation denial.

        Returns:
            A composed mapping function.
        """
        prioritized: list[tuple[int, Callable[[Any], Any], bool]] = []

        for index, constraint in enumerate(decision.obligations):
            for provider in self._mapping_providers:
                if provider.is_responsible(constraint):
                    unhandled_obligations.discard(index)
                    prioritized.append(
                        (provider.get_priority(), provider.get_handler(constraint), True),
                    )

        for constraint in decision.advice:
            for provider in self._mapping_providers:
                if provider.is_responsible(constraint):
                    prioritized.append(
                        (provider.get_priority(), provider.get_handler(constraint), False),
                    )

        prioritized.sort(key=lambda entry: entry[0], reverse=True)

        handler: Callable[[Any], Any] = _identity
        for _priority, raw, is_obligation in prioritized:
            if best_effort:
                wrapped = _wrap_best_effort_mapping(raw)
            elif is_obligation:
                wrapped = _wrap_obligation_mapping(raw, collector)
            else:
                wrapped = _wrap_advice_mapping(raw)
            handler = _map_both(handler, wrapped)

        return handler

    def _build_filter_predicates(
        self,
        decision: AuthorizationDecision,
        unhandled_obligations: set[int],
        best_effort: bool,
        collector: _FailureCollector,
    ) -> Callable[[Any], bool]:
        """Build composed filter predicate handlers with AND logic.

        Args:
            decision: The authorization decision.
            unhandled_obligations: Indices of obligations not yet handled (mutated).
            best_effort: If True, wrap all handlers for best-effort execution.
            collector: Failure collector for deferred obligation denial.

        Returns:
            A composed filter predicate.
        """
        handler: Callable[[Any], bool] = _always_true

        for index, constraint in enumerate(decision.obligations):
            for provider in self._filter_predicate_providers:
                if provider.is_responsible(constraint):
                    unhandled_obligations.discard(index)
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_filter(raw)
                        if best_effort
                        else _wrap_obligation_filter(raw, collector)
                    )
                    handler = _filter_both(handler, wrapped)

        for constraint in decision.advice:
            for provider in self._filter_predicate_providers:
                if provider.is_responsible(constraint):
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_filter(raw)
                        if best_effort
                        else _wrap_advice_filter(raw)
                    )
                    handler = _filter_both(handler, wrapped)

        return handler

    def _build_error_handlers(
        self,
        decision: AuthorizationDecision,
        unhandled_obligations: set[int],
        best_effort: bool,
        collector: _FailureCollector,
    ) -> Callable[[Exception], None]:
        """Build composed error handlers.

        Args:
            decision: The authorization decision.
            unhandled_obligations: Indices of obligations not yet handled (mutated).
            best_effort: If True, wrap all handlers for best-effort execution.
            collector: Failure collector for deferred obligation denial.

        Returns:
            A composed error handler.
        """
        handler: Callable[[Exception], None] = _noop_error_handler

        for index, constraint in enumerate(decision.obligations):
            for provider in self._error_handler_providers:
                if provider.is_responsible(constraint):
                    unhandled_obligations.discard(index)
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_error_handler(raw)
                        if best_effort
                        else _wrap_obligation_error_handler(raw, collector)
                    )
                    handler = _error_handle_both(handler, wrapped)

        for constraint in decision.advice:
            for provider in self._error_handler_providers:
                if provider.is_responsible(constraint):
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_error_handler(raw)
                        if best_effort
                        else _wrap_advice_error_handler(raw)
                    )
                    handler = _error_handle_both(handler, wrapped)

        return handler

    def _build_error_mappings(
        self,
        decision: AuthorizationDecision,
        unhandled_obligations: set[int],
        best_effort: bool,
        collector: _FailureCollector,
    ) -> Callable[[Exception], Exception]:
        """Build composed error mapping handlers sorted by priority.

        Args:
            decision: The authorization decision.
            unhandled_obligations: Indices of obligations not yet handled (mutated).
            best_effort: If True, wrap all handlers for best-effort execution.
            collector: Failure collector for deferred obligation denial.

        Returns:
            A composed error mapping function.
        """
        prioritized: list[tuple[int, Callable[[Exception], Exception], bool]] = []

        for index, constraint in enumerate(decision.obligations):
            for provider in self._error_mapping_providers:
                if provider.is_responsible(constraint):
                    unhandled_obligations.discard(index)
                    prioritized.append(
                        (provider.get_priority(), provider.get_handler(constraint), True),
                    )

        for constraint in decision.advice:
            for provider in self._error_mapping_providers:
                if provider.is_responsible(constraint):
                    prioritized.append(
                        (provider.get_priority(), provider.get_handler(constraint), False),
                    )

        prioritized.sort(key=lambda entry: entry[0], reverse=True)

        handler: Callable[[Exception], Exception] = _identity_error
        for _priority, raw, is_obligation in prioritized:
            if best_effort:
                wrapped = _wrap_best_effort_error_mapping(raw)
            elif is_obligation:
                wrapped = _wrap_obligation_error_mapping(raw, collector)
            else:
                wrapped = _wrap_advice_error_mapping(raw)
            handler = _error_map_both(handler, wrapped)

        return handler

    def _build_method_invocation_handlers(
        self,
        decision: AuthorizationDecision,
        unhandled_obligations: set[int],
        best_effort: bool,
        collector: _FailureCollector,
    ) -> Callable[[MethodInvocationContext], None]:
        """Build composed method invocation handlers.

        Args:
            decision: The authorization decision.
            unhandled_obligations: Indices of obligations not yet handled (mutated).
            best_effort: If True, wrap all handlers for best-effort execution.
            collector: Failure collector for deferred obligation denial.

        Returns:
            A composed method invocation handler.
        """
        handler: Callable[[MethodInvocationContext], None] = _noop_method_invocation

        for index, constraint in enumerate(decision.obligations):
            for provider in self._method_invocation_providers:
                if provider.is_responsible(constraint):
                    unhandled_obligations.discard(index)
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_method_invocation(raw)
                        if best_effort
                        else _wrap_obligation_method_invocation(raw, collector)
                    )
                    handler = _method_invocation_both(handler, wrapped)

        for constraint in decision.advice:
            for provider in self._method_invocation_providers:
                if provider.is_responsible(constraint):
                    raw = provider.get_handler(constraint)
                    wrapped = (
                        _wrap_best_effort_method_invocation(raw)
                        if best_effort
                        else _wrap_advice_method_invocation(raw)
                    )
                    handler = _method_invocation_both(handler, wrapped)

        return handler
