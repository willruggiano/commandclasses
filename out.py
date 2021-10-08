"""
Dedicated to all things standard out.
"""
import json as _json
import shutil

# see: https://pypi.org/project/colorama/
# this library helps us make our ANSI character sequences (defined below) compatible across platforms
import sys

import colorama

colorama.init()


class stylez:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


COLS, ROWS = shutil.get_terminal_size()  # TODO: word wrapping
EMPTY = ''
NEWLINE = '\n'
SPACE = ' '
TAB = '\t'


def join_str(*strings, delimiter: str = SPACE):
    return delimiter.join(filter(None, strings))


def join(*parts, delimiter: str = EMPTY):
    return delimiter.join(parts)


def _format(*parts, delimiter: str = EMPTY, **fargs):
    message = join(*parts, delimiter=delimiter)
    if fargs:
        # 2020-02 WMR HACK! message.format(...) raises a KeyError when trying to format a string with json in it
        return message.format(**fargs)
    return message


def style(message: str, *styles, **fargs):
    message = join(*styles, message, stylez.ENDC)
    return _format(message, **fargs)


def bold(message: str, **fargs):
    return style(message, stylez.BOLD, **fargs)


def header(message: str, newline_before=False, newline_after=False, **fargs):
    before = NEWLINE if newline_before else EMPTY
    after = NEWLINE if newline_after else EMPTY
    message = join(before, style(message, stylez.HEADER), after)
    return _format(message, **fargs)


def _spaced(line: str, spaces: int):
    return join((SPACE * spaces), line)


def _tabbed(line: str, tabs: int):
    return join((TAB * tabs), line)


# can't we all just get along?
def indented(*lines, spaces: int = 4, tabs: int = 0, **fargs):
    def f(line):
        return _tabbed(line, tabs) if tabs else _spaced(line, spaces)

    return _format(*(f(line) for line in lines), **fargs)


def jsonified(obj, **kwargs):
    kwargs.setdefault('indent', 4)
    kwargs.setdefault('sort_keys', True)
    kwargs.setdefault('default', str)
    return _json.dumps(obj, **kwargs)


# Note that, for the next three methods, the ostream cannot be given a default value e.g.
#   `def json(obj, os=sys.stdout, ...):`
# because that precludes our ability to do io redirection (e.g. via context-managers, as in the unit tests). This is
# because function defaults are *static* and NOT (strictly speaking) references, and therefore any runtime attempts to
# change the target attributes (i.e. sys.stdout and sys.stderr) have no effect (at least on these methods). This is the
# same reason that it is ill-advised to have *mutable* function defaults.
def json(obj, os=None, *styles):
    print(jsonified(obj), file=(os or sys.stdout))


def show(*lines, os=None, **fargs):
    print(_format(*lines, **fargs), file=(os or sys.stdout))  # See note above.


def error(*lines, os=None, **fargs):
    message = _format(*lines, **fargs)
    message = style(message, stylez.FAIL)
    print(message, file=(os or sys.stderr))  # See note above.


def prompt(msg=None, punctuator=':', os=None, **fargs):
    if msg:
        print(msg, end=f'{punctuator} ', file=(os or sys.stderr))  # Plus a space between prompt and input
    return input()  # no prompt, nothing to stdout, just read from stdin
