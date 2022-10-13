from sapl_base.policy_enforcement_points.streaming_policy_enforcement_point import StreamingPolicyEnforcementPoint


class DjangoStreamingPolicyEnforcementPoint(StreamingPolicyEnforcementPoint):
    async def enforce_till_denied(self, subject, action, resource, environment, scope):
        pass

    async def drop_while_denied(self, subject, action, resource, environment, scope):
        pass

    async def recoverable_if_denied(self, subject, action, resource, environment, scope):
        pass
