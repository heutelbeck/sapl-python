from sapl_base.authorization_subscription_factory import BaseAuthorizationSubscriptionFactory
from sapl_base.constraint_handling.constraint_handler_bundle import ConstraintHandlerBundle


class BasePolicyEnforcementPoint:
    constraint_handler_bundle: ConstraintHandlerBundle = None

    def __init__(self, fn, *args, **kwargs):
        self._enforced_function = fn
        args_dict = get_named_args_dict(fn, *args, **kwargs)
        self._function_args = args
        self._function_kwargs = kwargs

        try:
            class_object = args_dict.pop('self')
            self._pos_args = get_class_positional_args(fn, args)
            self.values_dict = {"function": fn, "class": class_object, "args": args_dict}

        except KeyError:
            self._pos_args = get_function_positional_args(fn, args)
            self.values_dict = {"function": fn, "args": args_dict}

    def get_return_value(self):
        self.values_dict["return_value"] = self._enforced_function(**self.values_dict["args"])
        return self.values_dict["return_value"]

    async def async_get_return_value(self):
        self.values_dict["return_value"] = await self._enforced_function(**self.values_dict["args"])
        return self.values_dict["return_value"]

    def get_subscription(self, subject, action, resource, environment, scope, enforcement_type):
        return auth_factory.create_authorization_subscription(self.values_dict, subject, action, resource, environment,
                                                              scope, enforcement_type)

    def fail_with_bundle(self, exception):
        self.constraint_handler_bundle.execute_on_error_handler(exception)

    def check_if_denied(self, decision):
        if decision["decision"] == "DENY":
            self.fail_with_bundle(Exception)


def get_function_positional_args(fn, args):
    return args[0:fn.__code__.co_argcount]


def get_class_positional_args(fn, args):
    return args[1:fn.__code__.co_argcount]


def get_named_args_dict(fn, *args, **kwargs):
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


auth_factory: BaseAuthorizationSubscriptionFactory
