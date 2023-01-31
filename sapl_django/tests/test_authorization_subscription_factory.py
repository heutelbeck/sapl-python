from django.conf import settings
settings.configure()

import sapl_base.authorization_subscription_factory
from sapl_django import DjangoAuthorizationSubscriptionFactory


def test_authorization_subscription_factory_is_django_factory():
    authorization_factory = sapl_base.authorization_subscription_factory.auth_factory
    assert isinstance(authorization_factory, DjangoAuthorizationSubscriptionFactory)
