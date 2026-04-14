# k3c/lang/ir.py
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Callable, Generic, Never, TypeVar

from k3c.errors import K3NothingException
from k3c.spec.result import WhyKind

if TYPE_CHECKING:
    from typing import Any

T = TypeVar("T")
U = TypeVar("U")


# ═══════════════════════════════════════════════════════════════════════════════
#  Option[T] = Some(T) | Nothing
#
#  The return type of eval(). Always a value. Never raises. Never None.
#
#  Design principles:
#    1. Nothing carries context  — field (which was absent) and step_hash
#       (which apply() call produced this). The audit trail is unbroken.
#    2. Nothing propagates       — through And, Or, Compare, Arith, Field, etc.
#       Like NaN in IEEE 754: one Nothing anywhere in the expression tree
#       makes the whole expression Nothing.
#    3. IsSome absorbs Nothing   — always returns Some(True|False). The one
#       operation that converts Nothing to a boolean cleanly.
#    4. UnwrapOr recovers        — Nothing becomes the default. Safe extraction.
#    5. raise_() is caller opt-in — eval() never calls it. Only the client
#       calls it when it decides an absent field is fatal.
#
#  Relation to K3Result:
#    Option   is the eval() level — value expressions, field access, guards
#    K3Result is the apply() level — causal steps, invariants, liveness
#    Nothing  at the apply() boundary → Impossible(Why(kind='missing'))
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Some(Generic[T]):
    """
    A present value. eval() found what it was looking for.

    Frozen — immutable, hashable, safe across the causal step.
    Generic over T so the type checker knows what val contains.
    """

    val: T
    # The present value. Any type: bool, int, str, dict, list, …

    # ── Combinators ───────────────────────────────────────────────────────────

    def map(self, f: Callable[[T], U]) -> Some[U]:
        """
        Transform the value. Always returns Some.
        Nothing implements the same interface but returns itself.

        Example:
            eval(Var('balance'), ctx).map(lambda b: b * 100)
        """
        return Some(f(self.val))

    def and_then(self, f: Callable[[T], K3Option[U]]) -> K3Option[U]:
        """
        Chain an operation that may itself return Nothing.

        Example:
            eval(Var('order'), ctx)
            .and_then(lambda o: Some(o['amount']) if 'amount' in o
                                else Nothing('amount', step_hash))
        """
        return f(self.val)

    def unwrap(self) -> T:
        """Extract the value. Safe — Some always has a value."""
        return self.val

    def unwrap_or(self, default: T) -> T:
        """Extract or use default. Always returns the value for Some."""
        return self.val

    def is_some(self) -> bool:
        return True

    def is_nothing(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"Some({self.val!r})"


@dataclass(frozen=True)
class Nothing:
    """
    An absent value. eval() could not resolve the expression.

    Carries field and step_hash so the audit trail is preserved when
    this Nothing surfaces at the apply() boundary and becomes
    Impossible(Why(kind='missing', rule=..., messages=[f"Field {field!r} absent"])).

    Never raised by eval(). raise_() is caller opt-in only.

    Propagation rule: any operation on Nothing returns Nothing with
    the ORIGINAL field and step_hash — the first absence in a chain
    is the root cause. Subsequent propagation does not overwrite it.

    Special cases:
      IsSome(Nothing)    → Some(False)   — absorbs Nothing, returns bool
      UnwrapOr(Nothing)  → eval(default) — recovers with a default value
    """

    field: str
    # Which field or expression was absent.
    # Examples: 'balance', 'order.amount', '[0]', 'div-by-zero',
    #           'before.status', 'after.total', 'unknown:MyNode'
    # Constructed by the nothing() helper inside eval():
    #   def nothing(field: str) -> Nothing:
    #       return Nothing(field=field, step_hash=step_hash)

    step_hash: str
    # The step_hash from the apply() call that was running when
    # this Nothing was produced. Threaded into eval() as a parameter
    # and captured here at construction time.
    # Preserved through propagation — never overwritten.

    # ── Combinators — all short-circuit ───────────────────────────────────────

    def map(self, f: Callable[..., object]) -> Nothing:
        """Nothing propagates — f is never called."""
        return self

    def and_then(self, f: Callable[..., object]) -> Nothing:
        """Nothing propagates — f is never called."""
        return self

    def unwrap_or(self, default: Any) -> Any:
        """
        Recover with a default. The one safe extraction from Nothing.
        Used by UnwrapOr k3l node in eval().
        """
        return default

    def is_some(self) -> bool:
        return False

    def is_nothing(self) -> bool:
        return True

    # ── Caller opt-in escalation ───────────────────────────────────────────────

    def raise_(self) -> Never:
        """
        Escalate to K3NothingException.

        Never called by eval(). Never called by apply().
        Only called by client code that decides an absent field is fatal.

        Example:
            match eval(Var('required_field'), ctx, step_hash):
                case Some(v): use(v)
                case Nothing() as n: n.raise_()   # caller decides it's fatal
        """
        raise K3NothingException(
            field=self.field,
            step_hash=self.step_hash,
        )

    # ── Boundary conversion ───────────────────────────────────────────────────

    def to_impossible_context(self, rule: str) -> dict[str, object]:
        """
        Produce the Why constructor kwargs for the apply() boundary.

        Called by engine.py when a Nothing surfaces from a permit guard eval.
        The field and step_hash are already set — they originated here.

        Usage in engine.py:
            case Nothing(field=f, step_hash=sh):
                return Impossible(Why(
                    rule=rule, kind=WhyKind.MISSING,
                    messages=(f"Field {f!r} absent — required by {rule!r}",),
                    step_hash=sh,
                    ...
                ))
        """

        return {
            "kind": WhyKind.MISSING,
            "messages": (f"Field {self.field!r} absent — required by {rule!r}",),
            "step_hash": self.step_hash,
        }

    def __repr__(self) -> str:
        return f"Nothing(field={self.field!r}, step={self.step_hash[:8]})"


# ── K3 Option ─────────────────────────────────────────────────────────────────

type K3Option[T] = Some[T] | Nothing


# ═══════════════════════════════════════════════════════════════════════════════
#  Typed enums for operator and format variants
# ═══════════════════════════════════════════════════════════════════════════════


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


class DateFormat(StrEnum):
    """Date format hints for TDate."""

    ISO8601 = "ISO8601"
    YYYYMMDD = "YYYYMMDD"
    SSIM = "SSIM"


class TimeFormat(StrEnum):
    """Time format hints for TTime."""

    ISO8601 = "ISO8601"
    HHMM = "HHMM"
    HHMMSS = "HHMMSS"


# ═══════════════════════════════════════════════════════════════════════════════
#  Tier 1 — K3lType: what things ARE
#
#  The type system for K3.Lang expressions. Used by the compiler, schema
#  validation, and well-formedness checks. Not used by eval() at runtime.
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TBool:
    """Boolean type."""


@dataclass(frozen=True)
class TInt:
    """Integer type."""


@dataclass(frozen=True)
class TString:
    """String type."""


@dataclass(frozen=True)
class TFloat:
    """Floating-point type."""


@dataclass(frozen=True)
class TRecord:
    """Record type — named fields with typed values."""

    fields: dict[str, K3lType]


@dataclass(frozen=True)
class TVariant:
    """Tagged union type — one of several named alternatives."""

    variants: dict[str, K3lType]


@dataclass(frozen=True)
class TList:
    """Homogeneous list type."""

    element: K3lType


@dataclass(frozen=True)
class TOption:
    """Optional type — Some(T) or Nothing."""

    inner: K3lType


@dataclass(frozen=True)
class TRef:
    """Reference to a named type — for recursive or cross-referenced types."""

    name: str


@dataclass(frozen=True)
class TUnit:
    """Unit type — no value, used for side-effect-only events."""


@dataclass(frozen=True)
class TBytes:
    """Binary bytes type. length=None means variable-length."""

    length: int | None = None


@dataclass(frozen=True)
class TDate:
    """Date type with format hint."""

    format: DateFormat = DateFormat.ISO8601


@dataclass(frozen=True)
class TTime:
    """Time type with format hint."""

    format: TimeFormat = TimeFormat.ISO8601


@dataclass(frozen=True)
class TEnum:
    """Closed enumeration — one of a fixed set of string values."""

    values: tuple[str, ...]


type K3lType = (
    TBool
    | TInt
    | TString
    | TFloat
    | TUnit
    | TBytes
    | TDate
    | TTime
    | TEnum
    | TRecord
    | TVariant
    | TList
    | TOption
    | TRef
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Tier 2 — K3l: what things DO
#
#  The complete discriminated union of K3.Lang expression nodes.
#  Every expression the system can represent is one of these frozen
#  dataclasses. Frozen = hashable + immutable + safe for the causal step.
#
#  eval() pattern-matches on these nodes. The compiler emits them.
#  serde.py round-trips them to/from JSON.
# ═══════════════════════════════════════════════════════════════════════════════


# ── Literals ─────────────────────────────────────────────────────────────────


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


# ── Variables and field access ───────────────────────────────────────────────


@dataclass(frozen=True)
class Var:
    """Variable reference — resolved from the eval context."""

    name: str


@dataclass(frozen=True)
class Field:
    """Field access on an expression — e.g. order.amount."""

    expr: K3l
    name: str


@dataclass(frozen=True)
class Index:
    """List/array index access — e.g. items[0]."""

    expr: K3l
    idx: int


@dataclass(frozen=True)
class EventField:
    """Named field from the current domain event. Shorthand for Field(Var('event'), name)."""

    name: str


@dataclass(frozen=True)
class Actual:
    """Field in K.lift(S) — the implementation's actual value for korrelation."""

    field: str


@dataclass(frozen=True)
class Intended:
    """Field in Ctx.spec_state — the spec's intended value for korrelation."""

    field: str


# ── Logic ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class And:
    """Logical AND. Short-circuits: right not evaluated if left is False or Nothing."""

    left: K3l
    right: K3l


@dataclass(frozen=True)
class Or:
    """Logical OR. Short-circuits: right not evaluated if left is True or Nothing."""

    left: K3l
    right: K3l


@dataclass(frozen=True)
class Not:
    """Logical NOT."""

    expr: K3l


@dataclass(frozen=True)
class If:
    """Conditional expression — if cond then then_ else else_."""

    cond: K3l
    then: K3l
    else_: K3l


# ── Comparison ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Compare:
    """Comparison operator."""

    op: CmpOp
    left: K3l
    right: K3l


# ── Arithmetic ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Arith:
    """Arithmetic operator. Div by zero → Nothing('div-by-zero'), never ZeroDivisionError."""

    op: ArithOp
    left: K3l
    right: K3l


# ── Option operations ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Mod:
    """Modulo operator. Div by zero → Nothing('mod-by-zero')."""

    left: K3l
    right: K3l


@dataclass(frozen=True)
class Negate:
    """Arithmetic negation: -expr."""

    expr: K3l


@dataclass(frozen=True)
class Abs:
    """Absolute value: |expr|."""

    expr: K3l


@dataclass(frozen=True)
class Min:
    """Minimum of two values."""

    left: K3l
    right: K3l


@dataclass(frozen=True)
class Max:
    """Maximum of two values."""

    left: K3l
    right: K3l


# ── Option operations ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IsSome:
    """Check if an expression evaluates to Some. Absorbs Nothing → Some(False)."""

    expr: K3l


@dataclass(frozen=True)
class UnwrapOr:
    """Extract value from Some, or evaluate default if Nothing."""

    expr: K3l
    default: K3l


# ── Temporal — cross-step references ─────────────────────────────────────────


@dataclass(frozen=True)
class Before:
    """Reference to a field's value from the previous state (prev_state)."""

    field: str


@dataclass(frozen=True)
class After:
    """Reference to a field's value from the current state (new_state)."""

    field: str


# ── Collections ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ForAll:
    """Universal quantifier: ∀ var ∈ collection : predicate."""

    var: str
    collection: K3l
    predicate: K3l


@dataclass(frozen=True)
class Exists:
    """Existential quantifier: ∃ var ∈ collection : predicate."""

    var: str
    collection: K3l
    predicate: K3l


@dataclass(frozen=True)
class Length:
    """Length of a list or string."""

    expr: K3l


@dataclass(frozen=True)
class Contains:
    """Check if a collection contains an element, or a string contains a substring."""

    collection: K3l
    element: K3l


@dataclass(frozen=True)
class Map:
    """Map a function over a list: [f(x) for x in collection]."""

    var: str
    collection: K3l
    body: K3l


@dataclass(frozen=True)
class Filter:
    """Filter a list: [x for x in collection if predicate(x)]."""

    var: str
    collection: K3l
    predicate: K3l


@dataclass(frozen=True)
class Fold:
    """Fold/reduce a list: fold(init, collection, (acc, x) -> body)."""

    init: K3l
    collection: K3l
    acc_var: str
    elem_var: str
    body: K3l


# ── String operations ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Concat:
    """String concatenation."""

    left: K3l
    right: K3l


@dataclass(frozen=True)
class Trim:
    """Strip leading/trailing whitespace."""

    expr: K3l


@dataclass(frozen=True)
class Slice:
    """Substring/list slice: expr[start:end]."""

    expr: K3l
    start: K3l
    end: K3l


@dataclass(frozen=True)
class Matches:
    """Regex match: expr matches pattern."""

    expr: K3l
    pattern: str


# ── Record construction ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Record:
    """Construct a record from field name/expression pairs."""

    fields: tuple[tuple[str, K3l], ...]


@dataclass(frozen=True)
class With:
    """Functional record update: { base with field = value, ... }."""

    base: K3l
    updates: tuple[tuple[str, K3l], ...]


@dataclass(frozen=True)
class LList:
    """List literal: [e1, e2, ...]."""

    elements: tuple[K3l, ...]


# ── Spec nodes — liveness and invariants ─────────────────────────────────────


@dataclass(frozen=True)
class Always:
    """Invariant: expr must hold on every step. Failure → Violated."""

    expr: K3l


@dataclass(frozen=True)
class Eventually:
    """Liveness: expr must become true at some future step. Untriggered at termination → Violated."""

    expr: K3l


@dataclass(frozen=True)
class Within:
    """Bounded liveness: expr must become true within n steps. Timer expires → Violated."""

    expr: K3l
    n: int


@dataclass(frozen=True)
class Until:
    """Temporal until: left holds until right becomes true. left U right."""

    left: K3l
    right: K3l


# ── Annotation ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Named:
    """Named expression — carries an identifier for JSON-LD @id export."""

    name: str
    expr: K3l


@dataclass(frozen=True)
class Described:
    """Described expression — carries documentation (rdfs:comment in JSON-LD)."""

    description: str
    expr: K3l


# ── Implication ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Implies:
    """Logical implication: left ⇒ right. Sugar for Or(Not(left), right)."""

    left: K3l
    right: K3l


# ── K3l discriminated union ──────────────────────────────────────────────────

type K3l = (
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
    # Temporal — cross-step references
    | Before
    | After
    # Spec nodes — liveness and invariants
    | Always
    | Eventually
    | Within
    | Until
    # Annotation
    | Named
    | Described
)
