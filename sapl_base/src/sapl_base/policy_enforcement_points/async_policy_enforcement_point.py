import asgiref.sync

from sapl_base.constraint_handling.constraint_handler_service import constraint_handler_service
from sapl_base.decision import Decision
import sapl_base.policy_decision_points
#from sapl_base.policy_decision_points import pdp
from sapl_base.policy_enforcement_points.policy_enforcement_point import PolicyEnforcementPoint


class AsyncPolicyEnforcementPoint(PolicyEnforcementPoint):
    """
    Implementation of an Asynchron PolicyEnforcementPoint
    """

    async def post_enforce(self, subject, action, resource, environment, scope):
        """
        Execute the decorated function, before creating an AuthorizationSubscription and receiving a Decision.
        The return-value of the executed function is sent to the PDP as a resource
        :param subject: subject which was provided to the decorator as argument if present
        :param action: action which was provided to the decorator as argument if present
        :param resource: resource which was provided to the decorator as argument if present
        :param environment: environment which was provided to the decorator as argument if present
        :param scope:

        :return: The return-value of the decorated function after it was enforced

        """
        await self._async_get_return_value()
        return await self._post_enforce_handling(subject, action, resource, environment, scope)

    async def pre_enforce(self, subject, action, resource, environment, scope):
        """
        Create a AuthorizationSubscription for the decorated function and request a Decision, before the function is executed.

        :param subject: subject which was provided to the decorator as argument if present
        :param action: action which was provided to the decorator as argument if present
        :param resource: resource which was provided to the decorator as argument if present
        :param environment: environment which was provided to the decorator as argument if present
        :param scope:
        :return: The return-value of the decorated function after it was enforced
        """
        subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource, environment,
                                                                                scope, "pre_enforce")
        decision = await sapl_base.policy_decision_points.pdp.async_decide_once(subscription)
        if decision is None:
            decision = Decision.deny_decision()
        self.constraint_handler_bundle = constraint_handler_service.build_pre_enforce_bundle(decision)
        self._check_if_denied(decision)
        self.constraint_handler_bundle.execute_on_decision_handler(decision)
        self.constraint_handler_bundle.execute_function_arguments_mapper(self.values_dict["args"])
        return_value = await self._async_get_return_value()
        return self.constraint_handler_bundle.execute_result_handler(return_value)

    async def pre_and_post_enforce(self, subject, action, resource, environment, scope):
        """
        Combination of pre_enforce and post_enforce.
        The decorated function is enforced before it is executed and after it is executed.

        :param subject: subject which was provided to the decorator as argument if present
        :param action: action which was provided to the decorator as argument if present
        :param resource: resource which was provided to the decorator as argument if present
        :param environment: environment which was provided to the decorator as argument if present
        :param scope:
        :return: The return-value of the decorated function after it was enforced
        """
        self.values_dict["return_value"] = await self.pre_enforce(subject, action, resource, environment, scope)
        return await self._post_enforce_handling(subject, action, resource, environment, scope)

    async def _post_enforce_handling(self, subject, action, resource, environment, scope):
        """
        Gets called after the decorated function is executed to enforce the function

        :param subject: subject which was provided to the decorator as argument if present
        :param action: action which was provided to the decorator as argument if present
        :param resource: resource which was provided to the decorator as argument if present
        :param environment: environment which was provided to the decorator as argument if present
        :param scope:
        :return: The return-value of the decorated function after it was enforced
        """
        subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource, environment,
                                                                                scope, "post_enforce")
        decision = await sapl_base.policy_decision_points.pdp.async_decide_once(subscription)
        if decision is None:
            decision = Decision.deny_decision()
        self.constraint_handler_bundle = constraint_handler_service.build_post_enforce_bundle(decision)
        self._check_if_denied(decision)
        self.constraint_handler_bundle.execute_on_decision_handler(decision)
        return self.constraint_handler_bundle.execute_result_handler(self.values_dict["return_value"])
