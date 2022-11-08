from sapl_base.authorization_subscription_factory import AuthorizationSubscriptionFactory, client_request
from sapl_base.authorization_subscriptions import AuthorizationSubscription



class DjangoAuthorizationSubscriptionFactory(AuthorizationSubscriptionFactory):
    def _create_subscription_for_type(self, fn_type, values: dict, subject, action, resource, environment,
                                      scope) -> AuthorizationSubscription:
        pass

    def _valid_combinations(self, fn_type, enforcement_type):
        pass

    def _identify_type(self, values: dict):
        pass

    def _add_contextvar_to_values(self, values: dict):
        request = client_request.get('request')
        args: dict = values.get('args')
        if 'request' in args:
            return
        args.update({'request': request})

