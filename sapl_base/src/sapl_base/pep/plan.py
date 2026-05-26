"""Enforcement plan and best-effort execution.

`EnforcementPlan` is the per-decision artefact produced by
`EnforcementPlanner`. It carries a per-signal sequence of
`PlanEntry` records and exposes a single operation, `execute`,
which runs all entries scheduled at a given signal.

`execute` is total: it never raises. Handler failures are logged
and recorded in the returned `PlanResult.failure_state`. Callers
inspect that flag and decide whether to raise an
`AccessDeniedError` (one-shot decoration) or transition the FSM
into Terminated (streaming).

Mappers may return the `DROP` sentinel to signal that the value
should be removed from the pipeline. Subsequent mappers and
consumers in the same `execute` call are skipped after a DROP.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable, Final

import structlog

from sapl_base.pep.provider import ConstraintTag, HandlerShape
from sapl_base.pep.signal import Signal, SignalKind

logger = structlog.get_logger(__name__)


class _Absent:
    """Sentinel for "no value" (used after a DROP or at void signals)."""

    _INSTANCE: "_Absent | None" = None

    def __new__(cls) -> "_Absent":
        if cls._INSTANCE is None:
            cls._INSTANCE = super().__new__(cls)
        return cls._INSTANCE

    def __repr__(self) -> str:
        return "<ABSENT>"


ABSENT: Final[_Absent] = _Absent()


class _Drop:
    """Sentinel returned by a mapper to drop the current item."""

    _INSTANCE: "_Drop | None" = None

    def __new__(cls) -> "_Drop":
        if cls._INSTANCE is None:
            cls._INSTANCE = super().__new__(cls)
        return cls._INSTANCE

    def __repr__(self) -> str:
        return "<DROP>"


DROP: Final[_Drop] = _Drop()


@dataclass(frozen=True, slots=True)
class PlanEntry:
    """One handler scheduled at one signal at one priority.

    `constraint` is kept so synthetic-failure-runner logs and audit
    consumers can identify which constraint produced this entry.
    """

    signal: SignalKind
    priority: int
    shape: HandlerShape
    tag: ConstraintTag
    constraint: Any
    handler: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class PlanResult:
    """Result of executing all entries at one signal.

    `value` is the threaded value after all mappers / consumers
    have run, or `ABSENT` if a mapper returned `DROP` or the signal
    is void. `failure_state` is True if any obligation-tagged
    handler raised.
    """

    value: Any
    failure_state: bool


class EnforcementPlan:
    """Per-decision, signal-keyed handler schedule.

    Construct via `EnforcementPlanner.plan(decision, supported_signals)`.
    Execute via `plan.execute(signal)` once per fired signal.
    """

    __slots__ = ("_entries",)

    def __init__(
        self,
        entries: Mapping[SignalKind, Sequence[PlanEntry]],
    ) -> None:
        self._entries: dict[SignalKind, tuple[PlanEntry, ...]] = {
            kind: tuple(seq) for kind, seq in entries.items() if seq
        }

    def entries_for(self, signal: SignalKind) -> tuple[PlanEntry, ...]:
        """Return the scheduled entries at `signal` (possibly empty)."""
        return self._entries.get(signal, ())

    def has_entries(self, signal: SignalKind) -> bool:
        return signal in self._entries

    def execute(
        self,
        signal: Signal,
        prior_failure: bool = False,
    ) -> PlanResult:
        """Run all entries scheduled at `signal.kind` in order.

        Best-effort discharge: a handler failure is logged and
        recorded; execution continues through the remaining
        handlers. The returned `failure_state` is True if any
        obligation-tagged handler raised.

        For void (non-data-carrying) signals and the self-contained
        decision signal, only runners execute; mappers and consumers
        are skipped if the plan happens to carry any (the planner
        guarantees it will not, but the executor stays defensive).
        """
        value: Any = ABSENT
        if signal.kind.data_carrying:
            value = _signal_value(signal)

        failure_state = prior_failure

        for entry in self._entries.get(signal.kind, ()):
            try:
                if entry.shape == "runner":
                    entry.handler()
                elif value is ABSENT:
                    continue
                elif entry.shape == "mapper":
                    result = entry.handler(value)
                    if result is DROP:
                        value = ABSENT
                    else:
                        value = result
                else:
                    entry.handler(value)
            except Exception as error:
                logger.warning(
                    "constraint_handler_failed",
                    signal=signal.kind.name,
                    shape=entry.shape,
                    tag=entry.tag,
                    constraint=entry.constraint,
                    error=str(error),
                    error_type=type(error).__name__,
                )
                if entry.tag == "obligation":
                    failure_state = True

        return PlanResult(value=value, failure_state=failure_state)


def _signal_value(signal: Signal) -> Any:
    """Extract the carried value from a data-carrying signal.

    Recognized attribute shapes:
    - `args` + `kwargs`  -> a `(args, kwargs)` tuple (input signals).
    - `value`            -> the value as-is (output signals).
    - `error`            -> the exception (error signals).

    Falls through to `ABSENT` when no recognized attribute is
    present, even on a data-carrying signal: the executor then
    runs only runners at that signal.
    """
    if hasattr(signal, "args") and hasattr(signal, "kwargs"):
        return (signal.args, signal.kwargs)
    if hasattr(signal, "value"):
        return signal.value
    if hasattr(signal, "error"):
        return signal.error
    return ABSENT
