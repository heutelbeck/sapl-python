import pytest

from sapl_base.authorization_subscriptions import AuthorizationSubscription, MultiSubscription


class TestAuthorizationSubscription:
    subject = "Subject"
    action = "Action"
    resource = "Resource"
    environment = "Environment"
    subscription_id = "Subscription_id"

    authorization_subscriptions = [AuthorizationSubscription(subject), AuthorizationSubscription(None, action),
                                   AuthorizationSubscription(None, None, resource),
                                   AuthorizationSubscription(None, None, None, environment),
                                   AuthorizationSubscription(None, None, None, None, subscription_id),
                                   AuthorizationSubscription(subject, action, resource, environment)]

    authorization_subscriptions_with_keywords = [AuthorizationSubscription(subject=subject),
                                                 AuthorizationSubscription(action=action),
                                                 AuthorizationSubscription(resource=resource),
                                                 AuthorizationSubscription(environment=environment),
                                                 AuthorizationSubscription(subscription_id=subscription_id),
                                                 AuthorizationSubscription(subject=subject, action=action,
                                                                           resource=resource, environment=environment,
                                                                           subscription_id=subscription_id)]

    @pytest.mark.parametrize("test_input", authorization_subscriptions)
    def test_authorization_subscription_repr_can_eval_object(self, test_input):
        rep = repr(test_input)
        obj = eval(rep)
        assert str(obj) == str(test_input)
        assert obj == test_input

    @pytest.mark.parametrize("test_input", authorization_subscriptions_with_keywords)
    def test_create_authorization_subscription_with_keywords_repr_can_eval_object(self, test_input):
        rep = repr(test_input)
        obj = eval(rep)
        assert str(obj) == str(test_input)
        assert obj == test_input


class TestMultiSubscription:
    subjects = ["subject_1", "subject_2"]
    actions = ["action_1", "action_2"]
    resources = ["resource_1", "resource_2"]
    environments = ["environment_1", "environment_2"]
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
    def test_create_authorization_subscription_from_representative(self, test_input):
        rep_obj = repr(test_input)
        recreation = eval(rep_obj)
        assert str(recreation) == str(test_input)
        assert recreation == test_input

    @pytest.mark.parametrize("test_input", multi_subscription_with_keywords)
    def test_create_authorization_subscription_from_representative(self, test_input):
        rep_obj = repr(test_input)
        recreation = eval(rep_obj)
        assert str(recreation) == str(test_input)
        assert recreation == test_input
