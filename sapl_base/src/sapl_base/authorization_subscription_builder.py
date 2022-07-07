from .authorization_subscriptions import AuthorizationSubscription, MultiSubscription


class BaseAuthorizationSubscriptionBuilder:

    def __init__(self, values: dict, subject=None, action=None, resource=None, environment=None,
                 subject_filter=None, action_filter=None, resource_filter=None,
                 environment_filter=None):

        self._values = values
        self._original_subject = subject
        self._original_action = action
        self._original_resource = resource
        self._original_environment = environment

        self._resource_filter = resource_filter
        self._subject_filter = subject_filter
        self._action_filter = action_filter
        self._environment_filter = environment_filter

        if subject is not None:
            self.subject = subject
        else:
            self.set_subject_filter(self._subject_filter)

        if action is not None:
            self.action = action
        else:
            self.set_action_filter(self._action_filter)

        if resource is not None:
            self.resource = resource
        else:
            self.set_resource_filter(self._resource_filter)

        if environment is not None:
            self.environment = environment
        else:
            self.set_environment_filter(self._environment_filter)

    def _get_attributes_from_dict(self, values, dictionary, authorization_subscription_dictionary):
        for k, v in dictionary.items():
            try:
                if values.__contains__(k):
                    authorization_subscription_dictionary[k] = self._filter_attributes_for_authorization_subscription(
                        values[k], v)
                if (values.__len__()-1) >= k:
                    authorization_subscription_dictionary[k] = self._filter_attributes_for_authorization_subscription(
                        values[k], v)
            except(TypeError, AttributeError):
                try:
                    if hasattr(values, k):
                        authorization_subscription_dictionary[
                            k] = self._filter_attributes_for_authorization_subscription(getattr(values, k), v)
                except(TypeError, AttributeError):
                    pass

    def _add_attribute_to_authorization_subscription(self, values, element, dictionary):
        try:
            if values.__contains__(element):
                if not callable(values[element]):
                    dictionary[element] = values.get(element)
            if (values.__len__() - 1) >= element:
                if not callable(values[element]):
                    dictionary[element] = values.get(element)
        except(TypeError, AttributeError):
            try:
                if hasattr(values, element):
                    dictionary[element] = getattr(values, element)
            except(TypeError, AttributeError):
                pass

    def _filter_attributes_for_authorization_subscription(self, values, sapl_filter):
        dic = dict()
        try:
            if isinstance(sapl_filter, (list, tuple, set, range)):
                for element in sapl_filter:
                    if isinstance(element, dict):
                        self._get_attributes_from_dict(values, element, dic)

                    else:
                        self._add_attribute_to_authorization_subscription(values, element, dic)

            elif isinstance(sapl_filter, dict):
                self._get_attributes_from_dict(values, sapl_filter, dic)

            else:
                self._add_attribute_to_authorization_subscription(values, sapl_filter, dic)

        except (TypeError, AttributeError):
            pass
        return dic

    def set_subject_filter(self, subject_filter):
        self._subject_filter = subject_filter
        if self._original_subject is None:
            self.subject = self._filter_attributes_for_authorization_subscription(self._values, self._subject_filter)

    def set_action_filter(self, action_filter):
        self._action_filter = action_filter
        if self._original_action is None:
            self.action = self._filter_attributes_for_authorization_subscription(self._values, self._action_filter)

    def set_resource_filter(self, resource_filter):
        self._resource_filter = resource_filter
        if self._original_resource is None:
            self.resource = self._filter_attributes_for_authorization_subscription(self._values, self._resource_filter)

    def set_environment_filter(self, environment_filter):
        self._environment_filter = environment_filter
        if self._original_environment is None:
            self.environment = self._filter_attributes_for_authorization_subscription(self._values,
                                                                                      self._environment_filter)

    def set_values(self, values: dict):
        self._values = values
        self.set_subject_filter(self._subject_filter)
        self.set_action_filter(self._action_filter)
        self.set_resource_filter(self._resource_filter)
        self.set_environment_filter(self._environment_filter)

    def create_authorization_subscription(self) -> AuthorizationSubscription:
        return AuthorizationSubscription(self._remove_empty_dicts(self.subject), self._remove_empty_dicts(self.action),
                                         self._remove_empty_dicts(self.resource),
                                         self._remove_empty_dicts(self.environment))

    def _remove_empty_dicts(self, dictionary: dict):
        dict_copy = dictionary.copy()
        for k, v in dictionary.items():
            if isinstance(v, dict):
                dict_copy[k] = self._remove_empty_dicts(v)

            if dict_copy[k] is None:
                dict_copy.pop(k)

        if not dict_copy:
            return None

        return dict_copy

    # @classmethod
    # def construct_authorization_subscription_builder_for_httprequest(cls, request: dict, subject=None, action=None,
    #                                                                  resource=None,
    #                                                                  environment=None):
    #     subject_filter = ['user']
    #     action_filter = None
    #     resource_filter = None
    #     environment_filter = None
    #     return BaseAuthorizationSubscriptionBuilder(request, subject, action, resource, environment, subject_filter,
    #                                                 action_filter, resource_filter,
    #                                                 environment_filter)


class MultiSubscriptionBuilder:
    SUBJECT_ID = "subjectID"
    ACTION_ID = "actionID"
    RESOURCE_ID = "resourceID"
    ENVIRONMENT_ID = "environmentID"
    AUTHORIZATION_SUBSCRIPTION_ID = "authorization_subscriptionID"

    def __init__(self):
        self.subject = []
        self.action = []
        self.resource = []
        self.environment = []
        self.authorization_subscription = []

    def add_authorization_subscription(self, authorization_subscription: AuthorizationSubscription):
        dic = dict()
        self._add_subject(authorization_subscription, dic)
        self._add_action(authorization_subscription, dic)
        self._add_resource(authorization_subscription, dic)
        self._add_environment(authorization_subscription, dic)
        self.authorization_subscription.append({authorization_subscription.subscription_id: dic})

    def _add_subject(self, authorization_subscription: AuthorizationSubscription, dictionary: dict):
        if authorization_subscription.subject:
            self.subject.append(authorization_subscription.subject)
            dictionary[self.SUBJECT_ID] = len(self.subject) - 1

    def _add_action(self, authorization_subscription: AuthorizationSubscription, dictionary: dict):
        if authorization_subscription.action:
            self.action.append(authorization_subscription.action)
            dictionary[self.ACTION_ID] = len(self.action) - 1

    def _add_resource(self, authorization_subscription: AuthorizationSubscription, dictionary: dict):
        if authorization_subscription.resource:
            self.resource.append(authorization_subscription.resource)
            dictionary[self.RESOURCE_ID] = len(self.resource) - 1

    def _add_environment(self, authorization_subscription: AuthorizationSubscription, dictionary: dict):
        if authorization_subscription.environment:
            self.environment.append(authorization_subscription.environment)
            dictionary[self.ENVIRONMENT_ID] = len(self.environment) - 1

    def _remove_empty_list(self, subscription_list):
        if not subscription_list:
            return None
        return subscription_list

    def create_multi_subscription(self):
        return MultiSubscription(self._remove_empty_list(self.subject), self._remove_empty_list(self.action),
                                 self._remove_empty_list(self.resource), self._remove_empty_list(self.environment),
                                 self._remove_empty_list(self.authorization_subscription))
