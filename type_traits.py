import sys

import typing


def typename(class_or_instance):
    if isinstance(class_or_instance, type):
        return class_or_instance.__name__
    return type(class_or_instance).__name__


def get_generic_type(tp):
    if sys.version_info >= (3, 8):
        return typing.get_origin(tp)
    return getattr(tp, '__origin__', None)


def get_generic_args(tp):
    if sys.version_info >= (3, 8):
        return typing.get_args(tp)
    return getattr(tp, '__args__', None)


def type_str(tp):
    g = get_generic_type(tp)
    if g:
        # we're dealing with a typing Generic, e.g. typing.Union
        g_args = get_generic_args(tp)
        if g_args:
            # return the type parameters, e.g. ('str', 'int') from typing.Union[str, int]
            return ', '.join(type_str(t) for t in g_args)
        return repr(g).lstrip('typing.')  # => Union
    return typename(tp)  # just a normal type, i.e. a class with a name attribute like all other things
