from functools import wraps


class NoHandlerException(Exception):
    """Raised when an object, which is not a ConstraintHandler is added to the ConstraintHandlerService"""
    pass


def double_wrap(f):
    """
    a decorator, allowing the decorator to be used as:
    @decorator(with, arguments, and=kwargs) or @decorator

    :type f: function or method
    :param f: function or method use the decorator
    """

    @wraps(f)
    def new_dec(*args, **kwargs):
        if len(args) == 1 and len(kwargs) == 0 and callable(args[0]):
            # actual decorated fn
            return f(args[0])
        else:
            # decorator arguments
            return lambda real_fn: f(real_fn, *args, **kwargs)

    return new_dec


def get_function_positional_args(fn, args):
    return args[0:fn.__code__.co_argcount]

def get_class_positional_args(fn,args):
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
