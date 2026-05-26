from __future__ import annotations

import pytest
from sqlalchemy import select

from sapl_sqlalchemy import SQL_QUERY, SqlQuerySignal


def test_signal_kind_name_is_namespaced() -> None:
    assert SQL_QUERY.name == "sqlalchemy_sql_query"


def test_signal_kind_is_data_carrying() -> None:
    assert SQL_QUERY.data_carrying is True


def test_signal_dataclass_carries_value() -> None:
    stmt = select(1)
    sig = SqlQuerySignal(value=stmt)
    assert sig.value is stmt
    assert sig.kind is SQL_QUERY


def test_signal_dataclass_is_frozen() -> None:
    sig = SqlQuerySignal(value=select(1))
    with pytest.raises((AttributeError, TypeError)):
        sig.value = select(2)  # type: ignore[misc]
