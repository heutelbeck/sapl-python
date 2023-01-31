import importlib
import logging

from django.core.exceptions import PermissionDenied
from django.conf import settings
import sapl_base.policy_decision_points

try:
    if settings.POLICY_DECISION_POINT:
        pdp_config = settings.POLICY_DECISION_POINT
    else:
        pdp_config = {}
except AttributeError as e:
    logging.info("Using default PDP configuration, because configuration is missing POLICY_DECISION_POINT entry")
    pdp_config = {}

sapl_base.policy_decision_points.pdp = sapl_base.policy_decision_points.PolicyDecisionPoint.from_settings(pdp_config)

import sapl_base.authorization_subscription_factory
from sapl_django.django_authorization_subscription_factory import DjangoAuthorizationSubscriptionFactory

sapl_base.authorization_subscription_factory.auth_factory = DjangoAuthorizationSubscriptionFactory()

import sapl_base.policy_enforcement_points.policy_enforcement_point
from sapl_django.django_streaming_policy_enforcement_point import DjangoStreamingPolicyEnforcementPoint

sapl_base.policy_enforcement_points.policy_enforcement_point.streaming_pep = DjangoStreamingPolicyEnforcementPoint
sapl_base.policy_enforcement_points.policy_enforcement_point.permission_denied_exception = PermissionDenied
