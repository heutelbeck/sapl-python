"""Cell-level content tests for `step(state, event)`.

Each row of `mealy-table.csv` is one cell of the transition function.
This file is one parameterised test over the canonical table.

The CSV is shared verbatim with the Java and TypeScript test suites.
Rows whose event is `PdpError` or `RapError` are skipped here because
those events are not in Python's alphabet (transport errors are
handled outside the FSM at the async-iterator boundary). Rows with
event `RapItem` are translated through the bijection
`{Present, Absent, Failed} -> {RapItem(value), RapEpsilon, RapObligationFailure}`
by `mealy_test_support.event_by_name`.

Semantic-subset claims (Lean theorems) live in
`test_mealy_invariant.py`.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from sapl_base.pep.streaming.mealy import step

from .mealy_test_support import (
    EVENTS_NOT_IN_PYTHON_ALPHABET,
    emission_kind,
    event_by_name,
    state_by_name,
)


def _load_rows() -> list[tuple[str, str, str, str, str]]:
    path = Path(__file__).parent / "mealy-table.csv"
    rows: list[tuple[str, str, str, str, str]] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row["event"] in EVENTS_NOT_IN_PYTHON_ALPHABET:
                continue
            rows.append((row["from"], row["event"], row["outcome"], row["to"], row["emissions"]))
    return rows


def _parse_emissions(raw: str) -> list[str]:
    if not raw:
        return []
    return raw.split("|")


_ROWS = _load_rows()


@pytest.mark.parametrize(
    ("from_", "event", "outcome", "to", "emissions"),
    _ROWS,
    ids=[f"{r[0]}-{r[1]}{f'-{r[2]}' if r[2] else ''}" for r in _ROWS],
)
def test_cell(from_: str, event: str, outcome: str, to: str, emissions: str) -> None:
    source_state = state_by_name(from_)
    trigger_event = event_by_name(event, outcome)
    expected_state = state_by_name(to)
    expected_emissions = _parse_emissions(emissions)

    result = step(source_state, trigger_event)

    assert type(result.state) is type(expected_state)
    assert [emission_kind(e) for e in result.emissions] == expected_emissions
