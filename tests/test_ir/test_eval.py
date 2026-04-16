"""Tests for k3c.ir.eval — total interpreter for K3 expressions."""

from __future__ import annotations

import pytest

from k3c.ir.eval import k3_eval
from k3c.ir.expr import (
    Abs,
    After,
    Always,
    And,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    Concat,
    Contains,
    EventField,
    Eventually,
    Exists,
    Field,
    Filter,
    Fold,
    ForAll,
    If,
    Implies,
    Index,
    IsSome,
    LBool,
    LFloat,
    LInt,
    LList,
    LStr,
    Length,
    Map,
    Matches,
    Max,
    Min,
    Mod,
    Negate,
    Not,
    Or,
    Record,
    Slice,
    Trim,
    UnwrapOr,
    Var,
    With,
    Within,
)
from k3c.ir.value import Nothing, Some


HASH = "testhash12345678"


def _eval(expr, ctx=None, step_hash=HASH):
    return k3_eval(expr, ctx or {}, step_hash)


def _val(expr, ctx=None):
    result = _eval(expr, ctx)
    assert isinstance(result, Some), f"Expected Some, got {result!r}"
    return result.val


def _nothing(expr, ctx=None):
    result = _eval(expr, ctx)
    assert isinstance(result, Nothing), f"Expected Nothing, got {result!r}"
    return result


# -- Literals ------------------------------------------------------------------


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

    def test_string(self):
        assert _val(LStr("hello")) == "hello"

    def test_string_empty(self):
        assert _val(LStr("")) == ""


# -- Variables -----------------------------------------------------------------


class TestVar:
    def test_present(self):
        assert _val(Var("x"), {"x": 42}) == 42

    def test_missing_returns_nothing(self):
        n = _nothing(Var("x"))
        assert n.field == "x"
        assert n.step_hash == HASH

    def test_none_value_is_some_none(self):
        assert _val(Var("x"), {"x": None}) is None


class TestField:
    def test_nested_access(self):
        ctx = {"order": {"amount": 100}}
        assert _val(Field(Var("order"), "amount"), ctx) == 100

    def test_missing_field(self):
        ctx = {"order": {"amount": 100}}
        n = _nothing(Field(Var("order"), "missing"), ctx)
        assert n.field == "missing"

    def test_missing_base(self):
        n = _nothing(Field(Var("missing_var"), "field"))
        assert n.field == "missing_var"

    def test_non_dict_base(self):
        ctx = {"x": 42}
        n = _nothing(Field(Var("x"), "field"), ctx)
        assert n.field == "field"

    def test_deeply_nested(self):
        ctx = {"a": {"b": {"c": 99}}}
        assert _val(Field(Field(Var("a"), "b"), "c"), ctx) == 99


class TestIndex:
    def test_valid_index(self):
        ctx = {"items": [10, 20, 30]}
        assert _val(Index(Var("items"), 1), ctx) == 20

    def test_out_of_bounds(self):
        ctx = {"items": [10]}
        n = _nothing(Index(Var("items"), 5), ctx)
        assert n.field == "[5]"


class TestEventField:
    def test_present(self):
        ctx = {"event": {"type": "Deposit", "amount": 50}}
        assert _val(EventField("amount"), ctx) == 50

    def test_missing(self):
        ctx = {"event": {"type": "Deposit"}}
        n = _nothing(EventField("missing"), ctx)
        assert n.field == "missing"


# -- Logic ---------------------------------------------------------------------


class TestAnd:
    def test_true_and_true(self):
        assert _val(And(LBool(True), LBool(True))) is True

    def test_true_and_false(self):
        assert _val(And(LBool(True), LBool(False))) is False

    def test_false_short_circuits(self):
        result = _eval(And(LBool(False), Var("missing")))
        assert isinstance(result, Some) and result.val is False

    def test_nothing_left(self):
        assert _nothing(And(Var("missing"), LBool(True))).field == "missing"

    def test_nothing_right(self):
        assert _nothing(And(LBool(True), Var("missing"))).field == "missing"

    def test_non_bool_left(self):
        assert _nothing(And(LInt(1), LBool(True))).field == "expected-bool"


class TestOr:
    def test_true_or_false(self):
        assert _val(Or(LBool(True), LBool(False))) is True

    def test_false_or_true(self):
        assert _val(Or(LBool(False), LBool(True))) is True

    def test_false_or_false(self):
        assert _val(Or(LBool(False), LBool(False))) is False

    def test_true_short_circuits(self):
        result = _eval(Or(LBool(True), Var("missing")))
        assert isinstance(result, Some) and result.val is True

    def test_nothing_left(self):
        assert _nothing(Or(Var("missing"), LBool(True))).field == "missing"


class TestNot:
    def test_not_true(self):
        assert _val(Not(LBool(True))) is False

    def test_not_false(self):
        assert _val(Not(LBool(False))) is True

    def test_nothing_propagates(self):
        assert _nothing(Not(Var("missing"))).field == "missing"

    def test_non_bool(self):
        assert _nothing(Not(LInt(1))).field == "expected-bool"


class TestIf:
    def test_true_branch(self):
        assert _val(If(LBool(True), LInt(1), LInt(2))) == 1

    def test_false_branch(self):
        assert _val(If(LBool(False), LInt(1), LInt(2))) == 2

    def test_nothing_cond(self):
        assert _nothing(If(Var("missing"), LInt(1), LInt(2))).field == "missing"

    def test_lazy_true_branch(self):
        assert _val(If(LBool(True), LInt(1), Var("missing"))) == 1

    def test_lazy_false_branch(self):
        assert _val(If(LBool(False), Var("missing"), LInt(2))) == 2


class TestImplies:
    def test_false_implies_anything(self):
        assert _val(Implies(LBool(False), Var("missing"))) is True

    def test_true_implies_true(self):
        assert _val(Implies(LBool(True), LBool(True))) is True

    def test_true_implies_false(self):
        assert _val(Implies(LBool(True), LBool(False))) is False


# -- Comparison ----------------------------------------------------------------


class TestCompare:
    def test_eq(self):
        assert _val(Compare(CmpOp.EQ, LInt(1), LInt(1))) is True
        assert _val(Compare(CmpOp.EQ, LInt(1), LInt(2))) is False

    def test_ne(self):
        assert _val(Compare(CmpOp.NE, LInt(1), LInt(2))) is True

    def test_lt(self):
        assert _val(Compare(CmpOp.LT, LInt(1), LInt(2))) is True
        assert _val(Compare(CmpOp.LT, LInt(2), LInt(1))) is False

    def test_le(self):
        assert _val(Compare(CmpOp.LE, LInt(1), LInt(1))) is True

    def test_gt(self):
        assert _val(Compare(CmpOp.GT, LInt(2), LInt(1))) is True

    def test_ge(self):
        assert _val(Compare(CmpOp.GE, LInt(1), LInt(1))) is True

    def test_string_comparison(self):
        assert _val(Compare(CmpOp.LT, LStr("a"), LStr("b"))) is True

    def test_nothing_left(self):
        assert _nothing(Compare(CmpOp.EQ, Var("missing"), LInt(1))).field == "missing"

    def test_nothing_right(self):
        assert _nothing(Compare(CmpOp.EQ, LInt(1), Var("missing"))).field == "missing"


# -- Arithmetic ----------------------------------------------------------------


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

    def test_div_by_zero(self):
        assert _nothing(Arith(ArithOp.DIV, LInt(10), LInt(0))).field == "div-by-zero"

    def test_nothing_left(self):
        assert _nothing(Arith(ArithOp.ADD, Var("missing"), LInt(1))).field == "missing"


class TestMod:
    def test_mod(self):
        assert _val(Mod(LInt(10), LInt(3))) == 1

    def test_mod_by_zero(self):
        assert _nothing(Mod(LInt(10), LInt(0))).field == "mod-by-zero"


class TestUnaryNumeric:
    def test_negate(self):
        assert _val(Negate(LInt(5))) == -5

    def test_abs(self):
        assert _val(Abs(LInt(-5))) == 5

    def test_min(self):
        assert _val(Min(LInt(3), LInt(7))) == 3

    def test_max(self):
        assert _val(Max(LInt(3), LInt(7))) == 7


# -- Option operations ---------------------------------------------------------


class TestIsSome:
    def test_some_returns_true(self):
        assert _val(IsSome(LInt(42))) is True

    def test_nothing_returns_false(self):
        assert _val(IsSome(Var("missing"))) is False

    def test_never_returns_nothing(self):
        result = _eval(IsSome(Var("missing")))
        assert isinstance(result, Some)


class TestUnwrapOr:
    def test_some_returns_value(self):
        assert _val(UnwrapOr(LInt(42), LInt(0))) == 42

    def test_nothing_returns_default(self):
        assert _val(UnwrapOr(Var("missing"), LInt(99))) == 99

    def test_default_not_evaluated_when_some(self):
        result = _eval(UnwrapOr(LInt(1), Var("boom")))
        assert isinstance(result, Some) and result.val == 1


# -- Temporal ------------------------------------------------------------------


class TestBefore:
    def test_present(self):
        ctx = {"__prev_state__": {"status": "pending"}}
        assert _val(Before("status"), ctx) == "pending"

    def test_missing_field(self):
        ctx = {"__prev_state__": {"other": 1}}
        assert _nothing(Before("status"), ctx).field == "before.status"

    def test_no_prev_state(self):
        assert _nothing(Before("status"), {}).field == "before.status"


class TestAfter:
    def test_present(self):
        ctx = {"__new_state__": {"status": "shipped"}}
        assert _val(After("status"), ctx) == "shipped"

    def test_missing_field(self):
        ctx = {"__new_state__": {"other": 1}}
        assert _nothing(After("status"), ctx).field == "after.status"


# -- Collections ---------------------------------------------------------------


class TestForAll:
    def test_all_true(self):
        ctx = {"items": [1, 2, 3]}
        expr = ForAll("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert _val(expr, ctx) is True

    def test_one_false(self):
        ctx = {"items": [1, -1, 3]}
        expr = ForAll("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert _val(expr, ctx) is False

    def test_empty_list(self):
        ctx = {"items": []}
        expr = ForAll("x", Var("items"), LBool(False))
        assert _val(expr, ctx) is True


class TestExists:
    def test_one_true(self):
        ctx = {"items": [0, 0, 1]}
        expr = Exists("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert _val(expr, ctx) is True

    def test_none_true(self):
        ctx = {"items": [0, 0, 0]}
        expr = Exists("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert _val(expr, ctx) is False


class TestLength:
    def test_list(self):
        ctx = {"items": [1, 2, 3]}
        assert _val(Length(Var("items")), ctx) == 3

    def test_string(self):
        assert _val(Length(LStr("hello"))) == 5


class TestContains:
    def test_list_contains(self):
        ctx = {"items": [1, 2, 3]}
        assert _val(Contains(Var("items"), LInt(2)), ctx) is True
        assert _val(Contains(Var("items"), LInt(5)), ctx) is False

    def test_string_contains(self):
        assert _val(Contains(LStr("hello world"), LStr("world"))) is True


class TestMap:
    def test_map_double(self):
        ctx = {"items": [1, 2, 3]}
        expr = Map("x", Var("items"), Arith(ArithOp.MUL, Var("x"), LInt(2)))
        assert _val(expr, ctx) == [2, 4, 6]


class TestFilter:
    def test_filter_positive(self):
        ctx = {"items": [-1, 0, 1, 2]}
        expr = Filter("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert _val(expr, ctx) == [1, 2]


class TestFold:
    def test_sum(self):
        ctx = {"items": [1, 2, 3]}
        expr = Fold(
            LInt(0), Var("items"), "acc", "x", Arith(ArithOp.ADD, Var("acc"), Var("x"))
        )
        assert _val(expr, ctx) == 6


# -- String operations ---------------------------------------------------------


class TestStringOps:
    def test_concat(self):
        assert _val(Concat(LStr("hello"), LStr(" world"))) == "hello world"

    def test_trim(self):
        assert _val(Trim(LStr("  hi  "))) == "hi"

    def test_slice(self):
        assert _val(Slice(LStr("hello"), LInt(0), LInt(3))) == "hel"

    def test_matches(self):
        assert _val(Matches(LStr("abc123"), r"\d+")) is True
        assert _val(Matches(LStr("abc"), r"\d+")) is False


# -- Record construction -------------------------------------------------------


class TestRecord:
    def test_construct(self):
        expr = Record(fields=(("x", LInt(1)), ("y", LInt(2))))
        assert _val(expr) == {"x": 1, "y": 2}


class TestWith:
    def test_update(self):
        ctx = {"base": {"x": 1, "y": 2}}
        expr = With(Var("base"), updates=(("x", LInt(99)),))
        result = _val(expr, ctx)
        assert result == {"x": 99, "y": 2}


class TestLList:
    def test_construct(self):
        expr = LList(elements=(LInt(1), LInt(2), LInt(3)))
        assert _val(expr) == [1, 2, 3]


# -- Spec nodes ----------------------------------------------------------------


class TestSpecNodes:
    def test_always(self):
        assert _val(Always(LBool(True))) is True

    def test_eventually(self):
        assert _val(Eventually(LBool(True))) is True

    def test_within(self):
        assert _val(Within(LBool(True), n=5)) is True


# -- step_hash threading -------------------------------------------------------


class TestStepHashThreading:
    def test_nothing_carries_step_hash(self):
        result = k3_eval(Var("x"), {}, step_hash="my_hash_123")
        assert isinstance(result, Nothing) and result.step_hash == "my_hash_123"

    def test_default_step_hash_is_empty(self):
        result = k3_eval(Var("x"), {})
        assert isinstance(result, Nothing) and result.step_hash == ""

    def test_nested_nothing_preserves_original(self):
        expr = Field(Var("missing"), "nested")
        result = k3_eval(expr, {}, step_hash="original")
        assert isinstance(result, Nothing)
        assert result.step_hash == "original"
        assert result.field == "missing"


# -- Compound expressions ------------------------------------------------------


class TestCompoundExpressions:
    def test_balance_check(self):
        ctx = {"state": {"balance": 100, "amount": 50}}
        expr = Compare(
            CmpOp.GE, Field(Var("state"), "balance"), Field(Var("state"), "amount")
        )
        assert _val(expr, ctx) is True

    def test_balance_insufficient(self):
        ctx = {"state": {"balance": 30, "amount": 50}}
        expr = Compare(
            CmpOp.GE, Field(Var("state"), "balance"), Field(Var("state"), "amount")
        )
        assert _val(expr, ctx) is False

    def test_compound_arithmetic(self):
        ctx = {"x": 2, "y": 3}
        expr = Compare(
            CmpOp.EQ,
            Arith(ArithOp.MUL, Arith(ArithOp.ADD, Var("x"), Var("y")), LInt(2)),
            LInt(10),
        )
        assert _val(expr, ctx) is True

    def test_before_after_maintain(self):
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

    def test_guard_with_is_some(self):
        ctx = {"opt": 42}
        expr = And(
            IsSome(Var("opt")),
            Compare(CmpOp.GT, UnwrapOr(Var("opt"), LInt(0)), LInt(0)),
        )
        assert _val(expr, ctx) is True

    def test_guard_with_missing_optional(self):
        expr = And(
            IsSome(Var("opt")),
            Compare(CmpOp.GT, UnwrapOr(Var("opt"), LInt(0)), LInt(0)),
        )
        assert _val(expr, {}) is False


class TestFallthrough:
    def test_unknown_type_raises_assertion(self):
        with pytest.raises(AssertionError, match="unreachable"):
            k3_eval("not_an_expr", {}, step_hash="h")  # type: ignore[arg-type]
