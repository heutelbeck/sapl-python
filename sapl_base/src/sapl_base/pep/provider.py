"""Constraint handler provider Protocol and scoped-handler shape.

A `ConstraintHandlerProvider` claims a constraint and returns the
set of scoped handlers that together enforce it. One constraint
may drive multiple handlers at different signals (e.g. a metric
that stamps a start time on `decision` and records elapsed time on
`complete`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from sapl_base.pep.signal import SignalKind

HandlerShape = Literal["runner", "consumer", "mapper"]
"""A runner is `() -> None`. A consumer is `(value) -> None`.
A mapper is `(value) -> value`. Mappers and consumers are
admissible only at data-carrying signals."""

ConstraintTag = Literal["obligation", "advice"]
"""An obligation MUST be discharged or the decision becomes a deny.
An advice MAY be discharged; its failure is logged and ignored."""


@dataclass(frozen=True, slots=True)
class ScopedHandler:
    """One handler scheduled at one signal, with a priority.

    The provider returns a sequence of these; the planner assembles
    them into a per-signal execution sequence.
    """

    signal: SignalKind
    priority: int
    shape: HandlerShape
    handler: Callable[..., Any]


@runtime_checkable
class ConstraintHandlerProvider(Protocol):
    """Implementations claim some subset of constraints.

    `get_handlers(constraint)` returns the scoped-handler triples
    for a claimed constraint, or an empty sequence for constraints
    this provider does not claim.

    The PEP enforces "exactly one claim per constraint" at plan-
    construction time: if more than one provider claims the same
    constraint, or no provider claims it, the planner replaces the
    claim with a synthetic failure runner.
    """

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        ...
