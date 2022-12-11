from abc import ABC, abstractmethod

import asgiref.sync

from sapl_base.authorization_subscription_factory import auth_factory
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

    async def _get_subscription(self, subject, action, resource, environment, scope, enforcement_type):
        """

        :param subject:
        :param action:
        :param resource:
        :param environment:
        :param scope:
        :param enforcement_type:
        :return:
        """

        return await asgiref.sync.sync_to_async(auth_factory.create_authorization_subscription)(self.values_dict,
                                                                                                subject, action,
                                                                                                resource, environment,
                                                                                                scope, enforcement_type)

    def _update_decision(self):
        while True:
            self._current_decision = yield
