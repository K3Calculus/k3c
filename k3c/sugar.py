# k3c/sugar.py
"""
Operator-overloaded sugar for building K3 expressions.

The frozen-dataclass IR (Var, Field, Compare, ...) is verbose:

    Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount"))

Sugar makes this read like Python:

    S.balance >= E.amount

S and E are accessor builders. They produce Q wrappers around IR nodes.
Q wrappers overload comparison/logic operators to build Compare/And/Or/Not
nodes. When passed to Spec construction, k3() unwraps them to plain IR.

Usage:
    from k3c.sugar import S, E, k3

    # Build a guard
    permit = Permit(name="has_funds", on="Withdraw",
                    when=k3(S.balance >= E.amount))

    # Build an invariant
    maintain = Maintain(name="non_negative",
                        expr=Always(k3(S.balance >= 0)))

    # Logical combinators
    when=k3((S.balance >= E.amount) & (S.status == "active"))
    when=k3((S.role == "admin") | (S.id == E.owner))
    when=k3(~(S.locked))

    # In/membership
    when=k3(S.status.in_("pending", "confirmed", "shipped"))
"""

from __future__ import annotations

from k3c.ir.expr import (
    After,
    AllOf,
    And,
    AnyOf,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    EventField,
    Expr,
    Field,
    In,
    LBool,
    LFloat,
    LInt,
    LNull,
    LStr,
    Not,
    Or,
    Var,
)


def _lift(value: object) -> Expr:
    """Lift a Python value, Q, or raw IR Expr node to an IR Expr."""
    if isinstance(value, Q):
        return value._expr
    if value is None:
        return LNull()
    if isinstance(value, bool):
        return LBool(value)
    if isinstance(value, int):
        return LInt(value)
    if isinstance(value, float):
        return LFloat(value)
    if isinstance(value, str):
        return LStr(value)
    # Raw IR Expr nodes (LInt(0), Field(...), etc.) — pass through
    if hasattr(value, "__dataclass_fields__"):
        return value  # type: ignore[return-value]
    msg = f"Cannot lift value of type {type(value).__name__} to Expr"
    raise TypeError(msg)


def k3(value: object) -> Expr:
    """Unwrap a Q (or any value) to a plain IR Expr.

    Use at the boundary where you pass sugar expressions into Spec, Permit,
    Maintain, etc. Pure Python literals are lifted; Q is unwrapped; raw
    IR Expr nodes pass through.
    """
    if isinstance(value, Q):
        return value._expr
    # Raw IR nodes: any frozen dataclass with no ._expr attr — assume Expr.
    if hasattr(value, "__dataclass_fields__"):
        return value  # type: ignore[return-value]
    return _lift(value)


class Q:
    """Wrapper around an IR Expr that supports operator overloads.

    Don't construct Q directly — use S, E, or wrap an existing IR expression
    via k3.lift().
    """

    __slots__ = ("_expr",)

    def __init__(self, expr: Expr) -> None:
        self._expr = expr

    def __getattr__(self, name: str) -> Q:
        # S.balance — sugar for field access
        if name.startswith("_"):
            raise AttributeError(name)
        return Q(Field(self._expr, name))

    def __getitem__(self, key: object) -> Q:
        if isinstance(key, str):
            return Q(Field(self._expr, key))
        msg = f"Q[...] requires str key, got {type(key).__name__}"
        raise TypeError(msg)

    # -- Comparison operators --------------------------------------------------

    def __eq__(self, other: object) -> Q:  # type: ignore[override]
        return Q(Compare(CmpOp.EQ, self._expr, _lift(other)))

    def __ne__(self, other: object) -> Q:  # type: ignore[override]
        return Q(Compare(CmpOp.NE, self._expr, _lift(other)))

    def __lt__(self, other: object) -> Q:
        return Q(Compare(CmpOp.LT, self._expr, _lift(other)))

    def __le__(self, other: object) -> Q:
        return Q(Compare(CmpOp.LE, self._expr, _lift(other)))

    def __gt__(self, other: object) -> Q:
        return Q(Compare(CmpOp.GT, self._expr, _lift(other)))

    def __ge__(self, other: object) -> Q:
        return Q(Compare(CmpOp.GE, self._expr, _lift(other)))

    # -- Arithmetic ------------------------------------------------------------

    def __add__(self, other: object) -> Q:
        return Q(Arith(ArithOp.ADD, self._expr, _lift(other)))

    def __sub__(self, other: object) -> Q:
        return Q(Arith(ArithOp.SUB, self._expr, _lift(other)))

    def __mul__(self, other: object) -> Q:
        return Q(Arith(ArithOp.MUL, self._expr, _lift(other)))

    def __truediv__(self, other: object) -> Q:
        return Q(Arith(ArithOp.DIV, self._expr, _lift(other)))

    def __radd__(self, other: object) -> Q:
        return Q(Arith(ArithOp.ADD, _lift(other), self._expr))

    def __rsub__(self, other: object) -> Q:
        return Q(Arith(ArithOp.SUB, _lift(other), self._expr))

    def __rmul__(self, other: object) -> Q:
        return Q(Arith(ArithOp.MUL, _lift(other), self._expr))

    # -- Logic combinators ----------------------------------------------------

    def __and__(self, other: object) -> Q:
        return Q(And(self._expr, _lift(other)))

    def __or__(self, other: object) -> Q:
        return Q(Or(self._expr, _lift(other)))

    def __invert__(self) -> Q:
        return Q(Not(self._expr))

    def __rand__(self, other: object) -> Q:
        return Q(And(_lift(other), self._expr))

    def __ror__(self, other: object) -> Q:
        return Q(Or(_lift(other), self._expr))

    # -- Membership ------------------------------------------------------------

    def in_(self, *values: object) -> Q:
        """Build an In expression: S.status.in_("a", "b", "c")."""
        return Q(In(expr=self._expr, values=tuple(_lift(v) for v in values)))

    # -- Boolean misuse trap --------------------------------------------------

    def __bool__(self) -> bool:
        msg = (
            "Q expressions cannot be used as Python bools. "
            "Use & | ~ for logic, not 'and or not'. "
            "Use k3(...) to unwrap to IR."
        )
        raise TypeError(msg)

    def __hash__(self) -> int:
        return hash(self._expr)

    def __repr__(self) -> str:
        return f"Q({self._expr!r})"


class _StateBuilder:
    """Sugar accessor for state fields. Use as a singleton: from k3c.sugar import S."""

    def __getattr__(self, name: str) -> Q:
        if name.startswith("_"):
            raise AttributeError(name)
        return Q(Field(Var("state"), name))

    def __call__(self, name: str) -> Q:
        return Q(Field(Var("state"), name))

    def __repr__(self) -> str:
        return "S"


class _EventBuilder:
    """Sugar accessor for event fields. Use as a singleton: from k3c.sugar import E."""

    def __getattr__(self, name: str) -> Q:
        if name.startswith("_"):
            raise AttributeError(name)
        return Q(EventField(name))

    def __call__(self, name: str) -> Q:
        return Q(EventField(name))

    def __repr__(self) -> str:
        return "E"


class _SpecStateBuilder:
    """Sugar accessor for spec_state fields (Korrelator/Require contexts)."""

    def __getattr__(self, name: str) -> Q:
        if name.startswith("_"):
            raise AttributeError(name)
        return Q(Field(Var("spec_state"), name))

    def __call__(self, name: str) -> Q:
        return Q(Field(Var("spec_state"), name))

    def __repr__(self) -> str:
        return "SS"


# Singletons — the public sugar surface
S = _StateBuilder()
E = _EventBuilder()
SS = _SpecStateBuilder()


# -- Variadic logic helpers ----------------------------------------------------


def all_of(*exprs: object) -> Q:
    """Sugar: all_of(e1, e2, e3) -> AllOf((e1, e2, e3))."""
    return Q(AllOf(exprs=tuple(_lift(e) for e in exprs)))


def any_of(*exprs: object) -> Q:
    """Sugar: any_of(e1, e2, e3) -> AnyOf((e1, e2, e3))."""
    return Q(AnyOf(exprs=tuple(_lift(e) for e in exprs)))


def lit(value: object) -> Q:
    """Wrap a literal value as a Q for explicit lifting."""
    return Q(_lift(value))


def before(field: str) -> Q:
    """Sugar: before('x') -> Q(Before('x')). Reference state field from previous step."""
    return Q(Before(field))


def after(field: str) -> Q:
    """Sugar: after('x') -> Q(After('x')). Reference state field from current step."""
    return Q(After(field))
