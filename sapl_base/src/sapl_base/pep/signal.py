"""Open signal taxonomy.

`SignalKind` is a self-describing tag: a name plus the
`data_carrying` flag that drives admissibility for mappers and
consumers. PEP layers (one-shot, streaming, framework-specific
shims) declare their own `SignalKind` constants at module level
and pass the supported set to the planner.

A `Signal` is anything that exposes a `kind: SignalKind`
attribute. The Protocol uses structural typing so PEPs may define
their own signal dataclasses without referencing a closed union.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SignalKind:
    """Identity-by-name tag for one PEP signal.

    `data_carrying` is True iff the signal carries a value that
    mappers and consumers can transform or observe. Self-contained
    signals (decision, lifecycle markers) admit runners only.
    """

    name: str
    data_carrying: bool

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SignalKind) and self.name == other.name

    def __str__(self) -> str:
        return self.name


@runtime_checkable
class Signal(Protocol):
    """Anything that carries a `SignalKind` tag.

    PEP layers define their own signal dataclasses; they only need
    a `kind: SignalKind` attribute to participate in plan
    execution.
    """

    @property
    def kind(self) -> SignalKind: ...
