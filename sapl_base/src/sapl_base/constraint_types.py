from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SubscriptionContext:
    """Rich context passed to subscription field callables.

    Provides all available information about the current invocation so that
    subscription field lambdas (``subject``, ``action``, ``resource``, etc.)
    can derive their values from request parameters, route params, or return
    values without needing framework-specific signatures.

    Args:
        args: Named arguments of the protected method.
        function_name: Name of the protected method.
        class_name: Qualified class name (empty for plain functions).
        request: Framework request object, or None for service-layer calls.
        params: Route/path parameters.
        query: Query string parameters.
        body: Parsed request body, or None.
        return_value: Return value of the method (PostEnforce only).
    """

    args: dict[str, Any] = field(default_factory=dict)
    function_name: str = ""
    class_name: str = ""
    request: Any = None
    params: dict[str, str] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    return_value: Any = None


class Signal(Enum):
    """Lifecycle signals for runnable constraint handlers."""

    ON_DECISION = "ON_DECISION"
    ON_COMPLETE = "ON_COMPLETE"
    ON_CANCEL = "ON_CANCEL"


@runtime_checkable
class Responsible(Protocol):
    """Base protocol for all constraint handler providers."""

    def is_responsible(self, constraint: Any) -> bool:
        """Return True if this provider can handle the given constraint."""
        ...


@runtime_checkable
class RunnableConstraintHandlerProvider(Responsible, Protocol):
    """Provider for side-effect handlers that take no arguments and return nothing.

    Handlers are dispatched based on their signal (ON_DECISION, ON_COMPLETE, ON_CANCEL).
    """

    def get_signal(self) -> Signal:
        """Return the lifecycle signal this handler responds to."""
        ...

    def get_handler(self, constraint: Any) -> Callable[[], None]:
        """Return a side-effect handler for the given constraint."""
        ...


@runtime_checkable
class ConsumerConstraintHandlerProvider(Responsible, Protocol):
    """Provider for handlers that consume a value without transforming it.

    Args:
        constraint: The constraint to handle.

    Returns:
        A callable that accepts a value and performs a side effect.
    """

    def get_handler(self, constraint: Any) -> Callable[[Any], None]:
        """Return a consumer handler for the given constraint."""
        ...


@runtime_checkable
class MappingConstraintHandlerProvider(Responsible, Protocol):
    """Provider for handlers that transform values.

    Handlers are composed in priority order (highest priority first).

    Args:
        constraint: The constraint to handle.

    Returns:
        A callable that accepts a value and returns a transformed value.
    """

    def get_priority(self) -> int:
        """Return the priority for ordering. Higher values execute first."""
        ...

    def get_handler(self, constraint: Any) -> Callable[[Any], Any]:
        """Return a mapping handler for the given constraint."""
        ...


@runtime_checkable
class FilterPredicateConstraintHandlerProvider(Responsible, Protocol):
    """Provider for handlers that filter elements by predicate.

    Multiple filter predicates are combined with AND logic.

    Args:
        constraint: The constraint to handle.

    Returns:
        A callable that accepts an element and returns True to keep it.
    """

    def get_handler(self, constraint: Any) -> Callable[[Any], bool]:
        """Return a filter predicate handler for the given constraint."""
        ...


@runtime_checkable
class ErrorHandlerProvider(Responsible, Protocol):
    """Provider for handlers that observe or log errors without transforming them.

    Args:
        constraint: The constraint to handle.

    Returns:
        A callable that accepts an exception and performs a side effect.
    """

    def get_handler(self, constraint: Any) -> Callable[[Exception], None]:
        """Return an error handler for the given constraint."""
        ...


@runtime_checkable
class ErrorMappingConstraintHandlerProvider(Responsible, Protocol):
    """Provider for handlers that transform errors.

    Handlers are composed in priority order (highest priority first).

    Args:
        constraint: The constraint to handle.

    Returns:
        A callable that accepts an exception and returns a (possibly different) exception.
    """

    def get_priority(self) -> int:
        """Return the priority for ordering. Higher values execute first."""
        ...

    def get_handler(self, constraint: Any) -> Callable[[Exception], Exception]:
        """Return an error mapping handler for the given constraint."""
        ...


@runtime_checkable
class MethodInvocationConstraintHandlerProvider(Responsible, Protocol):
    """Provider for handlers that modify the method invocation context before execution.

    Args:
        constraint: The constraint to handle.

    Returns:
        A callable that mutates a MethodInvocationContext in place.
    """

    def get_handler(self, constraint: Any) -> Callable[[MethodInvocationContext], None]:
        """Return a method invocation handler for the given constraint."""
        ...


@dataclass
class MethodInvocationContext:
    """Mutable context for method invocation handlers.

    Handlers can modify ``args`` and ``kwargs`` before the protected method executes.

    Args:
        args: Positional arguments to the protected method.
        kwargs: Keyword arguments to the protected method.
        function_name: Name of the protected method.
        class_name: Qualified class name of the method (empty for plain functions).
        request: Framework request object, or None for service-layer calls.
    """

    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    function_name: str = ""
    class_name: str = ""
    request: Any = None
