from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from sapl_base.constraint_types import MethodInvocationContext
from sapl_base.types import RESOURCE_ABSENT

log = structlog.get_logger()

ERROR_ACCESS_DENIED = "Access denied"
ERROR_OBLIGATION_FAILURES = "Obligation handler(s) failed"
ERROR_OBLIGATION_HANDLER_FAILED = "Obligation handler failed"


class _FailureCollector:
    """Collects obligation handler failures for deferred raising.

    Instead of raising AccessDeniedError immediately when an obligation handler
    fails, the failure is recorded. After all handlers in a stage have run,
    ``check`` raises AccessDeniedError if any failures were collected.
    """

    def __init__(self) -> None:
        self.failures: list[Exception] = []

    def record(self, error: Exception) -> None:
        """Record an obligation handler failure."""
        self.failures.append(error)

    def check(self) -> None:
        """Raise AccessDeniedError if any failures were recorded, then reset."""
        if self.failures:
            count = len(self.failures)
            first = self.failures[0]
            self.failures.clear()
            log.error(ERROR_OBLIGATION_FAILURES, count=count)
            raise AccessDeniedError(ERROR_OBLIGATION_HANDLER_FAILED) from first

ERROR_FILTER_REJECTED_SCALAR = "Filter predicate rejected scalar value"
ERROR_UNHANDLED_OBLIGATION = (
    "Access denied by PEP. The PDP required at least one obligation to be enforced "
    "for which no handler is registered. Unhandled obligations: %s"
)


class AccessDeniedError(Exception):
    """Raised when access is denied by enforcement logic."""


class UnhandledObligationError(AccessDeniedError):
    """Raised when an obligation has no registered handler.

    Args:
        constraints: The obligation constraints that could not be handled.
    """

    def __init__(self, constraints: Any) -> None:
        self.constraints = constraints
        super().__init__(ERROR_UNHANDLED_OBLIGATION % constraints)


class ConstraintHandlerBundle:
    """Non-streaming bundle for pre-enforce and post-enforce scenarios.

    Composes constraint handlers into a pipeline executed in a defined order:
    resource replacement, filter predicate, consumer, mapping.

    Args:
        on_decision_handlers: Side-effect runnable for the ON_DECISION signal.
        method_invocation_handlers: Handler that mutates MethodInvocationContext.
        on_next_consumers: Consumer called with each value (side effects only).
        on_next_mappings: Mapping applied to transform each value.
        filter_predicates: Predicate for filtering values or list elements.
        on_error_handlers: Error observer/logger.
        on_error_mappings: Error transformation mapping.
        resource_replacement: Replacement value from the decision, or RESOURCE_ABSENT.
        failure_collector: Collector for deferred obligation handler failures.
    """

    def __init__(
        self,
        on_decision_handlers: Callable[[], None],
        method_invocation_handlers: Callable[[MethodInvocationContext], None],
        on_next_consumers: Callable[[Any], None],
        on_next_mappings: Callable[[Any], Any],
        filter_predicates: Callable[[Any], bool],
        on_error_handlers: Callable[[Exception], None],
        on_error_mappings: Callable[[Exception], Exception],
        resource_replacement: Any = RESOURCE_ABSENT,
        failure_collector: _FailureCollector | None = None,
    ) -> None:
        self._on_decision_handlers = on_decision_handlers
        self._method_invocation_handlers = method_invocation_handlers
        self._on_next_consumers = on_next_consumers
        self._on_next_mappings = on_next_mappings
        self._filter_predicates = filter_predicates
        self._on_error_handlers = on_error_handlers
        self._on_error_mappings = on_error_mappings
        self._resource_replacement = resource_replacement
        self._failure_collector = failure_collector

    def handle_on_decision_constraints(self) -> None:
        """Execute on-decision runnables."""
        self._on_decision_handlers()
        if self._failure_collector:
            self._failure_collector.check()

    def handle_method_invocation_handlers(self, context: MethodInvocationContext) -> None:
        """Execute method invocation handlers, mutating the context.

        Args:
            context: The method invocation context to modify.
        """
        self._method_invocation_handlers(context)
        if self._failure_collector:
            self._failure_collector.check()

    def handle_all_on_next_constraints(self, value: Any) -> Any:
        """Apply the full on-next pipeline to a value.

        The pipeline executes in this order:
        1. Resource replacement (if the decision provides one).
        2. Filter predicate (scalar rejection or list filtering).
        3. Consumer (side effects on the value).
        4. Mapping (value transformation).

        Args:
            value: The value to process through the pipeline.

        Returns:
            The transformed value after all pipeline stages.

        Raises:
            AccessDeniedError: If the filter predicate rejects a scalar value.
        """
        if self._resource_replacement is not RESOURCE_ABSENT:
            value = self._resource_replacement

        if isinstance(value, list):
            value = [element for element in value if self._filter_predicates(element)]
        elif not self._filter_predicates(value):
            raise AccessDeniedError(ERROR_FILTER_REJECTED_SCALAR)

        self._on_next_consumers(value)
        result = self._on_next_mappings(value)
        if self._failure_collector:
            self._failure_collector.check()
        return result

    def handle_all_on_error_constraints(self, error: Exception) -> Exception:
        """Apply the full on-error pipeline to an exception.

        The pipeline executes in this order:
        1. Error handler (observation/logging side effects).
        2. Error mapping (transformation).

        Args:
            error: The exception to process.

        Returns:
            The (possibly transformed) exception.
        """
        self._on_error_handlers(error)
        result = self._on_error_mappings(error)
        if self._failure_collector:
            self._failure_collector.check()
        return result


class StreamingConstraintHandlerBundle(ConstraintHandlerBundle):
    """Extended bundle with lifecycle signals for streaming enforcement.

    Adds ON_COMPLETE and ON_CANCEL signal handlers to the base bundle.

    Args:
        on_complete_handlers: Side-effect runnable for the ON_COMPLETE signal.
        on_cancel_handlers: Side-effect runnable for the ON_CANCEL signal.
    """

    def __init__(
        self,
        on_decision_handlers: Callable[[], None],
        method_invocation_handlers: Callable[[MethodInvocationContext], None],
        on_next_consumers: Callable[[Any], None],
        on_next_mappings: Callable[[Any], Any],
        filter_predicates: Callable[[Any], bool],
        on_error_handlers: Callable[[Exception], None],
        on_error_mappings: Callable[[Exception], Exception],
        resource_replacement: Any = RESOURCE_ABSENT,
        on_complete_handlers: Callable[[], None] = lambda: None,
        on_cancel_handlers: Callable[[], None] = lambda: None,
        failure_collector: _FailureCollector | None = None,
    ) -> None:
        super().__init__(
            on_decision_handlers=on_decision_handlers,
            method_invocation_handlers=method_invocation_handlers,
            on_next_consumers=on_next_consumers,
            on_next_mappings=on_next_mappings,
            filter_predicates=filter_predicates,
            on_error_handlers=on_error_handlers,
            on_error_mappings=on_error_mappings,
            resource_replacement=resource_replacement,
            failure_collector=failure_collector,
        )
        self._on_complete_handlers = on_complete_handlers
        self._on_cancel_handlers = on_cancel_handlers

    def handle_on_complete_constraints(self) -> None:
        """Execute ON_COMPLETE runnables."""
        self._on_complete_handlers()
        if self._failure_collector:
            self._failure_collector.check()

    def handle_on_cancel_constraints(self) -> None:
        """Execute ON_CANCEL runnables."""
        self._on_cancel_handlers()
        if self._failure_collector:
            self._failure_collector.check()
