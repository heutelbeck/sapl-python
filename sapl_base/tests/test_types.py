from __future__ import annotations

import pytest

from sapl_base.types import (
    RESOURCE_ABSENT,
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
)


class TestDecision:
    def test_permit_value(self):
        assert Decision.PERMIT.value == "PERMIT"

    def test_deny_value(self):
        assert Decision.DENY.value == "DENY"

    def test_indeterminate_value(self):
        assert Decision.INDETERMINATE.value == "INDETERMINATE"

    def test_not_applicable_value(self):
        assert Decision.NOT_APPLICABLE.value == "NOT_APPLICABLE"

    def test_is_string_enum(self):
        assert isinstance(Decision.PERMIT, str)
        assert Decision.PERMIT == "PERMIT"

    def test_all_members_present(self):
        assert len(Decision) == 4


class TestAuthorizationSubscription:
    def test_default_fields_are_none(self):
        subscription = AuthorizationSubscription()
        assert subscription.subject is None
        assert subscription.action is None
        assert subscription.resource is None
        assert subscription.environment is None
        assert subscription.secrets is None

    def test_fields_are_set(self):
        subscription = AuthorizationSubscription(
            subject="alice",
            action="read",
            resource="document",
            environment={"time": "morning"},
            secrets={"api_key": "secret123"},
        )
        assert subscription.subject == "alice"
        assert subscription.action == "read"
        assert subscription.resource == "document"
        assert subscription.environment == {"time": "morning"}
        assert subscription.secrets == {"api_key": "secret123"}

    def test_frozen_prevents_mutation(self):
        subscription = AuthorizationSubscription(subject="alice")
        with pytest.raises(AttributeError):
            subscription.subject = "bob"  # type: ignore[misc]

    def test_to_dict_includes_secrets(self):
        subscription = AuthorizationSubscription(
            subject="alice",
            action="read",
            resource="doc",
            secrets={"key": "value"},
        )
        result = subscription.to_dict()
        assert result == {
            "subject": "alice",
            "action": "read",
            "resource": "doc",
            "secrets": {"key": "value"},
        }

    def test_to_dict_omits_secrets_when_none(self):
        subscription = AuthorizationSubscription(subject="alice")
        result = subscription.to_dict()
        assert "secrets" not in result

    def test_to_dict_omits_environment_when_none(self):
        subscription = AuthorizationSubscription(subject="alice")
        result = subscription.to_dict()
        assert "environment" not in result

    def test_to_dict_includes_environment_when_set(self):
        subscription = AuthorizationSubscription(subject="alice", environment={"time": "now"})
        result = subscription.to_dict()
        assert result["environment"] == {"time": "now"}

    def test_to_loggable_dict_excludes_secrets(self):
        subscription = AuthorizationSubscription(
            subject="alice",
            secrets={"api_key": "super_secret"},
        )
        result = subscription.to_loggable_dict()
        assert "secrets" not in result
        assert result["subject"] == "alice"

    def test_to_loggable_dict_includes_all_non_secret_fields(self):
        subscription = AuthorizationSubscription(
            subject="alice",
            action="read",
            resource="doc",
            environment={"time": "now"},
            secrets="hidden",
        )
        result = subscription.to_loggable_dict()
        assert set(result.keys()) == {"subject", "action", "resource", "environment"}

    def test_to_loggable_dict_omits_environment_when_none(self):
        subscription = AuthorizationSubscription(subject="alice")
        result = subscription.to_loggable_dict()
        assert "environment" not in result

    def test_equality_by_value(self):
        sub_a = AuthorizationSubscription(subject="alice", action="read")
        sub_b = AuthorizationSubscription(subject="alice", action="read")
        assert sub_a == sub_b

    def test_inequality_by_value(self):
        sub_a = AuthorizationSubscription(subject="alice")
        sub_b = AuthorizationSubscription(subject="bob")
        assert sub_a != sub_b


class TestResourceAbsentSentinel:
    def test_singleton(self):
        from sapl_base.types import _ResourceAbsentSentinel

        assert _ResourceAbsentSentinel() is _ResourceAbsentSentinel()

    def test_is_falsy(self):
        assert not RESOURCE_ABSENT

    def test_repr(self):
        assert repr(RESOURCE_ABSENT) == "<RESOURCE_ABSENT>"


class TestAuthorizationDecision:
    def test_default_is_indeterminate(self):
        decision = AuthorizationDecision()
        assert decision.decision == Decision.INDETERMINATE
        assert decision.obligations == ()
        assert decision.advice == ()
        assert decision.resource is RESOURCE_ABSENT

    def test_indeterminate_factory(self):
        decision = AuthorizationDecision.indeterminate()
        assert decision.decision == Decision.INDETERMINATE

    def test_deny_factory(self):
        decision = AuthorizationDecision.deny()
        assert decision.decision == Decision.DENY

    def test_permit_factory(self):
        decision = AuthorizationDecision.permit()
        assert decision.decision == Decision.PERMIT

    def test_has_resource_when_absent(self):
        decision = AuthorizationDecision()
        assert decision.has_resource is False

    def test_has_resource_when_present(self):
        decision = AuthorizationDecision(resource={"data": "replaced"})
        assert decision.has_resource is True

    def test_has_resource_when_explicitly_none(self):
        decision = AuthorizationDecision(resource=None)
        assert decision.has_resource is True

    def test_frozen_prevents_mutation(self):
        decision = AuthorizationDecision.permit()
        with pytest.raises(AttributeError):
            decision.decision = Decision.DENY  # type: ignore[misc]

    def test_obligations_as_tuple(self):
        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            obligations=({"type": "log"}, {"type": "notify"}),
        )
        assert len(decision.obligations) == 2
        assert decision.obligations[0] == {"type": "log"}

    def test_advice_as_tuple(self):
        decision = AuthorizationDecision(
            decision=Decision.PERMIT,
            advice=({"type": "info"},),
        )
        assert len(decision.advice) == 1

    def test_equality_by_value(self):
        decision_a = AuthorizationDecision(decision=Decision.PERMIT, obligations=({"log": True},))
        decision_b = AuthorizationDecision(decision=Decision.PERMIT, obligations=({"log": True},))
        assert decision_a == decision_b

    def test_inequality_by_value(self):
        decision_a = AuthorizationDecision.permit()
        decision_b = AuthorizationDecision.deny()
        assert decision_a != decision_b


class TestMultiAuthorizationSubscription:
    def test_default_empty(self):
        multi = MultiAuthorizationSubscription()
        assert multi.subscriptions == {}

    def test_to_dict_includes_secrets(self):
        multi = MultiAuthorizationSubscription(
            subscriptions={
                "sub1": AuthorizationSubscription(subject="alice", secrets="secret"),
            }
        )
        result = multi.to_dict()
        assert "secrets" in result["sub1"]

    def test_to_loggable_dict_excludes_secrets(self):
        multi = MultiAuthorizationSubscription(
            subscriptions={
                "sub1": AuthorizationSubscription(subject="alice", secrets="secret"),
            }
        )
        result = multi.to_loggable_dict()
        assert "secrets" not in result["sub1"]


class TestIdentifiableAuthorizationDecision:
    def test_fields(self):
        decision = IdentifiableAuthorizationDecision(
            subscription_id="sub1",
            decision=AuthorizationDecision.permit(),
        )
        assert decision.subscription_id == "sub1"
        assert decision.decision.decision == Decision.PERMIT


class TestMultiAuthorizationDecision:
    def test_default_empty(self):
        multi = MultiAuthorizationDecision()
        assert multi.decisions == {}

    def test_with_decisions(self):
        multi = MultiAuthorizationDecision(
            decisions={
                "sub1": AuthorizationDecision.permit(),
                "sub2": AuthorizationDecision.deny(),
            }
        )
        assert multi.decisions["sub1"].decision == Decision.PERMIT
        assert multi.decisions["sub2"].decision == Decision.DENY
