import functools
import types

__all__ = ['NoExceptNamespace', 'RecursiveNamespace']


class NoExceptNamespace(types.SimpleNamespace):
    """Returns 'None' instead of raising an AttributeError when the requested attribute does not exist."""

    def __getattr__(self, item):
        # N.B. from the Python datamodel documentation:
        #  "Called when the default attribute access fails with an AttributeError"
        return None


@functools.singledispatch
def recursive_namespace_from(o):
    return o


@recursive_namespace_from.register
def _recursive_namespace_from(d: dict):
    return RecursiveNamespace(**d)


@recursive_namespace_from.register(list)
@recursive_namespace_from.register(set)
@recursive_namespace_from.register(tuple)
def _recursive_namespace_from(s):
    return [recursive_namespace_from(e) for e in s]


class RecursiveNamespace(types.SimpleNamespace):
    """A namespace type that can contain nested namespaces."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            kwargs[k] = RecursiveNamespace.from_t(v)
        super().__init__(**kwargs)

    @staticmethod
    def from_t(o):
        return recursive_namespace_from(o)
