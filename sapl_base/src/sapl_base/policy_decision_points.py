import logging
from abc import ABC, abstractmethod
from base64 import b64encode

import aiohttp
import requests

from sapl_base.authorization_subscriptions import AuthorizationSubscription


class PolicyDecisionPoint(ABC):

    # Determine how to get a Remote PDP from settings independent from the Framework
    # Maybe with a toml file
    @classmethod
    def from_settings(cls):
        return RemotePolicyDecisionPoint()

    @classmethod
    def dummy_pdp(cls):
        return DummyPolicyDecisionPoint()

    @abstractmethod
    async def decide(self, subscription, decision_events="decide"):
        pass

    @abstractmethod
    async def decide_once(self, subscription: AuthorizationSubscription, decision_events="decide"):
        pass

    @abstractmethod
    def sync_decide(self, subscription: AuthorizationSubscription, decision_events="decide"):
        pass

    @abstractmethod
    def sync_decide_once(self, subscription: AuthorizationSubscription, decision_events="decide"):
        pass


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

    async def decide(self, subscription, decision_events="decide"):
        """
        The method give back always PERMIT for the interface decide
        """

        yield {"decision": "PERMIT"}

    async def decide_once(
            self, subscription: AuthorizationSubscription, decision_events="decide"
    ):
        """
        The Method give back always PERMIT for the Interface decide_one
        """
        return {"decision": "PERMIT"}

    def sync_decide(self, subscription: AuthorizationSubscription, decision_events="decide"):
        """
        The method give back always PERMIT for the interface decide
        """

        yield {"decision": "PERMIT"}

    def sync_decide_once(self, subscription: AuthorizationSubscription, decision_events="decide"):
        """
        The Method give back always PERMIT for the Interface decide_one
        """
        return {"decision": "PERMIT"}


class RemotePolicyDecisionPoint(PolicyDecisionPoint, ABC):
    # DEFAULT_POLICY_DECISION_POINT_SETTINGS = {
    #    "base_url": "http://localhost:8443/api/pdp/",
    #    "key": "YJidgyT2mfdkbmL",
    #    "secret": "Fa4zvYQdiwHZVXh",
    #    "verify": False,
    # }
    headers = {"Content-type": "application/json"}

    def __init__(self, base_url="http://localhost:8443/api/pdp/",
                 key="YJidgyT2mfdkbmL", secret="Fa4zvYQdiwHZVXh", verify=False):
        self.base_url = base_url
        self.verify = verify
        if (self.verify is None) or (self.base_url is None):
            raise Exception("No valid configuration for the PDP")
        if key is not None:
            key_and_secret = b64encode(str.encode(f"{key}:{secret}")).decode("ascii")
            self.headers["Authorization"] = f"Basic {key_and_secret}"

    def _sync_request(self, subscription, decision_events):
        stream_response = requests.post(
            self.base_url + decision_events,
            subscription,
            stream=True,
            verify=self.verify,
            headers=self.headers
        )
        return stream_response

    def _sync_decide(self, subscription: AuthorizationSubscription,
                     decision_events="decide"):
        with self._sync_request(
                subscription, decision_events
        ) as stream_response:
            if stream_response.status_code == 204:
                return {"decision": "INDETERMINATE"}
                # return
            elif stream_response.status_code != 200:
                return {"decision": "INDETERMINATE"}
                # return
            else:
                lines = b''
                for line in stream_response.content:
                    lines += line
                    if lines.endswith(b'\n\n'):
                        line_set = lines.splitlines(False)
                        response = ''
                        for item in line_set:
                            response += item.decode('utf-8')
                        return response

    def sync_decide_once(self, subscription: AuthorizationSubscription, decision_events="decide"
                         ):
        decision = self.sync_decide(subscription, decision_events)
        if decision == {"decision": "INDETERMINATE"}:
            return {"decision": "DENY"}
        return decision

    async def decide(self, subscription, decision_events="decide"):

        async with aiohttp.ClientSession(raise_for_status=True
                                         ) as session:
            async with session.get(
                    'http://localhost:8080/') as response:  # self.base_url + decision_events, data=subscription, verify_ssl=self.verify,
                # headers=self.headers)
                if response.status == 204:
                    yield {"decision": "INDETERMINATE"}
                    # return
                elif response.status != 200:
                    yield {"decision": "INDETERMINATE"}
                    # return
                else:
                    lines = b''
                    async for line in response.content:
                        lines += line
                        if lines.endswith(b'\n\n'):
                            line_set = lines.splitlines(False)
                            response = ''
                            for item in line_set:
                                response += item.decode('utf-8')
                            yield response
                            lines = b''

    async def decide_once(
            self, subscription: AuthorizationSubscription, decision_events="decide"
    ):
        decision_stream = self.decide(subscription, decision_events)
        try:
            decision = await decision_stream.__anext__()
            await decision_stream.aclose()
            if decision == {"decision": "INDETERMINATE"}:
                return {"decision": "DENY"}
        except Exception as e:
            return {"decision": "DENY"}
        return decision


pdp = PolicyDecisionPoint.from_settings()
