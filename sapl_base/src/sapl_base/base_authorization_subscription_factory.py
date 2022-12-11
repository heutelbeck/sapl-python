from sapl_base.authorization_subscription_factory import AuthorizationSubscriptionFactory
from sapl_base.authorization_subscriptions import AuthorizationSubscription


class BaseAuthorizationSubscriptionFactory(AuthorizationSubscriptionFactory):
    """
    Basic implementation of an AuthorizationSubscriptionFactory, which is used, when the used framework is not set.
    """

    def create_authorization_subscription(self, values: dict, subject, action, resource, environment, scope,
                                          enforcement_type):
        pass

    def _default_subject_function(self, values: dict) -> dict:
        pass

    def _default_action_function(self, values: dict) -> dict:
        pass

    def _default_resource_function(self, values: dict) -> dict:
        pass

    def _add_contextvar_to_values(self, values: dict):
        pass

    def _identify_type(self, values: dict):
        pass

    def _valid_combination(self, fn_type, enforcement_type):
        pass

    def _create_subscription_for_type(self, fn_type, values: dict, subject, action, resource, environment,
                                      scope) -> AuthorizationSubscription:
        pass
