"""Spring-parity scenarios for the JSON content filter.

The Spring reference (ContentFilter.java) is fail-closed: whenever a
redaction cannot be applied (missing path, non-textual blacken target,
unknown action type, non-textual replacement, oversized blacken), the
handler raises AccessDeniedException, which turns the obligation into a
DENY so sensitive data never reaches the caller. It also round-trips
arbitrary payloads through native JSON (so plain objects are redacted,
not just dicts/lists), evaluates full JSONPath, gates filterJsonContent
actions by the constraint's conditions, and masks with the black-square
glyph under a bounded output budget.

These scenarios assert that correct behaviour. They are expected to fail
against the current port, which logs-and-returns-the-value-unchanged on
every error path and only understands simple dot-paths over dicts.

Traceability: CC-1, CC-2, CC-4, CC-7, CC-8.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sapl_base.pep import (
    DECISION,
    ERROR,
    OUTPUT,
    EnforcementPlanner,
    OutputSignal,
)
from sapl_base.pep.filters import ContentFilteringProvider, ContentFilterPredicateProvider
from sapl_base.types import AuthorizationDecision, Decision

_STREAM_SIGNALS = frozenset({DECISION, OUTPUT, ERROR})

_BLACK_SQUARE = "█"

_PLAINTEXT_SSN = "111-22-3333"


def _obligation(constraint: dict[str, Any]) -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=(constraint,))


def _run(provider: Any, constraint: dict[str, Any], payload: Any):
    planner = EnforcementPlanner(providers=[provider])
    plan = planner.plan(_obligation(constraint), _STREAM_SIGNALS)
    return plan.execute(OutputSignal(value=payload))


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


class TestRedactionFailsClosed:
    """A redaction that cannot be applied must DENY, never leak the value.

    Spring raises AccessDeniedException for each of these; in the PEP that
    surfaces as failure_state=True on the obligation-tagged handler.
    """

    def test_missing_path_denies_instead_of_passing_value_through(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "blacken", "path": "$.ssn"}]},
            {"name": "Jane"},
        )
        assert result.failure_state is True

    def test_blacken_on_non_textual_target_denies(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "blacken", "path": "$.card"}]},
            {"card": 1234567812345678},
        )
        assert result.failure_state is True

    def test_unknown_action_type_denies(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "shibboleth", "path": "$.ssn"}]},
            {"ssn": _PLAINTEXT_SSN},
        )
        assert result.failure_state is True

    def test_replace_with_non_textual_replacement_when_required_denies(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "replace", "path": "$.ssn"}]},
            {"ssn": _PLAINTEXT_SSN},
        )
        assert result.failure_state is True


class TestNonDictPayloadsAreRedacted:
    """Plain objects (dataclasses, models, ORM entities) are round-tripped
    through native JSON and redacted element-wise, just like dicts."""

    def test_object_attribute_is_redacted_not_leaked(self) -> None:
        @dataclass
        class Patient:
            name: str
            ssn: str

        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "blacken", "path": "$.ssn", "discloseRight": 4}]},
            Patient(name="Jane", ssn=_PLAINTEXT_SSN),
        )
        assert result.failure_state is False
        assert _field(result.value, "ssn") != _PLAINTEXT_SSN

    def test_list_of_objects_is_redacted_element_wise(self) -> None:
        @dataclass
        class Patient:
            ssn: str

        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "blacken", "path": "$.ssn"}]},
            [Patient(ssn=_PLAINTEXT_SSN), Patient(ssn=_PLAINTEXT_SSN)],
        )
        assert all(_field(element, "ssn") != _PLAINTEXT_SSN for element in result.value)


class TestFullJsonPathSupport:
    """Paths are full JSONPath. Wildcards and recursive descent redact
    every matching node, not silently no-op (which would leak)."""

    def test_wildcard_index_path_redacts_nested_field(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "blacken", "path": "$.items[*].ssn"}]},
            {"items": [{"ssn": _PLAINTEXT_SSN}, {"ssn": _PLAINTEXT_SSN}]},
        )
        assert all(item["ssn"] != _PLAINTEXT_SSN for item in result.value["items"])

    def test_recursive_descent_path_redacts_field(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "delete", "path": "$..ssn"}]},
            {"patient": {"ssn": _PLAINTEXT_SSN}},
        )
        assert "ssn" not in result.value["patient"]


class TestConditionalContentFiltering:
    """filterJsonContent gates each element by its conditions: matching
    elements are transformed, non-matching elements pass unchanged."""

    def test_only_matching_elements_are_transformed(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {
                "type": "filterJsonContent",
                "actions": [{"type": "blacken", "path": "$.ssn"}],
                "conditions": [{"path": "$.role", "operator": "==", "value": "admin"}],
            },
            [
                {"role": "admin", "ssn": _PLAINTEXT_SSN},
                {"role": "user", "ssn": _PLAINTEXT_SSN},
            ],
        )
        admin_row, user_row = result.value
        assert admin_row["ssn"] != _PLAINTEXT_SSN
        assert user_row["ssn"] == _PLAINTEXT_SSN

    def test_predicate_condition_on_absent_path_denies_rather_than_silently_dropping(self) -> None:
        result = _run(
            ContentFilterPredicateProvider(),
            {
                "type": "jsonContentFilterPredicate",
                "conditions": [{"path": "$.clearance", "operator": "==", "value": "secret"}],
            },
            {"role": "doctor"},
        )
        assert result.failure_state is True


class TestBlackenBoundsAndDefaults:
    """Blacken uses the black-square default mask, honours an explicit
    length, and bounds total output to prevent amplification."""

    def test_default_replacement_is_black_square_glyph(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {"type": "filterJsonContent", "actions": [{"type": "blacken", "path": "$.ssn"}]},
            {"ssn": _PLAINTEXT_SSN},
        )
        assert result.value["ssn"] == _BLACK_SQUARE * len(_PLAINTEXT_SSN)

    def test_explicit_length_controls_repetition_count(self) -> None:
        result = _run(
            ContentFilteringProvider(),
            {
                "type": "filterJsonContent",
                "actions": [{"type": "blacken", "path": "$.ssn", "replacement": "X", "length": 3}],
            },
            {"ssn": _PLAINTEXT_SSN},
        )
        assert result.value["ssn"] == "XXX"

    def test_output_amplification_beyond_max_blacken_denies(self) -> None:
        long_secret = "s" * 600
        oversized_replacement = "X" * 2000
        result = _run(
            ContentFilteringProvider(),
            {
                "type": "filterJsonContent",
                "actions": [
                    {"type": "blacken", "path": "$.ssn", "replacement": oversized_replacement},
                ],
            },
            {"ssn": long_secret},
        )
        assert result.failure_state is True
