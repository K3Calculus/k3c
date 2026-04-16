# k3c/ir/expr.py
"""
Tier 2 - Expr: what things DO

The complete discriminated union of K3 expression nodes.
Every expression the system can represent is one of these frozen
dataclasses. Frozen = hashable + immutable + safe for the causal step.

eval() pattern-matches on these nodes. The compiler emits them.
serde.py round-trips them to/from JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CmpOp(StrEnum):
    """Comparison operators for Compare nodes."""

    EQ = "Eq"
    NE = "Ne"
    LT = "Lt"
    LE = "Le"
    GT = "Gt"
    GE = "Ge"


class ArithOp(StrEnum):
    """Arithmetic operators for Arith nodes."""

    ADD = "Add"
    SUB = "Sub"
    MUL = "Mul"
    DIV = "Div"


# -- Literals ------------------------------------------------------------------


@dataclass(frozen=True)
class LBool:
    """Boolean literal."""

    val: bool


@dataclass(frozen=True)
class LInt:
    """Integer literal."""

    val: int


@dataclass(frozen=True)
class LFloat:
    """Floating-point literal."""

    val: float


@dataclass(frozen=True)
class LStr:
    """String literal."""

    val: str


# -- Variables and field access ------------------------------------------------


@dataclass(frozen=True)
class Var:
    """Variable reference - resolved from the eval context."""

    name: str


@dataclass(frozen=True)
class Field:
    """Field access on an expression - e.g. order.amount."""

    expr: Expr
    name: str


@dataclass(frozen=True)
class Index:
    """List/array index access - e.g. items[0]."""

    expr: Expr
    idx: int


@dataclass(frozen=True)
class EventField:
    """Named field from the current domain event."""

    name: str


@dataclass(frozen=True)
class Actual:
    """Field in K.lift(S) - the implementation's actual value for korrelation."""

    field: str


@dataclass(frozen=True)
class Intended:
    """Field in Ctx.spec_state - the spec's intended value for korrelation."""

    field: str


# -- Logic ---------------------------------------------------------------------


@dataclass(frozen=True)
class And:
    """Logical AND. Short-circuits on False or Nothing."""

    left: Expr
    right: Expr


@dataclass(frozen=True)
class Or:
    """Logical OR. Short-circuits on True or Nothing."""

    left: Expr
    right: Expr


@dataclass(frozen=True)
class Not:
    """Logical NOT."""

    expr: Expr


@dataclass(frozen=True)
class If:
    """Conditional expression."""

    cond: Expr
    then: Expr
    else_: Expr


# -- Comparison ----------------------------------------------------------------


@dataclass(frozen=True)
class Compare:
    """Comparison operator."""

    op: CmpOp
    left: Expr
    right: Expr


# -- Arithmetic ----------------------------------------------------------------


@dataclass(frozen=True)
class Arith:
    """Arithmetic operator. Div by zero -> Nothing('div-by-zero')."""

    op: ArithOp
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Mod:
    """Modulo operator. Div by zero -> Nothing('mod-by-zero')."""

    left: Expr
    right: Expr


@dataclass(frozen=True)
class Negate:
    """Arithmetic negation: -expr."""

    expr: Expr


@dataclass(frozen=True)
class Abs:
    """Absolute value: |expr|."""

    expr: Expr


@dataclass(frozen=True)
class Min:
    """Minimum of two values."""

    left: Expr
    right: Expr


@dataclass(frozen=True)
class Max:
    """Maximum of two values."""

    left: Expr
    right: Expr


# -- Option operations ---------------------------------------------------------


@dataclass(frozen=True)
class IsSome:
    """Check if an expression evaluates to Some. Absorbs Nothing -> Some(False)."""

    expr: Expr


@dataclass(frozen=True)
class UnwrapOr:
    """Extract value from Some, or evaluate default if Nothing."""

    expr: Expr
    default: Expr


# -- Temporal cross-step references --------------------------------------------


@dataclass(frozen=True)
class Before:
    """Reference to a field's value from the previous state."""

    field: str


@dataclass(frozen=True)
class After:
    """Reference to a field's value from the current state."""

    field: str


# -- Collections ---------------------------------------------------------------


@dataclass(frozen=True)
class ForAll:
    """Universal quantifier: forall var in collection : predicate."""

    var: str
    collection: Expr
    predicate: Expr


@dataclass(frozen=True)
class Exists:
    """Existential quantifier: exists var in collection : predicate."""

    var: str
    collection: Expr
    predicate: Expr


@dataclass(frozen=True)
class Length:
    """Length of a list or string."""

    expr: Expr


@dataclass(frozen=True)
class Contains:
    """Check if a collection contains an element."""

    collection: Expr
    element: Expr


@dataclass(frozen=True)
class Map:
    """Map over a list: [body(x) for x in collection]."""

    var: str
    collection: Expr
    body: Expr


@dataclass(frozen=True)
class Filter:
    """Filter a list: [x for x in collection if predicate(x)]."""

    var: str
    collection: Expr
    predicate: Expr


@dataclass(frozen=True)
class Fold:
    """Fold/reduce a list: fold(init, collection, (acc, x) -> body)."""

    init: Expr
    collection: Expr
    acc_var: str
    elem_var: str
    body: Expr


# -- String operations ---------------------------------------------------------


@dataclass(frozen=True)
class Concat:
    """String concatenation."""

    left: Expr
    right: Expr


@dataclass(frozen=True)
class Trim:
    """Strip leading/trailing whitespace."""

    expr: Expr


@dataclass(frozen=True)
class Slice:
    """Substring/list slice: expr[start:end]."""

    expr: Expr
    start: Expr
    end: Expr


@dataclass(frozen=True)
class Matches:
    """Regex match: expr matches pattern."""

    expr: Expr
    pattern: str


# -- Record construction -------------------------------------------------------


@dataclass(frozen=True)
class Record:
    """Construct a record from field name/expression pairs."""

    fields: tuple[tuple[str, Expr], ...]


@dataclass(frozen=True)
class With:
    """Functional record update: { base with field = value, ... }."""

    base: Expr
    updates: tuple[tuple[str, Expr], ...]


@dataclass(frozen=True)
class LList:
    """List literal: [e1, e2, ...]."""

    elements: tuple[Expr, ...]


# -- Spec nodes: liveness and invariants ---------------------------------------


@dataclass(frozen=True)
class Always:
    """Invariant: expr must hold on every step. Failure -> Violated."""

    expr: Expr


@dataclass(frozen=True)
class Eventually:
    """Liveness: expr must become true at some future step."""

    expr: Expr


@dataclass(frozen=True)
class Within:
    """Bounded liveness: expr must become true within n steps."""

    expr: Expr
    n: int


@dataclass(frozen=True)
class Until:
    """Temporal until: left holds until right becomes true."""

    left: Expr
    right: Expr


# -- Annotation ----------------------------------------------------------------


@dataclass(frozen=True)
class Named:
    """Named expression - carries an identifier for export."""

    name: str
    expr: Expr


@dataclass(frozen=True)
class Described:
    """Described expression - carries documentation."""

    description: str
    expr: Expr


# -- Implication ---------------------------------------------------------------


@dataclass(frozen=True)
class Implies:
    """Logical implication: left => right."""

    left: Expr
    right: Expr


# -- Variadic logic ------------------------------------------------------------


@dataclass(frozen=True)
class AllOf:
    """Variadic AND: all exprs must be true. Short-circuits on False/Nothing."""

    exprs: tuple[Expr, ...]


@dataclass(frozen=True)
class AnyOf:
    """Variadic OR: at least one expr must be true. Short-circuits on True."""

    exprs: tuple[Expr, ...]


@dataclass(frozen=True)
class In:
    """Membership test: expr in values. Sugar for AnyOf(Compare(EQ, expr, v) for v in values)."""

    expr: Expr
    values: tuple[Expr, ...]


# -- Expr discriminated union --------------------------------------------------

type Expr = (
    # Literals
    LBool
    | LInt
    | LFloat
    | LStr
    | LList
    # Variables and access
    | Var
    | Field
    | Index
    | EventField
    | Actual
    | Intended
    # Logic
    | And
    | Or
    | Not
    | If
    | Implies
    | AllOf
    | AnyOf
    | In
    # Comparison and arithmetic
    | Compare
    | Arith
    | Mod
    | Negate
    | Abs
    | Min
    | Max
    # Option operations
    | IsSome
    | UnwrapOr
    # Collections
    | ForAll
    | Exists
    | Length
    | Contains
    | Map
    | Filter
    | Fold
    # String operations
    | Concat
    | Trim
    | Slice
    | Matches
    # Record construction
    | Record
    | With
    # Temporal cross-step references
    | Before
    | After
    # Spec nodes
    | Always
    | Eventually
    | Within
    | Until
    # Annotation
    | Named
    | Described
)
