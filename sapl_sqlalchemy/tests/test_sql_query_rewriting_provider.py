from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import delete, insert, select, union, update
from sqlalchemy.dialects import sqlite
from tests.models import Patient

from sapl_sqlalchemy import SQL_QUERY, SqlQueryRewritingProvider


def _provider() -> SqlQueryRewritingProvider:
    return SqlQueryRewritingProvider()


def _compile(stmt: Any) -> str:
    return str(
        stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})
    )


def _apply(constraint: Any, stmt: Any) -> Any:
    handlers = _provider().get_handlers(constraint)
    assert len(handlers) == 1
    return handlers[0].handler(stmt)


def _column_select() -> Any:
    return select(
        Patient.__table__.c.id,
        Patient.__table__.c.tenant_id,
        Patient.__table__.c.name,
        Patient.__table__.c.status,
        Patient.__table__.c.deleted_at,
    )


def _leaf(column: str, op: str, value: Any = ...) -> dict[str, Any]:
    leaf: dict[str, Any] = {"column": column, "op": op}
    if value is not ...:
        leaf["value"] = value
    return leaf


def _criteria_constraint(*criteria: Any) -> dict[str, Any]:
    return {"type": "sql:queryRewriting", "criteria": list(criteria)}


class TestResponsibility:
    def test_non_dict_constraint_yields_no_handlers(self) -> None:
        assert _provider().get_handlers("not-a-dict") == ()

    def test_dict_without_type_yields_no_handlers(self) -> None:
        assert _provider().get_handlers({"criteria": []}) == ()

    def test_unrelated_type_yields_no_handlers(self) -> None:
        assert _provider().get_handlers({"type": "audit"}) == ()

    def test_canonical_type_is_claimed(self) -> None:
        c = {"type": "sql:queryRewriting", "criteria": [_leaf("x", "isNull")]}
        assert len(_provider().get_handlers(c)) == 1

    def test_alias_relational_type_is_claimed(self) -> None:
        c = {"type": "relational:queryRewriting", "criteria": [_leaf("x", "isNull")]}
        assert len(_provider().get_handlers(c)) == 1

    def test_empty_constraint_yields_no_handlers(self) -> None:
        assert _provider().get_handlers({"type": "sql:queryRewriting"}) == ()

    def test_one_handler_attaches_to_sql_query(self) -> None:
        c = _criteria_constraint(_leaf("tenant_id", "=", 7))
        handler = _provider().get_handlers(c)[0]
        assert handler.signal is SQL_QUERY
        assert handler.shape == "mapper"
        assert handler.priority == 30


class TestBinaryOperators:
    @pytest.mark.parametrize(
        "op,value,fragment",
        [
            ("=", 7, "tenant_id = 7"),
            ("!=", 7, "tenant_id != 7"),
            (">", 7, "tenant_id > 7"),
            (">=", 7, "tenant_id >= 7"),
            ("<", 7, "tenant_id < 7"),
            ("<=", 7, "tenant_id <= 7"),
        ],
    )
    def test_numeric_binary(self, op: str, value: int, fragment: str) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("tenant_id", op, value)), _column_select()
        )
        assert fragment in _compile(stmt)

    def test_text_equality_renders_quoted_literal(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("name", "=", "alice")), _column_select()
        )
        assert "name = 'alice'" in _compile(stmt)

    def test_text_equality_escapes_single_quote(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("name", "=", "O'Brien")), _column_select()
        )
        assert "O''Brien" in _compile(stmt)

    def test_boolean_equality(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("status", "=", True)), _column_select()
        )
        sql = _compile(stmt)
        assert "= 1" in sql or "= true" in sql.lower()


class TestInOperator:
    def test_in_numeric_array(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("tenant_id", "in", [1, 2, 3])),
            _column_select(),
        )
        sql = _compile(stmt)
        assert "tenant_id IN" in sql
        for value in ("1", "2", "3"):
            assert value in sql

    def test_in_text_array(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("status", "in", ["active", "pending"])),
            _column_select(),
        )
        sql = _compile(stmt)
        assert "status IN" in sql
        assert "'active'" in sql and "'pending'" in sql

    def test_in_with_non_array_value_raises(self) -> None:
        with pytest.raises(ValueError, match="VALUE_KIND_FOR_OPERATOR"):
            _apply(
                _criteria_constraint(_leaf("tenant_id", "in", 7)), _column_select()
            )


class TestLikeOperators:
    def test_like_text(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("name", "like", "ali%")), _column_select()
        )
        assert "name LIKE 'ali%'" in _compile(stmt)

    def test_not_like_text(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("name", "notLike", "ali%")),
            _column_select(),
        )
        sql = _compile(stmt)
        assert "name NOT LIKE 'ali%'" in sql

    @pytest.mark.parametrize("op", ["like", "notLike"])
    def test_non_text_value_raises(self, op: str) -> None:
        with pytest.raises(ValueError, match="VALUE_KIND_FOR_OPERATOR"):
            _apply(
                _criteria_constraint(_leaf("name", op, 7)), _column_select()
            )


class TestNullOperators:
    def test_is_null(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("deleted_at", "isNull")),
            _column_select(),
        )
        assert "deleted_at IS NULL" in _compile(stmt)

    def test_is_not_null(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("deleted_at", "isNotNull")),
            _column_select(),
        )
        assert "deleted_at IS NOT NULL" in _compile(stmt)


class TestTreeComposition:
    def test_top_level_array_and_combines(self) -> None:
        stmt = _apply(
            _criteria_constraint(
                _leaf("tenant_id", "=", 7),
                _leaf("status", "=", "active"),
            ),
            _column_select(),
        )
        sql = _compile(stmt)
        assert "tenant_id = 7" in sql
        assert "status = 'active'" in sql
        assert "AND" in sql

    def test_or_group(self) -> None:
        stmt = _apply(
            _criteria_constraint(
                {"or": [
                    _leaf("tenant_id", "=", 1),
                    _leaf("tenant_id", "=", 2),
                ]}
            ),
            _column_select(),
        )
        sql = _compile(stmt)
        assert "tenant_id = 1 OR tenant_id = 2" in sql or "tenant_id = 2 OR tenant_id = 1" in sql

    def test_and_group(self) -> None:
        stmt = _apply(
            _criteria_constraint(
                {"and": [
                    _leaf("tenant_id", "=", 1),
                    _leaf("status", "=", "active"),
                ]}
            ),
            _column_select(),
        )
        sql = _compile(stmt)
        assert "tenant_id = 1 AND status = 'active'" in sql

    def test_nested_or_inside_and(self) -> None:
        stmt = _apply(
            _criteria_constraint(
                _leaf("tenant_id", "=", 7),
                {"or": [
                    _leaf("status", "=", "active"),
                    _leaf("status", "=", "pending"),
                ]},
            ),
            _column_select(),
        )
        sql = _compile(stmt)
        assert "tenant_id = 7" in sql
        assert "status = 'active' OR status = 'pending'" in sql


class TestConditions:
    def test_single_condition_fragment(self) -> None:
        stmt = _apply(
            {
                "type": "sql:queryRewriting",
                "conditions": ["status IN ('active', 'pending')"],
            },
            _column_select(),
        )
        sql = _compile(stmt)
        assert "status IN ('active', 'pending')" in sql

    def test_criteria_and_conditions_combine(self) -> None:
        stmt = _apply(
            {
                "type": "sql:queryRewriting",
                "criteria": [_leaf("tenant_id", "=", 7)],
                "conditions": ["status IN ('active', 'pending')"],
            },
            _column_select(),
        )
        sql = _compile(stmt)
        assert "tenant_id = 7" in sql
        assert "status IN ('active', 'pending')" in sql


class TestColumnsProjection:
    def test_intersection_narrows_select_list(self) -> None:
        stmt = _apply(
            {
                "type": "sql:queryRewriting",
                "columns": ["id", "name"],
            },
            _column_select(),
        )
        sql = _compile(stmt)
        assert "patient.id" in sql.replace('"', "")
        assert "patient.name" in sql.replace('"', "")
        assert "patient.status" not in sql.replace('"', "")
        assert "patient.deleted_at" not in sql.replace('"', "")

    def test_empty_intersection_yields_empty_projection(self) -> None:
        stmt = _apply(
            {"type": "sql:queryRewriting", "columns": ["nonexistent"]},
            _column_select(),
        )
        sql = _compile(stmt).replace('"', "")
        assert "patient.status" not in sql
        assert "patient.name" not in sql

    def test_columns_against_entity_select_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="COLUMNS_AGAINST_ENTITY_SELECT"):
            _apply(
                {"type": "sql:queryRewriting", "columns": ["id"]},
                select(Patient),
            )

    def test_columns_ignored_on_update(self) -> None:
        stmt = _apply(
            {
                "type": "sql:queryRewriting",
                "criteria": [_leaf("tenant_id", "=", 7)],
                "columns": ["id"],
            },
            update(Patient).values(status="archived"),
        )
        sql = _compile(stmt)
        assert "tenant_id = 7" in sql

    def test_columns_ignored_on_delete(self) -> None:
        stmt = _apply(
            {
                "type": "sql:queryRewriting",
                "criteria": [_leaf("tenant_id", "=", 7)],
                "columns": ["id"],
            },
            delete(Patient),
        )
        sql = _compile(stmt)
        assert "tenant_id = 7" in sql


class TestStatementTypes:
    def test_update_gets_where_injected(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("tenant_id", "=", 7)),
            update(Patient).values(status="archived"),
        )
        sql = _compile(stmt)
        assert sql.upper().startswith("UPDATE")
        assert "tenant_id = 7" in sql

    def test_delete_gets_where_injected(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("tenant_id", "=", 7)),
            delete(Patient),
        )
        sql = _compile(stmt)
        assert sql.upper().startswith("DELETE")
        assert "tenant_id = 7" in sql

    def test_insert_with_predicates_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="UNSUPPORTED_STATEMENT"):
            _apply(
                _criteria_constraint(_leaf("tenant_id", "=", 7)),
                insert(Patient).values(id=1, tenant_id=7, name="alice"),
            )

    def test_set_operation_select_with_conditions_fails_closed(self) -> None:
        stmt_a = select(Patient.__table__.c.id).where(Patient.__table__.c.tenant_id == 1)
        stmt_b = select(Patient.__table__.c.id).where(Patient.__table__.c.tenant_id == 2)
        with pytest.raises(ValueError, match="SET_OPERATION_WITH_CONDITIONS"):
            _apply(
                _criteria_constraint(_leaf("status", "=", "active")),
                union(stmt_a, stmt_b),
            )


class TestFailClosedLeaves:
    def test_missing_column(self) -> None:
        with pytest.raises(ValueError, match="MISSING_COLUMN"):
            _apply(_criteria_constraint({"op": "=", "value": 7}), _column_select())

    def test_missing_op(self) -> None:
        with pytest.raises(ValueError, match="MISSING_OP"):
            _apply(
                _criteria_constraint({"column": "x", "value": 7}), _column_select()
            )

    def test_unsupported_operator(self) -> None:
        with pytest.raises(ValueError, match="UNSUPPORTED_OPERATOR"):
            _apply(
                _criteria_constraint(_leaf("x", "regex", "foo")), _column_select()
            )

    def test_value_required_for_binary_op(self) -> None:
        with pytest.raises(ValueError, match="VALUE_REQUIRED"):
            _apply(_criteria_constraint(_leaf("x", "=")), _column_select())

    def test_value_null_for_binary_op_treated_as_missing(self) -> None:
        with pytest.raises(ValueError, match="VALUE_REQUIRED"):
            _apply(
                _criteria_constraint({"column": "x", "op": "=", "value": None}),
                _column_select(),
            )

    def test_unsupported_value_kind(self) -> None:
        with pytest.raises(ValueError, match="VALUE_KIND_FOR_OPERATOR"):
            _apply(
                _criteria_constraint(
                    {"column": "x", "op": "=", "value": {"nested": "dict"}}
                ),
                _column_select(),
            )


class TestPreservesExistingWhere:
    def test_select_with_existing_where_is_and_combined(self) -> None:
        existing = _column_select().where(Patient.__table__.c.id == 1)
        stmt = _apply(
            _criteria_constraint(_leaf("tenant_id", "=", 7)), existing
        )
        sql = _compile(stmt)
        assert "id = 1" in sql
        assert "tenant_id = 7" in sql
        assert "AND" in sql

    def test_select_with_existing_or_where_preserves_precedence(self) -> None:
        c = Patient.__table__.c
        existing = _column_select().where((c.tenant_id == 1) | (c.tenant_id == 2))
        stmt = _apply(
            _criteria_constraint(_leaf("status", "=", "active")), existing
        )
        sql = _compile(stmt).replace("\n", " ")
        assert "status = 'active'" in sql
        assert "(patient.tenant_id = 1 OR patient.tenant_id = 2)" in sql
        assert ") AND " in sql

    def test_update_with_existing_where_is_and_combined(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("tenant_id", "=", 7)),
            update(Patient).where(Patient.id == 1).values(status="archived"),
        )
        sql = _compile(stmt)
        assert "tenant_id = 7" in sql
        assert "id = 1" in sql

    def test_delete_with_existing_where_is_and_combined(self) -> None:
        stmt = _apply(
            _criteria_constraint(_leaf("tenant_id", "=", 7)),
            delete(Patient).where(Patient.id == 1),
        )
        sql = _compile(stmt)
        assert "tenant_id = 7" in sql
        assert "id = 1" in sql


class TestProjectionCannotWiden:
    def test_obligation_columns_outside_select_are_dropped(self) -> None:
        narrow = select(
            Patient.__table__.c.id, Patient.__table__.c.name
        )
        stmt = _apply(
            {
                "type": "sql:queryRewriting",
                "columns": ["id", "name", "ssn"],
            },
            narrow,
        )
        sql = _compile(stmt).replace('"', "")
        assert "patient.id" in sql
        assert "patient.name" in sql
        assert "ssn" not in sql


class TestEdgeCases:
    def test_raw_text_statement_fails_closed(self) -> None:
        from sqlalchemy import text as sql_text

        with pytest.raises(ValueError, match="UNSUPPORTED_RAW_TEXT"):
            _apply(
                _criteria_constraint(_leaf("tenant_id", "=", 7)),
                sql_text("SELECT * FROM patient"),
            )

    def test_columns_only_with_no_predicates_on_set_operation_allowed(self) -> None:
        stmt_a = select(Patient.__table__.c.id)
        stmt_b = select(Patient.__table__.c.id)
        u = union(stmt_a, stmt_b)
        result = _apply(
            {"type": "sql:queryRewriting", "columns": ["id"]}, u
        )
        assert result is u
