import asyncio
from functools import wraps

from sapl_base.policy_enforcement_point import BasePolicyEnforcementPoint
from sapl_base.sapl_util import double_wrap, get_named_args_dict


@double_wrap
def pre_enforce(fn, subject: str = None, action: str = None, resource: str = None, environment=None, scope="basic"):
    if asyncio.iscoroutinefunction(fn):
        @wraps(fn)
        async def wrap(*args, **kwargs):
            enforcement_point = BasePolicyEnforcementPoint(fn, args, kwargs)
            return await enforcement_point.pre_enforce(subject, action, resource, environment, scope)

        return wrap
    else:
        @wraps(fn)
        def sync_wrap(*args, **kwargs):
            enforcement_point = BasePolicyEnforcementPoint(fn, args, kwargs)
            return enforcement_point.sync_pre_enforce(subject, action, resource, environment, scope)

        return sync_wrap


@double_wrap
def post_enforce(fn, subject: str = None, action: str = None, resource: str = None, environment=None, scope="basic"):
    if asyncio.iscoroutinefunction(fn):
        @wraps(fn)
        async def wrap(*args, **kwargs):
            enforcement_point = BasePolicyEnforcementPoint(fn, *args, **kwargs)
            return await enforcement_point.post_enforce(subject, action, resource, environment, scope)

        return wrap
    else:
        @wraps(fn)
        def sync_wrap(*args, **kwargs):

            enforcement_point = BasePolicyEnforcementPoint(fn, *args, **kwargs)
            return enforcement_point.sync_post_enforce(subject, action, resource, environment, scope)

        return sync_wrap


"""
SAPL Decorators must be used as first Decorator to gather needed information of the annotated Function.
"""
@double_wrap
def pre_and_post_enforce(fn, subject: str = None, action: str = None, resource: str = None, environment=None):
    if asyncio.iscoroutinefunction(fn):
        @wraps(fn)
        async def wrap(*args, **kwargs):
            enforcement_point = BasePolicyEnforcementPoint(fn, *args, **kwargs)
            return await enforcement_point.pre_and_post_enforce(subject, action, resource, environment, scope)

        return wrap
    else:
        @wraps(fn)
        def sync_wrap(*args, **kwargs):
            enforcement_point = BasePolicyEnforcementPoint(fn, *args, **kwargs)
            return enforcement_point.sync_pre_and_post_enforce(subject, action, resource, environment, scope)

        return sync_wrap


@double_wrap
def enforce_drop_while_denied(fn, subject: str = None, action: str = None, resource: str = None, environment=None,
                              scope="basic"):
    if asyncio.iscoroutinefunction(fn):
        @wraps(fn)
        async def wrap(*args, **kwargs):
            enforcement_point = BasePolicyEnforcementPoint(fn, args, kwargs)
            return await enforcement_point.drop_while_denied(subject, action, resource, environment, scope)

        return wrap
    else:
        @wraps(fn)
        def sync_wrap(*args, **kwargs):
            raise Exception
        return sync_wrap


@double_wrap
def enforce_recoverable_if_denied(fn, subject: str = None, action: str = None, resource: str = None, environment=None,
                                  scope: str = "basic"):
    if asyncio.iscoroutinefunction(fn):
        @wraps(fn)
        async def wrap(*args, **kwargs):
            enforcement_point = BasePolicyEnforcementPoint(fn, args, kwargs)
            return await enforcement_point.recoverable_if_denied(subject, action, resource, environment, scope)

        return wrap
    else:
        @wraps(fn)
        def sync_wrap(*args, **kwargs):
            raise Exception
        return sync_wrap
