import types
from typing import Type, Union

from sapl_base.authorization_subscription_factory import auth_factory
from sapl_base.authorization_subscriptions import AuthorizationSubscription
from sapl_base.constraint_handling.constraint_handler_bundle import ConstraintHandlerBundle
from sapl_base.exceptions import PermissionDenied


class PolicyEnforcementPoint:
    constraint_handler_bundle: ConstraintHandlerBundle = None

    def __init__(self, fn: types.FunctionType, *args, **kwargs):
        self._enforced_function = fn
        args_dict = get_named_args_dict(fn, *args, **kwargs)
        self._function_args = args
        self._function_kwargs = kwargs

        try:
            class_object = args_dict.get('self')
            if class_object is None:
                raise KeyError
            self._pos_args = get_class_positional_args(fn, args)
            self.values_dict = {"function": fn, "self": class_object, "args": args_dict}

        except KeyError:
            self._pos_args = get_function_positional_args(fn, args)
            self.values_dict = {"function": fn, "args": args_dict}

    def get_return_value(self) -> dict:
        """

        :return:
        """
        self.values_dict["return_value"] = self._enforced_function(**self.values_dict["args"])
        return self.values_dict["return_value"]

    async def async_get_return_value(self) -> dict:
        """

        :return:
        """
        self.values_dict["return_value"] = await self._enforced_function(**self.values_dict["args"])
        return self.values_dict["return_value"]

    def get_subscription(self, subject: Union[str, callable], action: Union[str, callable],
                         resource: Union[str, callable], environment: Union[str, callable], scope: str,
                         enforcement_type: str) -> AuthorizationSubscription:
        """

        :param subject:
        :param action:
        :param resource:
        :param environment:
        :param scope:
        :param enforcement_type:
        :return:
        """
        return auth_factory.create_authorization_subscription(self.values_dict, subject, action, resource, environment,
                                                              scope, enforcement_type)

    def fail_with_bundle(self, exception: Exception) -> None:
        """
        :param exception:
        """

        try:
            self.constraint_handler_bundle.execute_on_error_handler(exception)
        except Exception as e:
            if isinstance(e, PermissionDenied):
                raise permission_denied_exception
            else:
                raise e

    def check_if_denied(self, decision) -> None:
        """

        :param decision:
        """
        if decision["decision"] == "DENY":
            self.fail_with_bundle(permission_denied_exception())


def get_function_positional_args(fn, args):
    """

    :param fn:
    :param args:
    :return:
    """
    return args[0:fn.__code__.co_argcount]


def get_class_positional_args(fn, args):
    """

    :param fn:
    :param args:
    :return:
    """
    return args[1:fn.__code__.co_argcount]


def get_named_args_dict(fn, *args, **kwargs) -> dict:
    """
    The method get the dictionary of arguments  of the function use the decorator.

    :param fn:
    :type self: function or method
    :param self: function or method use the decorator

    :type args: variable list
    :param args: variable list of the function use the decorator

    :type kwargs: keyworded variable
    :param kwargs: keyworded variable of the function use the decorator
    """

    if not hasattr(fn, "__code__"):
        args_names = fn.func.__code__.co_varnames[: fn.func.__code__.co_argcount]
    else:
        args_names = fn.__code__.co_varnames[: fn.__code__.co_argcount]

    return {**dict(zip(args_names, args)), **kwargs}


streaming_pep: PolicyEnforcementPoint
permission_denied_exception: Type[Exception] = PermissionDenied
