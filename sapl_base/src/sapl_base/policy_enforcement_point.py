import asyncio

import backoff

from sapl_base.authorization_subscription_factory import BaseAuthorizationSubscriptionFactory
from sapl_base.base_framework_error_handler import BaseFrameworkErrorHandler
from sapl_base.constraint_handler_service import constraint_handler_service
from sapl_base.policy_decision_points import pdp
from sapl_base.sapl_util import get_named_args_dict, get_function_positional_args, \
    get_class_positional_args


class PolicyEnforcementPoint:
    _enforcement_stream = None
    _current_decision = None
    _stream_gen = None

    """
    Create a PolicyDecisionPoint
    """

    def __init__(self, fn, *args, **kwargs):
        self._enforced_function = fn
        args_dict = get_named_args_dict(fn, *args, **kwargs)
        self._function_args = args
        self._function_kwargs = kwargs

        try:
            class_object = args_dict.pop('self')
            self._pos_args = get_class_positional_args(fn, args)
            self._values_dict = {"function": fn, "class": class_object, "args": args_dict}

        except KeyError:
            self._pos_args = get_function_positional_args(fn, args)
            self._values_dict = {"function": fn, "args": args_dict}

    def _get_sync_bundle(self, subject, action, resource, environment, scope):
        authorization_subscription = auth_factory.create_authorization_subscription(self._values_dict, subject, action,
                                                                                    resource,
                                                                                    environment, scope)
        self._current_decision = pdp.sync_decide_once(authorization_subscription)
        self._fail_on_non_permit()
        constraint_handler_bundle = constraint_handler_service.create_constraint_handler_bundle(self._current_decision)
        return constraint_handler_bundle

    def sync_pre_enforce(self, subject=None, action=None, resource=None, environment=None, scope: str = "default"):
        constraint_handler_bundle = self._get_sync_bundle(subject, action, resource, environment, scope)
        constraint_handler_bundle.handle_constraints()

        return_value = self._enforced_function(*self._function_args, **self._function_kwargs)
        # TODO get information about the return_value to check if stream
        return constraint_handler_bundle.handle_constraints_with_value(return_value)

    def _handle_sync_post_enforce(self, subject, action, resource, environment, return_value, scope):
        self._values_dict["return_value"] = return_value
        constraint_handler_bundle = self._get_sync_bundle(subject, action, resource, environment, scope)
        constraint_handler_bundle.handle_constraints()
        return constraint_handler_bundle.handle_constraints_with_value(return_value)

    def sync_post_enforce(self, subject=None, action=None, resource=None, environment=None, scope: str = "default"):
        return_value = self._enforced_function(*self._function_args, **self._function_kwargs)
        # TODO get information about the return_value to check if stream
        return self._handle_sync_post_enforce(subject, action, resource, environment, return_value, scope)

    def sync_pre_and_post_enforce(self, subject=None, action=None, resource=None, environment=None,
                                  scope: str = "default"):
        return_value = self.sync_pre_enforce(subject, action, resource, environment, scope)
        return self._handle_sync_post_enforce(subject, action, resource, environment, return_value, scope)

    async def _get_async_bundle(self, subject, action, resource, environment, scope):
        authorization_subscription = auth_factory.create_authorization_subscription(self._values_dict, subject, action,
                                                                                    resource, environment, scope)
        self._current_decision = self._get_initial_decision(authorization_subscription)
        self._fail_on_non_permit()
        constraint_handler_bundle = constraint_handler_service.create_constraint_handler_bundle(self._current_decision)
        return constraint_handler_bundle

    async def pre_enforce(self, subject=None, action=None, resource=None, environment=None, scope: str = "default"):
        constraint_handler_bundle = await self._get_async_bundle(subject, action, resource, environment, scope)
        constraint_handler_bundle.handle_constraints()
        return_value = await self._enforced_function(*self._function_args, **self._function_kwargs)
        # TODO get information about the return_value to check if stream
        is_stream = False
        if not is_stream:
            return constraint_handler_bundle.handle_constraints_with_value(return_value)

        # TODO get Generator of return_value
        # TODO Replace generator of function with new generator
        self._values_dict["return_value"] = return_value
        return constraint_handler_bundle.handle_constraints_with_value(return_value)

    async def post_enforce(self, subject=None, action=None, resource=None, environment=None, scope: str = "default"):
        return_value = self._enforced_function(*self._function_args, **self._function_kwargs)
        return await self._handle_async_post_enforce(action, environment, resource, return_value, subject, scope)

    async def _handle_async_post_enforce(self, action, environment, resource, return_value, subject, scope):
        self._values_dict["return_value"] = return_value
        # TODO get information about the return_value to check if stream
        constraint_handler_bundle = await self._get_async_bundle(subject, action, resource, environment, scope)
        constraint_handler_bundle.handle_constraints()
        return constraint_handler_bundle.handle_constraints_with_value(return_value)

    async def pre_and_post_enforce(self, subject=None, action=None, resource=None, environment=None,
                                   scope: str = "default"):
        constraint_handler_bundle = await self._get_async_bundle(subject, action, resource, environment, scope)
        constraint_handler_bundle.handle_constraints()

        return_value = await self._enforced_function(*self._function_args, **self._function_kwargs)
        return await self._handle_async_post_enforce(action, environment, resource, return_value, subject, scope)

    async def drop_while_denied(self, subject=None, action=None, resource=None, environment=None,
                                scope: str = "default"):
        authorization_subscription = auth_factory.create_authorization_subscription(self._values_dict, subject, action,
                                                                                    resource, environment, scope)
        self._current_decision = self._get_initial_decision(authorization_subscription)
        return_value = self._enforced_function(*self._function_args, **self._function_kwargs)
        stream_task = asyncio.create_task(self._update_decision(authorization_subscription))
        pass
        # TODO check if function is coroutine or gen, else throw
        # TODO get Generator of return_value
        # TODO Replace generator of function with new generator
        # check if stream sonst exception ( Abhängig vom Framework identifizierbar )
        # if not scope_identifier.is_stream(self._enforced_function):
        #     raise Exception
        #
        # authorization_subscription = self.create_authorization(subject, action, resource, environment, scope)
        # await self._get_initial_decision(authorization_subscription)
        # stream_task = asyncio.create_task(self._update_decision(authorization_subscription))
        # executed_function = self._enforced_function(self._function_args, self._function_kwargs)
        # gene = scope_identifier.get_stream_generator()
        # for i in gene:
        #     # if decision = permit
        #     # try handle constraint
        #     #   yield i
        #     # catch
        #     pass
        #
        # await asyncio.gather(self.ggd(), self.ggd())
        #
        # enforcetask = asyncio.create_task(self._update_decision())
        # # executed_function = self._enforced_function(self._function_args, self._function_kwargs)
        # # identify ob es eine Streaming response ist
        #
        # # asyncio.gather(enforcetask, task_2)
        #
        # pass

    async def recoverable_if_denied(self, subject=None, action=None, resource=None, environment=None,
                                    scope: str = "default"):
        pass

    def _indeterminate_decision(self):
        self._current_decision = {"decision": "INDETERMINATE"}
        self._enforcement_stream = None

    @backoff.on_exception(backoff.constant, Exception, max_time=20)
    def _sync_get_decision(self, subscription, decision_event="decide"):
        self._current_decision = pdp.sync_decide(subscription, decision_event)

    async def _get_initial_decision(self, subscription, decision_event="decide"):
        self._enforcement_stream = pdp.decide(subscription, decision_event)
        try:
            self._current_decision = await self._enforcement_stream.__anext__()
        except Exception as e:
            self._indeterminate_decision()

    @backoff.on_exception(backoff.expo, Exception, on_backoff=_indeterminate_decision, max_value=100)
    async def _update_decision(self, subscription, decision_event="decide"):
        if self._enforcement_stream is None:
            self._enforcement_stream = pdp.decide(subscription, decision_event)
        async for decision in self._enforcement_stream:
            self._current_decision = decision

    def _fail_on_non_permit(self):
        if self._current_decision != "permit":
            raise Exception


framework_handler: BaseFrameworkErrorHandler
auth_factory: BaseAuthorizationSubscriptionFactory
