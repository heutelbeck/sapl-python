import logging

import pytest

from sapl_base.policy_decision_points import DummyPolicyDecisionPoint
from sapl_base.authorization_subscriptions import AuthorizationSubscription


class TestDummyPolicyDecisionPoint:

    @pytest.fixture
    def dummy_pdp(self):
        return DummyPolicyDecisionPoint()

    def test_init(self, caplog):
        caplog.set_level(logging.WARNING)
        DummyPolicyDecisionPoint()
        assert caplog.messages[0] == (
            "ATTENTION THE APPLICATION USES A DUMMY PDP. ALL AUTHORIZATION REQUEST WILL RESULT IN A SINGLE "
            "PERMIT DECISION. DO NOT USE THIS IN PRODUCTION! THIS IS A PDP FOR TESTING AND DEVELOPING "
            "PURPOSE ONLY!")

    def test_from_settings(self):
        with pytest.raises(Exception):
            DummyPolicyDecisionPoint.from_settings()

    def test_decide(self, dummy_pdp):
        authorization_subscription = AuthorizationSubscription()
        assert dummy_pdp.decide(authorization_subscription) == {'decision': 'PERMIT'}

    def test_decide_once(self, dummy_pdp):
        authorization_subscription = AuthorizationSubscription()
        assert dummy_pdp.decide_once(authorization_subscription) == {'decision': 'PERMIT'}
    # def test_decide(self):
