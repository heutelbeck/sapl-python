from sapl_base.policy_decision_points import pdp
from sapl_base.policy_enforcement_points.base_policy_enforcement_point import BasePolicyEnforcementPoint


class SyncPolicyEnforcementPoint(BasePolicyEnforcementPoint):

    def post_enforce(self, subject, action, resource, environment, scope):
        self.get_return_value()
        subscription = self.get_subscription(subject, action, resource, environment, scope, "post_enforce")
        decision = pdp.sync_decide(subscription)
        self.get_bundle(decision)
        self.check_if_denied(decision)
        # bundle run runnables
        # bundle run weitere Sachen
        # return value
        return

    def pre_enforce(self, subject, action, resource, environment, scope):
        subscription = self.get_subscription(subject, action, resource, environment, scope, "pre_enforce")
        decision = pdp.sync_decide(subscription)
        self.get_bundle(decision)
        self.check_if_denied(decision)
        # bundle run runnables
        self.get_return_value()
        # bundle run weitere Sachen
        # return value
        return

    def pre_and_post_enforce(self, subject, action, resource, environment, scope):
        subscription = self.get_subscription(subject, action, resource, environment, scope, "pre_enforce")
        decision = pdp.sync_decide(subscription)
        self.get_bundle(decision)
        self.check_if_denied(decision)
        # bundle run runnables
        self.get_return_value()
        # bundle run weitere Sachen
        subscription = self.get_subscription(subject, action, resource, environment, scope, "post_enforce")
        decision = pdp.sync_decide(subscription)
        self.get_bundle(decision)
        self.check_if_denied(decision)
        # bundle run runnables
        # bundle run weitere Sachen
        # return value
        return
