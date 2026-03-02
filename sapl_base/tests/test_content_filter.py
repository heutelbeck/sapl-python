from __future__ import annotations

import copy
from typing import Any

import pytest

from sapl_base.content_filter import (
    ContentFilterPredicateProvider,
    ContentFilteringProvider,
    _blacken_value,
    _evaluate_condition,
    _identity,
    _is_safe_regex,
    _parse_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider() -> ContentFilteringProvider:
    return ContentFilteringProvider()


@pytest.fixture
def predicate_provider() -> ContentFilterPredicateProvider:
    return ContentFilterPredicateProvider()


def _make_constraint(actions: Any) -> dict[str, Any]:
    """Build a ``filterJsonContent`` constraint with the given actions."""
    return {"type": "filterJsonContent", "actions": actions}


def _make_predicate_constraint(conditions: Any) -> dict[str, Any]:
    """Build a ``jsonContentFilterPredicate`` constraint with the given conditions."""
    return {"type": "jsonContentFilterPredicate", "conditions": conditions}


# ===========================================================================
# ContentFilteringProvider
# ===========================================================================

class TestContentFilteringProviderResponsibility:
    """Verify is_responsible dispatches only on filterJsonContent."""

    def test_responsible_for_filter_json_content(self, provider: ContentFilteringProvider) -> None:
        constraint = {"type": "filterJsonContent", "actions": []}
        assert provider.is_responsible(constraint) is True

    @pytest.mark.parametrize("constraint", [
        {"type": "other"},
        {"type": "jsonContentFilterPredicate"},
        {"notType": "filterJsonContent"},
        "filterJsonContent",
        42,
        None,
    ], ids=[
        "different-type",
        "predicate-type",
        "missing-type-key",
        "string-not-dict",
        "int-not-dict",
        "none",
    ])
    def test_not_responsible_for_other_constraints(
        self,
        provider: ContentFilteringProvider,
        constraint: Any,
    ) -> None:
        assert provider.is_responsible(constraint) is False


class TestContentFilteringProviderPriority:

    def test_priority_is_zero(self, provider: ContentFilteringProvider) -> None:
        assert provider.get_priority() == 0


# ---------------------------------------------------------------------------
# Blacken action
# ---------------------------------------------------------------------------

class TestBlackenAction:
    """Blacken masks characters in string values at the given path."""

    def test_blacken_entire_string(self, provider: ContentFilteringProvider) -> None:
        obj = {"ssn": "123-45-6789"}
        constraint = _make_constraint([{"type": "blacken", "path": "$.ssn"}])
        result = provider.get_handler(constraint)(obj)
        assert result["ssn"] == "XXXXXXXXXXX"

    def test_blacken_with_disclose_right(self, provider: ContentFilteringProvider) -> None:
        obj = {"ssn": "123-45-6789"}
        constraint = _make_constraint([{
            "type": "blacken",
            "path": "$.ssn",
            "discloseRight": 4,
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["ssn"] == "XXXXXXX6789"

    def test_blacken_with_disclose_left(self, provider: ContentFilteringProvider) -> None:
        obj = {"ssn": "123-45-6789"}
        constraint = _make_constraint([{
            "type": "blacken",
            "path": "$.ssn",
            "discloseLeft": 3,
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["ssn"] == "123XXXXXXXX"

    def test_blacken_with_both_disclose(self, provider: ContentFilteringProvider) -> None:
        obj = {"card": "4111-1111-1111-1111"}
        constraint = _make_constraint([{
            "type": "blacken",
            "path": "$.card",
            "discloseLeft": 4,
            "discloseRight": 4,
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["card"] == "4111XXXXXXXXXXX1111"

    def test_blacken_custom_replacement(self, provider: ContentFilteringProvider) -> None:
        obj = {"pin": "9876"}
        constraint = _make_constraint([{
            "type": "blacken",
            "path": "$.pin",
            "replacement": "*",
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["pin"] == "****"

    def test_blacken_non_string_value_skips(self, provider: ContentFilteringProvider) -> None:
        obj = {"count": 42}
        constraint = _make_constraint([{"type": "blacken", "path": "$.count"}])
        result = provider.get_handler(constraint)(obj)
        assert result["count"] == 42

    def test_blacken_empty_string(self, provider: ContentFilteringProvider) -> None:
        obj = {"empty": ""}
        constraint = _make_constraint([{"type": "blacken", "path": "$.empty"}])
        result = provider.get_handler(constraint)(obj)
        assert result["empty"] == ""

    def test_blacken_disclosure_exceeds_length(self, provider: ContentFilteringProvider) -> None:
        obj = {"short": "AB"}
        constraint = _make_constraint([{
            "type": "blacken",
            "path": "$.short",
            "discloseLeft": 1,
            "discloseRight": 2,
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["short"] == "AB"

    def test_blacken_nested_path(self, provider: ContentFilteringProvider) -> None:
        obj = {"user": {"profile": {"ssn": "111-22-3333"}}}
        constraint = _make_constraint([{
            "type": "blacken",
            "path": "$.user.profile.ssn",
            "discloseRight": 4,
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["user"]["profile"]["ssn"] == "XXXXXXX3333"


# ---------------------------------------------------------------------------
# Replace action
# ---------------------------------------------------------------------------

class TestReplaceAction:
    """Replace overwrites the value at the given path."""

    def test_replace_string_value(self, provider: ContentFilteringProvider) -> None:
        obj = {"classification": "SECRET"}
        constraint = _make_constraint([{
            "type": "replace",
            "path": "$.classification",
            "replacement": "REDACTED",
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["classification"] == "REDACTED"

    def test_replace_with_none(self, provider: ContentFilteringProvider) -> None:
        obj = {"data": "sensitive"}
        constraint = _make_constraint([{
            "type": "replace",
            "path": "$.data",
            "replacement": None,
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["data"] is None

    def test_replace_nested_path(self, provider: ContentFilteringProvider) -> None:
        obj = {"a": {"b": {"c": "original"}}}
        constraint = _make_constraint([{
            "type": "replace",
            "path": "$.a.b.c",
            "replacement": "replaced",
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["a"]["b"]["c"] == "replaced"

    def test_replace_with_complex_object(self, provider: ContentFilteringProvider) -> None:
        obj = {"meta": "old"}
        replacement = {"status": "redacted", "reason": "policy"}
        constraint = _make_constraint([{
            "type": "replace",
            "path": "$.meta",
            "replacement": replacement,
        }])
        result = provider.get_handler(constraint)(obj)
        assert result["meta"] == {"status": "redacted", "reason": "policy"}

    def test_replace_nonexistent_key_no_error(self, provider: ContentFilteringProvider) -> None:
        obj = {"existing": "value"}
        constraint = _make_constraint([{
            "type": "replace",
            "path": "$.missing",
            "replacement": "x",
        }])
        result = provider.get_handler(constraint)(obj)
        assert result == {"existing": "value"}


# ---------------------------------------------------------------------------
# Delete action
# ---------------------------------------------------------------------------

class TestDeleteAction:
    """Delete removes the key at the given path."""

    def test_delete_top_level_key(self, provider: ContentFilteringProvider) -> None:
        obj = {"public": "ok", "internal": "secret"}
        constraint = _make_constraint([{"type": "delete", "path": "$.internal"}])
        result = provider.get_handler(constraint)(obj)
        assert result == {"public": "ok"}

    def test_delete_nested_key(self, provider: ContentFilteringProvider) -> None:
        obj = {"user": {"name": "Alice", "ssn": "123"}}
        constraint = _make_constraint([{"type": "delete", "path": "$.user.ssn"}])
        result = provider.get_handler(constraint)(obj)
        assert result == {"user": {"name": "Alice"}}

    def test_delete_nonexistent_key_no_error(self, provider: ContentFilteringProvider) -> None:
        obj = {"a": 1}
        constraint = _make_constraint([{"type": "delete", "path": "$.nonexistent"}])
        result = provider.get_handler(constraint)(obj)
        assert result == {"a": 1}


# ---------------------------------------------------------------------------
# Path parsing
# ---------------------------------------------------------------------------

class TestPathParsing:
    """Validate path parsing and rejection of unsupported syntax."""

    def test_simple_path(self) -> None:
        assert _parse_path("$.field") == ["field"]

    def test_nested_path(self) -> None:
        assert _parse_path("$.a.b.c") == ["a", "b", "c"]

    def test_invalid_path_no_dollar(self) -> None:
        assert _parse_path("field.nested") is None

    def test_invalid_path_array_indexing(self) -> None:
        assert _parse_path("$.items[0].name") is None

    def test_invalid_path_wildcard(self) -> None:
        assert _parse_path("$.items.*.name") is None

    def test_invalid_path_recursive_descent(self) -> None:
        assert _parse_path("$..name") is None

    def test_invalid_path_not_string(self) -> None:
        assert _parse_path(42) is None  # type: ignore[arg-type]

    def test_invalid_path_bare_dollar(self) -> None:
        assert _parse_path("$") is None

    def test_path_with_action_integration(self, provider: ContentFilteringProvider) -> None:
        """Actions with invalid paths are skipped, object returned unchanged."""
        obj = {"items": [{"name": "a"}]}
        constraint = _make_constraint([{"type": "delete", "path": "$.items[0].name"}])
        result = provider.get_handler(constraint)(obj)
        assert result == {"items": [{"name": "a"}]}


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

class TestSecurity:
    """Verify prototype pollution defense, ReDoS protection, and deep cloning."""

    @pytest.mark.parametrize("forbidden_key", [
        "__proto__",
        "__class__",
        "__dict__",
        "__globals__",
        "__builtins__",
        "__subclasses__",
    ])
    def test_prototype_pollution_path_rejected(
        self,
        provider: ContentFilteringProvider,
        forbidden_key: str,
    ) -> None:
        obj = {"safe": "value"}
        path = f"$.{forbidden_key}"
        constraint = _make_constraint([{"type": "delete", "path": path}])
        result = provider.get_handler(constraint)(obj)
        assert result == {"safe": "value"}

    def test_prototype_pollution_nested_path_rejected(
        self,
        provider: ContentFilteringProvider,
    ) -> None:
        obj = {"a": {"__proto__": "bad"}}
        constraint = _make_constraint([{"type": "delete", "path": "$.a.__proto__"}])
        result = provider.get_handler(constraint)(obj)
        # Action skipped because path contains forbidden key
        assert result == {"a": {"__proto__": "bad"}}

    def test_redos_nested_quantifiers_rejected(self) -> None:
        assert _is_safe_regex("(a+)+") is False

    def test_redos_long_pattern_rejected(self) -> None:
        assert _is_safe_regex("a" * 201) is False

    def test_safe_regex_accepted(self) -> None:
        assert _is_safe_regex(r"^\d{3}-\d{2}-\d{4}$") is True

    def test_deep_clone_original_not_mutated(self, provider: ContentFilteringProvider) -> None:
        original = {"user": {"name": "Alice", "ssn": "123-45-6789"}}
        frozen = copy.deepcopy(original)
        constraint = _make_constraint([
            {"type": "blacken", "path": "$.user.ssn"},
            {"type": "delete", "path": "$.user.name"},
        ])
        provider.get_handler(constraint)(original)
        assert original == frozen


# ---------------------------------------------------------------------------
# Multiple actions
# ---------------------------------------------------------------------------

class TestMultipleActions:
    """Actions within a single constraint are applied in sequence."""

    def test_apply_blacken_then_delete(self, provider: ContentFilteringProvider) -> None:
        obj = {"ssn": "123-45-6789", "notes": "internal only"}
        constraint = _make_constraint([
            {"type": "blacken", "path": "$.ssn", "discloseRight": 4},
            {"type": "delete", "path": "$.notes"},
        ])
        result = provider.get_handler(constraint)(obj)
        assert result == {"ssn": "XXXXXXX6789"}

    def test_apply_replace_then_blacken(self, provider: ContentFilteringProvider) -> None:
        obj = {"level": "TOP-SECRET", "code": "ABCDEF"}
        constraint = _make_constraint([
            {"type": "replace", "path": "$.level", "replacement": "CLASSIFIED"},
            {"type": "blacken", "path": "$.code", "discloseLeft": 2},
        ])
        result = provider.get_handler(constraint)(obj)
        assert result["level"] == "CLASSIFIED"
        assert result["code"] == "ABXXXX"


# ---------------------------------------------------------------------------
# Missing / invalid actions
# ---------------------------------------------------------------------------

class TestInvalidConstraints:
    """Edge cases for malformed constraints."""

    def test_missing_actions_key_returns_identity(
        self,
        provider: ContentFilteringProvider,
    ) -> None:
        constraint = {"type": "filterJsonContent"}
        handler = provider.get_handler(constraint)
        obj = {"a": 1}
        assert handler(obj) == {"a": 1}

    def test_actions_not_list_returns_identity(
        self,
        provider: ContentFilteringProvider,
    ) -> None:
        constraint = {"type": "filterJsonContent", "actions": "not-a-list"}
        handler = provider.get_handler(constraint)
        obj = {"a": 1}
        assert handler(obj) == {"a": 1}

    def test_invalid_action_type_skipped(
        self,
        provider: ContentFilteringProvider,
    ) -> None:
        obj = {"a": 1}
        constraint = _make_constraint([{"type": "unknown", "path": "$.a"}])
        result = provider.get_handler(constraint)(obj)
        assert result == {"a": 1}

    def test_action_not_dict_skipped(
        self,
        provider: ContentFilteringProvider,
    ) -> None:
        obj = {"a": 1}
        constraint = _make_constraint(["not-a-dict"])
        result = provider.get_handler(constraint)(obj)
        assert result == {"a": 1}

    def test_action_missing_type_skipped(
        self,
        provider: ContentFilteringProvider,
    ) -> None:
        obj = {"a": 1}
        constraint = _make_constraint([{"path": "$.a"}])
        result = provider.get_handler(constraint)(obj)
        assert result == {"a": 1}


# ---------------------------------------------------------------------------
# _blacken_value unit tests
# ---------------------------------------------------------------------------

class TestBlackenValueFunction:
    """Direct tests for the _blacken_value helper."""

    @pytest.mark.parametrize(
        "value, replacement, left, right, expected",
        [
            ("secret", "X", 0, 0, "XXXXXX"),
            ("secret", "*", 0, 0, "******"),
            ("secret", "X", 2, 0, "seXXXX"),
            ("secret", "X", 0, 3, "XXXret"),
            ("secret", "X", 2, 2, "seXXet"),
            ("AB", "X", 1, 1, "AB"),
            ("", "X", 0, 0, ""),
            ("A", "X", 0, 0, "X"),
            ("AB", "X", 0, 0, "XX"),
            ("ABC", "X", 1, 1, "AXC"),
        ],
        ids=[
            "full-mask",
            "custom-char",
            "disclose-left-only",
            "disclose-right-only",
            "disclose-both",
            "disclosure-equals-length",
            "empty-string",
            "single-char",
            "two-chars",
            "three-chars-both-disclosed",
        ],
    )
    def test_blacken_value(
        self,
        value: str,
        replacement: str,
        left: int,
        right: int,
        expected: str,
    ) -> None:
        assert _blacken_value(value, replacement, left, right) == expected


# ---------------------------------------------------------------------------
# _identity
# ---------------------------------------------------------------------------

class TestIdentity:

    def test_returns_input_unchanged(self) -> None:
        obj = {"a": [1, 2, 3]}
        assert _identity(obj) is obj


# ===========================================================================
# ContentFilterPredicateProvider
# ===========================================================================

class TestContentFilterPredicateProviderResponsibility:

    def test_responsible_for_predicate_constraint(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = {"type": "jsonContentFilterPredicate", "conditions": []}
        assert predicate_provider.is_responsible(constraint) is True

    @pytest.mark.parametrize("constraint", [
        {"type": "filterJsonContent"},
        {"type": "other"},
        "jsonContentFilterPredicate",
        None,
    ], ids=[
        "filter-type",
        "other-type",
        "string-not-dict",
        "none",
    ])
    def test_not_responsible_for_other_constraints(
        self,
        predicate_provider: ContentFilterPredicateProvider,
        constraint: Any,
    ) -> None:
        assert predicate_provider.is_responsible(constraint) is False


class TestConditionOperators:
    """Verify all supported comparison operators."""

    @pytest.mark.parametrize(
        "operator, element_value, condition_value, expected",
        [
            ("==", "PUBLIC", "PUBLIC", True),
            ("==", "PUBLIC", "PRIVATE", False),
            ("!=", "PUBLIC", "PRIVATE", True),
            ("!=", "PUBLIC", "PUBLIC", False),
            (">=", 10, 5, True),
            (">=", 5, 5, True),
            (">=", 4, 5, False),
            ("<=", 5, 10, True),
            ("<=", 5, 5, True),
            ("<=", 6, 5, False),
            (">", 10, 5, True),
            (">", 5, 5, False),
            ("<", 5, 10, True),
            ("<", 5, 5, False),
        ],
        ids=[
            "eq-true",
            "eq-false",
            "ne-true",
            "ne-false",
            "gte-greater",
            "gte-equal",
            "gte-less",
            "lte-less",
            "lte-equal",
            "lte-greater",
            "gt-true",
            "gt-false",
            "lt-true",
            "lt-false",
        ],
    )
    def test_operator(
        self,
        predicate_provider: ContentFilterPredicateProvider,
        operator: str,
        element_value: Any,
        condition_value: Any,
        expected: bool,
    ) -> None:
        constraint = _make_predicate_constraint([{
            "path": "$.field",
            "operator": operator,
            "value": condition_value,
        }])
        predicate = predicate_provider.get_handler(constraint)
        element = {"field": element_value}
        assert predicate(element) is expected


class TestRegexOperator:
    """Verify =~ operator with safe and unsafe patterns."""

    def test_regex_match_true(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([{
            "path": "$.email",
            "operator": "=~",
            "value": r"^[a-z]+@example\.com$",
        }])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"email": "alice@example.com"}) is True

    def test_regex_match_false(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([{
            "path": "$.email",
            "operator": "=~",
            "value": r"^[a-z]+@example\.com$",
        }])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"email": "ALICE@OTHER.COM"}) is False

    def test_regex_unsafe_pattern_returns_false(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([{
            "path": "$.data",
            "operator": "=~",
            "value": "(a+)+",
        }])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"data": "aaa"}) is False

    def test_regex_non_string_value_returns_false(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([{
            "path": "$.count",
            "operator": "=~",
            "value": r"\d+",
        }])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"count": 42}) is False

    def test_regex_non_string_pattern_returns_false(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([{
            "path": "$.data",
            "operator": "=~",
            "value": 42,
        }])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"data": "hello"}) is False


class TestMultipleConditions:
    """Multiple conditions use AND logic."""

    def test_all_conditions_pass(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([
            {"path": "$.level", "operator": "==", "value": "PUBLIC"},
            {"path": "$.score", "operator": ">=", "value": 5},
        ])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"level": "PUBLIC", "score": 10}) is True

    def test_one_condition_fails(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([
            {"path": "$.level", "operator": "==", "value": "PUBLIC"},
            {"path": "$.score", "operator": ">=", "value": 5},
        ])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"level": "PRIVATE", "score": 10}) is False


class TestConditionEdgeCases:
    """Edge cases for condition evaluation."""

    def test_missing_path_in_element_returns_false(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([{
            "path": "$.missing",
            "operator": "==",
            "value": "x",
        }])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"other": "y"}) is False

    def test_nested_path_in_condition(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([{
            "path": "$.user.role",
            "operator": "==",
            "value": "admin",
        }])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"user": {"role": "admin"}}) is True
        assert predicate({"user": {"role": "viewer"}}) is False

    def test_conditions_not_list_returns_true(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = {"type": "jsonContentFilterPredicate", "conditions": "invalid"}
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"anything": True}) is True

    def test_empty_conditions_returns_true(
        self,
        predicate_provider: ContentFilterPredicateProvider,
    ) -> None:
        constraint = _make_predicate_constraint([])
        predicate = predicate_provider.get_handler(constraint)
        assert predicate({"anything": True}) is True

    def test_condition_not_dict_returns_false(self) -> None:
        assert _evaluate_condition({"a": 1}, "not-a-dict") is False  # type: ignore[arg-type]

    def test_unknown_operator_returns_false(self) -> None:
        condition = {"path": "$.a", "operator": "??", "value": 1}
        assert _evaluate_condition({"a": 1}, condition) is False


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    """Verify that providers satisfy the constraint handler protocols."""

    def test_content_filtering_satisfies_mapping_protocol(self) -> None:
        from sapl_base.constraint_types import MappingConstraintHandlerProvider
        provider = ContentFilteringProvider()
        assert isinstance(provider, MappingConstraintHandlerProvider)

    def test_predicate_satisfies_filter_predicate_protocol(self) -> None:
        from sapl_base.constraint_types import FilterPredicateConstraintHandlerProvider
        provider = ContentFilterPredicateProvider()
        assert isinstance(provider, FilterPredicateConstraintHandlerProvider)
