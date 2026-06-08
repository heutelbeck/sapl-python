"""Unit tests for DjangoQueryRewritingProvider: criteria/conditions/columns lowering.

Applies the provider's mapper to a real Django ``Query`` and asserts on the compiled SQL
(``str(query)``), with no database access. Uses the built-in ``auth.User`` model and its real
fields (``id``, ``username``, ``last_login``, ``email``). The integration suite proves the
row-level effect end to end; these tests prove the lowering and the fail-closed contract.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User

from sapl_django.orm_providers import DjangoQueryRewritingProvider
from sapl_django.orm_signal import DJANGO_QUERY


def _handler(constraint: Any):
    handlers = DjangoQueryRewritingProvider().get_handlers(constraint)
    assert len(handlers) == 1
    return handlers[0].handler


def _apply(constraint: Any, query: Any = None) -> Any:
    query = User.objects.all().query if query is None else query
    return _handler(constraint)(query)


def _sql(query: Any) -> str:
    return str(query).replace('"', "")


def _leaf(column: str, op: str, value: Any = ...) -> dict[str, Any]:
    leaf: dict[str, Any] = {"column": column, "op": op}
    if value is not ...:
        leaf["value"] = value
    return leaf


def _criteria(*criteria: Any) -> dict[str, Any]:
    return {"type": "sql:queryRewriting", "criteria": list(criteria)}


class TestResponsibility:
    def test_non_dict_yields_no_handlers(self):
        assert DjangoQueryRewritingProvider().get_handlers("nope") == ()

    def test_dict_without_type_yields_no_handlers(self):
        assert DjangoQueryRewritingProvider().get_handlers({"criteria": []}) == ()

    def test_unrelated_type_yields_no_handlers(self):
        assert DjangoQueryRewritingProvider().get_handlers({"type": "audit"}) == ()

    def test_empty_constraint_yields_no_handlers(self):
        assert DjangoQueryRewritingProvider().get_handlers({"type": "sql:queryRewriting"}) == ()

    @pytest.mark.parametrize("ctype", ["sql:queryRewriting", "relational:queryRewriting"])
    def test_typed_constraint_is_claimed(self, ctype: str):
        handlers = DjangoQueryRewritingProvider().get_handlers(
            {"type": ctype, "criteria": [_leaf("id", "isNull")]}
        )
        assert len(handlers) == 1

    def test_handler_attaches_to_django_query_as_mapper_at_priority_30(self):
        handler = DjangoQueryRewritingProvider().get_handlers(_criteria(_leaf("id", "=", 7)))[0]
        assert handler.signal is DJANGO_QUERY
        assert handler.shape == "mapper"
        assert handler.priority == 30


class TestBinaryOperators:
    @pytest.mark.parametrize(
        "op,fragment",
        [("=", "id = 7"), (">", "id > 7"), (">=", "id >= 7"), ("<", "id < 7"), ("<=", "id <= 7")],
    )
    def test_numeric_binary(self, op: str, fragment: str):
        assert fragment in _sql(_apply(_criteria(_leaf("id", op, 7))))

    def test_not_equal_negates(self):
        sql = _sql(_apply(_criteria(_leaf("id", "!=", 7))))
        assert "NOT" in sql
        assert "id = 7" in sql

    def test_text_equality(self):
        assert "username = alice" in _sql(_apply(_criteria(_leaf("username", "=", "alice"))))


class TestInOperator:
    def test_in_numeric(self):
        sql = _sql(_apply(_criteria(_leaf("id", "in", [1, 2, 3]))))
        assert "id IN (1, 2, 3)" in sql

    def test_in_text(self):
        sql = _sql(_apply(_criteria(_leaf("username", "in", ["alice", "amy"]))))
        assert "username IN (alice, amy)" in sql

    def test_in_non_list_raises(self):
        handler = _handler(_criteria(_leaf("id", "in", 7)))
        query = User.objects.all().query
        with pytest.raises(ValueError, match="VALUE_KIND_FOR_OPERATOR"):
            handler(query)


class TestLikeOperators:
    def test_like_is_verbatim(self):
        assert "username LIKE ali%" in _sql(_apply(_criteria(_leaf("username", "like", "ali%"))))

    def test_not_like_negates(self):
        sql = _sql(_apply(_criteria(_leaf("username", "notLike", "ali%"))))
        assert "NOT" in sql
        assert "LIKE ali%" in sql

    @pytest.mark.parametrize("op", ["like", "notLike"])
    def test_non_text_value_raises(self, op: str):
        handler = _handler(_criteria(_leaf("username", op, 7)))
        query = User.objects.all().query
        with pytest.raises(ValueError, match="VALUE_KIND_FOR_OPERATOR"):
            handler(query)


class TestNullOperators:
    def test_is_null(self):
        assert "last_login IS NULL" in _sql(_apply(_criteria(_leaf("last_login", "isNull"))))

    def test_is_not_null(self):
        assert "last_login IS NOT NULL" in _sql(_apply(_criteria(_leaf("last_login", "isNotNull"))))


class TestTreeComposition:
    def test_top_level_list_combines_with_and(self):
        sql = _sql(_apply(_criteria(_leaf("id", "=", 7), _leaf("username", "=", "alice"))))
        assert "id = 7" in sql and "username = alice" in sql and "AND" in sql

    def test_or_group(self):
        sql = _sql(_apply(_criteria({"or": [_leaf("id", "=", 1), _leaf("id", "=", 2)]})))
        assert "OR" in sql and "id = 1" in sql and "id = 2" in sql

    def test_and_group(self):
        sql = _sql(_apply(_criteria({"and": [_leaf("id", "=", 1), _leaf("username", "=", "alice")]})))
        assert "AND" in sql and "id = 1" in sql and "username = alice" in sql

    def test_nested_or_inside_and(self):
        sql = _sql(
            _apply(_criteria(_leaf("id", "=", 7), {"or": [_leaf("username", "=", "a"), _leaf("username", "=", "b")]}))
        )
        assert "id = 7" in sql and "OR" in sql


class TestConditions:
    def test_single_condition_fragment(self):
        sql = _sql(_apply({"type": "sql:queryRewriting", "conditions": ["id > 0"]}))
        assert "id > 0" in sql

    def test_criteria_and_conditions_combine(self):
        sql = _sql(
            _apply({"type": "sql:queryRewriting", "criteria": [_leaf("id", "=", 7)], "conditions": ["id > 0"]})
        )
        assert "id = 7" in sql and "id > 0" in sql


class TestColumnsProjection:
    def test_only_narrows_select(self):
        sql = _sql(_apply({"type": "sql:queryRewriting", "columns": ["id", "username"]}))
        assert "auth_user.username" in sql
        assert "auth_user.email" not in sql

    def test_nonexistent_columns_leave_projection_unchanged(self):
        sql = _sql(_apply({"type": "sql:queryRewriting", "columns": ["does_not_exist"]}))
        assert "auth_user.email" in sql


class TestTargetSelection:
    def test_criteria_on_absent_column_passes_query_through(self):
        sql = _sql(_apply(_criteria(_leaf("tenant_id", "=", 7))))
        assert "tenant_id" not in sql
        assert "WHERE" not in sql

    def test_criteria_on_present_column_injects_where(self):
        assert "WHERE" in _sql(_apply(_criteria(_leaf("username", "=", "alice"))))

    def test_columns_on_absent_column_passes_query_through(self):
        sql = _sql(_apply({"type": "sql:queryRewriting", "columns": ["tenant_id"]}))
        assert "auth_user.email" in sql


class TestPreservesExistingWhere:
    def test_existing_filter_is_and_combined(self):
        sql = _sql(_apply(_criteria(_leaf("username", "=", "alice")), User.objects.filter(id=1).query))
        assert "id = 1" in sql and "username = alice" in sql and "AND" in sql


class TestSetOperationFailsClosed:
    def test_union_with_criteria_raises(self):
        union_query = User.objects.filter(id=1).union(User.objects.filter(id=2)).query
        handler = _handler(_criteria(_leaf("username", "=", "alice")))
        with pytest.raises(ValueError, match="SET_OPERATION_WITH_CONDITIONS"):
            handler(union_query)


class TestFailClosedLeaves:
    def test_missing_column(self):
        handler = _handler(_criteria({"op": "=", "value": 7}))
        query = User.objects.all().query
        with pytest.raises(ValueError, match="MISSING_COLUMN"):
            handler(query)

    def test_missing_op(self):
        handler = _handler(_criteria({"column": "id", "value": 7}))
        query = User.objects.all().query
        with pytest.raises(ValueError, match="MISSING_OP"):
            handler(query)

    def test_unsupported_operator(self):
        handler = _handler(_criteria(_leaf("id", "regex", "x")))
        query = User.objects.all().query
        with pytest.raises(ValueError, match="UNSUPPORTED_OPERATOR"):
            handler(query)

    def test_value_required(self):
        handler = _handler(_criteria(_leaf("id", "=")))
        query = User.objects.all().query
        with pytest.raises(ValueError, match="VALUE_REQUIRED"):
            handler(query)

    def test_value_none_is_treated_as_missing(self):
        handler = _handler(_criteria({"column": "id", "op": "=", "value": None}))
        query = User.objects.all().query
        with pytest.raises(ValueError, match="VALUE_REQUIRED"):
            handler(query)

    def test_unsupported_value_kind(self):
        handler = _handler(_criteria({"column": "id", "op": "=", "value": {"nested": "dict"}}))
        query = User.objects.all().query
        with pytest.raises(ValueError, match="VALUE_KIND_FOR_OPERATOR"):
            handler(query)
