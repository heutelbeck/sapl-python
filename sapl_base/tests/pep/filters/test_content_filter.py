from __future__ import annotations

from typing import Any

import pytest

from sapl_base.pep import (
    ABSENT,
    DECISION,
    ERROR,
    OUTPUT,
    EnforcementPlanner,
    OutputSignal,
)
from sapl_base.pep.filters import ContentFilteringProvider, ContentFilterPredicateProvider
from sapl_base.types import AuthorizationDecision, Decision

_STREAM_SIGNALS = frozenset({DECISION, OUTPUT, ERROR})


def _decision(*obligations: Any) -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=tuple(obligations))


class TestContentFilteringProvider:
    def test_blacken_action_masks_string_field(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilteringProvider()])
        plan = planner.plan(
            _decision({
                "type": "filterJsonContent",
                "actions": [{"type": "blacken", "path": "$.ssn", "discloseLeft": 0, "discloseRight": 4}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"name": "Jane", "ssn": "123-45-6789"}))
        assert result.value["ssn"].endswith("6789")
        assert result.value["ssn"].startswith("█")
        assert result.value["name"] == "Jane"

    def test_replace_action_substitutes_value(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilteringProvider()])
        plan = planner.plan(
            _decision({
                "type": "filterJsonContent",
                "actions": [{"type": "replace", "path": "$.email", "replacement": "[redacted]"}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"email": "alice@example.com"}))
        assert result.value == {"email": "[redacted]"}

    def test_delete_action_removes_key(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilteringProvider()])
        plan = planner.plan(
            _decision({
                "type": "filterJsonContent",
                "actions": [{"type": "delete", "path": "$.password"}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"user": "alice", "password": "x"}))
        assert "password" not in result.value
        assert result.value["user"] == "alice"

    def test_deep_clone_does_not_mutate_input(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilteringProvider()])
        plan = planner.plan(
            _decision({
                "type": "filterJsonContent",
                "actions": [{"type": "delete", "path": "$.secret"}],
            }),
            _STREAM_SIGNALS,
        )
        original = {"secret": "hush", "id": 1}
        plan.execute(OutputSignal(value=original))
        assert original == {"secret": "hush", "id": 1}

    def test_filters_each_element_in_a_list(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilteringProvider()])
        plan = planner.plan(
            _decision({
                "type": "filterJsonContent",
                "actions": [{"type": "delete", "path": "$.secret"}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(
            OutputSignal(value=[{"id": 1, "secret": "a"}, {"id": 2, "secret": "b"}])
        )
        assert result.value == [{"id": 1}, {"id": 2}]

    def test_prototype_pollution_path_denies(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilteringProvider()])
        plan = planner.plan(
            _decision({
                "type": "filterJsonContent",
                "actions": [{"type": "delete", "path": "$.__proto__"}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"foo": "bar"}))
        assert result.failure_state is True

    def test_unsupported_path_syntax_fails_closed(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilteringProvider()])
        plan = planner.plan(
            _decision({
                "type": "filterJsonContent",
                "actions": [{"type": "delete", "path": "$.items[?(@.id==1)]"}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"items": [{"id": 1}]}))
        assert result.failure_state is True

    def test_unknown_action_type_denies(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilteringProvider()])
        plan = planner.plan(
            _decision({
                "type": "filterJsonContent",
                "actions": [{"type": "exfiltrate", "path": "$.secret"}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"secret": "x"}))
        assert result.failure_state is True

    def test_irrelevant_constraint_type_yields_no_handlers(self) -> None:
        provider = ContentFilteringProvider()
        assert provider.get_handlers({"type": "other"}) == ()

    def test_provider_returns_one_output_mapper(self) -> None:
        provider = ContentFilteringProvider()
        handlers = provider.get_handlers({"type": "filterJsonContent", "actions": []})
        assert len(handlers) == 1
        assert handlers[0].signal is OUTPUT
        assert handlers[0].shape == "mapper"
        assert handlers[0].priority == 0


class TestContentFilterPredicateProvider:
    def test_predicate_keeps_element_when_all_conditions_pass(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilterPredicateProvider()])
        plan = planner.plan(
            _decision({
                "type": "jsonContentFilterPredicate",
                "conditions": [{"path": "$.role", "operator": "==", "value": "doctor"}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"role": "doctor"}))
        assert result.value == {"role": "doctor"}

    def test_predicate_drops_element_when_a_condition_fails(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilterPredicateProvider()])
        plan = planner.plan(
            _decision({
                "type": "jsonContentFilterPredicate",
                "conditions": [{"path": "$.role", "operator": "==", "value": "doctor"}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"role": "nurse"}))
        assert result.value is ABSENT  # mapper returned DROP

    def test_predicate_filters_list_keeping_only_matching_elements(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilterPredicateProvider()])
        plan = planner.plan(
            _decision({
                "type": "jsonContentFilterPredicate",
                "conditions": [{"path": "$.active", "operator": "==", "value": True}],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(
            OutputSignal(value=[
                {"id": 1, "active": True},
                {"id": 2, "active": False},
                {"id": 3, "active": True},
            ])
        )
        assert result.value == [{"id": 1, "active": True}, {"id": 3, "active": True}]

    @pytest.mark.parametrize(
        "operator, value, expected",
        [
            ("==", "x", True),
            ("!=", "y", True),
            (">=", 5, True),
            ("<=", 10, True),
            (">", 4, True),
            ("<", 11, True),
            ("=~", r"^x", True),
        ],
    )
    def test_condition_operators(self, operator: str, value: Any, expected: bool) -> None:
        planner = EnforcementPlanner(providers=[ContentFilterPredicateProvider()])
        plan = planner.plan(
            _decision({
                "type": "jsonContentFilterPredicate",
                "conditions": [{"path": "$.field", "operator": operator, "value": value}],
            }),
            _STREAM_SIGNALS,
        )
        record = {"field": "x" if operator in {"==", "!=", "=~"} else 7}
        result = plan.execute(OutputSignal(value=record))
        if expected:
            assert result.value == record
        else:
            assert result.value is ABSENT

    def test_redos_pattern_fails_closed(self) -> None:
        planner = EnforcementPlanner(providers=[ContentFilterPredicateProvider()])
        plan = planner.plan(
            _decision({
                "type": "jsonContentFilterPredicate",
                "conditions": [
                    {"path": "$.field", "operator": "=~", "value": "(a+)+"},
                ],
            }),
            _STREAM_SIGNALS,
        )
        result = plan.execute(OutputSignal(value={"field": "aaaa"}))
        assert result.value is ABSENT

    def test_irrelevant_constraint_type_yields_no_handlers(self) -> None:
        provider = ContentFilterPredicateProvider()
        assert provider.get_handlers({"type": "other"}) == ()


def test_combined_filter_and_predicate_priority_order_filters_then_drops() -> None:
    """The content filter (priority 0) runs first, then the predicate (priority 100)."""
    planner = EnforcementPlanner(
        providers=[ContentFilteringProvider(), ContentFilterPredicateProvider()]
    )
    plan = planner.plan(
        _decision(
            {
                "type": "filterJsonContent",
                "actions": [{"type": "delete", "path": "$.secret"}],
            },
            {
                "type": "jsonContentFilterPredicate",
                "conditions": [{"path": "$.role", "operator": "==", "value": "doctor"}],
            },
        ),
        _STREAM_SIGNALS,
    )
    result = plan.execute(OutputSignal(value={"role": "doctor", "secret": "hush"}))
    assert result.value == {"role": "doctor"}
