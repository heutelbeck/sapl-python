from typing import Callable, Any

from flask import Config

import sapl_base.authorization_subscription_factory
import sapl_base.policy_decision_points
import sapl_flask.flask_authorization_subscription_factory


def init_sapl(config: Config, subject_function: Callable[[], Any]):
    """
    Sets the configuration of the Policy Decision Point and the function which is used to evaluate the subject of an
    AuthorizationSubscription.

    This function should be called at the start, before app.run() is called.
    The recommended way of initializing SAPL flask is:

    app.config.from_file(...) \n
    import sapl_flask \n
    sapl_flask.init_sapl(...) \n
    ... \n
    app.run()
    \n
    :param config: The Configuration of the flask project.
    :param subject_function: A function, which is called to return a Subject for the AuthorizationSubscription

    :return: Any, which will be the Subject of the AuthorizationSubscription.
    """
    if config.get("POLICY_DECISION_POINT"):

        pdp_config = config.get("POLICY_DECISION_POINT")
    else:
        pdp_config = {}

    sapl_base.policy_decision_points.pdp = sapl_base.policy_decision_points.PolicyDecisionPoint.from_settings(pdp_config)

    authz_factory = sapl_flask.flask_authorization_subscription_factory.FlaskAuthorizationSubscriptionFactory(subject_function)

    sapl_base.authorization_subscription_factory.auth_factory = authz_factory
