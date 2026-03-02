from __future__ import annotations

import pytest

from sapl_base.types import (
    RESOURCE_ABSENT,
    Decision,
)
from sapl_base.validation import (
    parse_decision_from_json,
    parse_identifiable_decision_from_json,
    parse_multi_decision_from_json,
    validate_decision_response,
    validate_multi_decision_response,
)


class TestValidateDecisionResponse:
    class TestFailCloseBehavior:
        """REQ-FAILCLOSE-1: All failures must produce INDETERMINATE."""

        @pytest.mark.parametrize(
            "invalid_input",
            [
                pytest.param(None, id="none"),
                pytest.param("string", id="string"),
                pytest.param(42, id="integer"),
                pytest.param([], id="list"),
                pytest.param(True, id="boolean"),
            ],
        )
        def test_non_dict_input_returns_indeterminate(self, invalid_input):
            result = validate_decision_response(invalid_input)
            assert result.decision == Decision.INDETERMINATE

        def test_missing_decision_field_returns_indeterminate(self):
            result = validate_decision_response({"obligations": []})
            assert result.decision == Decision.INDETERMINATE

        @pytest.mark.parametrize(
            "invalid_decision",
            [
                pytest.param("ALLOW", id="unknown_string"),
                pytest.param("permit", id="lowercase"),
                pytest.param("", id="empty_string"),
                pytest.param(42, id="integer"),
                pytest.param(None, id="none"),
                pytest.param(True, id="boolean"),
            ],
        )
        def test_invalid_decision_value_returns_indeterminate(self, invalid_decision):
            result = validate_decision_response({"decision": invalid_decision})
            assert result.decision == Decision.INDETERMINATE

    class TestValidDecisions:
        @pytest.mark.parametrize(
            ("raw_decision", "expected"),
            [
                pytest.param("PERMIT", Decision.PERMIT, id="permit"),
                pytest.param("DENY", Decision.DENY, id="deny"),
                pytest.param("INDETERMINATE", Decision.INDETERMINATE, id="indeterminate"),
                pytest.param("NOT_APPLICABLE", Decision.NOT_APPLICABLE, id="not_applicable"),
            ],
        )
        def test_valid_decision_values_are_accepted(self, raw_decision, expected):
            result = validate_decision_response({"decision": raw_decision})
            assert result.decision == expected

    class TestObligationsAndAdvice:
        def test_obligations_as_list_become_tuple(self):
            result = validate_decision_response({
                "decision": "PERMIT",
                "obligations": [{"type": "log"}, {"type": "notify"}],
            })
            assert result.obligations == ({"type": "log"}, {"type": "notify"})

        def test_advice_as_list_becomes_tuple(self):
            result = validate_decision_response({
                "decision": "PERMIT",
                "advice": [{"info": "audit"}],
            })
            assert result.advice == ({"info": "audit"},)

        def test_missing_obligations_defaults_to_empty_tuple(self):
            result = validate_decision_response({"decision": "PERMIT"})
            assert result.obligations == ()

        def test_missing_advice_defaults_to_empty_tuple(self):
            result = validate_decision_response({"decision": "PERMIT"})
            assert result.advice == ()

        @pytest.mark.parametrize(
            "invalid_collection",
            [
                pytest.param("not_a_list", id="string"),
                pytest.param(42, id="integer"),
                pytest.param({"key": "value"}, id="dict"),
            ],
        )
        def test_non_list_obligations_default_to_empty_tuple(self, invalid_collection):
            result = validate_decision_response({
                "decision": "PERMIT",
                "obligations": invalid_collection,
            })
            assert result.obligations == ()

        @pytest.mark.parametrize(
            "invalid_collection",
            [
                pytest.param("not_a_list", id="string"),
                pytest.param(42, id="integer"),
                pytest.param({"key": "value"}, id="dict"),
            ],
        )
        def test_non_list_advice_defaults_to_empty_tuple(self, invalid_collection):
            result = validate_decision_response({
                "decision": "PERMIT",
                "advice": invalid_collection,
            })
            assert result.advice == ()

        def test_empty_obligations_list_becomes_empty_tuple(self):
            result = validate_decision_response({
                "decision": "PERMIT",
                "obligations": [],
            })
            assert result.obligations == ()

    class TestResourceSentinel:
        def test_absent_resource_uses_sentinel(self):
            result = validate_decision_response({"decision": "PERMIT"})
            assert result.resource is RESOURCE_ABSENT
            assert result.has_resource is False

        def test_present_resource_is_kept(self):
            result = validate_decision_response({
                "decision": "PERMIT",
                "resource": {"replacement": "data"},
            })
            assert result.resource == {"replacement": "data"}
            assert result.has_resource is True

        def test_null_resource_is_distinguished_from_absent(self):
            result = validate_decision_response({
                "decision": "PERMIT",
                "resource": None,
            })
            assert result.resource is None
            assert result.has_resource is True

    class TestUnknownFieldsStripped:
        def test_extra_fields_are_ignored(self):
            result = validate_decision_response({
                "decision": "PERMIT",
                "unknownField": "should be ignored",
                "anotherField": 42,
            })
            assert result.decision == Decision.PERMIT
            assert result.obligations == ()
            assert result.advice == ()
            assert result.has_resource is False


class TestParseDecisionFromJson:
    def test_valid_json_decision(self):
        result = parse_decision_from_json('{"decision": "PERMIT"}')
        assert result.decision == Decision.PERMIT

    def test_invalid_json_returns_indeterminate(self):
        result = parse_decision_from_json("not json at all")
        assert result.decision == Decision.INDETERMINATE

    def test_empty_string_returns_indeterminate(self):
        result = parse_decision_from_json("")
        assert result.decision == Decision.INDETERMINATE

    def test_none_input_returns_indeterminate(self):
        result = parse_decision_from_json(None)  # type: ignore[arg-type]
        assert result.decision == Decision.INDETERMINATE

    def test_full_decision_with_obligations(self):
        raw = '{"decision": "DENY", "obligations": [{"type": "log"}], "advice": [{"info": "x"}], "resource": "new"}'
        result = parse_decision_from_json(raw)
        assert result.decision == Decision.DENY
        assert result.obligations == ({"type": "log"},)
        assert result.advice == ({"info": "x"},)
        assert result.resource == "new"


class TestValidateMultiDecisionResponse:
    def test_valid_multi_decision(self):
        data = {
            "sub1": {"decision": "PERMIT"},
            "sub2": {"decision": "DENY"},
        }
        result = validate_multi_decision_response(data)
        assert result.decisions["sub1"].decision == Decision.PERMIT
        assert result.decisions["sub2"].decision == Decision.DENY

    def test_non_dict_returns_empty(self):
        result = validate_multi_decision_response("not a dict")
        assert result.decisions == {}

    def test_invalid_sub_decision_becomes_indeterminate(self):
        data = {
            "sub1": {"decision": "PERMIT"},
            "sub2": {"decision": "INVALID"},
        }
        result = validate_multi_decision_response(data)
        assert result.decisions["sub1"].decision == Decision.PERMIT
        assert result.decisions["sub2"].decision == Decision.INDETERMINATE


class TestParseMultiDecisionFromJson:
    def test_valid_json(self):
        raw = '{"sub1": {"decision": "PERMIT"}}'
        result = parse_multi_decision_from_json(raw)
        assert result.decisions["sub1"].decision == Decision.PERMIT

    def test_invalid_json_returns_empty(self):
        result = parse_multi_decision_from_json("not json")
        assert result.decisions == {}


class TestParseIdentifiableDecisionFromJson:
    def test_valid_identifiable_decision(self):
        raw = '{"authorizationSubscriptionId": "sub1", "authorizationDecision": {"decision": "PERMIT"}}'
        result = parse_identifiable_decision_from_json(raw)
        assert result is not None
        assert result.subscription_id == "sub1"
        assert result.decision.decision == Decision.PERMIT

    def test_missing_subscription_id_returns_none(self):
        raw = '{"authorizationDecision": {"decision": "PERMIT"}}'
        result = parse_identifiable_decision_from_json(raw)
        assert result is None

    def test_missing_decision_uses_indeterminate(self):
        raw = '{"authorizationSubscriptionId": "sub1"}'
        result = parse_identifiable_decision_from_json(raw)
        assert result is not None
        assert result.decision.decision == Decision.INDETERMINATE

    def test_invalid_json_returns_none(self):
        result = parse_identifiable_decision_from_json("not json")
        assert result is None

    def test_non_dict_returns_none(self):
        result = parse_identifiable_decision_from_json('"just a string"')
        assert result is None
