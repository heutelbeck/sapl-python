from sapl_base.authorization_subscription_factory import auth_factory
from sapl_django import DjangoAuthorizationSubscriptionFactory


def test_authorization_subscription_factory_is_django_factory():
    authorization_factory = auth_factory
    assert isinstance(authorization_factory, DjangoAuthorizationSubscriptionFactory)
