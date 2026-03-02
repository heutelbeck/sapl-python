from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from sapl_base.constraint_types import (
    ConsumerConstraintHandlerProvider,
    ErrorHandlerProvider,
    ErrorMappingConstraintHandlerProvider,
    FilterPredicateConstraintHandlerProvider,
    MappingConstraintHandlerProvider,
    MethodInvocationConstraintHandlerProvider,
    MethodInvocationContext,
    Responsible,
    RunnableConstraintHandlerProvider,
    Signal,
    SubscriptionContext,
)


class TestSubscriptionContext:
    """SubscriptionContext construction and immutability."""

    def test_defaults(self) -> None:
        context = SubscriptionContext()
        assert context.args == {}
        assert context.function_name == ""
        assert context.class_name == ""
        assert context.request is None
        assert context.params == {}
        assert context.query == {}
        assert context.body is None
        assert context.return_value is None

    def test_custom_values(self) -> None:
        request_obj = object()
        context = SubscriptionContext(
            args={"x": 1, "y": "hello"},
            function_name="my_func",
            class_name="MyClass",
            request=request_obj,
            params={"id": "42"},
            query={"q": "search"},
            body={"data": "payload"},
            return_value={"result": "ok"},
        )
        assert context.args == {"x": 1, "y": "hello"}
        assert context.function_name == "my_func"
        assert context.class_name == "MyClass"
        assert context.request is request_obj
        assert context.params == {"id": "42"}
        assert context.query == {"q": "search"}
        assert context.body == {"data": "payload"}
        assert context.return_value == {"result": "ok"}

    def test_frozen(self) -> None:
        context = SubscriptionContext(function_name="f")
        with pytest.raises(AttributeError):
            context.function_name = "g"  # type: ignore[misc]


class TestSignal:
    """Signal enum values and identity."""

    def test_signal_values(self) -> None:
        assert Signal.ON_DECISION.value == "ON_DECISION"
        assert Signal.ON_COMPLETE.value == "ON_COMPLETE"
        assert Signal.ON_CANCEL.value == "ON_CANCEL"

    def test_signal_members(self) -> None:
        assert set(Signal) == {Signal.ON_DECISION, Signal.ON_COMPLETE, Signal.ON_CANCEL}


class TestMethodInvocationContext:
    """MethodInvocationContext construction and mutability."""

    def test_defaults(self) -> None:
        context = MethodInvocationContext()
        assert context.args == []
        assert context.kwargs == {}
        assert context.function_name == ""

    def test_defaults_include_class_name_and_request(self) -> None:
        context = MethodInvocationContext()
        assert context.class_name == ""
        assert context.request is None

    def test_custom_values(self) -> None:
        request_obj = object()
        context = MethodInvocationContext(
            args=[1, 2],
            kwargs={"key": "value"},
            function_name="my_function",
            class_name="MyService",
            request=request_obj,
        )
        assert context.args == [1, 2]
        assert context.kwargs == {"key": "value"}
        assert context.function_name == "my_function"
        assert context.class_name == "MyService"
        assert context.request is request_obj

    def test_mutability(self) -> None:
        context = MethodInvocationContext(args=[1], kwargs={"a": 1}, function_name="f")
        context.args.append(2)
        context.kwargs["b"] = 2
        context.function_name = "g"
        assert context.args == [1, 2]
        assert context.kwargs == {"a": 1, "b": 2}
        assert context.function_name == "g"


class TestResponsibleProtocol:
    """Runtime checkability of the Responsible protocol."""

    def test_class_with_is_responsible_satisfies_protocol(self) -> None:
        class MyResponsible:
            def is_responsible(self, constraint: Any) -> bool:
                return True

        assert isinstance(MyResponsible(), Responsible)

    def test_class_without_is_responsible_does_not_satisfy(self) -> None:
        class NotResponsible:
            pass

        assert not isinstance(NotResponsible(), Responsible)


class TestRunnableConstraintHandlerProviderProtocol:
    """Runtime checkability of the RunnableConstraintHandlerProvider protocol."""

    def test_satisfies_protocol(self) -> None:
        class MyRunnable:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_signal(self) -> Signal:
                return Signal.ON_DECISION

            def get_handler(self, constraint: Any) -> Callable[[], None]:
                return lambda: None

        provider = MyRunnable()
        assert isinstance(provider, RunnableConstraintHandlerProvider)
        assert isinstance(provider, Responsible)

    def test_missing_get_signal_does_not_satisfy(self) -> None:
        class Incomplete:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_handler(self, constraint: Any) -> Callable[[], None]:
                return lambda: None

        assert not isinstance(Incomplete(), RunnableConstraintHandlerProvider)


class TestConsumerConstraintHandlerProviderProtocol:
    """Runtime checkability of the ConsumerConstraintHandlerProvider protocol."""

    def test_satisfies_protocol(self) -> None:
        class MyConsumer:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_handler(self, constraint: Any) -> Callable[[Any], None]:
                return lambda v: None

        assert isinstance(MyConsumer(), ConsumerConstraintHandlerProvider)


class TestMappingConstraintHandlerProviderProtocol:
    """Runtime checkability of the MappingConstraintHandlerProvider protocol."""

    def test_satisfies_protocol(self) -> None:
        class MyMapping:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_priority(self) -> int:
                return 0

            def get_handler(self, constraint: Any) -> Callable[[Any], Any]:
                return lambda v: v

        assert isinstance(MyMapping(), MappingConstraintHandlerProvider)

    def test_missing_get_priority_does_not_satisfy(self) -> None:
        class Incomplete:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_handler(self, constraint: Any) -> Callable[[Any], Any]:
                return lambda v: v

        assert not isinstance(Incomplete(), MappingConstraintHandlerProvider)


class TestFilterPredicateConstraintHandlerProviderProtocol:
    """Runtime checkability of the FilterPredicateConstraintHandlerProvider protocol."""

    def test_satisfies_protocol(self) -> None:
        class MyFilter:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_handler(self, constraint: Any) -> Callable[[Any], bool]:
                return lambda v: True

        assert isinstance(MyFilter(), FilterPredicateConstraintHandlerProvider)


class TestErrorHandlerProviderProtocol:
    """Runtime checkability of the ErrorHandlerProvider protocol."""

    def test_satisfies_protocol(self) -> None:
        class MyErrorHandler:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_handler(self, constraint: Any) -> Callable[[Exception], None]:
                return lambda e: None

        assert isinstance(MyErrorHandler(), ErrorHandlerProvider)


class TestErrorMappingConstraintHandlerProviderProtocol:
    """Runtime checkability of the ErrorMappingConstraintHandlerProvider protocol."""

    def test_satisfies_protocol(self) -> None:
        class MyErrorMapping:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_priority(self) -> int:
                return 0

            def get_handler(self, constraint: Any) -> Callable[[Exception], Exception]:
                return lambda e: e

        assert isinstance(MyErrorMapping(), ErrorMappingConstraintHandlerProvider)


class TestMethodInvocationConstraintHandlerProviderProtocol:
    """Runtime checkability of the MethodInvocationConstraintHandlerProvider protocol."""

    def test_satisfies_protocol(self) -> None:
        class MyMethodInvocation:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_handler(self, constraint: Any) -> Callable[[MethodInvocationContext], None]:
                return lambda ctx: None

        assert isinstance(MyMethodInvocation(), MethodInvocationConstraintHandlerProvider)


class TestMultiProtocolProvider:
    """A single class can implement multiple handler protocols."""

    def test_provider_satisfies_multiple_protocols(self) -> None:
        class MultiProvider:
            def is_responsible(self, constraint: Any) -> bool:
                return True

            def get_signal(self) -> Signal:
                return Signal.ON_DECISION

            def get_priority(self) -> int:
                return 0

            def get_handler(self, constraint: Any) -> Any:
                return lambda: None

        provider = MultiProvider()
        assert isinstance(provider, RunnableConstraintHandlerProvider)
        assert isinstance(provider, ConsumerConstraintHandlerProvider)
        assert isinstance(provider, MappingConstraintHandlerProvider)
        assert isinstance(provider, FilterPredicateConstraintHandlerProvider)
        assert isinstance(provider, ErrorHandlerProvider)
        assert isinstance(provider, MethodInvocationConstraintHandlerProvider)
