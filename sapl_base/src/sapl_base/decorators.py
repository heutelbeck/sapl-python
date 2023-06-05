import asyncio
import inspect
from functools import wraps
from typing import Callable

from sapl_base.policy_enforcement_points.async_generator_policy_enforcement_point import \
    AsyncGeneratorPolicyEnforcementPoint
import sapl_base.policy_enforcement_points.policy_enforcement_point as pep
from sapl_base.policy_enforcement_points.async_policy_enforcement_point import AsyncPolicyEnforcementPoint
from sapl_base.policy_enforcement_points.sync_policy_enforcement_point import SyncPolicyEnforcementPoint
from sapl_base.sapl_util import double_wrap


@double_wrap
def pre_enforce(fn, subject: str = None, action: str = None, resource = None,
                environment: str = None, scope: str = "automatic"):
    """
    Wraps the decorated resource action point function with a SAPL Policy Enforcement Point (PEP).

    If the function returns a stream, pre_enforce will cancel the stream when a DENY is received.

    SAPL Decorators must be used as first Decorator to gather needed information of the annotated Function.

    Identify if the function is a coroutine and calls the appropriate function to handle the enforcement in a coroutine
    throws an exception, when the decorated function returns a stream and is no coroutine.

    :param fn:  decorated function
    :param subject: subject of an authorization_subscription or a function to create the subject
    :param action: action of an authorization_subscription or a function to create the action
    :param resource: resource of an authorization_subscription or a function to create the resource
    :param environment: environment of an authorization_subscription or a function to create the environment
    :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
    :return: The pre_enforced value of the decorated function
    """
    if asyncio.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrap(*args, **kwargs):
            enforcement_point = AsyncPolicyEnforcementPoint(fn, *args, **kwargs)
            return await enforcement_point.pre_enforce(subject, action, resource, environment, scope)

        return async_wrap
    else:
        @wraps(fn)
        def wrap(*args, **kwargs):
            enforcement_point = SyncPolicyEnforcementPoint(fn, *args, **kwargs)
            return enforcement_point.pre_enforce(subject, action, resource, environment, scope)

        return wrap


@double_wrap
def post_enforce(fn, subject: str = None, action: str = None, resource: str = None,
                 environment: str = None, scope: str = "automatic"):
    """
    Post_enforces a decorated function with SAPL.

    SAPL Decorators must be used as first Decorator to gather needed information of the annotated Function.

    If the function returns a stream an exception is thrown.
    Identify if the function is a coroutine and calls the appropriate function to handle the enforcement in a coroutine

    :param fn:  decorated function
    :param subject: subject of an authorization_subscription or a function to create the subject
    :param action: action of an authorization_subscription or a function to create the action
    :param resource: resource of an authorization_subscription or a function to create the resource
    :param environment: environment of an authorization_subscription or a function to create the environment
    :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
    :return: The post_enforced value of the decorated function
    """
    if asyncio.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrap(*args, **kwargs):
            enforcement_point = AsyncPolicyEnforcementPoint(fn, *args, **kwargs)
            return await enforcement_point.post_enforce(subject, action, resource, environment, scope)

        return async_wrap
    else:
        @wraps(fn)
        def wrap(*args, **kwargs):

            enforcement_point = SyncPolicyEnforcementPoint(fn, *args, **kwargs)
            return enforcement_point.post_enforce(subject, action, resource, environment, scope)

        return wrap


"""
SAPL Decorators must be used as first Decorator to gather needed information of the annotated Function.
"""


@double_wrap
def pre_and_post_enforce(fn, subject: str = None, action: str = None, resource: str = None,
                         environment: str = None, scope: str = "automatic"):
    """
    Pre- and post_enforces a decorated function with SAPL.

    SAPL Decorators must be used as first Decorator to gather needed information of the annotated Function.

    If the function returns a stream an exception is thrown.

    Identify if the function is a coroutine and calls the appropriate function to handle the enforcement in a coroutine

    :param fn:  decorated function
    :param subject: subject of an authorization_subscription or a function to create the subject
    :param action: action of an authorization_subscription or a function to create the action
    :param resource: resource of an authorization_subscription or a function to create the resource
    :param environment: environment of an authorization_subscription or a function to create the environment
    :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
    :return: The pre- and post_enforced value of the decorated function
    """
    if asyncio.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrap(*args, **kwargs):
            enforcement_point = AsyncPolicyEnforcementPoint(fn, *args, **kwargs)
            return await enforcement_point.pre_and_post_enforce(subject, action, resource, environment, scope)

        return async_wrap
    else:
        @wraps(fn)
        def wrap(*args, **kwargs):
            enforcement_point = SyncPolicyEnforcementPoint(fn, *args, **kwargs)
            return enforcement_point.pre_and_post_enforce(subject, action, resource, environment, scope)

        return wrap


@double_wrap
def enforce_till_denied(fn, subject: str = None, action: str = None, resource: str = None,
                        environment: str = None, scope: str = "automatic"):
    """
    Enforces a stream and cancels the Stream when the Decision is not PERMIT

    SAPL Decorators must be used as first Decorator to gather needed information of the annotated Function.

    If the function doesn't return a stream, an exception will be thrown

    Identify if the function is a coroutine and will throw an exception, if it is not a coroutine.

    :param fn:  decorated function
    :param subject: subject of an authorization_subscription or a function to create the subject
    :param action: action of an authorization_subscription or a function to create the action
    :param resource: resource of an authorization_subscription or a function to create the resource
    :param environment: environment of an authorization_subscription or a function to create the environment
    :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
    :return: The return_value of the decorated function with a generator which will enforce each value, which is sent with the stream
    """
    if inspect.isclass(fn):
        "Replace the original init method of the decorated class with an init method which inits the class and creates " \
        "a Streaming PEP which enforces the decorated class with till_denied behaviour"
        fn.original_init = fn.__init__

        def new_init(self,*args,**kwargs):
            fn.original_init(self,*args,**kwargs)
            self.streaming_pep = pep.streaming_pep(fn,*args, instance=self,type_of_enforcement="enforce_till_denied",**kwargs)
            self.streaming_pep.enforce_till_denied(subject, action, resource, environment, scope)

        fn.__init__= new_init
        return fn

    if inspect.isasyncgenfunction(fn):

        @wraps(fn)
        async def async_wrap(*args, **kwargs):
            enforcement_point = AsyncGeneratorPolicyEnforcementPoint(fn, *args,type_of_enforcement="enforce_till_denied", **kwargs)
            async for value in enforcement_point.enforce_till_denied(subject,action,resource,environment,scope):
                yield value

        return async_wrap

    raise Exception


@double_wrap
def enforce_drop_while_denied(fn, subject: str = None, action: str = None, resource: str = None,
                              environment: str = None, scope: str = "automatic"):
    """
    Enforces a stream and drops values, when the current decision is not PERMIT

    SAPL Decorators must be used as first Decorator to gather needed information of the annotated Function.

    If the function doesn't return a stream, an exception will be thrown

    Identify if the function is a coroutine and will throw an exception, if it is not a coroutine.

    :param fn:  decorated function
    :param subject: subject of an authorization_subscription or a function to create the subject
    :param action: action of an authorization_subscription or a function to create the action
    :param resource: resource of an authorization_subscription or a function to create the resource
    :param environment: environment of an authorization_subscription or a function to create the environment
    :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
    :return: The return_value of the decorated function with a generator which will enforce each value, which is sent with the stream
    """


    if inspect.isclass(fn):
        "Replace the original init method of the decorated class with an init method which inits the class and creates " \
        "a Streaming PEP which enforces the decorated class with drop_while_denied behaviour"
        fn.original_init = fn.__init__

        def new_init(self,*args,**kwargs):
            fn.original_init(self,*args,**kwargs)
            self.streaming_pep = pep.streaming_pep(fn,*args, instance=self,type_of_enforcement="enforce_drop_while_denied",**kwargs)
            self.streaming_pep.drop_while_denied(subject, action, resource, environment, scope)

        fn.__init__= new_init
        return fn


    if inspect.isasyncgenfunction(fn):

        @wraps(fn)
        async def async_wrap(*args, **kwargs):
            enforcement_point = AsyncGeneratorPolicyEnforcementPoint(fn, *args,type_of_enforcement="enforce_drop_while_denied", **kwargs)
            async for value in enforcement_point.drop_while_denied(subject,action,resource,environment,scope):
                yield value

        return async_wrap

    raise Exception


@double_wrap
def enforce_recoverable_if_denied(fn, subject: str = None, action: str = None, resource: str = None,
                                  environment: str = None, scope: str = "automatic", handle_recoverable_deny_function : Callable[[], None] = None):
    """
    Enforces a stream and drops values, when the current decision is not PERMIT and notify the client, that
    values are dropped, because they are not PERMITTED to receive them.

    SAPL Decorators must be used as first Decorator to gather needed information of the annotated Function.

    If the function doesn't return a stream, an exception will be thrown

    Identify if the function is a coroutine and will throw an exception, if it is not a coroutine.


    :param fn:  decorated function
    :param subject: subject of an authorization_subscription or a function to create the subject
    :param action: action of an authorization_subscription or a function to create the action
    :param resource: resource of an authorization_subscription or a function to create the resource
    :param environment: environment of an authorization_subscription or a function to create the environment
    :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
    :return: The return_value of the decorated function with a generator which will enforce each value, which is sent with the stream
    """
    if inspect.isclass(fn):
        "Replace the original init method of the decorated class with an init method which inits the class and creates " \
        "a Streaming PEP which enforces the decorated class with recoverable_if_denied behaviour"
        fn.original_init = fn.__init__

        def new_init(self,*args,**kwargs):
            fn.original_init(self,*args,**kwargs)
            self.streaming_pep = pep.streaming_pep(fn,*args, instance=self,type_of_enforcement="enforce_recoverable_if_denied",**kwargs)
            self.streaming_pep.recoverable_if_denied(subject, action, resource, environment, scope, handle_recoverable_deny_function)

        fn.__init__= new_init
        return fn

    if inspect.isasyncgenfunction(fn):

        @wraps(fn)
        async def async_wrap(*args, **kwargs):
            enforcement_point = AsyncGeneratorPolicyEnforcementPoint(fn, *args, type_of_enforcement="enforce_recoverable_if_denied",**kwargs)
            async for value in enforcement_point.recoverable_if_denied(subject,action,resource,environment,scope, handle_recoverable_deny_function):
                yield value

        return async_wrap

    raise Exception


