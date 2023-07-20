import types
from abc import ABC, abstractmethod
from asyncio import Task
from typing import Union

import sapl_base.policy_decision_points
from sapl_base.constraint_handling.constraint_handler_bundle import ConstraintHandlerBundle
from sapl_base.constraint_handling.constraint_handler_service import constraint_handler_service
from sapl_base.decision import Decision
from sapl_base.exceptions import PermissionDenied
from sapl_base.policy_enforcement_points.policy_enforcement_point import PolicyEnforcementPoint


class StreamingPolicyEnforcementPoint(PolicyEnforcementPoint, ABC):
    """
    The Baseclass for StreamingPolicyEnforcementPoints serves as a foundation for implementing specific
    StreamingPolicyEnforcementPoints. It defines a set of abstract methods that must be implemented by any derived
    StreamingPolicyEnforcementPoint.

    In addition, this base class provides a generator that can be utilized by a Policy Decision Point (PDP). The generator
    handles incoming Decisions from the PDP and updates the current Decision whenever a new Decision is received.

    By extending this base class and implementing the required abstract methods, developers can create custom
    StreamingPolicyEnforcementPoints tailored to their specific needs. The provided generator facilitates seamless
    integration with a PDP, ensuring efficient handling of Decisions in a streaming environment.
    """
    def __init__(self, fn: types.FunctionType, *args, instance=None, type_of_enforcement, **kwargs):
        super().__init__(fn, *args, **kwargs)
        self._decision_generator = self._update_decision()
        self._decision_task: Union[Task, None] = None
        self.type_of_enforcement: Union[str, None] = type_of_enforcement
        self._current_decision: Decision = Decision.deny_decision()
        if instance is not None:
            self.values_dict.update({"self": instance})
        self.stream_task : Union[Task , None] = None

    async def init_decision_generator(self):
        await self._decision_generator.asend(None)

    async def request_decision(self, subscription):
        """
        The provided Authorization Subscription is used to request Decisions from a Policy Decision Point (PDP). The
        initial Decision is sent to the generator, which evaluates subsequent Decisions. The opened Stream to the PDP is
        returned and can be executed as an independent task, which can be started at a later time.

        :param subscription: The Authorization Subscription which is send to a PDP and for which Decisions are requested
        :return: A Generator which updates the current Decision of the PEP when new Decisions are received from the PDP
        """
        await self.init_decision_generator()
        decision, decision_stream = await sapl_base.policy_decision_points.pdp.async_decide(subscription,
                                                                                                self._decision_generator)
        await self._decision_generator.asend(decision)
        return decision_stream

    async def _update_decision(self):
        """
        When a connection to a Policy Decision Point (PDP) is established, the StreamingPolicyEnforcementPoint's
        generator receives new Decisions. Each new Decision triggers the creation of a new ConstraintHandlerBundle. The
        StreamingPolicyEnforcementPoint then reacts to the new Decision and ConstraintHandlerBundle based on the type of
        Enforcement.

        After processing the new Decision and ConstraintHandlerBundle, the current Decision is updated and set as
        current Decision.
        """
        try:
            while True:
                new_decision: Decision = yield
                "Check if the Stream was canceled without notification"
                if self.stream_task is not None:
                    if self.stream_task.done():
                        raise Exception
                "When the creation of a Bundle for the new Decision fails, the Decision is defaulted to DENY with an empty Bundle"
                try:
                    self.constraint_handler_bundle = constraint_handler_service.build_pre_enforce_bundle(new_decision)
                except PermissionDenied:
                    new_decision = Decision.deny_decision()
                    self.constraint_handler_bundle = ConstraintHandlerBundle.empty_bundle()

                "If for the decorator enforce_till_denied no permission is granted, the stream will cancelled"
                if new_decision.decision != "PERMIT" and self.type_of_enforcement == "enforce_till_denied":
                    try:
                        self.constraint_handler_bundle.execute_on_decision_handler(new_decision)

                    finally:
                        try:
                            await self._cancel_stream()
                        except Exception:
                            pass
                        self._fail_with_bundle()

                try:
                    self.constraint_handler_bundle.execute_on_decision_handler(new_decision)
                except Exception as e:
                    new_decision = Decision.deny_decision()
                finally:
                    if self._current_decision.decision == "PERMIT" and new_decision.decision != "PERMIT" and self.type_of_enforcement == "enforce_recoverable_if_denied":
                        await self._handle_deny_on_recoverable()
                    self._current_decision = new_decision
                    continue
        except Exception as e:
            try:
                self._decision_task.cancel()
            except Exception:
                pass

            raise e



    @abstractmethod
    def enforce_till_denied(self, subject, action, resource, environment, scope):
        """
        The implementation of this method is responsible for defining how the StreamingPolicyEnforcementPoint handles the
        situation where a class or asyncgenerator is decorated with enforce_till_denied. The specifics of this behavior will
        depend on the particular requirements and functionality of the derived StreamingPolicyEnforcementPoint.
        :param subject: Custom subject which will be set as the Subject for an AuthorizationSubscription
        :param action: Custom action which will be set as the Subject for an AuthorizationSubscription
        :param resource: Custom resource which will be set as the Subject for an AuthorizationSubscription
        :param environment: Custom environment which will be set as the Subject for an AuthorizationSubscription
        :param scope:
        """
        pass

    @abstractmethod
    async def drop_while_denied(self, subject, action, resource, environment, scope):
        """
        The implementation of this method is responsible for defining how the StreamingPolicyEnforcementPoint handles the
        situation where a class or asyncgenerator is decorated with drop_while_denied. The specifics of this behavior will
        depend on the particular requirements and functionality of the derived StreamingPolicyEnforcementPoint.

        :param subject: Custom subject which will be set as the Subject for an AuthorizationSubscription
        :param action: Custom action which will be set as the Subject for an AuthorizationSubscription
        :param resource: Custom resource which will be set as the Subject for an AuthorizationSubscription
        :param environment: Custom environment which will be set as the Subject for an AuthorizationSubscription
        :param scope:
        """
        pass

    @abstractmethod
    async def recoverable_if_denied(self, subject, action, resource, environment, scope,
                                    handle_recoverable_deny_function):
        """
        The implementation of this method is responsible for defining how the StreamingPolicyEnforcementPoint handles the
        situation where a class or asyncgenerator is decorated with recoverable_if_denied. The specifics of this behavior will
        depend on the particular requirements and functionality of the derived StreamingPolicyEnforcementPoint.

        :param subject: Custom subject which will be set as the Subject for an AuthorizationSubscription
        :param action: Custom action which will be set as the Subject for an AuthorizationSubscription
        :param resource: Custom resource which will be set as the Subject for an AuthorizationSubscription
        :param environment: Custom environment which will be set as the Subject for an AuthorizationSubscription
        :param scope:
        :param handle_recoverable_deny_function: Custom function, which replaces the _handle_deny_on_recoverable method of a StreamingPolicyEnforcementPoint
        """
        pass

    @abstractmethod
    async def _cancel_stream(self):
        """
        When the StreamingPolicyEnforcementPoint detects that the Stream needs to be cancelled, it invokes this method
        to handle the cancellation process. The specific implementation of this method will depend on the requirements
        and functionality of the derived StreamingPolicyEnforcementPoint.
        """
        pass

    @abstractmethod
    async def _handle_deny_on_recoverable(self):
        """
        This method is called when the current Decision transitions from "Permit" to a non-permitted state. Its purpose
        is to notify the client that updates will no longer be received until permission is granted again.

        The specific implementation of this method will depend on the requirements
        and functionality of the derived StreamingPolicyEnforcementPoint.
        """
        pass
