from sapl_base.sapl_util import configuration


def import_base():
    import sapl_base.authorization_subscription_factory
    from sapl_base.base_authorization_subscription_factory import BaseAuthorizationSubscriptionFactory
    sapl_base.authorization_subscription_factory.auth_factory = BaseAuthorizationSubscriptionFactory()

    import sapl_base.policy_enforcement_points.policy_enforcement_point
    from sapl_base.policy_enforcement_points.base_streaming_pep import BaseStreamingPolicyEnforcementPoint
    sapl_base.policy_enforcement_points.policy_enforcement_point.streaming_pep = BaseStreamingPolicyEnforcementPoint

"Get the set framework of the project"
framework = configuration.get("framework", None)

match framework:
    case 'django':
        from sapl_django import *
    case 'tornado':
        from sapl_tornado import *
    case 'flask':
        from sapl_flask import *
    case _:
        import_base()
