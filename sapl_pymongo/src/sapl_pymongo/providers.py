"""Constraint handler provider for the mongo:queryManipulation obligation.

``MongoDbQueryManipulationProvider`` lowers a ``mongo:queryManipulation`` obligation
into MongoDB filter fragments and AND-merges them into the query the shim intercepts,
so the obligation can only narrow the result set, never widen it. It mirrors the Spring
``MongoDbQueryManipulationProvider`` so the same obligation narrows identically on every
SAPL Mongo PEP.

Two obligation shapes are supported and may be combined:

- ``criteria``: the typed, backend-neutral form. Leaves are ``{"column", "op", "value"}``
  with ops ``=``, ``!=``, ``>``, ``>=``, ``<``, ``<=``, ``in``, ``isNull``, ``isNotNull``;
  ``and`` / ``or`` group nested criteria.
- ``conditions``: an escape hatch carrying raw MongoDB filter fragments as strings, for
  operators the typed form cannot express (``$regex``, ``$exists``, ``$geoWithin``). For
  portability across SAPL Mongo PEPs the strings must be double-quoted (extended) JSON.

An aggregation pipeline cannot be expressed by this contract, so a pipeline intercept
fails closed, as does a malformed ``conditions`` string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bson import json_util

from sapl_base.pep.provider import ScopedHandler
from sapl_pymongo.signal import MONGO_QUERY

if TYPE_CHECKING:
    from collections.abc import Sequence

_CONSTRAINT_TYPE_MONGO: str = "mongo:queryManipulation"
_DEFAULT_PRIORITY: int = 30

_FIELD_AND: str = "and"
_FIELD_COLUMN: str = "column"
_FIELD_CONDITIONS: str = "conditions"
_FIELD_CRITERIA: str = "criteria"
_FIELD_OP: str = "op"
_FIELD_OR: str = "or"
_FIELD_VALUE: str = "value"

_ERROR_AGGREGATE_NOT_SUPPORTED: str = "mongo:queryManipulation cannot narrow an aggregation pipeline"


class MongoDbQueryManipulationProvider:
    """ConstraintHandlerProvider for mongo:queryManipulation.

    Criteria and string conditions are AND-merged into the user's filter, so the
    obligation can only narrow access, never widen it. An aggregation pipeline or a
    malformed condition string fails closed.
    """

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not _is_responsible(constraint):
            return ()
        criteria = _extract_criteria(constraint)
        conditions = _extract_conditions(constraint)
        if not criteria and not conditions:
            return ()

        def _mapper(query: Any) -> Any:
            if isinstance(query, list):
                raise ValueError(_ERROR_AGGREGATE_NOT_SUPPORTED)
            fragments = [*criteria, *_parse_conditions(conditions)]
            return _merge(query, fragments) if fragments else query

        return (ScopedHandler(signal=MONGO_QUERY, priority=_DEFAULT_PRIORITY, shape="mapper", handler=_mapper),)


def _is_responsible(constraint: Any) -> bool:
    return isinstance(constraint, dict) and constraint.get("type") == _CONSTRAINT_TYPE_MONGO


def _extract_criteria(constraint: Any) -> list[dict[str, Any]]:
    criteria = constraint.get(_FIELD_CRITERIA) if isinstance(constraint, dict) else None
    if not isinstance(criteria, list):
        return []
    fragments: list[dict[str, Any]] = []
    for entry in criteria:
        fragment = _build_node(entry)
        if fragment is not None:
            fragments.append(fragment)
    return fragments


def _extract_conditions(constraint: Any) -> list[str]:
    conditions = constraint.get(_FIELD_CONDITIONS) if isinstance(constraint, dict) else None
    if not isinstance(conditions, list):
        return []
    return [condition for condition in conditions if isinstance(condition, str)]


def _parse_conditions(conditions: list[str]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for condition in conditions:
        parsed = json_util.loads(condition)
        if isinstance(parsed, dict) and parsed:
            fragments.append(parsed)
    return fragments


def _build_node(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    if isinstance(entry.get(_FIELD_OR), list):
        return _build_group(entry[_FIELD_OR], "$or")
    if isinstance(entry.get(_FIELD_AND), list):
        return _build_group(entry[_FIELD_AND], "$and")
    return _build_leaf(entry)


def _build_group(children: list[Any], operator: str) -> dict[str, Any] | None:
    parts = [node for child in children if (node := _build_node(child)) is not None]
    if not parts:
        return None
    return {operator: parts}


def _build_leaf(leaf: dict[str, Any]) -> dict[str, Any] | None:
    column = leaf.get(_FIELD_COLUMN)
    op = leaf.get(_FIELD_OP)
    if not isinstance(column, str) or not isinstance(op, str):
        return None
    if op == "isNull":
        return {column: None}
    if op == "isNotNull":
        return {column: {"$ne": None}}
    if _FIELD_VALUE not in leaf:
        return None
    return _apply_binary_op(column, op, leaf[_FIELD_VALUE])


def _apply_binary_op(column: str, op: str, value: Any) -> dict[str, Any] | None:
    match op:
        case "=":
            return {column: value}
        case "!=":
            return {column: {"$ne": value}}
        case ">":
            return {column: {"$gt": value}}
        case ">=":
            return {column: {"$gte": value}}
        case "<":
            return {column: {"$lt": value}}
        case "<=":
            return {column: {"$lte": value}}
        case "in":
            return {column: {"$in": value}} if isinstance(value, list) else None
        case _:
            return None


def _merge(query: Any, fragments: list[dict[str, Any]]) -> dict[str, Any]:
    if not query:
        return fragments[0] if len(fragments) == 1 else {"$and": fragments}
    return {"$and": [query, *fragments]}
