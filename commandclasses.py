import argparse
import functools
import itertools
import keyword
import logging
import types
import typing
from collections import defaultdict
from dataclasses import dataclass, asdict, InitVar, field, fields
from difflib import get_close_matches

from .utils import type_str, typename, get_generic_args, NoExceptNamespace, for_each_and_between, for_each_base, flatten, watch_method, out

log = logging.getLogger(__name__)

# There is an interesting opportunity here to simplify the loading of custom modules.
# The metaclass approach allows for a role similar to that of Singleton in terms of instance tracking.
# We could use such an approach to make custom modules more flexible (e.g. they need not be required to define a
# class strictly named "Command").
# We could also leverage such an approach for building up the "choices" tuple that is passed to the subcommand
# action of our argument parser. Hmm....
REGISTRY = defaultdict(list)
BREADCRUMBS = {}  # N.B. sorted


@dataclass(frozen=True)
class MISSING:  # pragma: no cover
    """Type alias for a descriptive, error inducing None state"""
    message: str = None
    name: str = None

    def __call__(self, *args, **kwargs):
        if self.message:
            raise TypeError(self.message)
        elif self.name:
            raise TypeError(f"the requested attribute '{self.name}' is missing")
        else:
            raise TypeError('the requested attribute is missing')


def raise_missing(message=None, name=None):  # pragma: no cover
    MISSING(message=message, name=name)()


def _pass(*args, **kwargs):
    pass


# Type alias for a no-op function
PASS = _pass


def generic_type_converter(*ts):
    """Attempt to construct a type from a command-line string representation. Given a variable list of potential types,
    will return the first type instance that does not throw when called. If none of the given types can be safely
    constructed, a ValueError will be thrown (e.g. to trigger an ArgumentParser notifying the user that an invalid
    argument choice has been given). Individual types need not be actual classes, rather just callable objects."""
    def type_converter(s):
        for t in ts:
            try:
                return t(s)
            except:
                pass
        raise ValueError(f'cannot construct any of {ts} from {s}')
    return type_converter


def deprecated(_f=None,
               alternative=None,
               message='This functionality is slated for deprecation!',
               timeline=None):
    def wrapper(f):
        @functools.wraps(f)
        def wraps(*args, **kwargs):
            msg = [message]
            if timeline:
                msg.append(f'It will reach end-of-life {timeline}.')
            if alternative:
                msg.append(f'Consider using {alternative} instead.')
            out.error(*msg, delimiter=out.NEWLINE)
            return f(*args, **kwargs)
        return wraps
    if _f is None:
        return wrapper
    return wrapper(_f)



def normalize_name(name):
    """Turn an attribute name into an argument name, e.g. foo_bar => foo-bar"""
    return name.replace('_', '-')


def denormalize_name(name):
    """Turn an argument name into an attribute name, e.g. --foo-bar => foo_bar"""
    return name.lstrip('-').replace('-', '_')


def show_option(name, option, cls, override_show_help: bool = False):  # pragma: no cover
    # this is the default, however some options are hidden as they pertain primarily to development of the cli rather
    # than everyday usage; the latter can be forced into the help text via the global option --show-all-help-options
    if option.show_help or override_show_help:
        if option.invertible:
            identifier = out.bold(f'--[no-]{normalize_name(name)}')
        else:
            identifier = out.bold(f'--{normalize_name(name)}')
        if option.aliases:
            identifier += (', ' + ', '.join(option.aliases))
        identifier += f' ({type_str(option.type)})'
        if option.choices:
            choices = option.choices
            if option.choices_help_formatter:
                choices = option.choices_help_formatter(choices)
            identifier += f'; choices: {choices}'
        default = option.default
        if option.default_help_formatter:
            default = option.default_help_formatter(default)
        elif option.default_factory:
            default = option.default_factory(cls) or default
        if default:
            identifier += f'; default: {default}'
        if option.required:
            # a subtle leading asterisk denotes required:
            out.show(out.indented(f'* {identifier}', spaces=2))
        else:
            out.show(out.indented(identifier))
        if option.help:
            out.show(out.indented(option.help.capitalize(), spaces=8))


@functools.singledispatch
def show_description(description):  # pragma: no cover
    out.show(out.indented(description))


@show_description.register
def _show_descriptions(descriptions: tuple):  # pragma: no cover
    for description in descriptions:
        out.show(out.indented(description))


@functools.singledispatch
def show_examples(example):  # pragma: no cover
    out.show(out.indented(example))


@show_examples.register
def _show_examples(examples: tuple):  # pragma: no cover
    for_each_and_between(examples, lambda e: out.show(out.indented(e)), lambda _: out.show(out.NEWLINE))


@show_examples.register
def _show_descriptive_examples(examples: dict):  # pragma: no cover
    def show(e):
        out.show(out.indented(e))
        out.show(out.indented('-' * 5))
        out.show(out.indented(examples[e], spaces=8))
    for_each_and_between(examples, show, lambda _: out.show(out.NEWLINE))


def filter_hidden(command_tuple):
    name, cmd = command_tuple
    return cmd.meta.hidden


@dataclass(repr=False)
class Documentation:  # pragma: no cover
    cls: type
    name: str
    description: typing.Union[str, tuple] = None
    examples: typing.Union[str, tuple, dict] = None
    notes: list = field(default_factory=list)
    options: dict = field(default_factory=dict)
    inherited_options: dict = field(default_factory=dict)
    subcommands: dict = field(default_factory=dict)
    inherited_subcommands: dict = field(default_factory=dict)
    usage: str = None

    def show_header(self):
        out.show(out.bold(f'{self.name.upper()} -'))
        if self.description:
            out.show(out.header('Description:', newline_before=True))
            show_description(self.description.capitalize())
        if self.usage:
            out.show(out.header('Usage:', newline_before=True))
            out.show(out.indented(self.usage))

    @staticmethod
    def iter_commands(command_tuples):
        return itertools.filterfalse(filter_hidden, command_tuples)

    def show_body(self, override_show_help: bool = False):
        if self.options:
            out.show(out.header('Options:', newline_before=True))
            all_inherited_options = list(flatten(self.inherited_options.values()))
            for opt_name, opt in sorted(self.options.items()):
                if opt_name not in all_inherited_options:
                    show_option(opt_name, opt, self.cls, override_show_help=override_show_help)
        if self.inherited_options:
            for base, base_opts in sorted(self.inherited_options.items()):
                out.show(out.header(f'Options inherited from {base}:', newline_before=True))
                for opt_name, opt in sorted(base_opts.items()):
                    show_option(opt_name, opt, self.cls, override_show_help=override_show_help)
        cmds = list(self.iter_commands(self.subcommands.items()))
        if cmds:
            out.show(out.header('Subcommands:', newline_before=True))
            for cmd_name, cmd in sorted(cmds):
                out.show(out.indented(out.bold(normalize_name(cmd_name))))
                if cmd.meta.help:
                    out.show(out.indented(cmd.meta.help.capitalize(), spaces=8))
        subcmds = list(self.iter_commands(self.inherited_subcommands.items()))
        if subcmds:
            for base, base_cmds in sorted(subcmds):
                out.show(out.header(f'Subcommands inherited from {base}:', newline_before=True))
                for cmd_name, cmd in sorted(base_cmds):
                    out.show(out.indented(out.bold(normalize_name(cmd_name))))
                    out.show(out.indented(cmd.meta.help, spaces=8))

    def show_footer(self):
        if self.examples:
            out.show(out.header('Examples:', newline_before=True))
            show_examples(self.examples)
        if self.notes:
            out.show(out.header('Notes:', newline_before=True))
            for note in self.notes:
                out.show(out.indented(note))
        out.show(out.header('To see help text:', newline_before=True))
        # TODO: Generic help text.
        out.show(out.indented('{prog} help', '{prog} <command> [<subcommand> ...] help', prog, delimiter=out.NEWLINE))

    def __call__(self, *args, **kwargs):
        self.show_header()
        self.show_body(override_show_help=kwargs.get('show_all_help_options', False))
        self.show_footer()

    # Implement a str() operator since we explicitly disable repr generation for the sake of watch_method debugging
    def __str__(self):
        return f"Documentation({', '.join(f'{f.name}={getattr(self, f.name)!r}' for f in fields(self))})"


def _build_documentation(cls):  # pragma: no cover
    args = arguments(cls)
    cmds = commands(cls)

    def usage():
        usage_str = f'{prog} [options] {cls.meta.usage_context or normalize_name(cls.meta.name)}'
        if cmds:
            usage_str += ' [<subcommand> ...]'
        if args:
            usage_str += ' [arguments]'
        return usage_str

    return Documentation(cls=cls,
                         name=cls.meta.name,
                         description=cls.meta.help,
                         examples=cls.meta.examples,
                         notes=cls.meta.notes,
                         options=args,
                         inherited_options=getattr(cls, '__inherited_arguments__', {}),
                         subcommands=cmds,
                         inherited_subcommands=getattr(cls, '__inherited_commands__', {}),
                         usage=cls.meta.usage or usage())


Predicate = typing.Callable[..., bool]


@dataclass
class Argument:
    parent = None  # Not used.
    # These are set during argument processing. See below: Commandclass::_create_argument_list
    name = None
    type = None

    aliases_: InitVar[tuple] = None
    allow_inverse_: InitVar[bool] = True
    # this allows customizing the way choices objects are displayed in help text
    choices_help_formatter_: InitVar[callable] = None
    # this allows the author of a command to pull argument defaults from some external source e.g. a configuration file
    default_factory_: InitVar[callable] = None
    # this allows customizing the way default objects are displayed in help text
    default_help_formatter_: InitVar[callable] = None
    # these are passed as-is to the "add_argument" method
    meta_args_: InitVar[dict] = None
    required_: InitVar[bool] = False
    required_when_: InitVar[Predicate] = None
    illegal_when_: InitVar[Predicate] = None
    show_help_: InitVar[bool] = True
    type_converter_: InitVar[callable] = None

    default: typing.Any = None
    help: str = None

    def __post_init__(self,
                      aliases_,
                      allow_inverse_,
                      choices_help_formatter_,
                      default_factory_,
                      default_help_formatter_,
                      meta_args_,
                      required_,
                      required_when_,
                      illegal_when_,
                      show_help_,
                      type_converter_):
        self.aliases = aliases_
        self.allow_inverse = allow_inverse_
        self.choices_help_formatter = choices_help_formatter_
        self.default_factory = default_factory_
        self.default_help_formatter = default_help_formatter_
        self.meta_args = meta_args_
        self.required = required_
        self.required_when = required_when_
        self.illegal_when = illegal_when_
        self.show_help = show_help_
        self.type_converter = type_converter_

    @property
    def choices(self):  # pragma: no cover
        return self.meta_args.get('choices')

    @property
    def invertible(self):  # pragma: no cover
        return self.type is bool and self.allow_inverse and not self.name.startswith('no')

    @property
    def properties(self):
        return {k: v for k, v in {**asdict(self), **self.meta_args}.items() if v is not None}

    def add_to(self, parser, parent):
        properties = self.properties
        # set the type property:
        if self.type_converter or get_generic_args(self.type):
            properties.update(type=self.type_converter or generic_type_converter(*get_generic_args(self.type)))
        elif self.type not in (None, bool, list, tuple):
            properties.update(type=self.type)
        # set the action property:
        if self.type is bool:
            properties.setdefault('action', 'store_true')
        elif self.type in (list, tuple):
            properties.setdefault('action', 'append')
        # this is the "long option format" e.g. --argument-name
        names_and_flags = [f'--{normalize_name(self.name)}']
        if self.aliases:
            # but we also allow the user to define other option strings
            names_and_flags += self.aliases
        if self.default_factory:
            new_default = self.default_factory(parent)
            if new_default:
                properties['default'] = new_default
            # else 'default' will be whatever it was before, which might be None, but at least allows for using a
            # hardcoded default when the default_factory fails to provide a valid default
        if self.invertible:
            group = parser.add_mutually_exclusive_group()
            properties.setdefault('dest', self.name)
            # add a --flag option:
            group.add_argument(*names_and_flags, **properties)
            # add a --no-flag option:
            properties['action'] = 'store_false'
            group.add_argument(f'--no-{normalize_name(self.name)}', **properties)
        else:
            parser.add_argument(*names_and_flags, **properties)


def argument(*,
             aliases=None,
             allow_inverse=True,
             choices_help_formatter=None,
             default=None,
             default_factory=None,
             help=None,
             default_help_formatter=None,
             show_help=True,
             required=False,
             required_when=None,
             illegal_when=None,
             type_converter=None,
             **kwargs):
    return Argument(aliases_=aliases,
                    allow_inverse_=allow_inverse,
                    choices_help_formatter_=choices_help_formatter,
                    default=default,
                    default_factory_=default_factory,
                    help=help,
                    default_help_formatter_=default_help_formatter,
                    show_help_=show_help,
                    required_=required,
                    required_when_=required_when,
                    illegal_when_=illegal_when,
                    type_converter_=type_converter,
                    meta_args_=kwargs)


def _default_parser(self_):
    class HelpfulArgumentParser(argparse.ArgumentParser):
        def __init__(self):
            super().__init__(add_help=False,
                             allow_abbrev=False,
                             argument_default=argparse.SUPPRESS,
                             conflict_handler='resolve',
                             usage=argparse.SUPPRESS)

        def _check_value(self, action, value):  # override
            try:
                super()._check_value(action, value)
            except:
                self._show_closest_matches(action, value)
                raise

        def _show_closest_matches(self, action, value):
            matches = get_close_matches(value, action.choices)
            if matches:
                out.error(f"Unknown choice '{value}'. Perhaps you meant one of: {matches}?")
            return matches

    return HelpfulArgumentParser()


def _subcommand_action(cmds, main):
    class SubCommandAction(argparse.Action):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.choices = list(cmds.keys())
            self.default = main

        def __call__(self, parser, namespace, value, option_string=None):
            if value is main:
                setattr(namespace, 'subcommand', main)
            else:
                # 2020-08-11 WMR We cannot instantiate yet here! In the case of the very first, top-level command, we
                # have failed to satisfy our only pre-condition for subcommandclass instantiation which is: we must
                # allow a commandclass's __after_parse__ method to execute as *it* might be responsible for setting the
                # pre-conditions upon which subcommands depend!
                setattr(namespace, 'subcommand', cmds.get(value))

    return SubCommandAction


def _help_action(help_cmd):
    class HelpCommandAction(argparse.Action):
        def __call__(self, parser, namespace, value, option_string=None):
            setattr(namespace, 'subcommand', help_cmd)

    return HelpCommandAction


def inject_command_documentation(instance):
    """Generate documentation/help text for a commandclass if not otherwise specified."""
    doc = _build_documentation(instance)
    show_help = getattr(instance, '__choose_help__', doc)

    add_to_commandclass(instance, help=Commandclass(typename(instance) + 'Help', (),
                                                    # attrs:
                                                    {
                                                        '__help__': True,
                                                        '__call__': show_help
                                                    },
                                                    # meta_args:
                                                    **dict(help='show detailed documentation for this command')))


def inject_completions_command(instance):
    """Generate shell completion options for a commandclass instance."""
    def call(*args, **kwargs):
        out.show(*itertools.filterfalse(lambda k: get_command(instance, k).meta.hidden, commands(instance)),
                 *map(lambda a: f'--{normalize_name(a)}', filter(lambda k: get_argument(instance, k).show_help, arguments(instance))),
                 delimiter=out.NEWLINE)
    add_to_commandclass(instance, completions=make_commandclass(f'Complete{typename(instance)}Command', [],
                                                                name='completions', call=call, hidden=True))


def _check_requirements_when_present(arg, instance):
    invalid = False
    if arg.illegal_when and arg.illegal_when(instance):
        out.error(f'--{normalize_name(arg.name)} is illegal, due to other options')
        invalid = True
    return invalid


def _check_requirements_when_missing(arg, instance):
    invalid = False
    if arg.required:
        out.error(f'--{normalize_name(arg.name)} is required but missing')
        invalid = True
    if arg.required_when and arg.required_when(instance):
        out.error(f'--{normalize_name(arg.name)} is required, due to other options, but missing')
        invalid = True
    return invalid


def _check_requirement(arg, instance):
    if getattr(instance, arg.name, None) is not None:  # if parsed
        return _check_requirements_when_present(arg, instance)
    else:
        return _check_requirements_when_missing(arg, instance)


class InvalidArgumentException(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


def _check_required_arguments(instance, *args, **kwargs):
    if any(list(filter(lambda a: _check_requirement(a, instance), arguments(instance).values()))):
        raise InvalidArgumentException('invalid argument(s) given to command')


class Commandclass(type):
    """A metaclass that creates the actual command classes."""

    @watch_method(show_all=True, log_level=0)  # logging.NOTSET
    def __new__(mcs, clsname, bases, attrs, **meta_args):
        attrs['__commandclasscheck__'] = True  # label this class as a commandclass
        meta_args['name'] = denormalize_name(meta_args.get('name', clsname.lower()))
        bases, attrs = mcs._create_argument_list(clsname, bases, attrs, **meta_args)
        bases, attrs = mcs._create_command_list(clsname, bases, attrs, **meta_args)
        bases, attrs = mcs._create_parser_hooks(clsname, bases, attrs, **meta_args)
        bases, attrs = mcs._create_call_method(clsname, bases, attrs, **meta_args)
        attrs['meta'] = NoExceptNamespace(**meta_args)
        cls = super().__new__(mcs, clsname, bases, attrs)
        REGISTRY[meta_args['name']].append(cls)
        return cls

    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        BREADCRUMBS[instance.meta.name] = cls
        if Commandclass.has_command(cls, 'help'):
            log.debug("Skipping generated help command for '%s' with a user-defined help command.", cls.__name__)
        else:
            inject_command_documentation(instance)
        # 2020-10-04 WMR Adding shell completion functionality
        inject_completions_command(instance)
        return instance

    @classmethod
    @watch_method(show_kwargs=True, log_level=0)  # logging.NOTSET
    def _create_argument_list(mcs, clsname, bases, attrs, **meta_args):
        """Extract and process any arguments that are part of this commandclass."""
        args = {}
        inherited_args = defaultdict(dict)

        dryrun = argument(help='echo input to stdout and exit', action='store_true')
        dryrun.name = denormalize_name('--dryrun')
        dryrun.type = bool
        args[dryrun.name] = dryrun
        attrs[dryrun.name] = None

        def process_arguments(name, cls_attrs, base_class=None):
            if base_class and Commandclass.is_commandclass(base_class):
                # we can do less work here since we've already processed this metaclass
                for a_name, a in arguments(base_class).items():
                    if a_name not in args:
                        args[a_name] = a
                        inherited_args[name][a_name] = a
            else:
                anns = cls_attrs.get('__annotations__', {})
                for a_name, a in cls_attrs.items():
                    if Commandclass.is_argument(a):
                        if a_name not in args:
                            a.name = a_name
                            a.type = anns.get(a_name)
                            # ensure as_dict(o) returns the correct repr of a commandclass object prior to parsing:
                            attrs[a_name] = None
                            if base_class:
                                inherited_args[name][a_name] = a
                            args[a_name] = a

        def process_base(base):
            process_arguments(base.__name__, vars(base), base_class=base)

        # base classes first
        for_each_base(bases, process_base, predicate=lambda c: not Commandclass.is_commandclass(c))
        # and finally this class (so our arguments take precedence over base class arguments)
        process_arguments(clsname, attrs.copy())

        attrs['__arguments__'] = args
        attrs['__inherited_arguments__'] = inherited_args
        return bases, attrs

    @classmethod
    def _create_command_list(mcs, clsname, bases, attrs, **meta_args):
        """Extract and process any sub-commands that are part of this commandclass."""
        cmds = {}
        inherited_cmds = defaultdict(list)

        def process_subcommands(name, cls_attrs, base_class=None):
            if base_class and Commandclass.is_commandclass(base_class):
                # we can do less work here since we've already processed this metaclass
                for c_name, c in commands(base_class).items():
                    cmds[c_name] = c
                    inherited_cmds[name].append((c_name, c))
            else:
                for a_name, a in filter(lambda e: Commandclass.is_commandclass(e[1]), cls_attrs.items()):
                    cmds[normalize_name(a_name)] = a
                    if a_name in attrs:  # so we don't KeyError when processing base classes
                        del attrs[a_name]
                    if base_class:
                        inherited_cmds[name].append((a_name, a))

        def process_base(base):
            process_subcommands(base.__name__, vars(base), base_class=base)

        # base classes first
        for_each_base(bases, process_base, predicate=lambda c: not Commandclass.is_commandclass(c))
        # and finally this class (so our commands take precedence over base class commands)
        process_subcommands(clsname, attrs.copy())

        attrs['__commands__'] = cmds
        attrs['__inherited_commands__'] = inherited_cmds
        return bases, attrs

    @classmethod
    def _create_parser_hooks(mcs, clsname, bases, attrs, **meta_args):
        """
        Parser hooks allow the user to perform custom logic at certain stages of argument parsing. Supported parser
        hooks are, in order of execution:

        1. __after_parse__ : executed after argument parsing has been completed but before __call__ is executed
        """
        after_parse = attrs.get('__after_parse__', PASS)

        def set_parsed_attrs(self_, **parsed):
            for k, v in parsed.items():
                setattr(self_, k, v)

        def create_parser(self_, main):
            p = _default_parser(self_)
            for _, a in arguments(self_).items():
                a.add_to(p, parent=self_)
            p.add_argument('subcommand', action=_subcommand_action(commands(self_), main), nargs='?')

            def parser(*args):
                namespace, args = p.parse_known_args(args)
                parsed = vars(namespace)
                f = parsed.pop('subcommand')
                set_parsed_attrs(self_, **parsed)
                return f, parsed, args

            return parser

        def parse(self_, main, *args):
            parser = create_parser(self_, main)
            f, kwargs, args = parser(*args)
            after_parse(self_)
            return f, kwargs, args

        attrs['__parse__'] = parse
        return bases, attrs

    @classmethod
    def _create_call_method(mcs, clsname, bases, attrs, **meta_args):
        """
        The user should have defined a __call__ method. If they do not, a default help-text __call__ method is added.
        The preconditions for the execution of the __call__ method are:

        #. argument parsing has been completed
        #. all parsing hooks have been executed
        #. the relevant parsed arguments have been set on the commandclass instance

        Additionally, the user can define a __before_call__ method if they so choose. The default __before_call__ method
        will validate that any "required" arguments have values. Note that the __before_call__ hook will only be called
        on the leaf command, i.e. interim commands will not have their __before_call__ method called!
        """
        before_call = watch_method(attrs.get('__before_call__', _check_required_arguments))
        user_call = watch_method(attrs.get('__call__', PASS), show_all=True)  # N.B. log_level=DEBUG
        parse = attrs.get('__parse__', MISSING(message=f'{clsname} is missing a parse function!'))

        @functools.wraps(user_call)
        def call(self_, *args, **kwargs):
            """
            The __call__ method that will wrap the user specified __call__ method, if defined.

            :param self_:  the 'self' object
            :param args:   a tuple of unrecognized, i.e. "remaining", arguments leftover from the command line
            :param kwargs: a mapping of global, i.e. "parsed", arguments excluding those parsed by this commandclass
            """
            f, parsed, args = parse(self_, user_call, *args)
            if f is user_call:  # f is this commandclass's call operator
                # so we call the __before_call__ hook BEFORE calling "f", or in the case of --dryrun print statements
                # and note that we MUST pass self_ here since a user-defined __before_call__ will be unbound
                before_call(self_, *args, **kwargs)

                # --dryrun is effectively global since all commandclasses have it
                # so we must check both our own parsed arguments (which are attributes on self_) as well as the globals
                if self_.dryrun or kwargs.get('dryrun'):
                    out.show('args: ', out.jsonified(args, indent=None))
                    out.show('kwargs: ', out.jsonified(kwargs, indent=None))
                    out.show('self: ', out.jsonified(as_dict(self_), indent=None))
                    return

                # and note that we MUST pass self_ here since "f" is an unbound method!
                return f(self_, *args, **kwargs)
            else:  # f is a subcommand of this commandclass
                # 2020-08-11 WMR We must instantiate here at which point we KNOW that we have satisfied the
                # pre-condition discussed above circa L335 in `_subcommand_action`.
                return f().__call__(*args, **{**kwargs, **parsed})

        attrs['__call__'] = call
        return bases, attrs

    @staticmethod
    def is_argument(a):
        return isinstance(a, Argument)

    @staticmethod
    def is_commandclass(class_or_instance):
        cls = class_or_instance if isinstance(class_or_instance, type) else type(class_or_instance)
        return hasattr(cls, '__commandclasscheck__')

    @staticmethod
    def arguments(class_or_instance):
        if not Commandclass.is_commandclass(class_or_instance):
            raise TypeError(f'cannot call arguments(...) on non-commandclass type or instance: {class_or_instance!r}')
        return getattr(class_or_instance, '__arguments__', {})

    @staticmethod
    def commands(class_or_instance):
        if not Commandclass.is_commandclass(class_or_instance):
            raise TypeError(f'cannot call commands(...) on non-commandclass type or instance: {class_or_instance!r}')
        return getattr(class_or_instance, '__commands__', {})

    @staticmethod
    def has_command(class_or_instance, command_name):
        if not Commandclass.is_commandclass(class_or_instance):
            raise TypeError(f'cannot call has_command(...) on non-commandclass type or instance: {class_or_instance!r}')
        return command_name in commands(class_or_instance)


def is_argument(obj):
    return Commandclass.is_argument(obj)


def is_commandclass(class_or_instance):
    return Commandclass.is_commandclass(class_or_instance)


def arguments(class_or_instance):
    return Commandclass.arguments(class_or_instance)


def commands(class_or_instance):
    return Commandclass.commands(class_or_instance)


def get_argument(class_or_instance, name):
    return arguments(class_or_instance).get(name)


def get_command(class_or_instance, name):
    return commands(class_or_instance).get(name)


def commandclass(_cls=None, **kwargs):
    """dataclass-style decorator that constructs a command class from the given class spec."""

    def wrap(cls):
        return Commandclass(cls.__name__, cls.__bases__, dict(cls.__dict__), type=cls, **kwargs)

    if _cls is None:
        return wrap
    return wrap(_cls)


def make_commandclass(cls_name, args_or_cmds=(), *, call: callable = PASS, name: str = None, bases=(), namespace=None,
                      **kwargs):
    """Create a commandclass dynamically.

    The commandclass name will be 'cls_name'. 'args_or_cmds' is an iterable of either (name|Commandclass), (name, type)
    or (name, type, Argument|commandclass) objects. If type is omitted, str will be used. Argument objects are created
    by the equivalent of calling 'argument(...)' while commandclass objects are created by the equivalent of calling
    'commandclass(cls)'.

        C = make_commandclass('C', ['x',
                                    ('y', int),
                                    ('z', str, argument(default='foo'),
                                    ('foo', FooCommand)],
                              bases=(B,))

    is equivalent to:

        @commandclass(name='c')
        class C(B):
            x: str
            y: int
            z: str = argument(default='foo')

            foo = commandclass(FooCommand)

    For the 'bases' and 'namespace' parameters see the builtin 'type()' function. The 'namespace' parameter can be used
    to add subcommands.

        C = make_commandclass(..., namespace={'help': commandclass(HelpCommand)}

    The parameter 'name' will be passed to commandclass() if specified, else 'cls_name.lower()' will be used.
    """
    if namespace is None:
        namespace = {}
    else:
        namespace = namespace.copy()

    seen = set()
    anns = {}
    for i, e in enumerate(args_or_cmds):
        if isinstance(e, str):
            a_name = denormalize_name(e)
            tp = str
            namespace[a_name] = argument()
        elif is_commandclass(e):
            a_name = e.meta.name or raise_missing(message=f'{e!r} is missing a name attribute')
            a_name = denormalize_name(a_name)
            tp = e
        elif len(e) == 2:
            a_name, tp = e
            a_name = denormalize_name(a_name)
            if is_commandclass(tp):
                pass
            else:
                namespace[a_name] = argument(type=tp)
        elif len(e) == 3:
            a_name, tp, spec = e
            a_name = denormalize_name(a_name)
            if is_argument(spec):
                namespace[a_name] = spec
            else:
                raise ValueError(f'the spec for {a_name!r} must be an Argument')
        else:
            raise ValueError(
                'argument and command specs must be one of [str|Commandclass, (str, type|Argument|Commandclass), (str, type, Argument)]')

        if not isinstance(a_name, str) or not a_name.isidentifier():
            raise ValueError(f'{a_name!r} is not a valid identifier')
        if keyword.iskeyword(a_name):
            raise ValueError(f'{a_name!r} cannot be a keyword')
        if a_name in seen:
            raise ValueError(f'{a_name!r} is a duplicate')

        seen.add(a_name)
        if is_commandclass(tp):
            # command.
            namespace[a_name] = tp
        else:
            # argument.
            anns[a_name] = tp

    namespace['__annotations__'] = anns
    namespace['__call__'] = call
    cls = types.new_class(cls_name, bases, {}, lambda ns: ns.update(namespace))
    name = name or cls_name.lower()
    return commandclass(cls, name=name, **kwargs)


def add_to_commandclass(class_or_instance, **changes):
    """Make changes to an existing commandclass class or instance. Changes can only be argument or subcommand changes!

    Add an argument:
        add_to_commandclass(c, foo_arg=argument(help='this is the foo argument'))

    Add a subcommand:
        add_to_commandclass(c, bar_cmd=BarCommandclass)
    """
    if not is_commandclass(class_or_instance):
        raise TypeError(
            f'cannot call add_to_commandclass() on non-commandclass type or instance: {type(class_or_instance).__name__}')

    args = {a_name: a for a_name, a in arguments(class_or_instance).items()}
    cmds = {c_name: c for c_name, c in commands(class_or_instance).items()}

    for a_name, a in changes.items():
        if is_argument(a):
            a.name = a.name or a_name
            args[denormalize_name(a_name)] = a
            setattr(class_or_instance, a_name, None)  # so we don't AttributeError when we as_dict(...)
        elif is_commandclass(a):
            a.meta.name = a.meta.name or a_name
            cmds[normalize_name(a_name)] = a
        else:
            raise TypeError(f'cannot call add_to_commandclass() with non-(argument,subcommand) changes: {a_name}')

    setattr(class_or_instance, '__arguments__', args)
    setattr(class_or_instance, '__commands__', cmds)


def as_dict(instance):
    return {a_name: getattr(instance, a_name) for a_name, _ in arguments(instance).items()}
