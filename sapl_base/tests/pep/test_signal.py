from __future__ import annotations

import pytest

from sapl_base.pep import (
    DECISION,
    ERROR,
    INPUT,
    OUTPUT,
    Signal,
    SignalKind,
)
from sapl_base.pep.streaming import (
    CANCEL_SIGNAL,
    COMPLETE,
    TERMINATION,
)


@pytest.mark.parametrize(
    "kind, expected",
    [
        (DECISION, False),
        (INPUT, True),
        (OUTPUT, True),
        (ERROR, True),
        (CANCEL_SIGNAL, False),
        (COMPLETE, False),
        (TERMINATION, False),
    ],
)
def test_kind_exposes_data_carrying_directly(kind: SignalKind, expected: bool) -> None:
    assert kind.data_carrying is expected


def test_signal_kind_str_returns_name() -> None:
    assert str(DECISION) == "decision"
    assert str(OUTPUT) == "output"
    assert str(TERMINATION) == "termination"


def test_signal_kind_equality_is_by_name() -> None:
    """Two SignalKind instances with the same name compare equal and share a hash."""
    a = SignalKind("decision", data_carrying=False)
    b = SignalKind("decision", data_carrying=False)
    assert a == b
    assert hash(a) == hash(b)
    assert a == DECISION


def test_signal_protocol_is_satisfied_by_any_kind_carrier() -> None:
    """Anything with a `kind: SignalKind` attribute is a Signal."""

    class _Anon:
        def __init__(self) -> None:
            self.kind = DECISION

    assert isinstance(_Anon(), Signal)
