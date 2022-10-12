import json
from abc import ABC, abstractmethod
from base64 import b64encode

import aiohttp
import backoff
import requests

from sapl_base.authorization_subscriptions import AuthorizationSubscription
from sapl_base.sapl_util import configuration


class PolicyDecisionPoint(ABC):

    @classmethod
    def from_settings(cls):
        """
        reads the configuration in the pyproject.toml file and creates a PolicyDecisionPoint depending on the configuration
        """
        if configuration.get("dummy", False):
            return DummyPolicyDecisionPoint()
        base_url = configuration.get("base_url", "http://localhost:8080/api/pdp/")
        key = configuration.get("key", "YJidgyT2mfdkbmL")
        secret = configuration.get("secret", "Fa4zvYQdiwHZVXh")
        verify = configuration.get("verify", False)
        return RemotePolicyDecisionPoint(base_url, key, secret, verify)

    @classmethod
    def dummy_pdp(cls):
        """
        :returns a DummyPolicyDecisionPoint, which always returns a 'PERMIT'
        """
        return DummyPolicyDecisionPoint()

    @abstractmethod
    async def async_decide(self, subscription, pep_decision_stream, decision_events="decide"):
        """
        async function to make a request to a pdp with the given subscription and event to create a stream of decisions

        :param pep_decision_stream:
        :param subscription: authorization_subscription which will be sent to a pdp to receive decisions based on it
        :param decision_events: what kind of decision will be requested from the pdp. defaults to 'decide'
        """
        pass

    @abstractmethod
    async def async_decide_once(self, subscription: AuthorizationSubscription, decision_events="decide"):
        """
        async function to make a request to a pdp with the given subscription and event to receive a
        single decision

        :param subscription: authorization_subscription which will be sent to a pdp to receive decisions based on it
        :param decision_events: what kind of decision will be requested from the pdp. defaults to 'decide'
        """
        pass

    @abstractmethod
    def decide(self, subscription: AuthorizationSubscription, decision_events="decide"):
        """
        synchronous function to make a request to a pdp with the given subscription and event to receive a
        single decision

        :param subscription: authorization_subscription which will be sent to a pdp to receive decisions based on it
        :param decision_events: what kind of decision will be requested from the pdp. defaults to 'decide'
        """
        pass


class DummyPolicyDecisionPoint(PolicyDecisionPoint):
    """
    Dummy settings to run the application without SAPL-Remote-Server, all will be PERMIT in this case
    """

    def __init__(self):
        super(DummyPolicyDecisionPoint, self).__init__()
        # self.logger = logging.getLogger(__name__)
        # self.logger.warning(
        #     "ATTENTION THE APPLICATION USES A DUMMY PDP. ALL AUTHORIZATION REQUEST WILL RESULT IN A SINGLE "
        #     "PERMIT DECISION. DO NOT USE THIS IN PRODUCTION! THIS IS A PDP FOR TESTING AND DEVELOPING "
        #     "PURPOSE ONLY!"
        # )

    async def async_decide(self, subscription, pep_decision_stream, decision_events="decide"):
        """
        implementation of decide, which always yields a PERMIT
        """
        return {"decision": "PERMIT"}, self.yield_permit(pep_decision_stream)

    async def yield_permit(self, pep_decision_stream):
        await pep_decision_stream.asend({"decision": "PERMIT"})

    async def async_decide_once(
            self, subscription: AuthorizationSubscription, decision_events="decide"
    ):
        """
        implementation of decide_once, which always returns a PERMIT
        """
        return {"decision": "PERMIT"}

    def decide(self, subscription: AuthorizationSubscription, decision_events="decide"):
        """
        implementation of sync_decide, which always returns a PERMIT
        """
        return {"decision": "PERMIT"}


async def recreate_stream(details):
    """

    :param details:
    """
    details['kwargs']['decision_stream'] = None


class RemotePolicyDecisionPoint(PolicyDecisionPoint, ABC):
    headers = {"Content-Type": "application/json"}

    def __init__(self, base_url, key, secret, verify):
        self.base_url = base_url
        self.verify = verify
        if (self.verify is None) or (self.base_url is None):
            raise Exception("No valid configuration for the PDP")
        if key is not None:
            key_and_secret = b64encode(str.encode(f"{key}:{secret}")).decode("ascii")
            self.headers["Authorization"] = f"Basic {key_and_secret}"

    @backoff.on_exception(backoff.constant, Exception, max_time=20)
    def decide(self, subscription: AuthorizationSubscription,
               decision_events="decide"):
        """
        Makes a synchronous request to the set pdp and returns a decision for the sent authorization_subscription

        :param subscription: An Authorization_Subscription which will be sent to the set pdp to receive decisions
        :param decision_events: Signal to tell the PDP what kind of Authorization_Subscription is sent
        and what kind of decision is expected
        """
        with requests.post(
                self.base_url + decision_events,
                subscription.__str__(),
                stream=True,
                verify=self.verify,
                headers=self.headers
        ) as stream_response:
            if stream_response.status_code == 204:
                return {"decision": "DENY"}
                # return
            elif stream_response.status_code != 200:
                return {"decision": "DENY"}
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
                        data_begin = str.find(response, '{')
                        response = json.loads(response[data_begin:])
                        if response == {"decision": "INDETERMINATE"}:
                            return {"decision": "DENY"}
                        return response

    async def async_decide(self, subscription, pep_decision_stream, decision_events="decide"):
        """

        :param subscription:
        :param pep_decision_stream:
        :param decision_events:
        :return:
        """
        try:
            decision, decision_stream = await self.get_first_decision_and_stream(subscription=subscription,
                                                                                 decision_events=decision_events)
        except Exception as e:
            decision = {"decision": "INDETERMINATE"}
            decision_stream = None
        return decision, self.update_stream(subscription=subscription, decision_stream=decision_stream,
                                            pep_decision_stream=pep_decision_stream, decision_events=decision_events)

    @backoff.on_exception(backoff.expo, Exception, on_backoff=recreate_stream, max_value=100)
    async def update_stream(self, subscription, decision_stream, pep_decision_stream, decision_events="decide"):
        """

        :param subscription:
        :param decision_stream:
        :param pep_decision_stream:
        :param decision_events:
        """
        if decision_stream is None:
            await pep_decision_stream.asend({"decision": "INDETERMINATE"})
            decision_stream = self.get_decision_stream(subscription=subscription, decision_events=decision_events)

        async for decision in decision_stream:
            await pep_decision_stream.asend(decision)

    @backoff.on_exception(backoff.constant, Exception, max_time=10)
    async def get_first_decision_and_stream(self, subscription, decision_events):
        """

        :param subscription:
        :param decision_events:
        :return:
        """
        decision_stream = self.get_decision_stream(subscription=subscription, decision_events=decision_events)
        decision = await decision_stream.__anext__()
        if decision == {"decision": "INDETERMINATE"}:
            return {"decision": "DENY"}, decision_stream
        return decision, decision_stream

    async def get_decision_stream(self, subscription, decision_events="decide"):
        """
        Makes a request to the set pdp and returns a stream of decisions for the sent authorization_subscription

        :param subscription: An Authorization_Subscription which will be sent to the set pdp to receive decisions
        :param decision_events: Signal to tell the PDP what kind of Authorization_Subscription is sent
        and what kind of decisions is expected
        """
        async with aiohttp.ClientSession(headers=self.headers, raise_for_status=True
                                         ) as session:

            async with session.post(self.base_url + decision_events, data=subscription.__str__()
                                    ) as response:

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
                            data_begin = str.find(response, '{')
                            yield json.loads(response[data_begin:])
                            lines = b''

    @backoff.on_exception(backoff.constant, Exception, max_time=20)
    async def async_decide_once(
            self, subscription: AuthorizationSubscription, decision_events="decide"
    ):
        """
        Makes a request to the set pdp and returns the first decision received for the sent authorization_subscription

        :param subscription: An Authorization_Subscription which will be sent to the set pdp to receive a decision
        :param decision_events: Signal to tell the PDP what kind of Authorization_Subscription is sent
        and what kind of decision is expected
        :return: A decision for the given Authorization_Subscription
        """
        decision_stream = self.get_decision_stream(subscription=subscription, decision_events=decision_events)
        decision = await decision_stream.__anext__()
        await decision_stream.aclose()
        if decision == {"decision": "INDETERMINATE"}:
            return {"decision": "DENY"}
        return decision


pdp = PolicyDecisionPoint.from_settings()
