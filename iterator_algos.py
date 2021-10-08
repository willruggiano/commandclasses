import functools
import itertools
from itertools import chain, filterfalse, repeat

"""Most of these are from Python3 docs section on 'Itertools Recipes'."""


def flatten(list_of_lists):
    """Flatten one level of nesting."""
    # flatten([['a','b'],['c','d'],['e']]) => ['a','b','c','d','e']
    # flatten([{'a':'aa'},{'b':'bb'}]) => ['a','b']
    return chain.from_iterable(list_of_lists)


def unique(iterable, normalize=None):
    """List unique elements, preserving order. Remember all elements ever seen."""
    # unique('AAAABBBCCDAABBB') --> A B C D
    # unique('ABBCcAD', str.lower) --> A B C D
    seen = set()
    seen_add = seen.add
    if normalize is None:
        for element in filterfalse(seen.__contains__, iterable):
            seen_add(element)
            yield element
    else:
        for element in iterable:
            k = normalize(element)
            if k not in seen:
                seen_add(k)
                yield element


def for_each_and_between(iterable, f, f_between):
    """Enumerate an iterable invoking the specified function 'f' for each element and call the specified function
    'f_between' between each of the enumerated elements.

    For an iterable i := (1, 2, 3, 4)
    and f := print
    and f_between := lambda e: print(f'between {e} and {e+1}')

    for_each_and_between(i, f, f_between) would result in the following output:
        1
        between 1 and 2
        2
        between 2 and 3
        3
        between 3 and 4
        4
    """
    for i, e in enumerate(iterable):
        f(e)
        (i + 1 < len(iterable)) and f_between(e)


def merge_dicts(source, destination):
    """Merge two dicts; overwrite existing keys in "destination" with those from "source".

    source := {'c': {'d': 'f'}}
    destination := {'a': 'b', 'c': {'d': 'e', 'f': 'g'}}
    merge_dicts(source, destination) => {'a': 'b', 'c': {'d': 'f', 'f': 'g'}}
    """
    for k, v in source.items():
        if isinstance(v, dict):
            node = destination.setdefault(k, {})
            merge_dicts(v, node)
        else:
            destination[k] = v
    return destination


def find_path(d, k, *ks):
    """Find the value of an arbitrarily long list of keys.

    d := {'a': {'b': {'c': 'd'}}}
    find_path(d, 'a', 'b', 'c') => 'd'
    """
    if k in d:
        if ks:
            return find_path(d[k], *ks)
        return d[k]
    return None


def remove_path(d, k, *ks):
    """Remove the value pointed to by some arbitrarily long list of keys.

    d := {'a': {'b': {'c': 'd'}}}
    remove_path(d, 'a', 'b', 'c')
    d := {'a': {'b': {}}}
    """
    if k in d:
        if ks:
            remove_path(d[k], *ks)
        else:
            del d[k]


def set_path(d, k, *ks, v):
    """Define a (arbitrarily long) path to the specific value.

    d := {'a': {'b': {'c': 'd'}}}
    set_path(d, 'a', 'b', 'c', v='foo')
    d := {'a': {'b': {'c': 'foo'}}}

    Creates intermediate dicts if intermediate keys do not exist:
    d := {}
    set_path(d, 'a', 'b', 'c', v='foo')
    d := {'a': {'b': {'c': 'foo'}}}
    """
    d_ = d.setdefault(k, {})
    if ks:
        set_path(d_, *ks, v=v)
    else:
        d[k] = v


@functools.singledispatch
def for_each_base(cls, f, depth_first=True, predicate=lambda cls: True):
    """Iterate a class hierarchy performing some function f on each base of a class cls. When depth_first is True, base
    classes are evaluated first and cls is evaluated last. When depth_first is False, cls is evaluated first and base
    classes are evaluated last. The depth_first specification applies recursively to all base classes. An optional
    predicate function can be supplied to gate the evaluation of function f on any given base's subtree.

    Given a class hierarchy:
                cls
           a     b     c
         d   e
             f
      where:
        predicate(cls) => True
        predicate(a) => False

      relevant invocations of f:
        f(cls) is called
        f(a) is called
        f(d), f(e), f(f) are not called

    Note that the d, e and f subtrees are not even entered (thus predicate(...) is never called) because predicate(a)
    evaluates to False, thus gating the evaluation of its subtree.
    """
    bases = getattr(cls, '__bases__', ())
    depth_first or f(cls)
    if predicate(cls):
        for base in bases:
            for_each_base(base, f, depth_first, predicate)
    depth_first and f(cls)


@for_each_base.register
def _for_each_base(bases: tuple, f, depth_first=True, predicate=lambda cls: True):
    for base in bases:
        for_each_base(base, f, depth_first, predicate)


def truthy_values(item):
    k, v = item
    return v and True


def falsey_values(item):
    return not truthy_values(item)


def cull_dict(d):
    return dict(itertools.filterfalse(falsey_values, d.items()))


def logical_and(*funcs):
    def f(*args):
        return all(func(*args) for func in funcs)
    return f


def logical_or(*funcs):
    def f(*args):
        return any(func(*args) for func in funcs)
    return f


def logical_not(*funcs):
    def f(*args):
        return all(not func(*args) for func in funcs)
    return f


def fill(shorter: list, longer: list, value):
    """Append `value` to shorter until its size equals longer.

        a = [1]
        b = [0, 0, 0]
        fill(a, b, -1) => [1, -1, -1]
    """
    return shorter + list(repeat(value, len(longer) - len(shorter)))
