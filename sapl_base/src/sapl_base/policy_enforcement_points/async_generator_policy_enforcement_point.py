import asyncio
from typing import AsyncGenerator

import asgiref.sync

import sapl_base.policy_enforcement_points.policy_enforcement_point as pep
from sapl_base.policy_enforcement_points.streaming_policy_enforcement_point import StreamingPolicyEnforcementPoint
from sapl_base.authorization_subscription_factory import consumer_scope

class AsyncGeneratorPolicyEnforcementPoint(StreamingPolicyEnforcementPoint):



    generator: AsyncGenerator

    async def _cancel_stream(self):
        """
        The decorated Generator is canceled by throwing a default permission denied exception
        """
        await self.generator.athrow(pep.permission_denied_exception())

    async def _handle_deny_on_recoverable(self):
        """
        Does nothing, which results in having the decorators drop_while_denied and recoverable_if_denied the same
        functionality.
        """
        pass

    async def start_generator_and_stream(self, decision_stream):
        """
        Start the decorated generator and create a task to handle new Decisions from the PDP and update the current Decision
        :param decision_stream: A Generator which yields new Decisions from a Connection to a PDP and sends them to the
        PEP to evaluate them and update the current Decision
        """
        self.generator = self._enforced_function(*self._function_args, **self._function_kwargs)
        self._decision_task = asyncio.create_task(decision_stream)

    async def run_generator(self, decision_stream):
        """
        Iterate over the decorated Generator, selectively discarding values when permission is not granted, and
        seamlessly revoke the Permission in case the Result-handler of the ConstraintHandlerBundle cannot be managed.

        Furthermore, if the Generator is canceled, the connection to the Policy Decision Point (PDP) will also be terminated,
        gracefully allowing the ConstraintHandlerBundle to handle any resulting Exceptions.

        :param decision_stream: A Generator which yields new Decisions from a Connection to a PDP and sends them to the
        PEP to evaluate them and update the current Decision
        """
        await self.start_generator_and_stream(decision_stream)


        try:
            async for value in self.generator:
                if self._current_decision.decision != "PERMIT":
                    continue
                result = self.constraint_handler_bundle.execute_result_handler(value)

                yield result
        except Exception as e:
            self._decision_task.cancel()
            self._fail_with_bundle(e)

        self._decision_task.cancel()

    async def enforce_till_denied(self, subject, action, resource, environment, scope):
        """
        The decorated generator will continue its execution as long as permission is granted and the constraints can be
        handled. However, if either the permission is revoked or the constraints can't be handled, the generator will
        be canceled, concluding its operation.

        :param subject: subject of an authorization_subscription or a function to create the subject
        :param action: action of an authorization_subscription or a function to create the action
        :param resource: resource of an authorization_subscription or a function to create the resource
        :param environment: environment of an authorization_subscription or a function to create the environment
        :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
        """
        try:
            consumer_scope.set(self.values_dict["self"].scope)
        except Exception:
            pass
        subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource, environment,
                                                                                scope, self.type_of_enforcement)
        decision_stream = await self.request_decision(subscription)

        await self.start_generator_and_stream(decision_stream)

        try:
            async for value in self.generator:

                result = self.constraint_handler_bundle.execute_result_handler(value)
                yield result

        except Exception as e:
            self._decision_task.cancel()
            self._fail_with_bundle(e)

        self._decision_task.cancel()



    async def drop_while_denied(self, subject, action, resource, environment, scope):
        """
        Once permission is granted, the obligations and advices outlined in the current decision will be applied to every
        value produced by the decorated generator before it is yielded as the final output. However, if access is
        denied, any generated values will be discarded until permission is reinstated. Once permission is granted again,
        the generator can resume yielding its values.

        :param subject: subject of an authorization_subscription or a function to create the subject
        :param action: action of an authorization_subscription or a function to create the action
        :param resource: resource of an authorization_subscription or a function to create the resource
        :param environment: environment of an authorization_subscription or a function to create the environment
        :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
        """
        try:
            consumer_scope.set(self.values_dict["self"].scope)
        except Exception:
            pass
        subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource, environment,
                                                                                scope, self.type_of_enforcement)
        decision_stream = await self.request_decision(subscription)

        async for result in self.run_generator(decision_stream):
            yield result

    async def recoverable_if_denied(self, subject, action, resource, environment, scope,
                                    handle_recoverable_deny_function):
        """
        Once permission is granted, the obligations and advice outlined in the current decision will be applied to every
        value produced by the decorated generator before it is yielded as the final output. However, if access is
        denied, any generated values will be discarded until permission is reinstated and the method
        _handle_deny_on_recoverable is called. Once permission is granted again, the generator can resume yielding its
        values.

        :param subject: subject of an authorization_subscription or a function to create the subject
        :param action: action of an authorization_subscription or a function to create the action
        :param resource: resource of an authorization_subscription or a function to create the resource
        :param environment: environment of an authorization_subscription or a function to create the environment
        :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
        :param handle_recoverable_deny_function: Method which replaces the default method _handle_deny_on_recoverable and is called, when permission is revoked.
        """
        if handle_recoverable_deny_function is not None:
            self._handle_deny_on_recoverable = handle_recoverable_deny_function
        try:
            consumer_scope.set(self.values_dict["self"].scope)
        except Exception:
            pass
        subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource, environment,
                                                                                scope, self.type_of_enforcement)
        decision_stream = await self.request_decision(subscription)

        if self._current_decision != "PERMIT":
            await self._handle_deny_on_recoverable()

        async for result in self.run_generator(decision_stream):
            yield result
