import asyncio
import types
from abc import ABC, abstractmethod
from asyncio import Task

import sapl_base.policy_decision_points
from sapl_base.constraint_handling.constraint_handler_service import constraint_handler_service
from sapl_base.decision import Decision
from sapl_base.policy_enforcement_points.policy_enforcement_point import PolicyEnforcementPoint


class StreamingPolicyEnforcementPoint(PolicyEnforcementPoint, ABC):

    def __init__(self, fn: types.FunctionType, *args, instance=None,**kwargs):
        super().__init__(fn, *args, **kwargs)
        self._decision_generator = self._update_decision()
        self._decision_task: Task | None = None
        self._current_decision: Decision = Decision.deny_decision()
        if instance is not None:
            self.values_dict.update({"self":instance})


    async def init_decision_generator(self):
        await anext(self._decision_generator)

    async def _update_decision(self):
        while True:
            self._current_decision = yield

    async def create_task_and_bundle(self, subscription):
        decision, decision_stream = await sapl_base.policy_decision_points.pdp.async_decide(subscription,
                                                                                            self._decision_generator)
        self._decision_task = asyncio.create_task(decision_stream)
        self.constraint_handler_bundle = constraint_handler_service.build_pre_enforce_bundle(decision)

    @abstractmethod
    async def enforce_till_denied(self, subject, action, resource, environment, scope):
        pass

    @abstractmethod
    async def drop_while_denied(self, subject, action, resource, environment, scope):
        pass

    @abstractmethod
    async def recoverable_if_denied(self, subject, action, resource, environment, scope):
        pass


