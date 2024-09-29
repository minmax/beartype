#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2024 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) transformers** (i.e., low-level classes
instrumenting well-typed third-party modules with runtime type-checking
dynamically generated by the :func:`beartype.beartype` decorator).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
# FIXME: [PEP 484] Additionally define:
# * Generator transformers. The idea here is that @beartype *CAN* actually
#  automatically type-check generator yields, sends, and returns at runtime.
#  How? By automatically injecting appropriate die_if_unbearable() calls
#  type-checking the values to be yielded, sent, and returned against the
#  appropriate type hints of the current generator factory *BEFORE* yielding,
#  sending, and returning those values. Shockingly, typeguard already does this
#  -- which is all manner of impressive. See the
#  TypeguardTransformer._use_memo() context manager for working code. Wow!
#
# See also:
#    https://github.com/agronholm/typeguard/blob/master/src/typeguard/_transformer.py

# FIXME: [SPEED] Consider generalizing the BeartypeNodeTransformer.__new__()
# class method to internally cache and return "BeartypeNodeTransformer" instances
# depending on the passed "conf_beartype" parameter. In general, most codebases
# will only leverage a single @beartype configuration (if any @beartype
# configuration at all); ergo, caching improves everything by enabling us to
# reuse the same "BeartypeNodeTransformer" instance for every hooked module.
# Score @beartype!
#
# See the BeartypeConf.__new__() method for relevant logic. \o/
# FIXME: Oh, wait. We probably do *NOT* want to cache -- at least, not without
# defining a comparable reinit() method as we do for "BeartypeDecorMeta". After
# retrieving a cached "BeartypeNodeTransformer" instance, we'll need to
# immediately call BeartypeNodeTransformer.reinit() to reinitialize that
# instance.
#
# This is all feasible, of course -- but let's just roll with the naive
# implementation for now, please.

# ....................{ IMPORTS                            }....................
from ast import (
    AST,
    ClassDef,
    Constant,
    Expr,
    ImportFrom,
    Module,
    NodeTransformer,
)

from beartype._conf.confcls import BeartypeConf
from beartype._data.ast.dataast import TYPES_NODE_LEXICAL_SCOPE
from beartype._data.hint.datahinttyping import (
    NodeCallable,
    NodeT,
)
from beartype._util.ast.utilastmake import make_node_importfrom
from beartype._util.ast.utilasttest import is_node_callable_typed
from beartype.claw._ast._clawastutil import BeartypeNodeTransformerUtilityMixin
from beartype.claw._ast.pep.clawastpep526 import BeartypeNodeTransformerPep526Mixin
from beartype.claw._ast.pep.clawastpep695 import BeartypeNodeTransformerPep695Mixin
from beartype.typing import (
    List,
    Optional,
    Type,
)

# ....................{ SUBCLASSES                         }....................
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: To improve forward compatibility with the superclass API over which
# we have *NO* control, avoid accidental conflicts by suffixing *ALL* private
# and public attributes of this subclass by "_beartype".
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

# FIXME: Unit test us up, please.
class BeartypeNodeTransformer(
    # PEP-agnostic superclass defining "core" AST node transformation logic.
    NodeTransformer,

    # PEP-agnostic mixins defining supplementary AST node functionality in a
    # PEP-agnostic manner.
    BeartypeNodeTransformerUtilityMixin,

    # PEP-specific mixins defining additional AST node transformations in a
    # PEP-specific manner.
    BeartypeNodeTransformerPep526Mixin,
    BeartypeNodeTransformerPep695Mixin,
):
    '''
    **Beartype abstract syntax tree (AST) node transformer** (i.e., visitor
    pattern recursively transforming the AST tree passed to the :meth:`visit`
    method by decorating all typed callables and classes by the
    :func:`beartype.beartype` decorator).

    Design
    ------
    This class was largely designed by reverse-engineering the standard
    :mod:`ast` module using the following code snippet. When run as the body of
    a script from the command line (e.g., ``python3 {muh_script}.py``), this
    snippet pretty-prints the desired target AST subtree implementing the
    desired source code (specified in this snippet via the ``CODE`` global). In
    short, this snippet trivializes the definition of arbitrarily complex
    AST-based code from arbitrarily complex Python code:

    .. code-block:: python

       import ast

       # Arbitrary desired code to pretty-print the AST representation of.
       CODE = """
       from beartype import beartype
       from beartype._conf.confcache import beartype_conf_id_to_conf

       @beartype(conf=beartype_conf_id_to_conf[139870142111616])
       def muh_func(): pass
       """

       # Dismantled, this is:
       # * "indent=...", producing pretty-printed (i.e., indented) output.
       # * "include_attributes=True", enabling pseudo-nodes (i.e., nodes lacking
       #   associated code metadata) to be distinguished from standard nodes
       #   (i.e., nodes having such metadata).
       print(ast.dump(ast.parse(CODE), indent=4, include_attributes=True))

    Attributes
    ----------
    _conf_beartype : BeartypeConf
        **Beartype configuration** (i.e., dataclass configuring the
        :mod:`beartype.beartype` decorator for *all* decoratable objects
        recursively decorated by this node transformer).
    _module_name_beartype : str
        Fully-qualified name of the current module being transformed.
    _scope_name_beartype : str
        Fully-qualified name of the current lexical scope (i.e., ``.``-delimited
        absolute name of the module containing this scope followed by the
        relative basenames of zero or more classes and/or callables). This name
        is guaranteed to be prefixed by :attr:`._module_name_beartype`.
    _scope_stack_beartype : list[type[AST]]
        **Current lexical scope stack** (i.e., list of the zero or more types of
        parent nodes of the node being recursively visited by this node
        transformer such that each of those parent nodes declares a new lexical
        scope). Specifically:

        * If this stack is empty, the current node directly resides in the body
          of a module (i.e., is a global attribute).
        * If this stack is non-empty, the current node does *not* directly
          reside in the body of a module. Instead, if the last item of this
          stack is:

          * The :class:`ClassDef` node type, the current node directly resides
            in the body of a class (i.e., is a class attribute or method).
          * The :class:`FunctionDef` node type, the current node directly
            resides in the body of a callable (i.e., is a local attribute).

    See Also
    --------
    https://github.com/agronholm/typeguard/blob/fe5b578595e00d5e45c3795d451dcd7935743809/src/typeguard/importhook.py
        Last commit of the third-party Python package whose
        ``@typeguard.importhook.TypeguardTransformer`` class implements import
        hooks performing runtime type-checking in a similar manner, strongly
        inspiring this implementation.

        Note that all subsequent commits to that package generalize those import
        hooks into something else entirely, which increasingly resembles a
        static type-checker run at runtime; while fascinating and almost
        certainly ingenious, those commits are sufficiently inscrutable,
        undocumented, and unintelligible to warrant caution. Nonetheless, thanks
        so much to @agronholm (Alex Grönholm) for his pulse-pounding innovations
        in this burgeoning field! Our AST transformer is for you, @agronholm.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Subclasses declaring uniquely subclass-specific instance
    # variables *MUST* additionally slot those variables. Subclasses violating
    # this constraint will be usable but unslotted, which defeats the purpose.
    # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Slot all instance variables defined on this object to reduce the costs of
    # both reading and writing these variables by approximately ~10%.
    __slots__ = (
        '_conf_beartype',
        '_module_name_beartype',
        '_scope_name_beartype',
        '_scope_stack_beartype',
    )

    # ..................{ INITIALIZERS                       }..................
    def __init__(
        self,

        # Mandatory keyword-only parameters.
        *,
        module_name_beartype: str,
        conf_beartype: BeartypeConf,
    ) -> None:
        '''
        Initialize this node transformer.

        Parameters
        ----------
        module_name_beartype : str
            Fully-qualified name of the external third-party module being
            transformed by this node transformer.
        conf_beartype : BeartypeConf
            **Beartype configuration** (i.e., dataclass configuring the
            :mod:`beartype.beartype` decorator for *all* decoratable objects
            recursively decorated by this node transformer).
        '''
        assert isinstance(module_name_beartype, str), (
            f'{module_name_beartype!r} not string.')
        assert isinstance(conf_beartype, BeartypeConf), (
            f'{conf_beartype!r} not beartype configuration.')

        # Initialize our superclass.
        super().__init__()

        # Classify all passed parameters.
        self._conf_beartype = conf_beartype
        self._module_name_beartype = self._scope_name_beartype = (
            module_name_beartype)

        # Nullify all remaining instance variables for safety.
        self._scope_stack_beartype: List[Type[AST]] = []

    # ..................{ SUPERCLASS                         }..................
    # Overridden methods first defined by the "NodeTransformer" superclass.

    def generic_visit(self, node: NodeT) -> NodeT:
        '''
        Recursively visit and possibly transform *all* child nodes of the passed
        parent node in-place (i.e., preserving this parent node as is).

        Parameters
        ----------
        node : NodeT
            Parent node to transform *all* child nodes of.

        Returns
        -------
        NodeT
            Parent node returned and thus preserved as is.
        '''

        # Type of this parent node.
        node_type = type(node)

        # If this parent node declares a new lexical scope (i.e., by defining a
        # new class or callable)...
        if node_type in TYPES_NODE_LEXICAL_SCOPE:
            # Fully-qualified name of the current lexical scope *BEFORE*
            # visiting this new lexical scope.
            scope_name_old = self._scope_name_beartype

            # Append to this fully-qualified name the unqualified basename of
            # this new class or callable declaring this new lexical scope.
            #
            # Note that both the "ast.ClassDef" *AND* "ast.FunctionDef" node
            # types define the "name" instance variable accessed here.
            self._scope_name_beartype += f'.{node.name}'  # type: ignore[attr-defined]

            # Add the type of this parent node to the top of the stack of all
            # current lexical scopes *BEFORE* visiting any child nodes of this
            # parent node.
            self._scope_stack_beartype.append(node_type)

            # Recursively visit *ALL* child nodes of this parent node.
            super().generic_visit(node)

            # Restore the fully-qualified name of the prior lexical scope.
            self._scope_name_beartype = scope_name_old

            # Remove the type of this parent node from the top of the stack of
            # all current lexical scopes *AFTER* visiting all child nodes of
            # this parent node.
            self._scope_stack_beartype.pop()
        # Else, this parent node does *NOT* declare a new lexical scope. In this
        # case...
        else:
            # Recursively visit all child nodes of this parent node *WITHOUT*.
            # modifying the stack of all current lexical scopes.
            super().generic_visit(node)

        # Return this parent node as is.
        return node

    # ..................{ VISITORS ~ module                  }..................
    def visit_Module(self, node: Module) -> Module:
        '''
        Add a new abstract syntax tree (AST) child node to the passed
        **module node** (i.e., node encapsulating the module currently being
        loaded by the
        :class:`beartype.claw._importlib._clawimpload.BeartypeSourceFileLoader`)
        importing various attributes required by lower-level child nodes added
        by subsequent visitor methods defined by this transformer.

        Parameters
        ----------
        node : Module
            Module node to be transformed.

        Returns
        -------
        Module
            That same module node.
        '''

        # 0-based index of an early child node of this parent module node
        # immediately *BEFORE* which to insert one or more statements importing
        # beartype-specific attributes, defaulting to the first child node of
        # this parent module. Specifically, if this module begins with:
        # * Neither a module docstring *NOR* any "from __future__" imports, this
        #   index is guaranteed to be 0.
        # * Only a module docstring but *NO* "from __future__" imports, this
        #   index is guaranteed to be 1.
        # * A module docstring and one or more "from __future__" imports, this
        #   index is guaranteed to be one more than the number of such imports.
        node_index_import_beartype_attrs = 0

        # 0-based index of the last child node of this parent module node.
        node_index_last = len(node.body)

        # Child node of this parent module node immediately preceding the output
        # import child node to be added below, defaulting to this parent module
        # node to ensure that the copy_node_metadata() function below *ALWAYS*
        # copies from a valid node (for simplicity).
        node_prev: AST = node

        # For the 0-based index and value of each direct child node of this
        # parent module node...
        #
        # This iteration efficiently finds "node_index_import_beartype_attrs"
        # (i.e., the 0-based index of the first safe position in the list of all
        # child nodes of this parent module node to insert an import statement
        # importing our beartype decorator). Despite superficially appearing to
        # perform a linear search of all n child nodes of this module parent
        # node and thus exhibit worst-case O(n) time complexity, this iteration
        # is guaranteed to exhibit worst-case O(1) time complexity. \o/
        #
        # Note that the "node.body" instance variable for module nodes is a list
        # of *ALL* child nodes of this parent module node.
        for node_prev in node.body:
            # print(f'node_index_import_beartype_attrs [IN]: {node_index_import_beartype_attrs}')

            # If it is *NOT* the case that this child node signifies either...
            if not (
                # A module docstring...
                #
                # If that module defines a docstring, that docstring *MUST* be
                # the first expression of that module. That docstring *MUST* be
                # explicitly found and iterated past to ensure that the import
                # statement added below appears *AFTER* rather than *BEFORE* any
                # docstring. (The latter would destroy the semantics of that
                # docstring by reducing that docstring to an ignorable string.)
                (
                    isinstance(node_prev, Expr) and
                    isinstance(node_prev.value, Constant)
                ) or
                # A future import (i.e., import of the form "from __future__
                # ...") *OR*...
                #
                # If that module performs one or more future imports, these
                # imports *MUST* necessarily be the first non-docstring
                # statement of that module and thus appear *BEFORE* all import
                # statements that are actually imports -- including the import
                # statement added below.
                (
                    isinstance(node_prev, ImportFrom) and
                    node_prev.module == '__future__'
                )
            # Then immediately halt iteration, guaranteeing O(1) runtime.
            ):
                break
            # Else, this child node signifies either a module docstring of
            # future import. In this case, implicitly skip past this child node
            # to the next child node.

            # Insert beartype-specific attributes immediately *AFTER* this node.
            node_index_import_beartype_attrs += 1
        # "node_index_import_beartype_attrs" is now the index of the first safe
        # position in this list to insert output child import nodes below.
        # print(f'node_index_import_beartype_attrs [AFTER]: {node_index_import_beartype_attrs}')
        # print(f'len(node.body): {len(node.body)}')

        # If the 0-based index of an early child node of this parent module node
        # immediately *BEFORE* which to insert one or more statements importing
        # beartype-specific attributes is *NOT* that of the last child node of
        # this parent module node, this module contains one or more semantically
        # meaningful child nodes and is thus non-empty. In this case...
        if node_index_import_beartype_attrs != node_index_last:
            # print('Injecting beartype imports...')

            # Module-scoped import nodes (i.e., child nodes to be inserted under
            # the parent node encapsulating the currently visited submodule in
            # the AST for that module).
            #
            # Note that:
            # * The original attributes are imported into the currently visited
            #   submodule under obfuscated beartype-specific names,
            #   significantly reducing the likelihood of a namespace collision
            #   with existing attributes of the same name in that submodule.
            # * These nodes are intentionally *NOT* generalized into global
            #   constants. In theory, doing so would reduce space and time
            #   complexity by enabling efficient reuse here. In practice, doing
            #   so would also be fundamentally wrong; these nodes are
            #   subsequently modified to respect the source code metadata (e.g.,
            #   line numbers) of this AST module parent node, which prevents
            #   such trivial reuse. Although we could further attempt to
            #   circumvent that by shallowly or deeply copying from global
            #   constants, both the copy() and deepcopy() functions defined by
            #   the standard "copy" module are pure-Python and thus shockingly
            #   slow -- which defeats the purpose.

            # Node importing all beartype-specific attributes explicitly
            # imported and implicitly exported by our private
            # "beartype.claw._ast.clawaststar" submodule, comprising the set of
            # all attributes required by code dynamically injected into this AST
            # by this AST transformer.
            node_import_all = make_node_importfrom(
                module_name='beartype.claw._ast._clawaststar',
                source_attr_name='*',
                node_sibling=node_prev,
            )

            # Insert these output child import nodes at this safe position of
            # the list of all child nodes of this parent module node.
            #
            # Note that this syntax efficiently (albeit unreadably) inserts
            # these output child import nodes at the desired index (in this
            # arbitrary order) of this parent module node.
            node.body[node_index_import_beartype_attrs:0] = (node_import_all,)
        # Else, the 0-based index of an early child node of this parent module
        # node immediately *BEFORE* which to insert one or more statements
        # importing beartype-specific attributes is that of the last child node
        # of this parent module node. In this case, this module contains *NO*
        # semantically meaningful child nodes and is thus effectively empty.
        # In this case, silently reduce to a noop. This edge case is *EXTREMELY*
        # uncommon and thus *NOT* optimized for (either here or elsewhere).
        #
        # Note that this edge cases cleanly matches:
        # * Syntactically empty modules containing only zero or more whitespace
        #   characters and zero or more inline comments.
        # * Syntactically non-empty modules containing only a prefacing module
        #   docstring and/or one or more "from __future__" import statements.
        #   Semantically, these sorts of modules are effectively empty as well.

        # #FIXME: Conditionally perform this logic if "conf.is_debug", please.
        # node = self.generic_visit(node)
        # print(
        #     f'Module abstract syntax tree (AST) transformed by @beartype to:\n\n'
        #     f'{get_node_repr_indented(node)}'
        # )
        # return node

        # Return this transformed module node.
        # Recursively transform *ALL* child nodes of this parent module node.
        return self.generic_visit(node)

    # ..................{ VISITORS ~ class                   }..................
    # FIXME: Implement us up, please.
    def visit_ClassDef(self, node: ClassDef) -> Optional[ClassDef]:
        '''
        Add a new child node to the passed **class node** (i.e., node
        encapsulating the definition of a pure-Python class) unconditionally
        decorating that class by our private
        :func:`beartype._decor.decorcore.beartype_object_nonfatal` decorator.

        Parameters
        ----------
        node : ClassDef
            Class node to be transformed.

        Returns
        -------
        Optional[ClassDef]
            This same class node.
        '''

        # Add a new child decoration node to this parent class node decorating
        # this class by @beartype under this configuration.
        self._decorate_node_beartype(node=node, conf=self._conf_beartype)

        # Recursively transform *ALL* child nodes of this parent class node.
        # Note that doing so implicitly calls the visit_FunctionDef() method
        # (defined below), each of which then effectively reduces to a noop.
        return self.generic_visit(node)

    # ..................{ VISITORS ~ callable                }..................
    def visit_FunctionDef(self, node: NodeCallable) -> Optional[NodeCallable]:
        '''
        Add a new child node to the passed **callable node** (i.e., node
        encapsulating the definition of a pure-Python function or method)
        decorating that callable by our private
        :func:`beartype._decor.decorcore.beartype_object_nonfatal` decorator if
        and only if that callable is **typed** (i.e., annotated by a return type
        hint and/or one or more parameter type hints).

        Parameters
        ----------
        node : NodeCallable
            Callable node to be transformed.

        Returns
        -------
        Optional[NodeCallable]
            This same callable node.
        '''

        # If...
        if (
            # * This callable node has one or more parent nodes previously
            #   visited by this node transformer *AND* the immediate parent node
            #   of this callable node is a class node, then this callable node
            #   encapsulates a method rather than a function. In this case, the
            #   visit_ClassDef() method defined above has already explicitly
            #   decorated the class defining this method by the @beartype
            #   decorator, which then implicitly decorates both this and all
            #   other methods of that class by that decorator. For safety and
            #   efficiency, avoid needlessly re-decorating this method by the
            #   same decorator by preserving and returning this node as is.
            # * That is *NOT* the case, then this callable node is either the
            #   root node of the current AST *OR* has a parent node that is not
            #   a class node. In either case, this callable node necessarily
            #   encapsulates a function (rather than a method), which yet to be
            #   decorated. Do so now! So say we all.
            #
            # This logic corresponds to the above "That is *NOT* the case" case
            # (i.e., this callable node necessarily encapsulates a function).
            # Look. Just accept that we have a tenuous grasp on reality at best.
            not self._is_scope_class_beartype and
            # ...and the currently visited callable is annotated by one or more
            # type hints and thus *NOT* ignorable with respect to beartype
            # decoration...
            is_node_callable_typed(node)
        ):
            # Add a new child decoration node to this parent callable node
            # decorating this callable by @beartype under this configuration.
            self._decorate_node_beartype(node=node, conf=self._conf_beartype)
        # Else, that callable is ignorable. In this case, avoid needlessly
        # decorating that callable by @beartype for efficiency.

        # Recursively transform *ALL* child nodes of this parent callable node.
        return self.generic_visit(node)
