# Kann allgemein verwendet werden und Frameworkunabhängig
import logging
from abc import ABC, abstractmethod
from base64 import b64encode

from sapl_base.authorization_subscriptions import AuthorizationSubscription


class PolicyDecisionPoint(ABC):
    DEFAULT_POLICY_DECISION_POINT_SETTINGS = {
        "base_url": "https://localhost:8443/api/pdp/",
        "key": "YJidgyT2mfdkbmL",
        "secret": "Fa4zvYQdiwHZVXh",
        "verify": False,
        "dummy": False,
    }

    headers = {"Content-type": "application/json"}

    def __init__(self, base_url=None, key=None, secret=None, verify=None, dummy=None):
        if dummy:
            return
        self.base_url = base_url
        self.verify = verify
        if (self.verify is None) or (self.base_url is None):
            raise Exception("No valid configuration for the PDP")
        if key is not None:
            key_and_secret = b64encode(str.encode(f"{key}:{secret}")).decode("ascii")
            self.headers["Authorization"] = f"Basic {key_and_secret}"

    @abstractmethod
    async def decide(self, subscription: AuthorizationSubscription, decision_events="decide"):
        """
        Interface decide of the PolicyDecisionPoint
        :type subscription: json
        :param subscription: AuthorizationSubscription for send request
        :param decision_events: type of request for the SAPL-Server
        to the Remoteserver
        """
        pass

    @abstractmethod
    async def decide_once(
            self, subscription: AuthorizationSubscription, decision_events="decide"
    ):
        """
        Interface decide_once of the PolicyDecisionPoint
        :type subscription: json
        :param subscription: AuthorizationSubscription for send request
        to the SAPL-Server
        :param decision_events: type of request for the SAPL-Server
        """
        pass

    @classmethod
    @abstractmethod
    def from_settings(cls):
        pass

    @classmethod
    def dummy_pdp(cls):
        return DummyPolicyDecisionPoint()


class DummyPolicyDecisionPoint(PolicyDecisionPoint):
    """
    Dummy settings to run the application without SAPL-Remote-Server, all will be PREMIT in this case
    """

    def __init__(self):
        super(DummyPolicyDecisionPoint, self).__init__(dummy=True)
        self.logger = logging.getLogger(__name__)
        self.logger.warning(
            "ATTENTION THE APPLICATION USES A DUMMY PDP. ALL AUTHORIZATION REQUEST WILL RESULT IN A SINGLE "
            "PERMIT DECISION. DO NOT USE THIS IN PRODUCTION! THIS IS A PDP FOR TESTING AND DEVELOPING "
            "PURPOSE ONLY!"
        )

    def decide(self, subscription: AuthorizationSubscription, decision_events="decide"):
        """
        The method give back always PERMIT for the interface decide
        """

        return {"decision": "PERMIT"}

    def decide_once(
            self, subscription: AuthorizationSubscription, decision_events="decide"
    ):
        """
        The Method give back always PERMIT for the Interface decide_one
        """
        return {"decision": "PERMIT"}

    @classmethod
    def from_settings(cls):
        raise Exception("DummyPolicyDecisionPoints can't be created from settings")


class BaseRemotePolicyDecisionPoint(PolicyDecisionPoint):

    async def decide(self, subscription: AuthorizationSubscription, decision_events="decide"):
        pass

    async def decide_once(self, subscription: AuthorizationSubscription, decision_events="decide"):
        pass

    @classmethod
    def from_settings(cls):
        pass

    def __init__(self, base_url=None, key=None, secret=None, verify=None, dummy=None):
        super().__init__(base_url, key, secret, verify, dummy)
