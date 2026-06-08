"""SqlQueryRewritingProvider.

Translates a `sql:queryRewriting` (or alias `relational:queryRewriting`)
constraint into a single mapper attached to SQL_QUERY. Lowers the typed
`criteria` tree, the string `conditions` array, and the `columns` projection
list to native SQLAlchemy expression objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Delete,
    Insert,
    Select,
    Update,
    and_,
    column,
    literal,
    not_,
    or_,
    text,
)
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import CompoundSelect

from sapl_base.pep.provider import ScopedHandler
from sapl_sqlalchemy.signal import SQL_QUERY

if TYPE_CHECKING:
    from collections.abc import Sequence

_CONSTRAINT_TYPE_SQL: str = "sql:queryRewriting"
_CONSTRAINT_TYPE_RELATIONAL: str = "relational:queryRewriting"
_DEFAULT_PRIORITY: int = 30

_FIELD_AND: str = "and"
_FIELD_COLUMN: str = "column"
_FIELD_COLUMNS: str = "columns"
_FIELD_CONDITIONS: str = "conditions"
_FIELD_CRITERIA: str = "criteria"
_FIELD_OP: str = "op"
_FIELD_OR: str = "or"
_FIELD_VALUE: str = "value"

_OP_EQ: str = "="
_OP_NE: str = "!="
_OP_GT: str = ">"
_OP_GE: str = ">="
_OP_LT: str = "<"
_OP_LE: str = "<="
_OP_IN: str = "in"
_OP_LIKE: str = "like"
_OP_NOT_LIKE: str = "notLike"
_OP_IS_NULL: str = "isNull"
_OP_IS_NOT_NULL: str = "isNotNull"

_BINARY_OPS: frozenset[str] = frozenset({
    _OP_EQ, _OP_NE, _OP_GT, _OP_GE, _OP_LT, _OP_LE,
    _OP_IN, _OP_LIKE, _OP_NOT_LIKE,
})

_ERROR_COLUMNS_AGAINST_ENTITY_SELECT: str = (
    "COLUMNS_AGAINST_ENTITY_SELECT: cannot narrow projection of an entity-typed "
    "SELECT without changing the return shape"
)
_ERROR_MISSING_COLUMN: str = "MISSING_COLUMN: criterion leaf has no 'column' string field"
_ERROR_MISSING_OP: str = "MISSING_OP: criterion leaf has no 'op' string field"
_ERROR_SET_OPERATION_WITH_CONDITIONS: str = (
    "SET_OPERATION_WITH_CONDITIONS: cannot inject WHERE into UNION/INTERSECT/EXCEPT "
    "with conditions present"
)
_ERROR_UNSUPPORTED_OPERATOR: str = "UNSUPPORTED_OPERATOR: %s"
_ERROR_UNSUPPORTED_RAW_TEXT: str = (
    "UNSUPPORTED_RAW_TEXT: cannot manipulate a raw text() statement"
)
_ERROR_UNSUPPORTED_STATEMENT: str = "UNSUPPORTED_STATEMENT: %s does not support WHERE injection"
_ERROR_VALUE_KIND_FOR_OPERATOR: str = "VALUE_KIND_FOR_OPERATOR: value kind %s incompatible with operator %s"
_ERROR_VALUE_REQUIRED: str = "VALUE_REQUIRED: value required for operator %s"


class SqlQueryRewritingProvider:
    """ConstraintHandlerProvider for sql:queryRewriting."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not _is_responsible(constraint):
            return ()
        criteria = _extract_array(constraint, _FIELD_CRITERIA)
        conditions = _extract_string_array(constraint, _FIELD_CONDITIONS)
        columns = _extract_string_array(constraint, _FIELD_COLUMNS)
        if not criteria and not conditions and not columns:
            return ()

        def _mapper(statement: Any) -> Any:
            return _rewrite(statement, criteria, conditions, columns)

        return (
            ScopedHandler(
                signal=SQL_QUERY,
                priority=_DEFAULT_PRIORITY,
                shape="mapper",
                handler=_mapper,
            ),
        )


def _is_responsible(constraint: Any) -> bool:
    if not isinstance(constraint, dict):
        return False
    ctype = constraint.get("type")
    return ctype in (_CONSTRAINT_TYPE_SQL, _CONSTRAINT_TYPE_RELATIONAL)


def _extract_array(constraint: Any, field: str) -> list[Any]:
    value = constraint.get(field) if isinstance(constraint, dict) else None
    if isinstance(value, list):
        return list(value)
    return []


def _extract_string_array(constraint: Any, field: str) -> list[str]:
    return [v for v in _extract_array(constraint, field) if isinstance(v, str)]


def _rewrite(
    statement: Any,
    criteria: list[Any],
    conditions: list[str],
    columns: list[str],
) -> Any:
    if isinstance(statement, TextClause):
        raise ValueError(_ERROR_UNSUPPORTED_RAW_TEXT)

    has_predicates = bool(criteria) or bool(conditions)

    if isinstance(statement, CompoundSelect) and has_predicates:
        raise ValueError(_ERROR_SET_OPERATION_WITH_CONDITIONS)

    if has_predicates and not _supports_where(statement):
        raise ValueError(_ERROR_UNSUPPORTED_STATEMENT % type(statement).__name__)

    predicate = _build_predicate(criteria, conditions)
    if predicate is not None:
        statement = statement.where(predicate)

    if columns:
        statement = _apply_columns(statement, columns)

    return statement


def _supports_where(statement: Any) -> bool:
    return isinstance(statement, (Select, Update, Delete)) and not isinstance(
        statement, Insert
    )


def _build_predicate(criteria: list[Any], conditions: list[str]) -> Any:
    fragments: list[Any] = []
    for node in criteria:
        rendered = _render_criterion(node)
        if rendered is not None:
            fragments.append(rendered)
    for fragment in conditions:
        fragments.append(text(fragment))
    if not fragments:
        return None
    if len(fragments) == 1:
        return fragments[0]
    return and_(*fragments)


def _render_criterion(node: Any) -> Any:
    if not isinstance(node, dict):
        return None
    if _FIELD_OR in node and isinstance(node[_FIELD_OR], list):
        children = [_render_criterion(c) for c in node[_FIELD_OR]]
        children = [c for c in children if c is not None]
        if not children:
            return None
        return or_(*children)
    if _FIELD_AND in node and isinstance(node[_FIELD_AND], list):
        children = [_render_criterion(c) for c in node[_FIELD_AND]]
        children = [c for c in children if c is not None]
        if not children:
            return None
        return and_(*children)
    return _render_leaf(node)


def _render_leaf(node: dict[str, Any]) -> Any:
    col_name = node.get(_FIELD_COLUMN)
    if not isinstance(col_name, str):
        raise ValueError(_ERROR_MISSING_COLUMN)
    op = node.get(_FIELD_OP)
    if not isinstance(op, str):
        raise ValueError(_ERROR_MISSING_OP)
    col = column(col_name)

    if op == _OP_IS_NULL:
        return col.is_(None)
    if op == _OP_IS_NOT_NULL:
        return col.isnot(None)

    if op not in _BINARY_OPS:
        raise ValueError(_ERROR_UNSUPPORTED_OPERATOR % op)

    if _FIELD_VALUE not in node or node[_FIELD_VALUE] is None:
        raise ValueError(_ERROR_VALUE_REQUIRED % op)

    value = node[_FIELD_VALUE]
    return _render_binary(col, op, value)


def _render_binary(col: Any, op: str, value: Any) -> Any:
    if op == _OP_IN:
        if not isinstance(value, list):
            raise ValueError(
                _ERROR_VALUE_KIND_FOR_OPERATOR % (type(value).__name__, op)
            )
        return col.in_([literal(_check_scalar(v, op)) for v in value])
    if op == _OP_LIKE:
        if not isinstance(value, str):
            raise ValueError(
                _ERROR_VALUE_KIND_FOR_OPERATOR % (type(value).__name__, op)
            )
        return col.like(literal(value))
    if op == _OP_NOT_LIKE:
        if not isinstance(value, str):
            raise ValueError(
                _ERROR_VALUE_KIND_FOR_OPERATOR % (type(value).__name__, op)
            )
        return not_(col.like(literal(value)))

    rendered_value = literal(_check_scalar(value, op))
    return _BINARY_DISPATCH[op](col, rendered_value)


def _check_scalar(value: Any, op: str) -> Any:
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    raise ValueError(_ERROR_VALUE_KIND_FOR_OPERATOR % (type(value).__name__, op))


_BINARY_DISPATCH: dict[str, Any] = {
    _OP_EQ: lambda c, v: c == v,
    _OP_NE: lambda c, v: c != v,
    _OP_GT: lambda c, v: c > v,
    _OP_GE: lambda c, v: c >= v,
    _OP_LT: lambda c, v: c < v,
    _OP_LE: lambda c, v: c <= v,
}


def _apply_columns(statement: Any, columns: list[str]) -> Any:
    if not isinstance(statement, Select):
        return statement
    if _is_entity_typed_select(statement):
        raise ValueError(_ERROR_COLUMNS_AGAINST_ENTITY_SELECT)
    obligation = set(columns)
    intersected = [
        col for col in statement.selected_columns if col.key in obligation
    ]
    return statement.with_only_columns(*intersected)


def _is_entity_typed_select(statement: Select) -> bool:
    return any(desc.get("entity") is not None for desc in statement.column_descriptions)
