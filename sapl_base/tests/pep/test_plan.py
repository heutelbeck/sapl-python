from __future__ import annotations

from typing import Any

import pytest

from sapl_base.pep import (
    ABSENT,
    DECISION,
    DROP,
    ERROR,
    INPUT,
    OUTPUT,
    DecisionSignal,
    EnforcementPlan,
    ErrorSignal,
    InputSignal,
    OutputSignal,
    PlanEntry,
    SignalKind,
)
from sapl_base.pep.streaming import (
    CancelSignal,
    CompleteSignal,
    TerminationSignal,
)


def _runner(record: list[str], label: str, *, raises: bool = False) -> Any:
    def _run() -> None:
        record.append(label)
        if raises:
            raise RuntimeError(f"{label} failed")
    return _run


def _consumer(record: list[tuple[str, Any]], label: str) -> Any:
    def _consume(value: Any) -> None:
        record.append((label, value))
    return _consume


def _mapper(record: list[tuple[str, Any]], label: str, transform: Any) -> Any:
    def _map(value: Any) -> Any:
        record.append((label, value))
        return transform(value) if callable(transform) else transform
    return _map


def _entry(
    signal: SignalKind,
    shape: str,
    handler: Any,
    *,
    priority: int = 0,
    tag: str = "obligation",
    constraint: Any = None,
) -> PlanEntry:
    return PlanEntry(
        signal=signal,
        priority=priority,
        shape=shape,  # type: ignore[arg-type]
        tag=tag,  # type: ignore[arg-type]
        constraint=constraint or {"type": "test"},
        handler=handler,
    )


class TestExecuteRunners:
    def test_runner_invoked_with_no_args(self) -> None:
        log: list[str] = []
        plan = EnforcementPlan(
            {DECISION: [_entry(DECISION, "runner", _runner(log, "audit"))]}
        )
        result = plan.execute(DecisionSignal())
        assert log == ["audit"]
        assert result.failure_state is False
        assert result.value is ABSENT


class TestExecuteMappersAndConsumers:
    def test_mapper_threads_value(self) -> None:
        log: list[tuple[str, Any]] = []
        plan = EnforcementPlan(
            {
                OUTPUT: [
                    _entry(OUTPUT, "mapper", _mapper(log, "m1", lambda v: v + 1)),
                    _entry(OUTPUT, "mapper", _mapper(log, "m2", lambda v: v * 10), priority=1),
                ]
            }
        )
        result = plan.execute(OutputSignal(value=5))
        assert result.value == 60
        assert log == [("m1", 5), ("m2", 6)]

    def test_consumer_observes_but_does_not_transform(self) -> None:
        log: list[tuple[str, Any]] = []
        plan = EnforcementPlan(
            {
                OUTPUT: [
                    _entry(OUTPUT, "mapper", _mapper(log, "m", lambda v: v + 1)),
                    _entry(OUTPUT, "consumer", _consumer(log, "c"), priority=1),
                ]
            }
        )
        result = plan.execute(OutputSignal(value=10))
        assert result.value == 11
        assert log == [("m", 10), ("c", 11)]

    def test_mapper_returning_drop_sets_value_absent_and_skips_followups(self) -> None:
        log: list[tuple[str, Any]] = []
        plan = EnforcementPlan(
            {
                OUTPUT: [
                    _entry(OUTPUT, "mapper", _mapper(log, "m1", lambda _: DROP)),
                    _entry(OUTPUT, "consumer", _consumer(log, "c"), priority=1),
                ]
            }
        )
        result = plan.execute(OutputSignal(value="x"))
        assert result.value is ABSENT
        assert log == [("m1", "x")]


class TestBestEffortDischarge:
    def test_obligation_failure_sets_state_but_continues(self) -> None:
        log: list[str] = []
        plan = EnforcementPlan(
            {
                DECISION: [
                    _entry(DECISION, "runner", _runner(log, "first", raises=True)),
                    _entry(DECISION, "runner", _runner(log, "second")),
                ]
            }
        )
        result = plan.execute(DecisionSignal())
        assert log == ["first", "second"]
        assert result.failure_state is True

    def test_advice_failure_does_not_set_failure_state(self) -> None:
        log: list[str] = []
        plan = EnforcementPlan(
            {
                DECISION: [
                    _entry(
                        DECISION,
                        "runner",
                        _runner(log, "first", raises=True),
                        tag="advice",
                    )
                ]
            }
        )
        result = plan.execute(DecisionSignal())
        assert result.failure_state is False

    def test_prior_failure_propagates_into_returned_state(self) -> None:
        plan = EnforcementPlan({DECISION: []})
        result = plan.execute(DecisionSignal(), prior_failure=True)
        assert result.failure_state is True


@pytest.mark.parametrize(
    "signal_factory",
    [
        CancelSignal,
        CompleteSignal,
        TerminationSignal,
    ],
)
def test_void_signals_yield_absent_value(signal_factory: Any) -> None:
    plan = EnforcementPlan({})
    result = plan.execute(signal_factory())
    assert result.value is ABSENT
    assert result.failure_state is False


def test_input_signal_threads_args_kwargs_tuple_through_mappers() -> None:
    def _mapper_drop_first_arg(value: tuple[tuple[Any, ...], dict[str, Any]]) -> Any:
        args, kwargs = value
        return (args[1:], kwargs)

    plan = EnforcementPlan(
        {
            INPUT: [
                _entry(INPUT, "mapper", _mapper_drop_first_arg),
            ]
        }
    )
    result = plan.execute(InputSignal(args=("admin", "doc"), kwargs={"x": 1}))
    assert result.value == (("doc",), {"x": 1})


def test_error_signal_threads_exception_through_mappers() -> None:
    def _wrap(error: BaseException) -> BaseException:
        return RuntimeError(f"wrapped: {error}")

    plan = EnforcementPlan(
        {ERROR: [_entry(ERROR, "mapper", _wrap)]}
    )
    original = ValueError("boom")
    result = plan.execute(ErrorSignal(error=original))
    assert isinstance(result.value, RuntimeError)
    assert "wrapped: boom" in str(result.value)
