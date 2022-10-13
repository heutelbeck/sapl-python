from sapl_base.authorization_subscription_factory import AuthorizationSubscriptionFactory
from sapl_base.authorization_subscriptions import AuthorizationSubscription


class DjangoAuthorizationSubscriptionFactory(AuthorizationSubscriptionFactory):
    def _create_subscription_for_type(self, fn_type, values: dict, subject, action, resource, environment,
                                      scope) -> AuthorizationSubscription:
        pass

    def _valid_combinations(self, fn_type, enforcement_type):
        pass

    def _identify_type(self, values: dict):
        pass


