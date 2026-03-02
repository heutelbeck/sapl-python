from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import pytest

from sapl_base.deduplication import deduplicate, deep_equal


async def _async_iter(*items: Any) -> AsyncIterator[Any]:
    for item in items:
        yield item


async def _collect(stream: AsyncIterator[Any]) -> list[Any]:
    return [item async for item in stream]


class TestDeepEqual:
    class TestPrimitives:
        @pytest.mark.parametrize(
            ("value_a", "value_b", "expected"),
            [
                pytest.param(1, 1, True, id="equal_ints"),
                pytest.param(1, 2, False, id="different_ints"),
                pytest.param("a", "a", True, id="equal_strings"),
                pytest.param("a", "b", False, id="different_strings"),
                pytest.param(True, True, True, id="equal_bools"),
                pytest.param(True, False, False, id="different_bools"),
                pytest.param(None, None, True, id="both_none"),
                pytest.param(None, 0, False, id="none_vs_zero"),
                pytest.param(1.5, 1.5, True, id="equal_floats"),
                pytest.param(1.5, 2.5, False, id="different_floats"),
            ],
        )
        def test_primitive_equality(self, value_a, value_b, expected):
            assert deep_equal(value_a, value_b) is expected

    class TestTypeMismatch:
        @pytest.mark.parametrize(
            ("value_a", "value_b"),
            [
                pytest.param(1, "1", id="int_vs_string"),
                pytest.param([], {}, id="list_vs_dict"),
                pytest.param(True, 1, id="bool_vs_int"),
                pytest.param((1,), [1], id="tuple_vs_list"),
            ],
        )
        def test_different_types_are_not_equal(self, value_a, value_b):
            assert deep_equal(value_a, value_b) is False

    class TestDicts:
        def test_equal_dicts(self):
            assert deep_equal({"a": 1, "b": 2}, {"a": 1, "b": 2}) is True

        def test_different_values(self):
            assert deep_equal({"a": 1}, {"a": 2}) is False

        def test_different_keys(self):
            assert deep_equal({"a": 1}, {"b": 1}) is False

        def test_different_lengths(self):
            assert deep_equal({"a": 1}, {"a": 1, "b": 2}) is False

        def test_nested_dicts(self):
            assert deep_equal(
                {"a": {"b": {"c": 1}}},
                {"a": {"b": {"c": 1}}},
            ) is True

        def test_nested_dicts_different(self):
            assert deep_equal(
                {"a": {"b": {"c": 1}}},
                {"a": {"b": {"c": 2}}},
            ) is False

        def test_empty_dicts(self):
            assert deep_equal({}, {}) is True

    class TestLists:
        def test_equal_lists(self):
            assert deep_equal([1, 2, 3], [1, 2, 3]) is True

        def test_different_elements(self):
            assert deep_equal([1, 2], [1, 3]) is False

        def test_different_lengths(self):
            assert deep_equal([1, 2], [1, 2, 3]) is False

        def test_nested_lists(self):
            assert deep_equal([[1, 2], [3]], [[1, 2], [3]]) is True

        def test_empty_lists(self):
            assert deep_equal([], []) is True

    class TestTuples:
        def test_equal_tuples(self):
            assert deep_equal((1, 2), (1, 2)) is True

        def test_different_tuples(self):
            assert deep_equal((1, 2), (1, 3)) is False

    class TestSets:
        def test_equal_sets(self):
            assert deep_equal({1, 2, 3}, {3, 2, 1}) is True

        def test_different_sets(self):
            assert deep_equal({1, 2}, {1, 3}) is False

    class TestIdentity:
        def test_same_object_is_equal(self):
            obj = {"a": [1, 2, {"b": 3}]}
            assert deep_equal(obj, obj) is True

    class TestDepthLimit:
        def test_depth_limit_exceeded_returns_false(self):
            import copy

            nested: dict[str, Any] = {"value": "leaf"}
            for _ in range(25):
                nested = {"child": nested}
            # Must use distinct objects to avoid the `a is b` identity shortcut
            assert deep_equal(nested, copy.deepcopy(nested), max_depth=20) is False

        def test_within_depth_limit_returns_true(self):
            import copy

            nested: dict[str, Any] = {"value": "leaf"}
            for _ in range(5):
                nested = {"child": nested}
            assert deep_equal(nested, copy.deepcopy(nested), max_depth=20) is True

        def test_custom_depth_limit(self):
            import copy

            nested: dict[str, Any] = {"value": "leaf"}
            for _ in range(3):
                nested = {"child": nested}
            assert deep_equal(nested, copy.deepcopy(nested), max_depth=2) is False
            assert deep_equal(nested, copy.deepcopy(nested), max_depth=10) is True


class TestDeduplicate:
    async def test_suppresses_consecutive_duplicates(self):
        stream = _async_iter(1, 1, 1, 2, 2, 3, 3, 3)
        result = await _collect(deduplicate(stream))
        assert result == [1, 2, 3]

    async def test_preserves_non_consecutive_duplicates(self):
        stream = _async_iter(1, 2, 1, 2)
        result = await _collect(deduplicate(stream))
        assert result == [1, 2, 1, 2]

    async def test_single_item(self):
        stream = _async_iter(42)
        result = await _collect(deduplicate(stream))
        assert result == [42]

    async def test_empty_stream(self):
        stream = _async_iter()
        result = await _collect(deduplicate(stream))
        assert result == []

    async def test_all_identical(self):
        stream = _async_iter("x", "x", "x")
        result = await _collect(deduplicate(stream))
        assert result == ["x"]

    async def test_all_different(self):
        stream = _async_iter(1, 2, 3, 4)
        result = await _collect(deduplicate(stream))
        assert result == [1, 2, 3, 4]

    async def test_dict_deduplication(self):
        stream = _async_iter(
            {"decision": "PERMIT"},
            {"decision": "PERMIT"},
            {"decision": "DENY"},
            {"decision": "DENY"},
        )
        result = await _collect(deduplicate(stream))
        assert result == [{"decision": "PERMIT"}, {"decision": "DENY"}]

    async def test_nested_dict_deduplication(self):
        item = {"a": {"b": [1, 2, 3]}}
        stream = _async_iter(item, {"a": {"b": [1, 2, 3]}}, {"a": {"b": [1, 2, 4]}})
        result = await _collect(deduplicate(stream))
        assert len(result) == 2
        assert result[0] == {"a": {"b": [1, 2, 3]}}
        assert result[1] == {"a": {"b": [1, 2, 4]}}

    async def test_none_values(self):
        stream = _async_iter(None, None, 1, None)
        result = await _collect(deduplicate(stream))
        assert result == [None, 1, None]
