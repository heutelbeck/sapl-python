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


