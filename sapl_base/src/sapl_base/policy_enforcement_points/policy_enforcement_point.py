import inspect
import types
from typing import Type, Union, Callable, Dict

import sapl_base.authorization_subscription_factory
from sapl_base.authorization_subscriptions import AuthorizationSubscription
from sapl_base.constraint_handling.constraint_handler_bundle import ConstraintHandlerBundle
from sapl_base.exceptions import PermissionDenied
from sapl_base.sapl_util import get_function_positional_args, get_named_args_dict, get_class_positional_args


class PolicyEnforcementPoint:
    """
    Baseclass for PolicyEnforcementPoints(PEP).
    It handles the enforcement of decorated functions
    """
    constraint_handler_bundle: ConstraintHandlerBundle = None

    def __init__(self, fn: types.FunctionType, *args, **kwargs):
        self._enforced_function = fn
        args_dict = get_named_args_dict(fn, *args, **kwargs)
        self._function_args = args
        self._function_kwargs = kwargs

        if inspect.isclass(fn):
            self.values_dict = {"class": fn, "args": args_dict}
            return

        try:
            class_object = args_dict.get('self')
            if class_object is None:
                raise KeyError
            self._pos_args = get_class_positional_args(fn, args)
            self.values_dict = {"function": fn, "self": class_object, "args": args_dict}

        except KeyError:
            self._pos_args = get_function_positional_args(fn, args)
            self.values_dict = {"function": fn, "args": args_dict}

    def _get_return_value(self) -> Dict:
        """
        Call the decorated function and get the return-value

        :return: The return-value of the decorated function
        """
        self.values_dict["return_value"] = self._enforced_function(**self.values_dict["args"])
        return self.values_dict["return_value"]

    async def _async_get_return_value(self) -> Dict:
        """
        Call the decorated function and get the return-value

        :return: The return-value of the decorated function
        """
        self.values_dict["return_value"] = await self._enforced_function(**self.values_dict["args"])
        return self.values_dict["return_value"]

    def _get_subscription(self, subject: Union[str, Callable], action: Union[str, Callable],
                          resource: Union[str, Callable], environment: Union[str, Callable], scope: str,
                          enforcement_type: str) -> AuthorizationSubscription:
        """
        Create an AuthorizationSubscription for the decorated function

        :param subject: subject which was provided to the decorator as argument if present
        :param action: action which was provided to the decorator as argument if present
        :param resource: resource which was provided to the decorator as argument if present
        :param environment: environment which was provided to the decorator as argument if present
        :param scope:
        :param enforcement_type: Type of enforcement, with which the function is decorated
        :return: An AuthorizationSubscription
        """
        return sapl_base.authorization_subscription_factory.auth_factory.create_authorization_subscription(
            self.values_dict, subject, action, resource, environment,
            scope, enforcement_type)

    def _fail_with_bundle(self, exception: Union[Exception , None] = None) -> None:
        """
        Call all responsible ErrorConstraintHandlerprovider with the given Exception and fail with the Exception of the
        ErrorConstraintHandlerProvider

        :param exception:Exception with which the ErrorConstraintHandlerProvider are called
        """
        exce = permission_denied_exception() if exception is None  else exception

        try:
            self.constraint_handler_bundle.execute_on_error_handler(exce)
        except Exception as e:
            if isinstance(e, type(permission_denied_exception())):
                raise permission_denied_exception()
            else:
                raise e

    def _check_if_denied(self, decision) -> None:
        """
        Check if the Decision is DENY and call the method fail_with_bundle with a PermissionDenied Exception if true
        :param decision: Decision
        """
        if decision.decision != "PERMIT":
            self._fail_with_bundle(permission_denied_exception())


streaming_pep = None
permission_denied_exception: Type[Exception] = PermissionDenied
