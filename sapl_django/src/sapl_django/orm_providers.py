"""DjangoQueryRewritingProvider: lower sql:queryRewriting to a Django Query rewrite.

Mirrors the `sapl_sqlalchemy` provider's contract field-for-field -- a `criteria` tree
(`and`/`or` + `{column, op, value}` leaves), a string `conditions` array, a `columns`
projection list, ops `= != > >= < <= in like notLike isNull isNotNull`, priority 30 -- lowered
into Django ORM constructs: criteria -> `Q` (`add_q`), conditions -> raw WHERE (`add_extra`),
columns -> `.only()`.

Django-specific TARGET SELECTION. The `SQLCompiler.execute_sql` cut point fires for every query
in an enforced call -- the protected model's query, but also prefetch and cascade-delete SELECTs
against other models. A query is a target only when its model carries the columns the criteria
reference (or, absent criteria, the projection columns); non-target queries pass through
unchanged. This applies the filter to every matching (tenant-scoped) table the call touches while
never injecting a column an unrelated model lacks (which would raise `FieldError`). The siblings
(SQLAlchemy `do_orm_execute`, Spring R2DBC) need no such step -- their hook fires once per
developer query, so the query is unambiguously the target.

The mapper raises `ValueError` on a malformed or unsupported constraint; the planner's executor
records that as an obligation failure, so the shim fails closed (deny), exactly as the SQLAlchemy
provider does.

`columns` projection uses Django `.only()`: it narrows the immediate SELECT to the requested
columns that exist on the model and keeps model instances. Deferred columns still load lazily on
attribute access, so `.only()` is a projection, not a hard column block -- pair it with content
filtering (an OUTPUT obligation) when a column must be blanked unconditionally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Field, Lookup, Q
from django.db.models.sql.subqueries import DeleteQuery, UpdateQuery

from sapl_base.pep import ScopedHandler
from sapl_django.orm_signal import DJANGO_QUERY

if TYPE_CHECKING:
    from collections.abc import Sequence

_CONSTRAINT_TYPE_RELATIONAL = "relational:queryRewriting"
_CONSTRAINT_TYPE_SQL = "sql:queryRewriting"
_DEFAULT_PRIORITY = 30
_SAPL_LIKE = "sapllike"

_FIELD_AND = "and"
_FIELD_COLUMN = "column"
_FIELD_CONDITIONS = "conditions"
_FIELD_COLUMNS = "columns"
_FIELD_CRITERIA = "criteria"
_FIELD_OP = "op"
_FIELD_OR = "or"
_FIELD_VALUE = "value"

_OP_EQ = "="
_OP_GE = ">="
_OP_GT = ">"
_OP_IN = "in"
_OP_IS_NOT_NULL = "isNotNull"
_OP_IS_NULL = "isNull"
_OP_LE = "<="
_OP_LIKE = "like"
_OP_LT = "<"
_OP_NE = "!="
_OP_NOT_LIKE = "notLike"

_SCALAR_OPS = frozenset({_OP_EQ, _OP_NE, _OP_GT, _OP_GE, _OP_LT, _OP_LE})
_BINARY_OPS = _SCALAR_OPS | frozenset({_OP_IN, _OP_LIKE, _OP_NOT_LIKE})
_SCALAR_LOOKUP = {_OP_GT: "gt", _OP_GE: "gte", _OP_LT: "lt", _OP_LE: "lte"}

ERROR_MISSING_COLUMN = "MISSING_COLUMN: criterion leaf has no 'column' string field"
ERROR_MISSING_OP = "MISSING_OP: criterion leaf has no 'op' string field"
ERROR_SET_OPERATION_WITH_CONDITIONS = (
    "SET_OPERATION_WITH_CONDITIONS: cannot inject WHERE into a UNION/INTERSECT/EXCEPT query"
)
ERROR_UNSUPPORTED_OPERATOR = "UNSUPPORTED_OPERATOR: %s"
ERROR_VALUE_KIND_FOR_OPERATOR = "VALUE_KIND_FOR_OPERATOR: value kind %s incompatible with operator %s"
ERROR_VALUE_REQUIRED = "VALUE_REQUIRED: value required for operator %s"


class _SaplLike(Lookup):
    """Verbatim SQL LIKE: the value is the pattern as-is, no implicit wildcards (unlike __contains)."""

    lookup_name = _SAPL_LIKE

    def as_sql(self, compiler: Any, connection: Any) -> tuple[str, Any]:
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} LIKE {rhs}", (*lhs_params, *rhs_params)


Field.register_lookup(_SaplLike)


class DjangoQueryRewritingProvider:
    """ConstraintHandlerProvider for `sql:queryRewriting` against the Django ORM."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not _is_responsible(constraint):
            return ()
        criteria = _extract_array(constraint, _FIELD_CRITERIA)
        conditions = _extract_string_array(constraint, _FIELD_CONDITIONS)
        columns = _extract_string_array(constraint, _FIELD_COLUMNS)
        if not criteria and not conditions and not columns:
            return ()
        target_columns = _criteria_columns(criteria) or set(columns)

        def _mapper(query: Any) -> Any:
            return _rewrite(query, criteria, conditions, columns, target_columns)

        return (
            ScopedHandler(signal=DJANGO_QUERY, priority=_DEFAULT_PRIORITY, shape="mapper", handler=_mapper),
        )


def _is_responsible(constraint: Any) -> bool:
    if not isinstance(constraint, dict):
        return False
    return constraint.get("type") in (_CONSTRAINT_TYPE_SQL, _CONSTRAINT_TYPE_RELATIONAL)


def _extract_array(constraint: Any, field: str) -> list[Any]:
    value = constraint.get(field) if isinstance(constraint, dict) else None
    return list(value) if isinstance(value, list) else []


def _extract_string_array(constraint: Any, field: str) -> list[str]:
    return [v for v in _extract_array(constraint, field) if isinstance(v, str)]


def _criteria_columns(criteria: list[Any]) -> set[str]:
    columns: set[str] = set()
    for node in criteria:
        _collect_columns(node, columns)
    return columns


def _collect_columns(node: Any, columns: set[str]) -> None:
    if not isinstance(node, dict):
        return
    if isinstance(node.get(_FIELD_OR), list):
        for child in node[_FIELD_OR]:
            _collect_columns(child, columns)
        return
    if isinstance(node.get(_FIELD_AND), list):
        for child in node[_FIELD_AND]:
            _collect_columns(child, columns)
        return
    column = node.get(_FIELD_COLUMN)
    if isinstance(column, str):
        columns.add(column)


def _rewrite(
    query: Any,
    criteria: list[Any],
    conditions: list[str],
    columns: list[str],
    target_columns: set[str],
) -> Any:
    model = getattr(query, "model", None)
    if model is None:
        return query
    if target_columns and not _model_has_all(model, target_columns):
        return query

    has_predicates = bool(criteria) or bool(conditions)
    if has_predicates and getattr(query, "combinator", None):
        raise ValueError(ERROR_SET_OPERATION_WITH_CONDITIONS)

    clone = query.clone()
    predicate = _build_predicate(criteria)
    if predicate is not None:
        clone.add_q(predicate)
    if conditions:
        clone.add_extra(None, None, list(conditions), None, None, None)
    if columns and _accepts_projection(clone):
        valid = [column for column in columns if _model_has(model, column)]
        if valid:
            clone.add_immediate_loading(valid)
    return clone


def _model_has(model: Any, column: str) -> bool:
    try:
        model._meta.get_field(column)
    except FieldDoesNotExist:
        return False
    return True


def _model_has_all(model: Any, columns: set[str]) -> bool:
    return all(_model_has(model, column) for column in columns)


def _accepts_projection(query: Any) -> bool:
    return not isinstance(query, (UpdateQuery, DeleteQuery)) and not query.values_select


def _build_predicate(criteria: list[Any]) -> Q | None:
    fragments = [rendered for node in criteria if (rendered := _render_node(node)) is not None]
    if not fragments:
        return None
    predicate = fragments[0]
    for fragment in fragments[1:]:
        predicate &= fragment
    return predicate


def _render_node(node: Any) -> Q | None:
    if not isinstance(node, dict):
        return None
    if isinstance(node.get(_FIELD_OR), list):
        return _combine(node[_FIELD_OR], disjunction=True)
    if isinstance(node.get(_FIELD_AND), list):
        return _combine(node[_FIELD_AND], disjunction=False)
    return _render_leaf(node)


def _combine(children: list[Any], *, disjunction: bool) -> Q | None:
    rendered = [child for node in children if (child := _render_node(node)) is not None]
    if not rendered:
        return None
    result = rendered[0]
    for fragment in rendered[1:]:
        result = (result | fragment) if disjunction else (result & fragment)
    return result


def _render_leaf(node: dict[str, Any]) -> Q:
    column = node.get(_FIELD_COLUMN)
    if not isinstance(column, str):
        raise ValueError(ERROR_MISSING_COLUMN)
    op = node.get(_FIELD_OP)
    if not isinstance(op, str):
        raise ValueError(ERROR_MISSING_OP)
    if op == _OP_IS_NULL:
        return Q(**{f"{column}__isnull": True})
    if op == _OP_IS_NOT_NULL:
        return Q(**{f"{column}__isnull": False})
    if op not in _BINARY_OPS:
        raise ValueError(ERROR_UNSUPPORTED_OPERATOR % op)
    if _FIELD_VALUE not in node or node[_FIELD_VALUE] is None:
        raise ValueError(ERROR_VALUE_REQUIRED % op)
    return _render_binary(column, op, node[_FIELD_VALUE])


def _render_binary(column: str, op: str, value: Any) -> Q:
    if op == _OP_IN:
        if not isinstance(value, list):
            raise ValueError(ERROR_VALUE_KIND_FOR_OPERATOR % (type(value).__name__, op))
        for element in value:
            _check_scalar(element, op)
        return Q(**{f"{column}__in": value})
    if op in (_OP_LIKE, _OP_NOT_LIKE):
        if not isinstance(value, str):
            raise ValueError(ERROR_VALUE_KIND_FOR_OPERATOR % (type(value).__name__, op))
        like = Q(**{f"{column}__{_SAPL_LIKE}": value})
        return ~like if op == _OP_NOT_LIKE else like
    _check_scalar(value, op)
    if op == _OP_EQ:
        return Q(**{column: value})
    if op == _OP_NE:
        return ~Q(**{column: value})
    return Q(**{f"{column}__{_SCALAR_LOOKUP[op]}": value})


def _check_scalar(value: Any, op: str) -> None:
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    raise ValueError(ERROR_VALUE_KIND_FOR_OPERATOR % (type(value).__name__, op))
