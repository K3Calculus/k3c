"""Tests for k3c.lang.eval — total interpreter for K3l expressions."""

from __future__ import annotations

import pytest

from k3c.lang.eval import k3_eval
from k3c.lang.ir import (
    After,
    Always,
    And,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    Eventually,
    Field,
    If,
    IsSome,
    LBool,
    LFloat,
    LInt,
    LStr,
    Not,
    Nothing,
    Or,
    Some,
    UnwrapOr,
    Var,
    Within,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

HASH = "testhash12345678"


def _eval(expr, ctx=None, step_hash=HASH):
    return k3_eval(expr, ctx or {}, step_hash)


def _val(expr, ctx=None):
    """Unwrap a Some result — fails if Nothing."""
    result = _eval(expr, ctx)
    assert isinstance(result, Some), f"Expected Some, got {result!r}"
    return result.val


def _nothing(expr, ctx=None):
    """Assert Nothing and return it."""
    result = _eval(expr, ctx)
    assert isinstance(result, Nothing), f"Expected Nothing, got {result!r}"
    return result


# Literals


class TestLiterals:
    def test_bool_true(self):
        assert _val(LBool(True)) is True

    def test_bool_false(self):
        assert _val(LBool(False)) is False

    def test_int(self):
        assert _val(LInt(42)) == 42

    def test_int_zero(self):
        assert _val(LInt(0)) == 0

    def test_int_negative(self):
        assert _val(LInt(-7)) == -7

    def test_float(self):
        assert _val(LFloat(3.14)) == pytest.approx(3.14)

    def test_float_zero(self):
        assert _val(LFloat(0.0)) == pytest.approx(0.0)

    def test_string(self):
        assert _val(LStr("hello")) == "hello"

    def test_string_empty(self):
        assert _val(LStr("")) == ""


# Variables


class TestVar:
    def test_present(self):
        assert _val(Var("x"), {"x": 42}) == 42

    def test_missing_returns_nothing(self):
        n = _nothing(Var("x"))
        assert n.field == "x"
        assert n.step_hash == HASH

    def test_none_value_is_some_none(self):
        assert _val(Var("x"), {"x": None}) is None

    def test_dict_value(self):
        d = {"a": 1}
        assert _val(Var("x"), {"x": d}) == d


class TestField:
    def test_nested_access(self):
        ctx = {"order": {"amount": 100}}
        assert _val(Field(Var("order"), "amount"), ctx) == 100

    def test_missing_field_returns_nothing(self):
        ctx = {"order": {"amount": 100}}
        n = _nothing(Field(Var("order"), "missing"), ctx)
        assert n.field == "missing"

    def test_missing_base_propagates_nothing(self):
        n = _nothing(Field(Var("missing_var"), "field"))
        assert n.field == "missing_var"

    def test_non_dict_base_returns_nothing(self):
        ctx = {"x": 42}
        n = _nothing(Field(Var("x"), "field"), ctx)
        assert n.field == "field"

    def test_deeply_nested(self):
        ctx = {"a": {"b": {"c": 99}}}
        expr = Field(Field(Var("a"), "b"), "c")
        assert _val(expr, ctx) == 99

    def test_deeply_nested_missing_middle(self):
        ctx = {"a": {"b": {"c": 99}}}
        expr = Field(Field(Var("a"), "missing"), "c")
        n = _nothing(expr, ctx)
        assert n.field == "missing"


# Logic — And


class TestAnd:
    def test_true_and_true(self):
        assert _val(And(LBool(True), LBool(True))) is True

    def test_true_and_false(self):
        assert _val(And(LBool(True), LBool(False))) is False

    def test_false_and_true(self):
        assert _val(And(LBool(False), LBool(True))) is False

    def test_false_and_false(self):
        assert _val(And(LBool(False), LBool(False))) is False

    def test_short_circuit_false_skips_right(self):
        # If right were evaluated, Var("missing") would produce Nothing
        result = _eval(And(LBool(False), Var("missing")))
        assert isinstance(result, Some)
        assert result.val is False

    def test_nothing_left_propagates(self):
        n = _nothing(And(Var("missing"), LBool(True)))
        assert n.field == "missing"

    def test_nothing_right_propagates(self):
        n = _nothing(And(LBool(True), Var("missing")))
        assert n.field == "missing"

    def test_non_bool_left_returns_nothing(self):
        n = _nothing(And(LInt(1), LBool(True)))
        assert n.field == "expected-bool"

    def test_non_bool_right_returns_nothing(self):
        n = _nothing(And(LBool(True), LInt(1)))
        assert n.field == "expected-bool"


# Logic — Or


class TestOr:
    def test_true_or_false(self):
        assert _val(Or(LBool(True), LBool(False))) is True

    def test_false_or_true(self):
        assert _val(Or(LBool(False), LBool(True))) is True

    def test_false_or_false(self):
        assert _val(Or(LBool(False), LBool(False))) is False

    def test_true_or_true(self):
        assert _val(Or(LBool(True), LBool(True))) is True

    def test_short_circuit_true_skips_right(self):
        result = _eval(Or(LBool(True), Var("missing")))
        assert isinstance(result, Some)
        assert result.val is True

    def test_nothing_left_propagates(self):
        n = _nothing(Or(Var("missing"), LBool(True)))
        assert n.field == "missing"

    def test_nothing_right_propagates(self):
        n = _nothing(Or(LBool(False), Var("missing")))
        assert n.field == "missing"

    def test_non_bool_left_returns_nothing(self):
        n = _nothing(Or(LInt(0), LBool(True)))
        assert n.field == "expected-bool"

    def test_non_bool_right_returns_nothing(self):
        n = _nothing(Or(LBool(False), LInt(1)))
        assert n.field == "expected-bool"


# Logic — Not


class TestNot:
    def test_not_true(self):
        assert _val(Not(LBool(True))) is False

    def test_not_false(self):
        assert _val(Not(LBool(False))) is True

    def test_nothing_propagates(self):
        n = _nothing(Not(Var("missing")))
        assert n.field == "missing"

    def test_non_bool_returns_nothing(self):
        n = _nothing(Not(LInt(1)))
        assert n.field == "expected-bool"


# Logic — If


class TestIf:
    def test_true_branch(self):
        expr = If(LBool(True), LInt(1), LInt(2))
        assert _val(expr) == 1

    def test_false_branch(self):
        expr = If(LBool(False), LInt(1), LInt(2))
        assert _val(expr) == 2

    def test_nothing_cond_propagates(self):
        expr = If(Var("missing"), LInt(1), LInt(2))
        n = _nothing(expr)
        assert n.field == "missing"

    def test_nothing_in_then_propagates(self):
        expr = If(LBool(True), Var("missing"), LInt(2))
        n = _nothing(expr)
        assert n.field == "missing"

    def test_nothing_in_else_propagates(self):
        expr = If(LBool(False), LInt(1), Var("missing"))
        n = _nothing(expr)
        assert n.field == "missing"

    def test_false_branch_not_evaluated_when_true(self):
        expr = If(LBool(True), LInt(1), Var("missing"))
        assert _val(expr) == 1

    def test_true_branch_not_evaluated_when_false(self):
        expr = If(LBool(False), Var("missing"), LInt(2))
        assert _val(expr) == 2

    def test_non_bool_cond_returns_nothing(self):
        expr = If(LInt(1), LInt(10), LInt(20))
        n = _nothing(expr)
        assert n.field == "expected-bool"


# Compare


class TestCompare:
    def test_eq_true(self):
        assert _val(Compare(CmpOp.EQ, LInt(1), LInt(1))) is True

    def test_eq_false(self):
        assert _val(Compare(CmpOp.EQ, LInt(1), LInt(2))) is False

    def test_ne_true(self):
        assert _val(Compare(CmpOp.NE, LInt(1), LInt(2))) is True

    def test_ne_false(self):
        assert _val(Compare(CmpOp.NE, LInt(1), LInt(1))) is False

    def test_lt(self):
        assert _val(Compare(CmpOp.LT, LInt(1), LInt(2))) is True
        assert _val(Compare(CmpOp.LT, LInt(2), LInt(1))) is False

    def test_le(self):
        assert _val(Compare(CmpOp.LE, LInt(1), LInt(1))) is True
        assert _val(Compare(CmpOp.LE, LInt(2), LInt(1))) is False

    def test_gt(self):
        assert _val(Compare(CmpOp.GT, LInt(2), LInt(1))) is True
        assert _val(Compare(CmpOp.GT, LInt(1), LInt(2))) is False

    def test_ge(self):
        assert _val(Compare(CmpOp.GE, LInt(1), LInt(1))) is True
        assert _val(Compare(CmpOp.GE, LInt(1), LInt(2))) is False

    def test_string_comparison(self):
        assert _val(Compare(CmpOp.EQ, LStr("a"), LStr("a"))) is True
        assert _val(Compare(CmpOp.LT, LStr("a"), LStr("b"))) is True

    # ── Negative ──────────────────────────────────────────────────────────

    def test_nothing_left_propagates(self):
        n = _nothing(Compare(CmpOp.EQ, Var("missing"), LInt(1)))
        assert n.field == "missing"

    def test_nothing_right_propagates(self):
        n = _nothing(Compare(CmpOp.EQ, LInt(1), Var("missing")))
        assert n.field == "missing"

    def test_both_nothing_propagates_left(self):
        n = _nothing(Compare(CmpOp.EQ, Var("left"), Var("right")))
        assert n.field == "left"

    def test_unknown_op_returns_nothing(self):
        n = _nothing(Compare("BadOp", LInt(1), LInt(2)))
        assert n.field == "unknown-cmp:BadOp"


# Arithmetic


class TestArith:
    def test_add(self):
        assert _val(Arith(ArithOp.ADD, LInt(3), LInt(4))) == 7

    def test_sub(self):
        assert _val(Arith(ArithOp.SUB, LInt(10), LInt(3))) == 7

    def test_mul(self):
        assert _val(Arith(ArithOp.MUL, LInt(3), LInt(4))) == 12

    def test_div(self):
        assert _val(Arith(ArithOp.DIV, LInt(10), LInt(2))) == pytest.approx(5.0)

    def test_float_arith(self):
        assert _val(Arith(ArithOp.ADD, LFloat(1.5), LFloat(2.5))) == pytest.approx(4.0)

    def test_mixed_int_float(self):
        assert _val(Arith(ArithOp.MUL, LInt(3), LFloat(2.5))) == pytest.approx(7.5)

    # ── Division edge cases ──────────────────────────────────────────────

    def test_div_by_zero_returns_nothing(self):
        n = _nothing(Arith(ArithOp.DIV, LInt(10), LInt(0)))
        assert n.field == "div-by-zero"

    def test_div_by_zero_int_zero(self):
        n = _nothing(Arith(ArithOp.DIV, LFloat(3.14), LInt(0)))
        assert n.field == "div-by-zero"

    # ── Nothing propagation ──────────────────────────────────────────────

    def test_nothing_left_propagates(self):
        n = _nothing(Arith(ArithOp.ADD, Var("missing"), LInt(1)))
        assert n.field == "missing"

    def test_nothing_right_propagates(self):
        n = _nothing(Arith(ArithOp.ADD, LInt(1), Var("missing")))
        assert n.field == "missing"

    def test_div_nothing_left_propagates(self):
        n = _nothing(Arith(ArithOp.DIV, Var("missing"), LInt(2)))
        assert n.field == "missing"

    def test_div_nothing_right_propagates(self):
        n = _nothing(Arith(ArithOp.DIV, LInt(10), Var("missing")))
        assert n.field == "missing"

    def test_unknown_op_returns_nothing(self):
        n = _nothing(Arith("BadOp", LInt(10), LInt(3)))  # type: ignore[arg-type]
        assert n.field == "unknown-arith:BadOp"


# IsSome


class TestIsSome:
    def test_some_returns_true(self):
        assert _val(IsSome(LInt(42))) is True

    def test_nothing_returns_false(self):
        assert _val(IsSome(Var("missing"))) is False

    def test_some_none_is_still_some(self):
        assert _val(IsSome(Var("x")), {"x": None}) is True

    def test_never_returns_nothing(self):
        result = _eval(IsSome(Var("missing")))
        assert isinstance(result, Some)


# UnwrapOr


class TestUnwrapOr:
    def test_some_returns_value(self):
        assert _val(UnwrapOr(LInt(42), LInt(0))) == 42

    def test_nothing_returns_default(self):
        assert _val(UnwrapOr(Var("missing"), LInt(99))) == 99

    def test_present_var_returns_var(self):
        assert _val(UnwrapOr(Var("x"), LInt(0)), {"x": 42}) == 42

    def test_default_can_be_expression(self):
        default = Arith(ArithOp.ADD, LInt(10), LInt(5))
        assert _val(UnwrapOr(Var("missing"), default)) == 15

    def test_default_not_evaluated_when_some(self):
        # If default were evaluated, Var("boom") would produce Nothing
        # But UnwrapOr returns the Some value, so default is never touched
        result = _eval(UnwrapOr(LInt(1), Var("boom")))
        assert isinstance(result, Some)
        assert result.val == 1


# Before / After — temporal references


class TestBefore:
    def test_present(self):
        ctx = {"__prev_state__": {"status": "pending"}}
        assert _val(Before("status"), ctx) == "pending"

    def test_missing_field(self):
        ctx = {"__prev_state__": {"other": 1}}
        n = _nothing(Before("status"), ctx)
        assert n.field == "before.status"

    def test_no_prev_state(self):
        n = _nothing(Before("status"), {})
        assert n.field == "before.status"

    def test_prev_state_not_dict(self):
        ctx = {"__prev_state__": "not_a_dict"}
        n = _nothing(Before("field"), ctx)
        assert n.field == "before.field"


class TestAfter:
    def test_present(self):
        ctx = {"__new_state__": {"status": "shipped"}}
        assert _val(After("status"), ctx) == "shipped"

    def test_missing_field(self):
        ctx = {"__new_state__": {"other": 1}}
        n = _nothing(After("status"), ctx)
        assert n.field == "after.status"

    def test_no_new_state(self):
        n = _nothing(After("status"), {})
        assert n.field == "after.status"


# Spec nodes — Always, Eventually, Within


class TestAlways:
    def test_evaluates_inner(self):
        assert _val(Always(LBool(True))) is True

    def test_inner_false(self):
        assert _val(Always(LBool(False))) is False

    def test_nothing_propagates(self):
        n = _nothing(Always(Var("missing")))
        assert n.field == "missing"


class TestEventually:
    def test_evaluates_inner(self):
        assert _val(Eventually(LBool(True))) is True

    def test_nothing_propagates(self):
        n = _nothing(Eventually(Var("missing")))
        assert n.field == "missing"


class TestWithin:
    def test_evaluates_inner(self):
        assert _val(Within(LBool(True), n=5)) is True

    def test_nothing_propagates(self):
        n = _nothing(Within(Var("missing"), n=5))
        assert n.field == "missing"


# step_hash threading


class TestStepHashThreading:
    def test_nothing_carries_step_hash(self):
        result = k3_eval(Var("x"), {}, step_hash="my_hash_123")
        assert isinstance(result, Nothing)
        assert result.step_hash == "my_hash_123"

    def test_default_step_hash_is_empty(self):
        result = k3_eval(Var("x"), {})
        assert isinstance(result, Nothing)
        assert result.step_hash == ""

    def test_nested_nothing_preserves_original_hash(self):
        # Field propagates the Nothing from Var, keeping the original step_hash
        expr = Field(Var("missing"), "nested")
        result = k3_eval(expr, {}, step_hash="original")
        assert isinstance(result, Nothing)
        assert result.step_hash == "original"
        assert result.field == "missing"  # root cause preserved


class TestFallthrough:
    def test_unknown_type_raises_assertion(self):
        with pytest.raises(AssertionError, match="unreachable"):
            k3_eval("not_a_k3l_node", {}, step_hash="h")  # type: ignore[arg-type]


# Compound expressions — integration


class TestCompoundExpressions:
    def test_balance_check(self):
        """balance >= withdrawal_amount"""
        ctx = {"state": {"balance": 100, "amount": 50}}
        expr = Compare(
            "Ge",
            Field(Var("state"), "balance"),
            Field(Var("state"), "amount"),
        )
        assert _val(expr, ctx) is True

    def test_balance_insufficient(self):
        ctx = {"state": {"balance": 30, "amount": 50}}
        expr = Compare(
            "Ge",
            Field(Var("state"), "balance"),
            Field(Var("state"), "amount"),
        )
        assert _val(expr, ctx) is False

    def test_compound_arithmetic(self):
        """(x + y) * 2 == 10"""
        ctx = {"x": 2, "y": 3}
        expr = Compare(
            CmpOp.EQ,
            Arith(ArithOp.MUL, Arith(ArithOp.ADD, Var("x"), Var("y")), LInt(2)),
            LInt(10),
        )
        assert _val(expr, ctx) is True

    def test_guard_with_is_some_and_unwrap(self):
        """IsSome(optional_field) AND unwrap_or(optional_field, 0) > 0"""
        ctx = {"opt": 42}
        expr = And(
            IsSome(Var("opt")),
            Compare(CmpOp.GT, UnwrapOr(Var("opt"), LInt(0)), LInt(0)),
        )
        assert _val(expr, ctx) is True

    def test_guard_with_missing_optional(self):
        ctx = {}
        expr = And(
            IsSome(Var("opt")),
            Compare(CmpOp.GT, UnwrapOr(Var("opt"), LInt(0)), LInt(0)),
        )
        # IsSome returns Some(False), And short-circuits
        assert _val(expr, ctx) is False

    def test_before_after_maintain(self):
        """After(balance) == Before(balance) - event.amount"""
        ctx = {
            "__prev_state__": {"balance": 100},
            "__new_state__": {"balance": 70},
            "event": {"amount": 30},
        }
        expr = Compare(
            CmpOp.EQ,
            After("balance"),
            Arith(ArithOp.SUB, Before("balance"), Field(Var("event"), "amount")),
        )
        assert _val(expr, ctx) is True

    def test_nested_if_with_comparison(self):
        """if x > 0 then x * 2 else 0"""
        ctx = {"x": 5}
        expr = If(
            Compare(CmpOp.GT, Var("x"), LInt(0)),
            Arith(ArithOp.MUL, Var("x"), LInt(2)),
            LInt(0),
        )
        assert _val(expr, ctx) == 10

    def test_nested_if_negative_path(self):
        ctx = {"x": -3}
        expr = If(
            Compare(CmpOp.GT, Var("x"), LInt(0)),
            Arith(ArithOp.MUL, Var("x"), LInt(2)),
            LInt(0),
        )
        assert _val(expr, ctx) == 0

    def test_chained_or(self):
        """a OR b OR c — first true wins"""
        ctx = {"a": False, "b": True}
        expr = Or(Var("a"), Or(Var("b"), LBool(False)))
        assert _val(expr, ctx) is True

    def test_div_safe_with_unwrap(self):
        """total / unwrap_or(count, 1) — safe default avoids div-by-zero"""
        ctx = {"total": 100}
        expr = Arith(ArithOp.DIV, Var("total"), UnwrapOr(Var("count"), LInt(1)))
        assert _val(expr, ctx) == pytest.approx(100.0)
