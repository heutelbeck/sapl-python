"""Unit tests for MongoDbQueryRewritingProvider criteria lowering.

These exercise the obligation-to-BSON-filter lowering in isolation: no enforcement,
no driver, no database. They pin the mongo:queryRewriting contract that must
narrow identically on every SAPL Mongo PEP (mirroring the Spring provider): the op
set, and / or grouping, value passthrough, the AND-merge narrowing semantic, and
the aggregation-pipeline fail-closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from sapl_base.pep.provider import ScopedHandler
from sapl_pymongo import MONGO_QUERY, MongoDbQueryRewritingProvider

if TYPE_CHECKING:
    from collections.abc import Callable

TYPE = "mongo:queryRewriting"


def _mapper_for(obligation: dict[str, Any]) -> Callable[[Any], Any]:
    handlers = MongoDbQueryRewritingProvider().get_handlers(obligation)
    assert len(handlers) == 1
    return handlers[0].handler


def _obligation(*criteria: dict[str, Any]) -> dict[str, Any]:
    return {"type": TYPE, "criteria": list(criteria)}


@pytest.mark.parametrize(
    ("op", "expected"),
    [
        ("=", {"age": 18}),
        ("!=", {"age": {"$ne": 18}}),
        (">", {"age": {"$gt": 18}}),
        (">=", {"age": {"$gte": 18}}),
        ("<", {"age": {"$lt": 18}}),
        ("<=", {"age": {"$lte": 18}}),
    ],
)
def test_binary_op_lowers_to_filter_fragment(op, expected):
    mapper = _mapper_for(_obligation({"column": "age", "op": op, "value": 18}))
    assert mapper({}) == expected


def test_in_lowers_to_dollar_in():
    mapper = _mapper_for(_obligation({"column": "moon", "op": "in", "value": ["io", "europa"]}))
    assert mapper({}) == {"moon": {"$in": ["io", "europa"]}}


def test_in_without_list_value_is_dropped():
    handlers = MongoDbQueryRewritingProvider().get_handlers(
        _obligation({"column": "moon", "op": "in", "value": "io"})
    )
    assert handlers == ()


@pytest.mark.parametrize(
    ("op", "expected"),
    [("isNull", {"deletedAt": None}), ("isNotNull", {"deletedAt": {"$ne": None}})],
)
def test_null_ops_lower_without_value(op, expected):
    mapper = _mapper_for(_obligation({"column": "deletedAt", "op": op}))
    assert mapper({}) == expected


def test_value_types_pass_through():
    mapper = _mapper_for(
        _obligation(
            {"column": "tenantId", "op": "=", "value": 7},
            {"column": "active", "op": "=", "value": True},
            {"column": "label", "op": "=", "value": "alice"},
        )
    )
    assert mapper({}) == {"$and": [{"tenantId": 7}, {"active": True}, {"label": "alice"}]}


def test_or_group_lowers_to_dollar_or():
    mapper = _mapper_for(
        _obligation(
            {"or": [{"column": "ownerId", "op": "=", "value": "alice"}, {"column": "public", "op": "=", "value": True}]}
        )
    )
    assert mapper({}) == {"$or": [{"ownerId": "alice"}, {"public": True}]}


def test_nested_and_inside_or_group():
    mapper = _mapper_for(
        _obligation(
            {
                "or": [
                    {"column": "public", "op": "=", "value": True},
                    {"and": [{"column": "ownerId", "op": "=", "value": "alice"}, {"column": "shared", "op": "=", "value": True}]},
                ]
            }
        )
    )
    assert mapper({}) == {
        "$or": [{"public": True}, {"$and": [{"ownerId": "alice"}, {"shared": True}]}],
    }


def test_merge_ands_obligation_onto_non_empty_user_filter():
    mapper = _mapper_for(_obligation({"column": "age", "op": ">=", "value": 18}))
    assert mapper({"status": "active"}) == {"$and": [{"status": "active"}, {"age": {"$gte": 18}}]}


def test_single_fragment_on_empty_filter_is_unwrapped():
    mapper = _mapper_for(_obligation({"column": "tenantId", "op": "=", "value": 7}))
    assert mapper({}) == {"tenantId": 7}


def test_aggregate_pipeline_fails_closed():
    mapper = _mapper_for(_obligation({"column": "tenantId", "op": "=", "value": 7}))
    pipeline = [{"$match": {"status": "active"}}]
    with pytest.raises(ValueError, match="aggregation pipeline"):
        mapper(pipeline)


def test_handler_is_a_mapper_on_mongo_query_at_default_priority():
    handlers = MongoDbQueryRewritingProvider().get_handlers(_obligation({"column": "x", "op": "=", "value": 1}))
    handler = handlers[0]
    assert handler == ScopedHandler(
        signal=MONGO_QUERY, priority=handler.priority, shape="mapper", handler=handler.handler
    )
    assert (handler.signal, handler.shape, handler.priority) == (MONGO_QUERY, "mapper", 30)


def test_double_quoted_condition_parses_and_merges():
    mapper = _mapper_for({"type": TYPE, "conditions": ['{"age": {"$gte": 18}}']})
    assert mapper({}) == {"age": {"$gte": 18}}


def test_criteria_and_conditions_combine_under_and():
    mapper = _mapper_for(
        {
            "type": TYPE,
            "criteria": [{"column": "owner", "op": "=", "value": "alice"}],
            "conditions": ['{"age": {"$gte": 18}}'],
        }
    )
    assert mapper({"status": "active"}) == {
        "$and": [{"status": "active"}, {"owner": "alice"}, {"age": {"$gte": 18}}],
    }


def test_empty_condition_document_is_skipped():
    mapper = _mapper_for(
        {"type": TYPE, "criteria": [{"column": "owner", "op": "=", "value": "alice"}], "conditions": ["{}"]}
    )
    assert mapper({}) == {"owner": "alice"}


def test_single_quoted_condition_fails_closed():
    mapper = _mapper_for({"type": TYPE, "conditions": ["{'age': {'$gte': 18}}"]})
    with pytest.raises(ValueError):
        mapper({})


def test_conditions_only_obligation_yields_a_handler():
    handlers = MongoDbQueryRewritingProvider().get_handlers(
        {"type": TYPE, "conditions": ['{"tenantId": 7}']}
    )
    assert len(handlers) == 1


def test_not_responsible_for_other_constraint_type():
    assert MongoDbQueryRewritingProvider().get_handlers({"type": "other"}) == ()


@pytest.mark.parametrize(
    "criterion",
    [
        "not-a-dict",
        {"or": []},
        {"op": "=", "value": 1},
        {"column": "x", "value": 1},
        {"column": "x", "op": "="},
        {"column": "x", "op": "between", "value": 1},
    ],
)
def test_invalid_criterion_is_skipped(criterion):
    handlers = MongoDbQueryRewritingProvider().get_handlers({"type": TYPE, "criteria": [criterion]})
    assert handlers == ()


def test_no_handler_when_criteria_absent_or_empty():
    provider = MongoDbQueryRewritingProvider()
    assert provider.get_handlers({"type": TYPE}) == ()
    assert provider.get_handlers(_obligation()) == ()
