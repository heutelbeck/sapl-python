from sapl_base.constraint_handling.constraint_handler_service import constraint_handler_service
from sapl_base.policy_decision_points import pdp
from sapl_base.policy_enforcement_points.base_policy_enforcement_point import BasePolicyEnforcementPoint


class AsyncPolicyEnforcementPoint(BasePolicyEnforcementPoint):

    async def post_enforce(self, subject, action, resource, environment, scope):
        await self.async_get_return_value()
        return self._post_enforce_handling(subject, action, resource, environment, scope)

    async def pre_enforce(self, subject, action, resource, environment, scope):
        subscription = self.get_subscription(subject, action, resource, environment, scope, "pre_enforce")
        decision = await pdp.async_decide_once(subscription)
        bundle = constraint_handler_service.build_pre_enforce_bundle(decision)
        self.check_if_denied(decision)
        bundle.execute_on_decision_handler(decision)
        bundle.execute_function_arguments_mapper(self.values_dict["args"])
        return_value = await self.async_get_return_value()
        return bundle.execute_result_handler(return_value)

    async def pre_and_post_enforce(self, subject, action, resource, environment, scope):
        self.values_dict["return_value"] = self.pre_enforce(subject, action, resource, environment, scope)
        return self._post_enforce_handling(subject, action, resource, environment, scope)

    async def _post_enforce_handling(self, subject, action, resource, environment, scope):
        subscription = self.get_subscription(subject, action, resource, environment, scope, "post_enforce")
        decision = await pdp.async_decide_once(subscription)
        bundle = constraint_handler_service.build_post_enforce_bundle(decision)
        self.check_if_denied(decision)
        bundle.execute_on_decision_handler(decision)
        return bundle.execute_result_handler(self.values_dict["return_value"])
