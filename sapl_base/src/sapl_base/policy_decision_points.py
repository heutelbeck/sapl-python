import json
import logging
import types
from abc import ABC, abstractmethod
from base64 import b64encode
from typing import Coroutine

import aiohttp
import backoff
import requests
from sseclient import SSEClient

from sapl_base.authorization_subscriptions import AuthorizationSubscription
from sapl_base.decision import Decision


class PolicyDecisionPoint(ABC):
    """
    Baseclass of PolicyDecisionPoints(PDP), which creates a PDP based on the current configuration
    Configurations can be provided by a pyproject.toml file

    A PDP returns a Decision, based on the type of PDP, the called method and the
    provided AuthorizationSubscription as argument

    The PDP is a Singleton, which is created on startup can be instantiated directly
    """
    logger: logging.Logger = logging.getLogger(__name__)
    backoff_const_max_time: int
    backoff_expo_max_value: int

    @classmethod
    def from_settings(cls, configuration: dict):
        """
        reads the configuration in the pyproject.toml file and creates a PolicyDecisionPoint(PDP) depending on the
        configuration.
        If no arguments are provided in the pyproject.toml file a RemotePDP is created, with the
        parameters to connect to a SAPL-Server-lt docker container.
        https://github.com/heutelbeck/sapl-policy-engine/tree/master/sapl-server-lt
        """
        logging.basicConfig()
        if configuration.get("dummy", False):
            return DummyPolicyDecisionPoint()
        debug = configuration.get("debug", False)
        base_url = configuration.get("base_url", "http://localhost:8080/api/pdp/")
        key = configuration.get("key", "YJidgyT2mfdkbmL")
        secret = configuration.get("secret", "Fa4zvYQdiwHZVXh")
        verify = configuration.get("verify", False)
        backoff_const_max_time = configuration.get("backoff_const_max_time", 3)
        backoff_expo_max_value = configuration.get("backoff_expo_max_value", 50)
        return RemotePolicyDecisionPoint(base_url, key, secret, verify, debug, backoff_const_max_time,
                                         backoff_expo_max_value)

    @classmethod
    def dummy_pdp(cls):
        """
        Creates a DummyPolicyDecisionPoint without the need to change the configuration

        :return: a DummyPolicyDecisionPoint, which always returns a 'PERMIT'
        """
        return DummyPolicyDecisionPoint()

    @abstractmethod
    async def async_decide(self, subscription: AuthorizationSubscription,
                           pep_decision_stream: types.GeneratorType,
                           decision_events: str = "decide") -> (Decision, Coroutine):
        """
        Request Decisions based on the given AuthorizationSubscription and decision_event
        returns a tuple of the first received Decision and a Coroutine
        which will send received new Decisions to the generator of the calling StreamingPolicyEnforcementpoint

        :param pep_decision_stream: a generator function inside the calling StreamingPolicyEnforcementpoint, to which new Decisions are sent
        :param subscription: AuthorizationSubscription, for which a Decision will be given
        :param decision_events: what kind of decision will be requested from the PDP. defaults to 'decide'
        :return : Tuple of the first received Decision and a Coroutine to send future Decisions to the generator provided as an argument
        """
        pass

    @abstractmethod
    async def async_decide_once(self, subscription: AuthorizationSubscription, decision_events="decide") -> Decision:
        """
        Request only one Decision based on the given AuthorizationSubscription and decision_event

        :param subscription: AuthorizationSubscription, for which a Decision will be given
        :param decision_events: what kind of decision will be requested from the PolicyDecisionPoint. defaults to 'decide'
        :return: A single Decision for the provided AuthorizationSubscription
        """
        pass

    @abstractmethod
    def decide(self, subscription: AuthorizationSubscription, decision_events="decide") -> Decision:
        """
        Blocking method to request a single Decision for the given AuthorizationSubscription and decision_event

        :param subscription: AuthorizationSubscription, for which a Decision will be given
        :param decision_events: what kind of decision will be requested from the PolicyDecisionPoint. defaults to 'decide'
        :return: A single Decision for the provided AuthorizationSubscription
        """
        pass


class DummyPolicyDecisionPoint(PolicyDecisionPoint):
    """
    PolicyDecisionPoint which will always return a PERMIT
    """

    def __init__(self):
        super(DummyPolicyDecisionPoint, self).__init__()
        self.logger.warning(
            "ATTENTION THE APPLICATION USES A DUMMY PDP. ALL AUTHORIZATION REQUEST WILL RESULT IN A SINGLE "
            "PERMIT DECISION. DO NOT USE THIS IN PRODUCTION! THIS IS A PDP FOR TESTING AND DEVELOPING "
            "PURPOSE ONLY!"
        )

    async def async_decide(self, subscription: AuthorizationSubscription, pep_decision_stream: types.GeneratorType,
                           decision_events: str = "decide") -> (Decision, Coroutine):
        """
        implementation of decide, which returns a tuple of a Decision with Permit and a Coroutine which will send a
        Permit to the provided Generator
        """
        return Decision.permit_decision(), self._yield_permit(pep_decision_stream)

    @staticmethod
    async def _yield_permit(pep_decision_stream: types.GeneratorType):
        """
        Send a Permit to the given Generator

        :param pep_decision_stream:  Generator to which the Decision is sent
        """
        pep_decision_stream.send(Decision.permit_decision())

    async def async_decide_once(
            self, subscription: AuthorizationSubscription = None, decision_events: str = None
    ) -> Decision:
        """
        Returns a single Decision with PERMIT

        :return: Decision with Permit
        """
        return Decision.permit_decision()

    def decide(self, subscription: AuthorizationSubscription = None, decision_events=None) -> Decision:
        """
        Returns a single Decision with PERMIT

        :return: Decision with Permit
        """
        return Decision.permit_decision()


async def recreate_stream(details) -> None:
    """
    Function to remove the current Connection to a RemotePDP when an Exception occurs, to establish a new Connection and
    try to reconnect.

    :param details: dictionary of the function which has thrown an Exception
    """
    details['kwargs']['decision_stream'] = None

def set_const_max_time():
    """
    Set the max amount of retrys for a constant backoff from the configuration
    """
    return pdp.backoff_const_max_time


def set_expo_max_value():
    """
    Set the max intervall for an exponential backoff from the configuration
    """
    return pdp.backoff_expo_max_value


class RemotePolicyDecisionPoint(PolicyDecisionPoint, ABC):
    """
    Implementation of a PolicyDecisionPoint(PDP) which connects to an external PDP sends the Authorization and returns
    the Decision received from the external PDP for the given AuthorizationSubscription
    """
    headers = {"Content-Type": "application/json"}

    def __init__(self, base_url: str, key, secret, verify, debug, backoff_const_max_time, backoff_expo_max_value):
        self.debug = debug
        if self.debug:
            self.logger.setLevel('DEBUG')
        if not base_url.endswith('/'):
            self.base_url = base_url + '/'
        else:
            self.base_url = base_url
        self.verify = verify
        if (self.verify is None) or (self.base_url is None):
            raise Exception("No valid configuration for the PDP")
        if key is not None:
            key_and_secret = b64encode(str.encode(f"{key}:{secret}")).decode("ascii")
            self.headers["Authorization"] = f"Basic {key_and_secret}"
        self.logger.info("PDP initialized. \n base url: %s \n key: %s \n secret: %s \n verify: %s", base_url, key,
                         secret, verify)
        self.backoff_const_max_time = backoff_const_max_time
        self.backoff_expo_max_value = backoff_expo_max_value

    @backoff.on_exception(backoff.constant, Exception, max_time=set_const_max_time, raise_on_giveup=False,
                          logger=__name__)
    def decide(self, subscription: AuthorizationSubscription,
               decision_events="decide") -> Decision:
        """
        Blocking method to request a single Decision from the RemotePDP for the given AuthorizationSubscription.

        When an Exception is thrown this method trys to get a Decision again for a maximum 5 seconds.
        On giveup None is returned.

        :param subscription: An Authorization_Subscription for which a Decision is requested
        :param decision_events: For what kind of AuthorizationSubscription should a Decision be returned
        :return: Decision for the given AuthorizationSubscription, or None when no Decision could be evaluated in time.
        """
        if self.debug:
            self.logger.debug("Requesting decision for AuthorizationSubscription: %s", subscription.__str__())
        with requests.post(
                self.base_url + decision_events,
                subscription.__str__(),
                stream=True,
                verify=self.verify,
                headers=self.headers
        ) as stream_response:
            if stream_response.status_code != 200:
                self.logger.debug("Responsecode != 200, was %s . Decision defaults to DENY",
                                      stream_response.status_code)
                return Decision.deny_decision()
            for event in SSEClient(stream_response).events():
                decision = Decision(json.loads(event.data))

                self.logger.debug("Decision : %s", json.dumps(decision.__dict__, indent=2, skipkeys=True, default=lambda o: str(o)))
                return decision

    async def async_decide(self, subscription: AuthorizationSubscription, pep_decision_stream: types.GeneratorType,
                           decision_events: str = "decide") -> (Decision, types.CoroutineType):
        """
        Establish a connection to the RemotePDP and receive new Decisions, which are send to the provided Generator.
        When the connection to the RemotePDP fails, an INDETERMINATE Decision is sent to the Generator and it is
        retried to establish a connection again. Retry works with an exponential backoff and a maximum.

        :param subscription: AuthorizationSubscription for which Decisions should be made
        :param pep_decision_stream: Generator, to which new received Decision are sent
        :param decision_events: For what kind of AuthorizationSubscription should a Decision be returned
        :return: A tuple of the first received Decision and a Coroutine, which will send Decisions to the given pep_decision_stream
        """
        try:
            decision, decision_stream = await self._get_first_decision_and_stream(subscription=subscription,
                                                                                  decision_events=decision_events)
        except Exception as e:
            self.logger.debug("An Error occured while getting the first Decision. Decision defaults to INDETERMINATE")
            decision = {"decision": "INDETERMINATE"}
            decision_stream = None
        return decision, self._update_decision(subscription=subscription, decision_stream=decision_stream,
                                               pep_decision_stream=pep_decision_stream, decision_events=decision_events)

    @backoff.on_exception(backoff.expo, Exception, on_backoff=recreate_stream, max_value=set_expo_max_value)
    async def _update_decision(self, subscription: AuthorizationSubscription, decision_stream: types.AsyncGeneratorType,
                               pep_decision_stream: types.GeneratorType, decision_events: str = "decide") -> None:
        """
        Returns a Coroutine, which will send new Decisions to the provided Generator.
        When an Exception occurs this method sends a INDETERMINATE Decision to the Generator and trys to reestablish a
        connection to the RemotePDP with an exponential backoff

        :param subscription: AuthorizationSubscription for which Decision will be evaluated
        :param decision_stream: Generator, which receives new Decisions from the RemotePDP
        :param pep_decision_stream: Generator, to which new Decisions are sent
        :param decision_events: For what kind of AuthorizationSubscription should a Decision be returned
        """
        if decision_stream is None:
            self.logger.debug("Stream to PDP was cancelled. Retrying to connect to the PDP")
            await pep_decision_stream.send({"decision": "INDETERMINATE"})
            decision_stream = self._get_decision_stream(subscription=subscription, decision_events=decision_events)

        async for decision in decision_stream:
            await pep_decision_stream.send(decision)

    @backoff.on_exception(backoff.constant, Exception, max_time=set_const_max_time)
    async def _get_first_decision_and_stream(self, subscription: AuthorizationSubscription, decision_events: str) -> (
            Decision, types.AsyncGeneratorType):
        """
        Establish a connection to the RemotePDP and return the first Decision together with the Generator,
        which receives new Decisions from the RemotePDP.
        When an Exception occurs this method trys again, until it gives up after 10 seconds.

        :param subscription: AuthorizationSubscription for which Decision will be evaluated
        :param decision_events: For what kind of AuthorizationSubscription should a Decision be returned
        :return: tuple of the first Decision and a Generator which receives new Decisions from the RemotePDP
        """
        decision_stream = self._get_decision_stream(subscription=subscription, decision_events=decision_events)
        decision = await decision_stream.__anext__()
        if decision == {"decision": "INDETERMINATE"}:
            self.logger.debug("First Decision was INDETERMINATE. Defaulting to DENY")
            return Decision.deny_decision(), decision_stream
        return Decision(decision), decision_stream

    async def _get_decision_stream(self, subscription: AuthorizationSubscription,
                                   decision_events: str = "decide") -> types.AsyncGeneratorType:
        """
        Establish a connection to the RemotePDP and yield new Decisions

        :param subscription: AuthorizationSubscription for which Decision will be evaluated
        :param decision_events: For what kind of AuthorizationSubscription should a Decision be returned
        :return: A Generator yielding new Decisions received from the RemotePDP
        """
        async with aiohttp.ClientSession(headers=self.headers, raise_for_status=True) as session:

            async with session.post(self.base_url + decision_events, data=subscription.__str__()
                                    ) as response:

                if response.status != 200:
                    self.logger.debug("Responsecode != 200, was %s . Decision defaults to INDETERMINATE",
                                      response.status)
                    yield {"decision": "INDETERMINATE"}
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
                            decision = json.loads(response[data_begin:])
                            try:
                                self.logger.debug("Decision : %s",json.dumps(decision, indent=2, skipkeys=True,
                                                             default=lambda o: str(o)))
                            except Exception:
                                pass
                            yield decision
                            lines = b''

    @backoff.on_exception(backoff.constant, Exception, max_time=set_const_max_time, raise_on_giveup=False)
    async def async_decide_once(
            self, subscription: AuthorizationSubscription, decision_events: str = "decide") -> Decision:
        """
        Request a single Decision from the RemotePDP for the given AuthorizationSubscription.

        When an Exception is thrown this method trys again to get a Decision, for a maximum 5 seconds.
        On giveup None is returned.

        :param subscription: An Authorization_Subscription for which a Decision is requested
        :param decision_events: For what kind of AuthorizationSubscription should a Decision be returned
        :return: Decision for the given AuthorizationSubscription, or None when no Decision could be evaluated in time.
        """
        decision_stream = self._get_decision_stream(subscription=subscription, decision_events=decision_events)
        decision = await decision_stream.__anext__()
        await decision_stream.aclose()
        if decision == {"decision": "INDETERMINATE"}:
            self.logger.debug("Decision was INDETERMINATE. Defaulting to DENY")
            return Decision.deny_decision()
        return Decision(decision)


pdp: PolicyDecisionPoint
