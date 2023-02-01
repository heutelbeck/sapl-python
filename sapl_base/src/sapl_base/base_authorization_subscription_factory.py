from typing import Dict

from sapl_base.authorization_subscription_factory import AuthorizationSubscriptionFactory
from sapl_base.authorization_subscriptions import AuthorizationSubscription


class BaseAuthorizationSubscriptionFactory(AuthorizationSubscriptionFactory):
    """
    Basic implementation of an AuthorizationSubscriptionFactory, which is used, when the used framework is not set.
    """

    def create_authorization_subscription(self, values: Dict, subject, action, resource, environment, scope,
                                          enforcement_type):
        pass

    def _default_subject_function(self, values: Dict) -> Dict:
        pass

    def _default_action_function(self, values: Dict) -> Dict:
        pass

    def _default_resource_function(self, values: Dict) -> Dict:
        pass

    def _add_contextvar_to_values(self, values: Dict):
        pass

    def _identify_type(self, values: Dict):
        pass

    def _valid_combination(self, fn_type, enforcement_type):
        pass

    def _create_subscription_for_type(self, fn_type, values: Dict, subject, action, resource, environment,
                                      scope) -> AuthorizationSubscription:
        pass
