import functools
import inspect
import logging


def watch_method(_f=None, *,
                 log_impl=None, log_level=logging.DEBUG,
                 show_all=False, show_args=False, show_kwargs=False,
                 predicate=lambda *args, **kwargs: True):
    """Useful debugging decorator that logs when a function is entered into and again when the function exits."""
    def before(log, f_repr, signature, *args, **kwargs):
        if any([show_all, show_args, show_kwargs]):
            arguments = [str(a) for a in args]
            keywords = [f'{k}={v!r}' for k, v in kwargs.items()]
            if show_all:
                args_and_kwargs = ', '.join(arguments + keywords)
                # <function Class.func at 0x?????????>(*args, **kwargs): ...
                log(f'{f_repr}({args_and_kwargs}): ...')
            elif show_args:
                arguments = ', '.join(arguments) + (', ...' if kwargs else '')
                # <function Class.func at 0x?????????>(*args, ...): ...
                log(f'{f_repr}({arguments}): ...')
            else:
                keywords = ('..., ' if args else '') + ', '.join(keywords)
                # <function Class.func at 0x?????????>(..., **kwargs): ...
                log(f'{f_repr}({keywords}): ...')
        else:
            # <function Class.func at 0x?????????>(self, *names, *keywords): ...
            log(f'{f_repr}{signature}: ...')

    def after(log, f_name, signature, *args, **kwargs):
        log(f'{f_name}{signature}: done.')

    def _watch_method(f):
        @functools.wraps(f)
        def _(*args, **kwargs):
            watch = predicate(*args, **kwargs)
            if log_impl:
                def log(msg): log_impl(msg)
            else:
                logger = logging.getLogger(f.__module__)  # same as the standard form: logging.getLogger(__name__)
                def log(msg): logger.log(log_level, msg)
            sig = inspect.signature(f)
            f_repr = repr(f)  # repr(f) => '<function Class.func at 0x?????????>'
            watch and before(log, f_repr, sig, *args, **kwargs)
            try:
                return f(*args, **kwargs)
            finally:
                watch and after(log, f_repr, sig, *args, **kwargs)
        return _

    if _f:
        # called without parens
        return _watch_method(_f)

    # called with parens
    return _watch_method
