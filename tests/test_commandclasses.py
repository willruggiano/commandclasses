import io
import re
import unittest
from contextlib import redirect_stderr

from commandclasses import (Argument, InvalidArgumentException,
                            add_to_commandclass, argument, arguments, as_dict,
                            commandclass, commands, make_commandclass)


def strip_ansi_color(s):
    return re.sub('\x1b\\[(K|.*?m)', '', s)


@commandclass
class FooCommand:
    foo: str = argument()

    def __call__(self, *args, **kwargs):
        return self.foo


def required_f(self_):
    return self_.required == 'required_when'


def illegal_f(self_):
    return self_.required == 'illegal_when'


@commandclass
class SuperUsefulCommand:
    # also tests (list,tuple)-specific action property:
    aliases: list = argument(aliases=('-a', ), help='test aliases')
    choice_help_formatter: str = argument(
        choices_help_formatter=lambda _: 'choice_help_formatter',
        help='test choices_help_formatter')
    default: str = argument(default='default', help='test default')
    default_factory: str = argument(
        default_factory=lambda _: 'default_factory',
        help='test default_factory')
    default_factory_falsey: str = argument(default_factory=lambda _: None,
                                           help='test default_factory_falsey')
    required: str = argument(required=True, help='test required')
    required_when: bool = argument(required_when=required_f,
                                   help='test required_when')
    illegal_when: bool = argument(illegal_when=illegal_f,
                                  help='test illegal_when')
    # also tests bool-specific action property:
    show_help: bool = argument(show_help=False, help='test show_help')
    type_converter: str = argument(type_converter=str.upper,
                                   help='test type_converted')

    sub = FooCommand

    after_parse = False

    def __after_parse__(self):
        self.after_parse = True

    def __call__(self, *args, **kwargs):
        return as_dict(self)


class TestDecorator(unittest.TestCase):
    def test_arguments(self):
        actual = arguments(SuperUsefulCommand)
        expected = {
            'dryrun':
            Argument(default=None, help='echo input to stdout and exit'),
            'aliases':
            Argument(default=None, help='test aliases', aliases_=('-a', )),
            'choice_help_formatter':
            Argument(default=None, help='test choices_help_formatter'),
            'default':
            Argument(default='default', help='test default'),
            'default_factory':
            Argument(default=None, help='test default_factory'),
            'default_factory_falsey':
            Argument(help='test default_factory_falsey'),
            'required':
            Argument(default=None, help='test required', required_=True),
            'required_when':
            Argument(default=None,
                     help='test required_when',
                     required_when_=required_f),
            'illegal_when':
            Argument(default=None,
                     help='test illegal_when',
                     illegal_when_=illegal_f),
            'show_help':
            Argument(default=None, help='test show_help', show_help_=False),
            'type_converter':
            Argument(default=None, help='test type_converted')
        }
        self.maxDiff = None
        self.assertDictEqual(actual, expected)

    def test_commands(self):
        actual = commands(SuperUsefulCommand)
        self.assertDictEqual(actual, {'sub': FooCommand})

    def test_parser_hooks(self):
        cmd = SuperUsefulCommand()
        cmd('--required', 'ignored')
        self.assertTrue(cmd.after_parse, 'after_parse != True')

    def test_call_wellformed(self):
        cmd = SuperUsefulCommand()
        actual = cmd('-a', 'a0', '-a', 'a1', '--required', 'req',
                     '--type-converter', 'upper')
        self.assertDictEqual(
            actual,
            dict(aliases=['a0', 'a1'],
                 choice_help_formatter=None,
                 default='default',
                 default_factory='default_factory',
                 default_factory_falsey=None,
                 dryrun=None,
                 required='req',
                 required_when=None,
                 illegal_when=None,
                 show_help=None,
                 type_converter='UPPER'))

    def test_call_arguments_with_requirements(self):
        # test explicitly required arguments
        self.assertRaises(InvalidArgumentException,
                          lambda: SuperUsefulCommand()())
        # test implicitly required arguments (i.e. arguments using required_when predicates)
        self.assertRaises(
            InvalidArgumentException, lambda: SuperUsefulCommand()
            ('--required', 'required_when'))
        # test illegal arguments
        self.assertRaises(
            InvalidArgumentException, lambda: SuperUsefulCommand()
            ('--illegal-when', '--required', 'illegal_when'))


def call_return_as_dict(self_, *args, **kwargs):
    return as_dict(self_)


class TestMakeCommandclass(unittest.TestCase):
    def test_make_commandclass_arguments(self):
        cc = make_commandclass(
            'TestCommand',
            ['a', ('b', int), ('c', str, argument(default='c'))],
            call=call_return_as_dict,
            name='test')
        instance = cc()
        rv = instance('--a', 'a', '--b', '1')
        self.assertEqual('test', instance.meta.name)
        self.assertDictEqual({'a': 'a', 'b': 1, 'c': 'c', 'dryrun': None}, rv)

    def test_make_commandclass_commands(self):
        cc = make_commandclass('TestCommand', [('foo', FooCommand)],
                               call=call_return_as_dict,
                               name='test')
        cmd = cc()
        actual = cmd('foo', '--foo', 'bar')
        self.assertEqual('bar', actual)

    def test_validation(self):
        # check that the third element of three-tuple specs are of type Argument
        def three_tuple_non_argument():
            cc = make_commandclass('TestCommand', [('foo', str, object)],
                                   call=call_return_as_dict,
                                   name='test')
            return cc()

        self.assertRaises(ValueError, three_tuple_non_argument)

        # check that arg/command tuples are a valid combination
        def invalid_arg_cmd_spec():
            cc = make_commandclass('TestCommand', [('foo', str, object, type)],
                                   call=call_return_as_dict,
                                   name='test')
            return cc()

        self.assertRaises(ValueError, invalid_arg_cmd_spec)

        # check that names must not be identifiers or keywords
        def identifier_name():
            cc = make_commandclass('TestCommand', ['%s'],
                                   call=call_return_as_dict,
                                   name='test')
            return cc()

        self.assertRaises(ValueError, identifier_name)

        def keyword_name():
            cc = make_commandclass('TestCommand', ['False'],
                                   call=call_return_as_dict,
                                   name='test')
            return cc()

        self.assertRaises(ValueError, keyword_name)

        # check for duplicates
        def duplicate():
            cc = make_commandclass('TestCommand', ['foo', 'foo'],
                                   call=call_return_as_dict,
                                   name='test')
            return cc()

        self.assertRaises(ValueError, duplicate)


@commandclass
class EmptyCommand:
    __call__ = call_return_as_dict


class TestAddToCommandclass(unittest.TestCase):
    def test_add_argument(self):
        add_to_commandclass(EmptyCommand, foo=argument())
        self.assertIn('foo', arguments(EmptyCommand))

    def test_add_command(self):
        add_to_commandclass(EmptyCommand, foo=FooCommand)
        self.assertIn('foo', commands(EmptyCommand))

    def test_validation(self):
        # check that add_to_commandclass can only be called on commandclass objects
        o = object()

        def add_to_non_commandclass():
            add_to_commandclass(o, foo=argument())

        self.assertRaises(TypeError, add_to_non_commandclass)

        # check that add_to_commandclass can only add arguments or subcommands
        def make_arbitrary_change():
            add_to_commandclass(EmptyCommand, foo='bar')

        self.assertRaises(TypeError, make_arbitrary_change)


class TestAsDict(unittest.TestCase):
    def test_before_parse(self):
        self.assertDictEqual(as_dict(FooCommand), {
            'foo': None,
            'dryrun': None
        })

    def test_after_parse(self):
        instance = FooCommand()
        instance('--foo', 'bar')
        self.assertDictEqual(as_dict(instance), {'foo': 'bar', 'dryrun': None})


class TestAssortedFeatures(unittest.TestCase):
    def test_suggestions(self):
        f = io.StringIO()
        with redirect_stderr(f):
            cmd = make_commandclass('TestCommand', (FooCommand, ))()
            try:
                cmd('foocmmand')  # almost foocommand
            except:
                pass
        actual = strip_ansi_color(f.getvalue().strip())
        self.assertIn(
            "Unknown choice 'foocmmand'. Perhaps you meant one of: ['foocommand']?",
            actual)
