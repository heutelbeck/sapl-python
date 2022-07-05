from .authorization_subscriptions import AuthorizationSubscription


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

    def _filter_values(self, values: dict, sapl_filter):
        dic = dict()
        try:
            if isinstance(sapl_filter, list):
                for element in sapl_filter:
                    if isinstance(element, dict):
                        for k, v in element.items():
                            if values.__contains__(k):
                                dic[k] = self._filter_values(values[k], v)
                    elif values.__contains__(element):
                        dic[element] = values.get(element)

            elif isinstance(sapl_filter, dict):
                for k, v in sapl_filter.items():
                    if values.__contains__(k):
                        dic[k] = self._filter_values(values[k], v)

            else:
                if values.__contains__(sapl_filter):
                    dic[sapl_filter] = values.get(sapl_filter)

        except (TypeError, IndexError):
            pass
        return dic

    def set_subject_filter(self, subject_filter):
        self._subject_filter = subject_filter
        if self._original_subject is None:
            self.subject = self._filter_values(self._values, self._subject_filter)

    def set_action_filter(self, action_filter):
        self._action_filter = action_filter
        if self._original_action is None:
            self.action = self._filter_values(self._values, self._action_filter)

    def set_resource_filter(self, resource_filter):
        self._resource_filter = resource_filter
        if self._original_resource is None:
            self.resource = self._filter_values(self._values, self._resource_filter)

    def set_environment_filter(self, environment_filter):
        self._environment_filter = environment_filter
        if self._original_environment is None:
            self.environment = self._filter_values(self._values, self._environment_filter)

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

        if dict_copy.__len__() == 0:
            return None

        return dict_copy

    @classmethod
    def construct_authorization_subscription_builder_for_httprequest(cls, request: dict, subject=None, action=None,
                                                                     resource=None,
                                                                     environment=None):
        subject_filter = ['user']
        action_filter = None
        resource_filter = None
        environment_filter = None
        return BaseAuthorizationSubscriptionBuilder(request, subject, action, resource, environment, subject_filter,
                                                    action_filter, resource_filter,
                                                    environment_filter)
