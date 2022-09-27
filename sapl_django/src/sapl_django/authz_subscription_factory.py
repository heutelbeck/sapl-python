from sapl_base.authorization_subscription_factory import BaseAuthorizationSubscriptionFactory
from sapl_base.authorization_subscriptions import AuthorizationSubscription


class DjangoAuthorizationSubscriptionFactory(BaseAuthorizationSubscriptionFactory):
    def _identify_type(self, values: dict):
        pass

    def _create_subscription_for_type(self, fn_type, values: dict, subject, action, resource,
                                      environment) -> AuthorizationSubscription:
        pass
