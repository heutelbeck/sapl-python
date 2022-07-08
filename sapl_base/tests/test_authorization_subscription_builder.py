import pytest

from sapl_base.authorization_subscription_builder import BaseAuthorizationSubscriptionFactory, MultiSubscriptionBuilder
from sapl_base.authorization_subscriptions import AuthorizationSubscription, MultiSubscription


class TestMultiSubscriptionBuilder:
    dict_subject = {"dict_subject": "dict_subject_value"}
    list_subject = [{"list_subject_1": "list_subject_value_1"}, {"list_subject_2": "list_subject_value_2"}]
    nested_subject = [dict_subject, {"nested_list_subject": list_subject}, {"neste_dict_subject": dict_subject}]

    dict_action = {"dict_action": "dict_action_value"}
    list_action = [{"list_action_1": "list_action_value_1"}, {"list_action_2": "list_action_value_2"}]
    nested_action = [dict_action, {"nested_list_action": list_action}, {"neste_dict_action": dict_action}]

    dict_resource = {"dict_resource": "dict_resource_value"}
    list_resource = [{"list_resource_1": "list_resource_value_1"}, {"list_resource_2": "list_resource_value_2"}]
    nested_resource = [dict_resource, {"nested_list_resource": list_resource}, {"neste_dict_resource": dict_resource}]

    dict_environment = {"dict_environment": "dict_environment_value"}
    list_environment = [{"list_environment_1": "list_environment_value_1"},
                        {"list_environment_2": "list_environment_value_2"}]
    nested_environment = [dict_environment, {"nested_list_environment": list_environment},
                          {"neste_dict_environment": dict_environment}]

    multi_builder_test_subscriptions = [
        [
            AuthorizationSubscription(dict_subject, None, dict_resource, nested_environment),
            AuthorizationSubscription(nested_subject, dict_action, dict_resource),
            AuthorizationSubscription(dict_subject, nested_action, None, dict_environment)],
        [
            AuthorizationSubscription(subject=list_subject, resource=dict_environment),
            AuthorizationSubscription(action=dict_action, resource=list_resource, subject=nested_subject),
            AuthorizationSubscription(subject=nested_subject, environment=list_environment)],
        [
            AuthorizationSubscription(nested_subject, dict_action, dict_environment, list_environment),
            AuthorizationSubscription(dict_subject, action=dict_action, resource=list_resource),
            AuthorizationSubscription(list_subject, list_action, dict_resource, list_environment)]
    ]

    @pytest.mark.parametrize("test_input", multi_builder_test_subscriptions)
    def test_add_subscription(self, test_input):
        multi = MultiSubscriptionBuilder()
        # Add every AuthorizationSubscription
        for element in test_input:
            multi.with_authorization_subscription(element)

        # Iterate through every Element of the authorization_subscription list of the MultiSubscriptionBuilder
        for subscription in multi.authorization_subscription:

            # Iterate through the Values of the Dictionarys, every Key describes the ID of the AuthorizationSubscription
            for dictionary in subscription.values():

                # Iterate through all  5 possible dictionarys, these are subjectID,actionID...
                for dict_key, dict_value in dictionary.items():

                    # Strip 'ID' postfix from every Key, the keynames of AuthorizationSubscriptions
                    # are equal to dict_key.strip('ID')
                    k_stripped = dict_key.strip('ID')
                    value_of_attribute_index = getattr(multi, k_stripped)[dict_value]
                    input_value = None
                    counter = -1
                    for i in test_input:
                        try:
                            input_value = getattr(i, k_stripped)
                            if input_value is not None:
                                counter += 1
                        except AttributeError:
                            pass
                        if counter == dict_value:
                            input_value = getattr(i, k_stripped)
                            break

                    assert value_of_attribute_index == input_value

    @pytest.mark.parametrize("test_input", multi_builder_test_subscriptions)
    def test_create_multi_subscription(self, test_input):
        multi = MultiSubscriptionBuilder()
        for element in test_input:
            multi.with_authorization_subscription(element)
        subscription = multi.build()
        assert isinstance(subscription, MultiSubscription)


class TestAuthorizationSubscriptionBuilder:
    subject = dict(subject_entry="subject")
    action = dict(action_entry="action")
    resource = dict(resource_entry="resource")
    environment = dict(environment_entry="environment")

    @pytest.fixture
    def basic_values_dict(self):
        dic = dict(self.subject)
        dic.update(self.action)
        dic.update(self.resource)
        dic.update(self.environment)
        return dic

    @pytest.fixture
    def basic_authorization_subscription_builder_with_values(self, basic_values_dict):
        return BaseAuthorizationSubscriptionFactory(basic_values_dict)

    @pytest.fixture
    def basic_authorization_subscription_builder_with_values_and_filter(self, basic_values_dict):
        return BaseAuthorizationSubscriptionFactory(basic_values_dict, subject_filter="subject_entry",
                                                    action_filter="action_entry",
                                                    resource_filter="resource_entry",
                                                    environment_filter="environment_entry")

    @pytest.fixture
    def basic_authorization_subscription_builder_with_static_values(self, basic_values_dict):
        return BaseAuthorizationSubscriptionFactory(basic_values_dict, "static_subject", "static_action",
                                                    "static_resource", "static_environment")

    def test_change_subject_filter_on_builder_with_static_subject_doesnt_change_entry(self,
                                                                                      basic_authorization_subscription_builder_with_static_values):
        assert basic_authorization_subscription_builder_with_static_values.subject == "static_subject"
        basic_authorization_subscription_builder_with_static_values.set_subject_filter("subject_entry")
        assert basic_authorization_subscription_builder_with_static_values.subject == "static_subject"

    def test_set_subject_filter_removes_entry(self, basic_authorization_subscription_builder_with_values_and_filter):
        assert basic_authorization_subscription_builder_with_values_and_filter.subject == self.subject
        basic_authorization_subscription_builder_with_values_and_filter.set_subject_filter(None)
        assert basic_authorization_subscription_builder_with_values_and_filter.subject == {}

    def test_set_subject_filter_adds_entry(self, basic_authorization_subscription_builder_with_values):
        assert basic_authorization_subscription_builder_with_values.subject == {}
        basic_authorization_subscription_builder_with_values.set_subject_filter("subject_entry")
        assert basic_authorization_subscription_builder_with_values.subject == self.subject

    def test_change_action_filter_on_builder_with_static_action_doesnt_change_entry(self,
                                                                                    basic_authorization_subscription_builder_with_static_values):
        assert basic_authorization_subscription_builder_with_static_values.action == "static_action"
        basic_authorization_subscription_builder_with_static_values.set_action_filter("action_entry")
        assert basic_authorization_subscription_builder_with_static_values.action == "static_action"

    def test_set_action_filter_removes_entry(self, basic_authorization_subscription_builder_with_values_and_filter):
        assert basic_authorization_subscription_builder_with_values_and_filter.action == self.action
        basic_authorization_subscription_builder_with_values_and_filter.set_action_filter(None)
        assert basic_authorization_subscription_builder_with_values_and_filter.action == {}

    def test_set_action_filter_adds_entry(self, basic_authorization_subscription_builder_with_values):
        assert basic_authorization_subscription_builder_with_values.action == {}
        basic_authorization_subscription_builder_with_values.set_action_filter("action_entry")
        assert basic_authorization_subscription_builder_with_values.action == self.action

    def test_change_resource_filter_on_builder_with_static_resource_doesnt_change_entry(self,
                                                                                        basic_authorization_subscription_builder_with_static_values):
        assert basic_authorization_subscription_builder_with_static_values.resource == "static_resource"
        basic_authorization_subscription_builder_with_static_values.set_resource_filter("resource_entry")
        assert basic_authorization_subscription_builder_with_static_values.resource == "static_resource"

    def test_set_resource_filter_removes_entry(self, basic_authorization_subscription_builder_with_values_and_filter):
        assert basic_authorization_subscription_builder_with_values_and_filter.resource == self.resource
        basic_authorization_subscription_builder_with_values_and_filter.set_resource_filter(None)
        assert basic_authorization_subscription_builder_with_values_and_filter.resource == {}

    def test_set_resource_filter_adds_entry(self, basic_authorization_subscription_builder_with_values):
        assert basic_authorization_subscription_builder_with_values.resource == {}
        basic_authorization_subscription_builder_with_values.set_resource_filter("resource_entry")
        assert basic_authorization_subscription_builder_with_values.resource == self.resource

    def test_change_environment_filter_on_builder_with_static_environment_doesnt_change_entry(self,
                                                                                              basic_authorization_subscription_builder_with_static_values):
        assert basic_authorization_subscription_builder_with_static_values.environment == "static_environment"
        basic_authorization_subscription_builder_with_static_values.set_environment_filter("environment_entry")
        assert basic_authorization_subscription_builder_with_static_values.environment == "static_environment"

    def test_set_environment_filter_removes_entry(self,
                                                  basic_authorization_subscription_builder_with_values_and_filter):
        assert basic_authorization_subscription_builder_with_values_and_filter.environment == self.environment
        basic_authorization_subscription_builder_with_values_and_filter.set_environment_filter(None)
        assert basic_authorization_subscription_builder_with_values_and_filter.environment == {}

    def test_set_environment_filter_adds_entry(self, basic_authorization_subscription_builder_with_values):
        assert basic_authorization_subscription_builder_with_values.environment == {}
        basic_authorization_subscription_builder_with_values.set_environment_filter("environment_entry")
        assert basic_authorization_subscription_builder_with_values.environment == self.environment

    def test_set_values_adds_entry(self, basic_values_dict):
        authorization_subscription_builder = BaseAuthorizationSubscriptionFactory(dict(),
                                                                                  subject_filter="subject_entry",
                                                                                  action_filter="action_entry",
                                                                                  resource_filter="resource_entry",
                                                                                  environment_filter="environment_entry")
        assert all([authorization_subscription_builder.subject == {},
                    authorization_subscription_builder.action == {},
                    authorization_subscription_builder.resource == {},
                    authorization_subscription_builder.environment == {}])

        authorization_subscription_builder.set_values(basic_values_dict)

        assert all([authorization_subscription_builder.subject == self.subject,
                    authorization_subscription_builder.action == self.action,
                    authorization_subscription_builder.resource == self.resource,
                    authorization_subscription_builder.environment == self.environment])

    def test_create_authorization_subscription(self):
        authorization_subscription_builder = BaseAuthorizationSubscriptionFactory(
            dict(subject="subject_value",
                 action={"action_value": [1, 2], "action_value_2": "actionval"},
                 resource="resource_value",
                 environment="environment_value"),
            subject_filter="subject",
            environment_filter="no_matching_filter",
            action_filter={"action": {"action_value_2"}})

        authorization_subscription = authorization_subscription_builder.create_authorization_subscription()
        assert isinstance(authorization_subscription, AuthorizationSubscription)
        assert all([authorization_subscription.subject == dict(subject="subject_value"),
                    authorization_subscription.action == {"action": {"action_value_2": "actionval"}},
                    authorization_subscription.resource is None, authorization_subscription.environment is None])

    test_init_authorization_subscription_builder_params = [(dict(values={}, subject="subject",
                                                                 subject_filter=None),
                                                            dict(subject="subject")),

                                                           (dict(values={"subject_key": "subject_value"},
                                                                 subject="subject",
                                                                 subject_filter={"subject_key": "subject_value"}),
                                                            dict(subject="subject")),

                                                           (dict(values={"subject_key": "subject_value"},
                                                                 subject=None,
                                                                 subject_filter={"subject_key"}),
                                                            dict(subject={"subject_key": "subject_value"})),

                                                           (dict(values={"subject_key": ["subject_value", {
                                                               "subject_value_2": "is_val"}]}, subject=None,
                                                                 subject_filter={
                                                                     "subject_key": {1: "subject_value_2"}}),
                                                            dict(subject={
                                                                "subject_key": {1: {"subject_value_2": "is_val"}}})),

                                                           ]

    @pytest.mark.parametrize("example_input,expect", test_init_authorization_subscription_builder_params)
    def test_basic_init_authorization_subscription_builder(self, example_input, expect):
        builder = BaseAuthorizationSubscriptionFactory(values=example_input['values'], subject=example_input['subject'],
                                                       subject_filter=example_input['subject_filter'])
        assert builder.subject == expect['subject']
