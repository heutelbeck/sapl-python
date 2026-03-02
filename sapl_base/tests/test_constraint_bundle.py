from __future__ import annotations

from typing import Any

import pytest

from sapl_base.constraint_bundle import (
    AccessDeniedError,
    ConstraintHandlerBundle,
    StreamingConstraintHandlerBundle,
    UnhandledObligationError,
)
from sapl_base.constraint_types import MethodInvocationContext
from sapl_base.types import RESOURCE_ABSENT


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


def _noop_method_invocation(_context: MethodInvocationContext) -> None:
    pass


def _make_bundle(
    on_decision_handlers: Any = None,
    method_invocation_handlers: Any = None,
    on_next_consumers: Any = None,
    on_next_mappings: Any = None,
    filter_predicates: Any = None,
    on_error_handlers: Any = None,
    on_error_mappings: Any = None,
    resource_replacement: Any = RESOURCE_ABSENT,
) -> ConstraintHandlerBundle:
    return ConstraintHandlerBundle(
        on_decision_handlers=on_decision_handlers or _noop,
        method_invocation_handlers=method_invocation_handlers or _noop_method_invocation,
        on_next_consumers=on_next_consumers or _noop_consumer,
        on_next_mappings=on_next_mappings or _identity,
        filter_predicates=filter_predicates or _always_true,
        on_error_handlers=on_error_handlers or _noop_error_handler,
        on_error_mappings=on_error_mappings or _identity_error,
        resource_replacement=resource_replacement,
    )


class TestUnhandledObligationError:
    """UnhandledObligationError carries constraint data and is an AccessDeniedError."""

    def test_stores_constraints(self) -> None:
        constraints = [{"type": "log"}, {"type": "audit"}]
        error = UnhandledObligationError(constraints)
        assert error.constraints == constraints

    def test_is_access_denied_error(self) -> None:
        error = UnhandledObligationError([])
        assert isinstance(error, AccessDeniedError)

    def test_message_contains_constraints(self) -> None:
        error = UnhandledObligationError([{"type": "missing"}])
        assert "missing" in str(error)


class TestAccessDeniedError:
    """AccessDeniedError is a plain exception."""

    def test_message(self) -> None:
        error = AccessDeniedError("denied")
        assert str(error) == "denied"

    def test_is_exception(self) -> None:
        assert issubclass(AccessDeniedError, Exception)


class TestOnDecisionHandlers:
    """Bundle executes on-decision handlers."""

    def test_handler_called(self) -> None:
        called = []
        bundle = _make_bundle(on_decision_handlers=lambda: called.append(True))
        bundle.handle_on_decision_constraints()
        assert called == [True]


class TestMethodInvocationHandlers:
    """Bundle executes method invocation handlers."""

    def test_handler_mutates_context(self) -> None:
        def handler(ctx: MethodInvocationContext) -> None:
            ctx.args.append("added")

        bundle = _make_bundle(method_invocation_handlers=handler)
        context = MethodInvocationContext(args=[], kwargs={}, function_name="fn")
        bundle.handle_method_invocation_handlers(context)
        assert context.args == ["added"]


class TestResourceReplacement:
    """Resource replacement in the on-next pipeline."""

    def test_absent_resource_passes_original_value(self) -> None:
        bundle = _make_bundle()
        result = bundle.handle_all_on_next_constraints("original")
        assert result == "original"

    def test_present_resource_replaces_value(self) -> None:
        bundle = _make_bundle(resource_replacement={"replaced": True})
        result = bundle.handle_all_on_next_constraints("original")
        assert result == {"replaced": True}

    def test_none_resource_replaces_value_with_none(self) -> None:
        bundle = _make_bundle(resource_replacement=None)
        result = bundle.handle_all_on_next_constraints("original")
        assert result is None


class TestFilterPredicate:
    """Filter predicate behavior for scalars and lists."""

    def test_scalar_passes_when_predicate_true(self) -> None:
        bundle = _make_bundle(filter_predicates=lambda v: True)
        result = bundle.handle_all_on_next_constraints("value")
        assert result == "value"

    def test_scalar_rejected_raises_access_denied(self) -> None:
        bundle = _make_bundle(filter_predicates=lambda v: False)
        with pytest.raises(AccessDeniedError):
            bundle.handle_all_on_next_constraints("value")

    def test_list_elements_filtered(self) -> None:
        bundle = _make_bundle(filter_predicates=lambda v: v > 0)
        result = bundle.handle_all_on_next_constraints([1, -2, 3, -4, 5])
        assert result == [1, 3, 5]

    def test_list_all_elements_filtered_returns_empty_list(self) -> None:
        bundle = _make_bundle(filter_predicates=lambda v: False)
        result = bundle.handle_all_on_next_constraints([1, 2, 3])
        assert result == []


class TestOnNextPipeline:
    """Full on-next pipeline: resource replacement -> filter -> consumer -> mapping."""

    def test_consumer_receives_value_before_mapping(self) -> None:
        received: list[Any] = []
        bundle = _make_bundle(
            on_next_consumers=lambda v: received.append(v),
            on_next_mappings=lambda v: v.upper(),
        )
        result = bundle.handle_all_on_next_constraints("hello")
        assert received == ["hello"]
        assert result == "HELLO"

    def test_filter_then_consumer_then_mapping(self) -> None:
        received: list[Any] = []
        bundle = _make_bundle(
            filter_predicates=lambda v: v > 0,
            on_next_consumers=lambda v: received.append(v),
            on_next_mappings=lambda v: [x * 2 for x in v],
        )
        result = bundle.handle_all_on_next_constraints([1, -2, 3])
        assert received == [[1, 3]]
        assert result == [2, 6]

    def test_resource_replacement_then_filter_then_consumer_then_mapping(self) -> None:
        received: list[Any] = []
        bundle = _make_bundle(
            resource_replacement="replaced",
            filter_predicates=lambda v: True,
            on_next_consumers=lambda v: received.append(v),
            on_next_mappings=lambda v: v.upper(),
        )
        result = bundle.handle_all_on_next_constraints("original")
        assert received == ["replaced"]
        assert result == "REPLACED"


class TestOnErrorPipeline:
    """On-error pipeline: error handler -> error mapping."""

    def test_error_handler_called_before_mapping(self) -> None:
        handled: list[Exception] = []
        bundle = _make_bundle(
            on_error_handlers=lambda e: handled.append(e),
            on_error_mappings=lambda e: RuntimeError(str(e)),
        )
        original = ValueError("test")
        result = bundle.handle_all_on_error_constraints(original)
        assert handled == [original]
        assert isinstance(result, RuntimeError)
        assert str(result) == "test"

    def test_identity_error_mapping(self) -> None:
        bundle = _make_bundle()
        original = ValueError("unchanged")
        result = bundle.handle_all_on_error_constraints(original)
        assert result is original


class TestStreamingConstraintHandlerBundle:
    """Streaming bundle lifecycle signals."""

    def test_on_complete(self) -> None:
        called: list[str] = []
        bundle = StreamingConstraintHandlerBundle(
            on_decision_handlers=_noop,
            method_invocation_handlers=_noop_method_invocation,
            on_next_consumers=_noop_consumer,
            on_next_mappings=_identity,
            filter_predicates=_always_true,
            on_error_handlers=_noop_error_handler,
            on_error_mappings=_identity_error,
            on_complete_handlers=lambda: called.append("complete"),
            on_cancel_handlers=_noop,
        )
        bundle.handle_on_complete_constraints()
        assert called == ["complete"]

    def test_on_cancel(self) -> None:
        called: list[str] = []
        bundle = StreamingConstraintHandlerBundle(
            on_decision_handlers=_noop,
            method_invocation_handlers=_noop_method_invocation,
            on_next_consumers=_noop_consumer,
            on_next_mappings=_identity,
            filter_predicates=_always_true,
            on_error_handlers=_noop_error_handler,
            on_error_mappings=_identity_error,
            on_complete_handlers=_noop,
            on_cancel_handlers=lambda: called.append("cancel"),
        )
        bundle.handle_on_cancel_constraints()
        assert called == ["cancel"]

    def test_inherits_on_next_behavior(self) -> None:
        bundle = StreamingConstraintHandlerBundle(
            on_decision_handlers=_noop,
            method_invocation_handlers=_noop_method_invocation,
            on_next_consumers=_noop_consumer,
            on_next_mappings=lambda v: v * 2,
            filter_predicates=_always_true,
            on_error_handlers=_noop_error_handler,
            on_error_mappings=_identity_error,
            on_complete_handlers=_noop,
            on_cancel_handlers=_noop,
        )
        result = bundle.handle_all_on_next_constraints(5)
        assert result == 10

    def test_is_constraint_handler_bundle(self) -> None:
        bundle = StreamingConstraintHandlerBundle(
            on_decision_handlers=_noop,
            method_invocation_handlers=_noop_method_invocation,
            on_next_consumers=_noop_consumer,
            on_next_mappings=_identity,
            filter_predicates=_always_true,
            on_error_handlers=_noop_error_handler,
            on_error_mappings=_identity_error,
        )
        assert isinstance(bundle, ConstraintHandlerBundle)

    def test_default_lifecycle_handlers_are_noop(self) -> None:
        bundle = StreamingConstraintHandlerBundle(
            on_decision_handlers=_noop,
            method_invocation_handlers=_noop_method_invocation,
            on_next_consumers=_noop_consumer,
            on_next_mappings=_identity,
            filter_predicates=_always_true,
            on_error_handlers=_noop_error_handler,
            on_error_mappings=_identity_error,
        )
        bundle.handle_on_complete_constraints()
        bundle.handle_on_cancel_constraints()
