from sapl_base.constraint_handling.constraint_handler_service import constraint_handler_service
from sapl_base.decision import Decision
import sapl_base.policy_decision_points
#from sapl_base.policy_decision_points import pdp
from sapl_base.policy_enforcement_points.policy_enforcement_point import PolicyEnforcementPoint


class SyncPolicyEnforcementPoint(PolicyEnforcementPoint):

    def post_enforce(self, subject, action, resource, environment, scope):
        """

        :param subject:
        :param action:
        :param resource:
        :param environment:
        :param scope:
        :return:
        """
        self._get_return_value()
        return self._post_enforce_handling(subject, action, resource, environment, scope)

    def pre_enforce(self, subject, action, resource, environment, scope):
        """

        :param subject:
        :param action:
        :param resource:
        :param environment:
        :param scope:
        :return:
        """
        subscription = self._get_subscription(subject, action, resource, environment, scope, "pre_enforce")
        decision = sapl_base.policy_decision_points.pdp.decide(subscription)
        if decision is None:
            decision = Decision.deny_decision()
        self.constraint_handler_bundle = constraint_handler_service.build_pre_enforce_bundle(decision)
        self._check_if_denied(decision)
        self.constraint_handler_bundle.execute_on_decision_handler(decision)
        self.constraint_handler_bundle.execute_function_arguments_mapper(self.values_dict["args"])
        return_value = self._get_return_value()
        return self.constraint_handler_bundle.execute_result_handler(return_value)

    def pre_and_post_enforce(self, subject, action, resource, environment, scope):
        """

        :param subject:
        :param action:
        :param resource:
        :param environment:
        :param scope:
        :return:
        """
        self.values_dict["return_value"] = self.pre_enforce(subject, action, resource, environment, scope)
        return self._post_enforce_handling(subject, action, resource, environment, scope)

    def _post_enforce_handling(self, subject, action, resource, environment, scope):
        """

        :param subject:
        :param action:
        :param resource:
        :param environment:
        :param scope:
        :return:
        """
        subscription = self._get_subscription(subject, action, resource, environment, scope, "post_enforce")
        decision = sapl_base.policy_decision_points.pdp.decide(subscription)
        if decision is None:
            decision = Decision.deny_decision()
        self.constraint_handler_bundle = constraint_handler_service.build_post_enforce_bundle(decision)
        self._check_if_denied(decision)
        self.constraint_handler_bundle.execute_on_decision_handler(decision)
        return self.constraint_handler_bundle.execute_result_handler(self.values_dict["return_value"])
