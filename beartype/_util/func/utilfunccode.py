#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2023 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable source code** (i.e., file providing the uncompiled
pure-Python source code from which a compiled callable originated) utilities.

This private submodule implements supplementary callable-specific utility
functions required by various :mod:`beartype` facilities, including callables
generated by the :func:`beartype.beartype` decorator.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: *FILE UPSTREAM CPYTHON ISSUES.* Unfortunately, this submodule exposed a
#number of significant issues in the CPython stdlib -- all concerning parsing
#of lambda functions. These include:
#
#1. The inspect.getsourcelines() function raises unexpected
#   "tokenize.TokenError" exceptions when passed lambda functions preceded by
#   one or more triple-quoted strings: e.g.,
#       >>> import inspect
#       >>> built_to_fail = (
#       ...     ('''Uh-oh.
#       ... ''', lambda obj: 'Oh, Gods above and/or below!'
#       ...     )
#       ... )
#       >>> inspect.getsourcelines(built_to_fail[1])}
#       tokenize.TokenError: ('EOF in multi-line string', (323, 8))
#2. The "func.__code__.co_firstlineno" attribute is incorrect for syntactic
#   constructs resembling:
#       assert is_hint_pep593_beartype(Annotated[        # <--- line 1
#           str, Is[lambda text: bool(text)]]) is True   # <--- line 2
#   Given such a construct, the nested lambda function should have a
#   "func.__code__.co_firstlineno" attribute whose value is "2". Instead, that
#   attribute's value is "1". This then complicates detection of lambda
#   functions, which are already non-trivial enough to detect. Specifically,
#   this causes the inspect.findsource() function to either raise an unexpected
#   "OSError" *OR* return incorrect source when passed a file containing the
#   above snippet. In either case, that is bad. *sigh*
#3. Introspecting the source code for two or more lambdas defined on the same
#   line is infeasible, because code objects only record line numbers rather
#   than both line and column numbers. Well, that's unfortunate.
#   ^--- Actually, we're *PRETTY* sure that Python 3.11 has finally resolved
#        this by now recording column numbers with code objects. So, let's
#        improve the logic below to handle this edge case under Python >= 3.11.
#FIXME: Contribute get_func_code_or_none() back to this StackOverflow question
#as a new answer, as this is highly non-trivial, frankly:
#    https://stackoverflow.com/questions/59498679/how-can-i-get-exactly-the-code-of-a-lambda-function-in-python/64421174#64421174

# ....................{ IMPORTS                           }....................
from ast import (
    NodeVisitor,
    parse as ast_parse,
)
from beartype.roar._roarwarn import _BeartypeUtilCallableWarning
from beartype.typing import (
    List,
    Optional,
)
from beartype._data.datatyping import TypeWarning
from beartype._util.func.utilfunccodeobj import get_func_codeobj
from beartype._util.py.utilpyversion import IS_PYTHON_AT_LEAST_3_9
from collections.abc import Callable
from inspect import findsource, getsource
from traceback import format_exc
from warnings import warn

# ....................{ GETTERS ~ code : lines             }....................
#FIXME: Unit test us up.
def get_func_code_lines_or_none(
    # Mandatory parameters.
    func: Callable,

    # Optional parameters.
    warning_cls: TypeWarning = _BeartypeUtilCallableWarning,
) -> Optional[str]:
    '''
    **Line-oriented callable source code** (i.e., string concatenating the
    subset of all lines of the on-disk Python script or module declaring the
    passed pure-Python callable) if that callable was declared on-disk *or*
    ``None`` otherwise (i.e., if that callable was dynamically declared
    in-memory).

    Caveats
    ----------
    **The higher-level** :func:`get_func_code_or_none` **getter should
    typically be called instead.** Why? Because this lower-level getter
    inexactly returns all lines embedding the declaration of the passed
    callable rather than the exact substring of those lines declaring that
    callable. Although typically identical for non-lambda functions, those two
    strings typically differ for lambda functions. Lambda functions are
    expressions embedded in larger statements rather than full statements.

    **This getter is excruciatingly slow.** See the
    :func:`get_func_code_or_none` getter for further commentary.

    Parameters
    ----------
    func : Callable
        Callable to be inspected.
    warning_cls : TypeWarning, optional
        Type of warning to be emitted in the event of a non-fatal error.
        Defaults to :class:`_BeartypeUtilCallableWarning`.

    Returns
    ----------
    Optional[str]
        Either:

        * If the passed callable was physically declared by a file, a string
          concatenating the subset of lines of that file declaring that
          callable.
        * If the passed callable was dynamically declared in-memory, ``None``.

    Warns
    ----------
    :class:`warning_cls`
         If the passed callable is defined by a pure-Python source code file
         but is *not* parsable from that file. While we could allow any parser
         exception to percolate up the call stack and halt the active Python
         process when left unhandled, doing so would render :mod:`beartype`
         fragile -- gaining us little and costing us much.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfuncfile import is_func_file
    from beartype._util.text.utiltextprefix import prefix_callable

    # If the passed callable exists on-disk and is thus pure-Python...
    if is_func_file(func):
        # Attempt to defer to the standard inspect.getsource() function.
        try:
            return getsource(func)
        # If that function raised *ANY* exception, reduce that exception to a
        # non-fatal warning.
        except Exception:
            # Reduce this fatal error to a non-fatal warning embedding a full
            # exception traceback as a formatted string.
            warn(
                f'{prefix_callable(func)}not parsable:\n{format_exc()}',
                warning_cls,
            )
    # Else, the passed callable only exists in-memory.

    # Return "None" as a fallback.
    return None


#FIXME: Unit test us up.
def get_func_file_code_lines_or_none(
    # Mandatory parameters.
    func: Callable,

    # Optional parameters.
    warning_cls: TypeWarning = _BeartypeUtilCallableWarning,
) -> Optional[str]:
    '''
    **Line-oriented callable source file code** (i.e., string concatenating
    *all* lines of the on-disk Python script or module declaring the passed
    pure-Python callable) if that callable was declared on-disk *or* ``None``
    otherwise (i.e., if that callable was dynamically declared in-memory).

    Caveats
    ----------
    **This getter is excruciatingly slow.** See the
    :func:`get_func_code_or_none` getter for further commentary.

    Parameters
    ----------
    func : Callable
        Callable to be inspected.
    warning_cls : TypeWarning, optional
        Type of warning to be emitted in the event of a non-fatal error.
        Defaults to :class:`_BeartypeUtilCallableWarning`.

    Returns
    ----------
    Optional[str]
        Either:

        * If the passed callable was physically declared by an file, a string
          concatenating *all* lines of that file.
        * If the passed callable was dynamically declared in-memory, ``None``.

    Warns
    ----------
    :class:`warning_cls`
         If the passed callable is defined by a pure-Python source code file
         but is *not* parsable from that file. While we could allow any parser
         exception to percolate up the call stack and halt the active Python
         process when left unhandled, doing so would render :mod:`beartype`
         fragile -- gaining us little and costing us much.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfuncfile import is_func_file
    from beartype._util.text.utiltextprefix import prefix_callable

    # If the passed callable exists on-disk and is thus pure-Python...
    if is_func_file(func):
        # Attempt to defer to the standard inspect.findsource() function, which
        # returns a 2-tuple "(file_code_lines, file_code_lineno_start)", where:
        # * "file_code_lines" is a list of all lines of the script or module
        #    declaring the passed callable.
        # * "file_code_lineno_start" is the line number of the first such line
        #   declaring the passed callable. Since this line number is already
        #   provided by the "co_firstlineno" instance variable of this
        #   callable's code object, however, there is *NO* reason whatsoever to
        #   return this line number. Indeed, it's unclear why that function
        #   returns this uselessly redundant metadata in the first place.
        try:
            # List of all lines of the file declaring the passed callable.
            func_file_code_lines, _ = findsource(func)

            # Return this list concatenated into a string.
            return ''.join(func_file_code_lines)
        # If that function raised *ANY* exception, reduce that exception to a
        # non-fatal warning. While we could permit this exception to percolate
        # up the call stack and inevitably halt the active Python process when
        # left unhandled, doing so would render @beartype fragile -- gaining us
        # little and costing us much.
        #
        # Notably, the lower-level inspect.getblock() function internally
        # called by the higher-level findsource() function prematurely halted
        # due to an unexpected bug in the pure-Python tokenizer leveraged by
        # inspect.getblock(). Notably, this occurs when passing lambda
        # functions preceded by triple-quoted strings: e.g.,
        #     >>> import inspect
        #     >>> built_to_fail = (
        #     ...     ('''Uh-oh.
        #     ... ''', lambda obj: 'Oh, Gods above and/or below!'
        #     ...     )
        #     ... )
        #     >>> inspect.findsource(built_to_fail[1])}
        #     tokenize.TokenError: ('EOF in multi-line string', (323, 8))
        except Exception:
            # Reduce this fatal error to a non-fatal warning embedding a full
            # exception traceback as a formatted string.
            warn(
                f'{prefix_callable(func)}not parsable:\n{format_exc()}',
                warning_cls,
            )
    # Else, the passed callable only exists in-memory.

    # Return "None" as a fallback.
    return None

# ....................{ GETTERS ~ code : lambda            }....................
# If the active Python interpreter targets Python >= 3.9 and thus defines the
# ast.unparse() function required to decompile AST nodes into source code,
# define the get_func_code_or_none() getter to get only the exact source code
# substring defining a passed lambda function rather than the inexact
# concatenation of all source code lines embedding that definition.
if IS_PYTHON_AT_LEAST_3_9:
    # Defer version-specific imports.
    from ast import unparse as ast_unparse  # type: ignore[attr-defined]


    _LAMBDA_CODE_FILESIZE_MAX = 1000000
    '''
    Maximum size (in bytes) of files to be safely parsed for lambda function
    declarations by the :func:`get_func_code_or_none` getter.
    '''


    def get_func_code_or_none(
        # Mandatory parameters.
        func: Callable,

        # Optional parameters.
        warning_cls: TypeWarning = _BeartypeUtilCallableWarning,
    ) -> Optional[str]:

        # Avoid circular import dependencies.
        from beartype._util.func.utilfunctest import is_func_lambda
        from beartype._util.text.utiltextprefix import prefix_callable

        # If the passed callable is a pure-Python lambda function...
        if is_func_lambda(func):
            # Attempt to parse the substring of the source code defining this
            # lambda from the file providing that code.
            #
            # For safety, this function reduces *ALL* exceptions raised by this
            # introspection to non-fatal warnings and returns "None". Why?
            # Because the standard "ast" module in general and our
            # "_LambdaNodeUnparser" class in specific are sufficiently fragile
            # as to warrant extreme caution. AST parsing and unparsing is
            # notoriously unreliable across different versions of different
            # Python interpreters and compilers.
            #
            # Moreover, we *NEVER* call this function in a critical code path;
            # we *ONLY* call this function to construct human-readable
            # exception messages. Clearly, raising low-level non-human-readable
            # exceptions when attempting to raise high-level human-readable
            # exceptions rather defeats the entire purpose of the latter.
            #
            # Lastly, note that "pytest" will still fail any tests emitting
            # unexpected warnings. In short, raising exceptions here would gain
            # @beartype little and cost @beartype much.
            try:
                # String concatenating all lines of the file defining that
                # lambda if that lambda is defined by a file *OR* "None".
                lambda_file_code = get_func_file_code_lines_or_none(
                    func=func, warning_cls=warning_cls)

                # If that lambda is defined by a file...
                if lambda_file_code:
                    # Code object underlying this lambda.
                    func_codeobj = get_func_codeobj(func)

                    # If this file exceeds a sane maximum file size, emit a
                    # non-fatal warning and safely ignore this file.
                    if len(lambda_file_code) >= _LAMBDA_CODE_FILESIZE_MAX:
                        warn(
                            (
                                f'{prefix_callable(func)}not parsable, '
                                f'as file size exceeds safe maximum '
                                f'{_LAMBDA_CODE_FILESIZE_MAX}MB.'
                            ),
                            warning_cls,
                        )
                    # Else, this file *SHOULD* be safely parsable by the
                    # standard "ast" module without inducing a fatal
                    # segmentation fault.
                    else:
                        # Abstract syntax tree (AST) parsed from this file.
                        ast_tree = ast_parse(lambda_file_code)

                        # Lambda node unparser decompiling all AST lambda nodes
                        # encapsulating lambda functions starting at the same
                        # line number as the passed lambda in this file.
                        lambda_node_unparser = _LambdaNodeUnparser(
                            lambda_lineno=func_codeobj.co_firstlineno)

                        # Perform this decompilation.
                        lambda_node_unparser.visit(ast_tree)

                        # List of each code substring exactly covering each
                        # lambda function starting at that line number.
                        lambdas_code = lambda_node_unparser.lambdas_code

                        # If one or more lambda functions start at that line
                        # number...
                        if lambdas_code:
                            # If two or more lambda functions start at that
                            # line number, emit a non-fatal warning. Since
                            # lambda functions only provide a starting line
                            # number rather than both starting line number
                            # *AND* column, we have *NO* means of
                            # disambiguating between these lambda functions and
                            # thus *CANNOT* raise an exception.
                            if len(lambdas_code) >= 2:
                                # Human-readable concatenation of the
                                # definitions of all lambda functions defined
                                # on that line.
                                lambdas_code_str = '\n    '.join(lambdas_code)

                                # Emit this warning.
                                warn(
                                    (
                                        f'{prefix_callable(func)}ambiguous, '
                                        f'as that line defines '
                                        f'{len(lambdas_code)} lambdas; '
                                        f'arbitrarily selecting first '
                                        f'lambda:\n{lambdas_code_str}'
                                    ),
                                    warning_cls,
                                )
                            # Else, that line number defines one lambda.

                            # Return the substring covering that lambda.
                            return lambdas_code[0]
                        # Else, *NO* lambda functions start at that line
                        # number. In this case, emit a non-fatal warning.
                        #
                        # Ideally, we would instead raise a fatal exception.
                        # Why? Because this edge case violates expectations.
                        # Since the passed lambda function claims it originates
                        # from some line number of some file *AND* since that
                        # file both exists and is parsable as valid Python, we
                        # expect that line number to define one or more lambda
                        # functions. If it does not, raising an exception seems
                        # superficially reasonable. Yet, we don't. See above.
                        else:
                            warn(
                                f'{prefix_callable(func)}not found.',
                                warning_cls,
                            )
                # Else, that lambda is dynamically defined in-memory.
            # If *ANY* of the dodgy stdlib callables (e.g., ast.parse(),
            # inspect.findsource()) called above raise *ANY* other unexpected
            # exception, reduce this fatal error to a non-fatal warning with an
            # exception traceback as a formatted string.
            #
            # Note that the likeliest (but certainly *NOT* only) type of
            # exception to be raised is a "RecursionError", as described by the
            # official documentation for the ast.unparse() function:
            #     Warning: Trying to unparse a highly complex expression would
            #     result with RecursionError.
            except Exception:
                warn(
                    f'{prefix_callable(func)}not parsable:\n{format_exc()}',
                    warning_cls,
                )
        # Else, the passed callable is *NOT* a pure-Python lambda function.

        # In any case, the above logic failed to introspect code for the passed
        # callable. Defer to the get_func_code_lines_or_none() function.
        return get_func_code_lines_or_none(func=func, warning_cls=warning_cls)


    # Helper class instantiated above to decompile AST lambda nodes.
    class _LambdaNodeUnparser(NodeVisitor):
        '''
        **Lambda node unparser** (i.e., object decompiling the abstract syntax
        tree (AST) nodes of *all* pure-Python lambda functions defined in a
        caller-specified block of source code into the exact substrings of that
        block defining those lambda functions by applying the visitor design
        pattern to an AST parsed from that block).

        Attributes
        ----------
        lambdas_code : List[str]
            List of one or more **source code substrings** (i.e., of one or
            more lines of code) defining each of the one or more lambda
            functions starting at line :attr:`_lambda_lineno` of the code from
            which the AST visited by this visitor was parsed.
        _lambda_lineno : int
            Caller-requested line number (of the code from which the AST
            visited by this object was parsed) starting the definition of the
            lambda functions to be unparsed by this visitor.
        '''

        # ................{ INITIALIZERS                      }................
        def __init__(self, lambda_lineno: int) -> None:
            '''
            Initialize this visitor.

            Parameters
            ----------
            lambda_lineno : int
                Caller-specific line number (of the code from which the AST
                visited by this object was parsed) starting the definition of
                the lambda functions to be unparsed by this visitor.
            '''
            assert isinstance(lambda_lineno, int), (
                f'{repr(lambda_lineno)} not integer.')
            assert lambda_lineno >= 0, f'{lambda_lineno} < 0.'

            # Initialize our superclass.
            super().__init__()

            # Classify all passed parameters.
            self._lambda_lineno = lambda_lineno

            # Initialize all remaining instance variables.
            self.lambdas_code: List[str] = []


        def visit_Lambda(self, node):
            '''
            Visit (i.e., handle, process) the passed AST node encapsulating the
            definition of a lambda function (parsed from the code from which
            the AST visited by this visitor was parsed) *and*, if that lambda
            starts on the caller-requested line number, decompile this node
            back into the substring of this line defining that lambda.

            Parameters
            ----------
            node : LambdaNode
                AST node encapsulating the definition of a lambda function.
            '''

            # If the desired lambda starts on the current line number...
            if node.lineno == self._lambda_lineno:
                # Decompile this node into the substring of this line defining
                # this lambda.
                self.lambdas_code.append(ast_unparse(node))

                # Recursively visit all child nodes of this lambda node. While
                # doing so is largely useless, a sufficient number of dragons
                # are skulking to warrant an abundance of caution and magic.
                self.generic_visit(node)
            # Else if the desired lambda starts on a later line number than
            # the current line number, recursively visit all child nodes of
            # the current lambda node.
            elif node.lineno < self._lambda_lineno:
                self.generic_visit(node)
            #FIXME: Consider raising an exception here instead like
            #"StopException" to force a premature halt to this recursion. Of
            #course, handling exceptions also incurs a performance cost, so...
            # Else, the desired lambda starts on an earlier line number than
            # the current line number, the current lambda *CANNOT* be the
            # desired lambda and is thus ignorable. In this case, avoid
            # recursively visiting *ANY* child nodes of the current lambda node
            # to induce a premature halt to this recursive visitation.
# Else, the active Python interpreter targets only Python < 3.9 and thus does
# *NOT* define the ast.unparse() function required to decompile AST nodes into
# source code. In this case...
else:
    def get_func_code_or_none(
        # Mandatory parameters.
        func: Callable,

        # Optional parameters.
        warning_cls: TypeWarning = _BeartypeUtilCallableWarning,
    ) -> Optional[str]:

        # Defer to the get_func_code_lines_or_none() function as is.
        return get_func_code_lines_or_none(func=func, warning_cls=warning_cls)


get_func_code_or_none.__doc__ = '''
**Callable source code** (i.e., substring of all lines of the on-disk Python
script or module declaring the passed pure-Python callable) if that callable
was declared on-disk *or* ``None`` otherwise (i.e., if that callable was
dynamically declared in-memory).

Specifically, this getter returns:

* If the passed callable is a lambda function *and* active Python interpreter
  targets Python >= 3.9 (and thus defines the ast.unparse() function required
  to decompile AST lambda nodes into original source code), the exact substring
  of that code declaring that lambda function.
* Else, the concatenation of all lines of that code declaring that callable.

Caveats
----------
**This getter is excruciatingly slow.** This getter should *only* be called
when unavoidable and ideally *only* in performance-agnostic code paths.
Notably, this getter finds relevant lines by parsing the script or module
declaring the passed callable starting at the first line of that declaration
and continuing until a rudimentary tokenizer implemented in pure-Python (with
*no* concern for optimization and thus slow beyond all understanding of slow)
detects the last line of that declaration. In theory, we could significantly
optimize that routine; in practice, anyone who cares will preferably compile or
JIT :mod:`beartype` instead.

Parameters
----------
func : Callable
    Callable to be inspected.
warning_cls : TypeWarning, optional
    Type of warning to be emitted in the event of a non-fatal error. Defaults
    to :class:`_BeartypeUtilCallableWarning`.

Returns
----------
Optional[str]
    Either:

    * If the passed callable was physically declared by a file, the exact
      substring of all lines of that file declaring that callable.
    * If the passed callable was dynamically declared in-memory, ``None``.

Warns
----------
:class:`warning_cls`
    If the passed callable is a pure-Python lambda function that was physically
    declared by either:

    * A large file exceeding a sane maximum file size (e.g., 1MB). Note that:

      * If this is *not* explicitly guarded against, passing absurdly long
        strings to the :func:`ast.parse` function can actually induce a
        segmentation fault in the active Python process. This is a longstanding
        and unresolved issue in the :mod:`ast` module. See also:
        https://bugs.python.org/issue32758
      * Generously assuming each line of that file contains between
        40 to 80 characters, this maximum supports files of between 12,500 to
        25,000 lines, which at even the lower end of that range covers most
        real-world files of interest.

    * A complex (but *not* necessarily large) file causing the recursive
      :func:`ast.parse` or :func:`ast.unparse` function or any other :mod:`ast`
      callable to exceed Python's recursion limit by exhausting the stack.
    * A line of source code declaring two or more lambda functions (e.g.,
      ``lambdas = lambda: 'and black,', lambda: 'and pale,'``). In this case,
      the substring of code declaring the first such function is ambiguously
      returned; all subsequent such functions are unavoidably ignored.

See Also
----------
https://stackoverflow.com/questions/59498679/how-can-i-get-exactly-the-code-of-a-lambda-function-in-python/64421174#64421174
    StackOverflow answer strongly inspiring this implementation.
'''

# ....................{ GETTERS ~ label                    }....................
#FIXME: This getter no longer has a sane reason to exist. Consider excising.
# from beartype.roar._roarexc import _BeartypeUtilCallableException
# from beartype._cave._cavefast import CallableTypes
# from sys import modules
#
# def get_func_code_label(func: Callable) -> str:
#     '''
#     Human-readable label describing the **origin** (i.e., uncompiled source) of
#     the passed callable.
#
#     Specifically, this getter returns either:
#
#     * If that callable is pure-Python *and* physically declared on-disk, the
#       absolute filename of the uncompiled on-disk Python script or module
#       physically declaring that callable.
#     * If that callable is pure-Python *and* dynamically declared in-memory,
#       the placeholder string ``"<string>"``.
#     * If that callable is C-based, the placeholder string ``"<C-based>"``.
#
#     Caveats
#     ----------
#     **This getter is intentionally implemented for speed rather than robustness
#     against unlikely edge cases.** The string returned by this getter is *only*
#     intended to be embedded in human-readable labels, warnings, and exceptions.
#     Avoid using this string for *any* mission-critical purpose.
#
#     Parameters
#     ----------
#     func : Callable
#         Callable to be inspected.
#
#     Returns
#     ----------
#     str
#         Either:
#
#         * If that callable is physically declared by an uncompiled Python
#           script or module, the absolute filename of this script or module.
#         * Else, the placeholder string ``"<string>"`` implying that callable to
#           have been dynamically declared in-memory.
#
#     Raises
#     ------
#     _BeartypeUtilCallableException
#         If that callable is *not* callable.
#
#     See Also
#     ----------
#     :func:`inspect.getsourcefile`
#         Inefficient stdlib function strongly inspiring this implementation,
#         which has been highly optimized for use by the performance-sensitive
#         :func:`beartype.beartype` decorator.
#     '''
#
#     # If this callable is uncallable, raise an exception.
#     if not callable(func):
#         raise _BeartypeUtilCallableException(f'{repr(func)} not callable.')
#     # Else, this callable is callable.
#
#     # Human-readable label describing the origin of the passed callable.
#     func_origin_label = '<string>'
#
#     # If this callable is a standard callable rather than arbitrary class or
#     # object overriding the __call__() dunder method...
#     if isinstance(func, CallableTypes):
#         # Avoid circular import dependencies.
#         from beartype._util.func.utilfuncfile import get_func_filename_or_none
#         from beartype._util.func.utilfuncwrap import unwrap_func
#
#         # Code object underlying the passed pure-Python callable unwrapped if
#         # this callable is pure-Python *OR* "None" otherwise.
#         func_filename = get_func_filename_or_none(unwrap_func(func))
#
#         # If this callable has a code object, set this label to either the
#         # absolute filename of the physical Python module or script declaring
#         # this callable if this code object provides that metadata *OR* a
#         # placeholder string specific to C-based callables otherwise.
#         func_origin_label = func_filename if func_filename else '<C-based>'
#     # Else, this callable is *NOT* a standard callable. In this case...
#     else:
#         # If this callable is *NOT* a class (i.e., is an object defining the
#         # __call__() method), reduce this callable to the class of this object.
#         if not isinstance(func, type):
#             func = type(func)
#         # In either case, this callable is now a class.
#
#         # Fully-qualified name of the module declaring this class if this class
#         # was physically declared by an on-disk module *OR* "None" otherwise.
#         func_module_name = func.__module__
#
#         # If this class was physically declared by an on-disk module, defer to
#         # the absolute filename of that module.
#         #
#         # Note that arbitrary modules need *NOT* declare the "__file__" dunder
#         # attribute. Unlike most other core Python objects, modules are simply
#         # arbitrary objects that reside in the "sys.modules" dictionary.
#         if func_module_name:
#             func_origin_label = getattr(
#                 modules[func_module_name], '__file__', func_origin_label)
#
#     # Return this label.
#     return func_origin_label
