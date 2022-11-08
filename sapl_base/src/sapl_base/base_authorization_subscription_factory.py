from sapl_base.authorization_subscription_factory import AuthorizationSubscriptionFactory
from sapl_base.authorization_subscriptions import AuthorizationSubscription


class BaseAuthorizationSubscriptionFactory(AuthorizationSubscriptionFactory):
    def _add_contextvar_to_values(self, values: dict):
        pass

    def _identify_type(self, values: dict):
        """

        :param values:
        """
        pass

    def _valid_combinations(self, fn_type, enforcement_type):
        """

        :param fn_type:
        :param enforcement_type:
        """
        pass

    def _create_subscription_for_type(self, fn_type, values: dict, subject, action, resource, environment,
                                      scope) -> AuthorizationSubscription:
        """

        :param fn_type:
        :param values:
        :param subject:
        :param action:
        :param resource:
        :param environment:
        :param scope:
        """
        pass
