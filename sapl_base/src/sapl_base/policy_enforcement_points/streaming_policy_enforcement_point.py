import types

from sapl_base.policy_enforcement_points.base_policy_enforcement_point import BasePolicyEnforcementPoint
from sapl_base.policy_decision_points import pdp


class StreamingPolicyEnforcementPoint(BasePolicyEnforcementPoint):
    _current_decision: dict

    def __init__(self, fn, *args, **kwargs):
        super().__init__(fn, *args, **kwargs)
        self._decision_generator = self._update_decision()
        self._decision_generator.send(None)

    async def enforce_till_denied(self, subject, action, resource, environment, scope):
        subscription = self.get_subscription(subject, action, resource, environment, scope)
        first_decision,decision_update_coro = pdp.decide(subscription, self._decision_generator)
        self.get_bundle(first_decision)
        self.check_if_denied(first_decision)
        await self.get_return_value()
        # bundle run weitere Sachen
        # return value
        # Gen ist bekannt
        # Decisionstream ist vorhanden
        pass

    async def drop_while_denied(self, subject, action, resource, environment, scope):
        pass

    async def recoverable_if_denied(self, subject, action, resource, environment, scope):
        pass

    def _update_decision(self):
        while True:
            self._current_decision = yield
