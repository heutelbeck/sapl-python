from abc import ABC, abstractmethod

from sapl_base.policy_enforcement_points.policy_enforcement_point import PolicyEnforcementPoint


class StreamingPolicyEnforcementPoint(PolicyEnforcementPoint, ABC):
    _current_decision: dict

    def __init__(self, fn, *args, **kwargs):
        super().__init__(fn, *args, **kwargs)
        self._decision_generator = self._update_decision()
        self._decision_generator.send(None)

    @abstractmethod
    async def enforce_till_denied(self, subject, action, resource, environment, scope):
        pass

    @abstractmethod
    async def drop_while_denied(self, subject, action, resource, environment, scope):
        pass

    @abstractmethod
    async def recoverable_if_denied(self, subject, action, resource, environment, scope):
        pass

    def _update_decision(self):
        while True:
            self._current_decision = yield
