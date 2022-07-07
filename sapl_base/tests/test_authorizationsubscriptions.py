import pytest

from sapl_base.authorization_subscriptions import AuthorizationSubscription, MultiSubscription


class TestAuthorizationSubscription:
    basic_subject = "basic_user"
    basic_action = {"requestType": "GET"}
    basic_resource = {"Port": 8888}
    basic_environment = {"hometown": "London"}

    list_subject = [{"admin_user": "admin_list_user"}, {"basic_user": "basic_list_user"}]
    set_action = {"set_function": {"set_function_1", "set_function_2"}}, {"set_request": {"set_GET", "set_POST"}}
    tuple_resource = ({"tuple_resource": "resource"}, {"tuple_port": 5555})
    nested_environment = {
        "Land": ({"Deutschland": ["Koeln", "Bonn", "Berlin"]}, {"US": {"State": ("Florida", "New York", "Washington")}},
                 "Frankreich")}

    subscription_id = 55433
    failing_subscription_id = "subscription_id"
    basic_authorization_subscriptions = [AuthorizationSubscription(basic_subject),
                                         AuthorizationSubscription(None, basic_action),
                                         AuthorizationSubscription(None, None, basic_resource),
                                         AuthorizationSubscription(None, None, None, basic_environment),
                                         AuthorizationSubscription(None, None, None, None, subscription_id),
                                         AuthorizationSubscription(basic_subject, basic_action, basic_resource,
                                                                   basic_environment)]

    complex_authorization_subscriptions = [AuthorizationSubscription(list_subject),
                                           AuthorizationSubscription(None, set_action),
                                           AuthorizationSubscription(None, None, tuple_resource),
                                           AuthorizationSubscription(None, basic_action, None, nested_environment),
                                           AuthorizationSubscription(None, None, None, None, subscription_id),
                                           AuthorizationSubscription(list_subject, set_action, tuple_resource,
                                                                     nested_environment)]

    basic_authorization_subscriptions_with_keywords = [
        AuthorizationSubscription(subject=basic_subject, environment=basic_environment),
        AuthorizationSubscription(action=basic_action),
        AuthorizationSubscription(resource=basic_resource),
        AuthorizationSubscription(environment=basic_environment, action=basic_action),
        AuthorizationSubscription(subscription_id=subscription_id),
        AuthorizationSubscription(subject=basic_subject,
                                  action=basic_action,
                                  resource=basic_resource,
                                  environment=basic_environment,
                                  subscription_id=subscription_id)]

    complex_authorization_subscriptions_with_keywords = [AuthorizationSubscription(subject=list_subject),
                                                         AuthorizationSubscription(action=set_action,
                                                                                   subject=list_subject),
                                                         AuthorizationSubscription(resource=tuple_resource,
                                                                                   environment=nested_environment),
                                                         AuthorizationSubscription(environment=nested_environment,
                                                                                   action=set_action),
                                                         AuthorizationSubscription(subscription_id=subscription_id),
                                                         AuthorizationSubscription(subject=list_subject,
                                                                                   action=set_action,
                                                                                   resource=tuple_resource,
                                                                                   environment=nested_environment,
                                                                                   subscription_id=subscription_id)]

    @pytest.mark.parametrize("test_input", basic_authorization_subscriptions)
    def test_basic_authorization_subscription_from_representative(self, test_input):
        rep = repr(test_input)
        obj = eval(rep)
        assert str(obj) == str(test_input)
        assert obj == test_input

    @pytest.mark.parametrize("test_input", complex_authorization_subscriptions)
    def test_complex_authorization_subscription_from_representative(self, test_input):
        rep = repr(test_input)
        obj = eval(rep)
        assert str(obj) == str(test_input)
        assert obj == test_input

    def test_wrong_subsription_id_type(self):
        with pytest.raises(TypeError):
            AuthorizationSubscription(None, None, None, None, self.failing_subscription_id)

    @pytest.mark.parametrize("test_input", basic_authorization_subscriptions_with_keywords)
    def test_basic_authorization_subscription_with_keywords_from_representative(self, test_input):
        rep = repr(test_input)
        obj = eval(rep)
        assert str(obj) == str(test_input)
        assert obj == test_input

    @pytest.mark.parametrize("test_input", complex_authorization_subscriptions_with_keywords)
    def test_complex_authorization_subscription_with_keywords_from_representative(self, test_input):
        rep = repr(test_input)
        obj = eval(rep)
        assert str(obj) == str(test_input)
        assert obj == test_input

    not_equal_data = ["testinput", 5, AuthorizationSubscription("5")]

    @pytest.mark.parametrize("test_input", not_equal_data)
    def test_authorization_subscription_not_equal(self, test_input):
        authorization_subscription = AuthorizationSubscription("subject")
        assert authorization_subscription.__eq__(test_input) == False


class TestMultiSubscription:
    subjects = [{"subject_1": "nutzer2"}, {"subject_2": "nutzer"}]
    actions = [{"action_1": "action"}, {"action_2": "action_2"}]
    resources = [{"resource_1": "function_1"}, {"resource_2": "function_2"}]
    environments = [{"environment_1": "environment_1"}, {"environment_2": "environment_2"}]
    authorization_subscriptions = [{"id_1": {"subjectId": 0, "actionID": 0, "resourceId": 0, "environmentId": 0}},
                                   {"id_2": {"subjectId": 1, "actionID": 1, "resourceId": 1, "environmentId": 1}}]

    multi_subscription = [MultiSubscription(subjects, actions, resources, environments, authorization_subscriptions),
                          MultiSubscription(None, actions, resources, environments, authorization_subscriptions),
                          MultiSubscription(None, None, resources, environments, authorization_subscriptions),
                          MultiSubscription(None, None, None, environments, authorization_subscriptions),
                          MultiSubscription(None, None, None, None, authorization_subscriptions)]

    multi_subscription_with_keywords = [
        MultiSubscription(subject=subjects, action=actions, resource=resources, environment=environments,
                          authorization_subscriptions=authorization_subscriptions),
        MultiSubscription(action=actions, ),
        MultiSubscription(resource=resources),
        MultiSubscription(environment=environments),
        MultiSubscription(authorization_subscriptions=authorization_subscriptions)]

    @pytest.mark.parametrize("test_input", multi_subscription)
    def test_create_multi_subscription_from_representative(self, test_input):
        rep_obj = repr(test_input)
        recreation = eval(rep_obj)
        assert str(recreation) == str(test_input)
        assert recreation == test_input

    @pytest.mark.parametrize("test_input", multi_subscription_with_keywords)
    def test_create_multi_subscription_with_keywords_from_representative(self, test_input):
        rep_obj = repr(test_input)
        recreation = eval(rep_obj)
        assert str(recreation) == str(test_input)
        assert recreation == test_input

    not_equal_data = ["testinput", 5, MultiSubscription(["5", {"subject": "user"}])]

    @pytest.mark.parametrize("test_input", not_equal_data)
    def test_authorization_subscription_not_equal(self, test_input):
        authorization_subscription = MultiSubscription(["subject"])
        assert authorization_subscription.__eq__(test_input) == False
