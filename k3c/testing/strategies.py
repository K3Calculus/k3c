# k3c/testing/strategies.py
"""
Hypothesis strategies for K3 expressions and specs.

Provides strategies for generating random Expr nodes, Specs, and events
for property-based testing.
"""

from __future__ import annotations

from k3c.ir.expr import (
    Arith,
    ArithOp,
    CmpOp,
    Compare,
    Expr,
    LBool,
    LFloat,
    LInt,
    LStr,
)

try:
    from hypothesis import strategies as st

    @st.composite
    def literal_exprs(draw: st.DrawFn) -> Expr:
        """Generate random literal expressions."""
        choice = draw(st.sampled_from(["bool", "int", "float", "str"]))
        match choice:
            case "bool":
                return LBool(draw(st.booleans()))
            case "int":
                return LInt(draw(st.integers(min_value=-1000, max_value=1000)))
            case "float":
                return LFloat(
                    draw(
                        st.floats(
                            min_value=-1000,
                            max_value=1000,
                            allow_nan=False,
                            allow_infinity=False,
                        )
                    )
                )
            case "str":
                return LStr(draw(st.text(min_size=0, max_size=20)))
            case _:
                return LBool(True)

    @st.composite
    def compare_exprs(draw: st.DrawFn) -> Expr:
        """Generate random comparison expressions."""
        op = draw(st.sampled_from(list(CmpOp)))
        left = draw(literal_exprs())
        right = draw(literal_exprs())
        return Compare(op, left, right)

    @st.composite
    def arith_exprs(draw: st.DrawFn) -> Expr:
        """Generate random arithmetic expressions."""
        op = draw(st.sampled_from(list(ArithOp)))
        left = LInt(draw(st.integers(min_value=-100, max_value=100)))
        right = LInt(draw(st.integers(min_value=-100, max_value=100)))
        return Arith(op, left, right)

    @st.composite
    def simple_events(
        draw: st.DrawFn, event_types: list[str] | None = None
    ) -> dict[str, object]:
        """Generate random simple events."""
        types = event_types or ["Deposit", "Withdraw", "Transfer"]
        event: dict[str, object] = {
            "type": draw(st.sampled_from(types)),
            "amount": draw(st.integers(min_value=0, max_value=1000)),
        }
        return event

except ImportError:
    pass  # hypothesis not available
