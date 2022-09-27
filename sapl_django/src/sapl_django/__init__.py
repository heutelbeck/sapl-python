import sapl_base.policy_enforcement_point
from sapl_django.src.sapl_django.authz_subscription_factory import DjangoAuthorizationSubscriptionFactory

sapl_base.policy_enforcement_point.auth_factory = DjangoAuthorizationSubscriptionFactory()

__all__ = [
    'DjangoAuthorizationSubscriptionFactory',
]
