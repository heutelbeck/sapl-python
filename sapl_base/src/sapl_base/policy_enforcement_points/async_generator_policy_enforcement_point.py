import asgiref.sync

from sapl_base.policy_enforcement_points.streaming_policy_enforcement_point import StreamingPolicyEnforcementPoint


class AsyncGeneratorPolicyEnforcementPoint(StreamingPolicyEnforcementPoint):


    async def yield_return_value(self):
        async for value in self._enforced_function(self._function_args, self._function_kwargs):
            yield value

    async def enforce_till_denied(self, subject, action, resource, environment, scope):
        subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource, environment,
                                                                                scope, "enforce_till_denied")
        await self.create_task_and_bundle(subscription)

        async for value in self.yield_return_value():
            self._check_if_denied(self._current_decision)
            yield value

    async def drop_while_denied(self, subject, action, resource, environment, scope):
        subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource, environment,
                                                                                scope, "drop_while_denied")

        await self.create_task_and_bundle(subscription)

        async for value in self.yield_return_value():
            if self._current_decision == "DENY":
                continue
            yield value

    async def recoverable_if_denied(self, subject, action, resource, environment, scope):

        subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource, environment,
                                                                                scope, "recoverable_if_denied")

        await self.create_task_and_bundle(subscription)
        async for value in self.yield_return_value():
            """TODO"""
            yield value


