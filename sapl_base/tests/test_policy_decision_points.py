from unittest.mock import patch

import pytest

from sapl_base.decision import Decision
from sapl_base.policy_decision_points import PolicyDecisionPoint, DummyPolicyDecisionPoint, RemotePolicyDecisionPoint


class TestDummyPdp:

    @pytest.fixture(scope="class")
    def dummy_pdp(self):
        return PolicyDecisionPoint.dummy_pdp()

    def test_create_dummy_pdp(self, dummy_pdp):
        assert isinstance(dummy_pdp, DummyPolicyDecisionPoint)

    def test_decide_returns_permit(self, dummy_pdp):
        assert dummy_pdp.decide(None).decision == Decision.permit_decision().decision

    @pytest.mark.asyncio
    async def test_async_decide_once_returns_permit(self, event_loop, dummy_pdp):
        decision = await dummy_pdp.async_decide_once(None)
        assert decision.decision == Decision.permit_decision().decision

    @pytest.mark.asyncio
    async def test_async_decide_yields_permit(self, event_loop, dummy_pdp):
        async def decision_collector_gen():
            while True:
                decision = yield
                assert decision.decision == Decision.permit_decision().decision

        collector_gen = decision_collector_gen()
        await collector_gen.asend(None)
        initial_decision, permit_stream = await dummy_pdp.async_decide(None, collector_gen)
        assert initial_decision.decision == Decision.permit_decision().decision
        await permit_stream


def test_instantiate_pdp_raises():
    with pytest.raises(TypeError):
        PolicyDecisionPoint()


@patch.dict('sapl_base.sapl_util.configuration', {'dummy': True})
def test_dummy_configuration_creates_dummy_pdp():
    dummy_pdp = PolicyDecisionPoint.from_settings()
    assert isinstance(dummy_pdp, DummyPolicyDecisionPoint)


class TestRemotePolicyDecisionPoint:

    @patch.dict('sapl_base.sapl_util.configuration', {'verify': None})
    def test_when_verify_none_raise_exception(self):
        with pytest.raises(Exception):
            PolicyDecisionPoint.from_settings()

    @patch.dict('sapl_base.sapl_util.configuration', {'base_url': None})
    def test_when_url_none_raise_exception(self):
        with pytest.raises(Exception):
            PolicyDecisionPoint.from_settings()

    @pytest.fixture(scope="class")
    def pdp_from_configuration(self):
        return PolicyDecisionPoint.from_settings()

    def test_create_default_pdp_from_config(self, pdp_from_configuration):
        assert isinstance(pdp_from_configuration, RemotePolicyDecisionPoint)
