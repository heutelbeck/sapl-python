"""Enforcement plan construction.

`EnforcementPlanner.plan(decision, supported_signals)` runs the
paper's Algorithm 2:

- Phase 1: per constraint, gather the set of provider claims.
  Admit the unique claim if every triple in it is well-formed for
  the constraint's tag; otherwise schedule a single synthetic
  failure runner at the decision signal at priority 0.
- Phase 2: per signal, sort by ascending priority with tiebreak
  `runner < mapper < consumer`. Replace each non-singleton mapper
  group at equal priority with one synthetic failure runner per
  mapper (commutativity is not guaranteed at construction time).

The planner is stateless apart from its provider list. One
provider per constraint is enforced at construction time: a
constraint claimed by zero or by more than one provider produces
the synthetic-failure-runner outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import structlog

from sapl_base.pep.plan import EnforcementPlan, PlanEntry
from sapl_base.pep.signal import SignalKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sapl_base.pep.provider import (
        ConstraintHandlerProvider,
        ConstraintTag,
        HandlerShape,
        ScopedHandler,
    )
    from sapl_base.types import AuthorizationDecision

logger = structlog.get_logger(__name__)


_SHAPE_ORDER: Final[dict[HandlerShape, int]] = {
    "runner": 0,
    "mapper": 1,
    "consumer": 2,
}

_DECISION: Final[SignalKind] = SignalKind("decision", data_carrying=False)
"""The signal at which synthetic failure runners are scheduled.

Identified by name; equal to any other `SignalKind("decision", ...)`
the caller passes in `supported_signals`. Every PEP layer that
expects synthetic-failure routing to its decision signal must
include a signal kind named `decision` in its supported set.
"""


@dataclass(frozen=True, slots=True)
class _SyntheticFailureError(Exception):
    """Raised by a synthetic failure runner to signal obligation failure."""

    reason: str = "synthetic failure"


@dataclass(slots=True)
class EnforcementPlanner:
    """Builds an `EnforcementPlan` from a decision and the deployed providers."""

    providers: Sequence[ConstraintHandlerProvider] = field(default_factory=tuple)

    def plan(
        self,
        decision: AuthorizationDecision,
        supported_signals: frozenset[SignalKind],
    ) -> EnforcementPlan:
        per_signal: dict[SignalKind, list[PlanEntry]] = {
            kind: [] for kind in supported_signals
        }
        per_signal.setdefault(_DECISION, [])

        for constraint in _iter_constraints(decision.obligations, "obligation"):
            self._resolve_constraint(
                constraint, "obligation", supported_signals, per_signal
            )
        for constraint in _iter_constraints(decision.advice, "advice"):
            self._resolve_constraint(
                constraint, "advice", supported_signals, per_signal
            )

        for kind in list(per_signal.keys()):
            per_signal[kind].sort(key=lambda e: (e.priority, _SHAPE_ORDER[e.shape]))
            kept, displaced = _split_non_commuting_mappers(per_signal[kind])
            per_signal[kind] = kept
            for entry in displaced:
                per_signal.setdefault(_DECISION, []).append(
                    _make_synthetic_entry(entry.constraint, "obligation", "NON_COMMUTING")
                )

        return EnforcementPlan(per_signal)

    def _resolve_constraint(
        self,
        constraint: Any,
        tag: ConstraintTag,
        supported_signals: frozenset[SignalKind],
        per_signal: dict[SignalKind, list[PlanEntry]],
    ) -> None:
        claims: list[tuple[ScopedHandler, ...]] = []
        for provider in self.providers:
            try:
                handlers = tuple(provider.get_handlers(constraint))
            except Exception:  # a misbehaving provider must not crash planning
                logger.warning(
                    "constraint_handler_provider_failed",
                    tag=tag,
                    constraint=constraint,
                    provider=type(provider).__name__,
                    exc_info=True,
                )
                continue
            if handlers:
                claims.append(handlers)

        if len(claims) != 1 or not _all_well_formed(claims[0], tag, supported_signals):
            reason = _classify_rejection(claims)
            _append_synthetic(per_signal, constraint, tag, reason)
            return

        for handler in claims[0]:
            per_signal.setdefault(handler.signal, []).append(
                PlanEntry(
                    signal=handler.signal,
                    priority=handler.priority,
                    shape=handler.shape,
                    tag=tag,
                    constraint=constraint,
                    handler=handler.handler,
                )
            )


def _iter_constraints(value: Any, tag: ConstraintTag) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return value
    logger.warning(
        "decision_constraint_field_not_iterable",
        tag=tag,
        actual_type=type(value).__name__,
    )
    return ()


def _all_well_formed(
    triples: Sequence[ScopedHandler],
    tag: ConstraintTag,
    supported_signals: frozenset[SignalKind],
) -> bool:
    """A claim is well-formed only if EVERY triple in it is well-formed.

    Per paper §5: a triple `(a, s, p)` is well-formed for tag `t`
    when `a` is admissible at `s`, `s` is supported by the PEP,
    and `a` is not a mapper OR `t = obligation`.
    """
    return all(
        _is_admissible(triple) and triple.signal in supported_signals
        and (triple.shape != "mapper" or tag == "obligation")
        for triple in triples
    )


def _is_admissible(triple: ScopedHandler) -> bool:
    if triple.shape == "runner":
        return True
    return triple.signal.data_carrying


def _classify_rejection(claims: list[tuple[ScopedHandler, ...]]) -> str:
    if len(claims) == 0:
        return "UNRESOLVED"
    if len(claims) > 1:
        return "AMBIGUOUS"
    return "INADMISSIBLE"


def _append_synthetic(
    per_signal: dict[SignalKind, list[PlanEntry]],
    constraint: Any,
    tag: ConstraintTag,
    reason: str,
) -> None:
    per_signal.setdefault(_DECISION, []).append(
        _make_synthetic_entry(constraint, tag, reason)
    )


def _make_synthetic_entry(
    constraint: Any,
    tag: ConstraintTag,
    reason: str,
) -> PlanEntry:
    def _run() -> None:
        logger.warning(
            "synthetic_failure_runner",
            reason=reason,
            tag=tag,
            constraint=constraint,
        )
        if tag == "obligation":
            raise _SyntheticFailureError(reason=reason)

    return PlanEntry(
        signal=_DECISION,
        priority=0,
        shape="runner",
        tag=tag,
        constraint=constraint,
        handler=_run,
    )


def _split_non_commuting_mappers(
    entries: list[PlanEntry],
) -> tuple[list[PlanEntry], list[PlanEntry]]:
    """Walk a per-signal sequence and identify same-priority mapper groups.

    Returns `(kept, displaced)`: every mapper in a same-priority group
    larger than one goes into `displaced` (the caller will replace it
    with a synthetic failure runner scheduled at the decision signal).
    Singleton mapper groups are kept in place.
    """
    if not entries:
        return [], []

    kept: list[PlanEntry] = []
    displaced: list[PlanEntry] = []
    run: list[PlanEntry] = []
    run_priority: int | None = None

    def _flush() -> None:
        if not run:
            return
        if len(run) > 1:
            displaced.extend(run)
        else:
            kept.extend(run)
        run.clear()

    for entry in entries:
        if entry.shape == "mapper" and entry.priority == run_priority:
            run.append(entry)
            continue
        _flush()
        if entry.shape == "mapper":
            run.append(entry)
            run_priority = entry.priority
        else:
            run_priority = None
            kept.append(entry)
    _flush()
    return kept, displaced
