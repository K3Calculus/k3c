"""Tests for k3c.ir.expr — expression node construction and properties."""

from __future__ import annotations

import pytest

from k3c.ir.expr import (
    Abs,
    Actual,
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
    Described,
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
    Intended,
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
    Named,
    Negate,
    Not,
    Or,
    Record,
    Slice,
    Trim,
    Until,
    UnwrapOr,
    Var,
    With,
    Within,
)


class TestLiterals:
    def test_lbool(self):
        assert LBool(True).val is True
        assert LBool(False).val is False

    def test_lint(self):
        assert LInt(42).val == 42
        assert LInt(-7).val == -7

    def test_lfloat(self):
        assert LFloat(3.14).val == pytest.approx(3.14)

    def test_lstr(self):
        assert LStr("hello").val == "hello"

    def test_llist(self):
        lst = LList(elements=(LInt(1), LInt(2)))
        assert len(lst.elements) == 2


class TestFrozen:
    def test_lbool_frozen(self):
        with pytest.raises(AttributeError):
            LBool(True).val = False  # type: ignore[misc]

    def test_var_frozen(self):
        with pytest.raises(AttributeError):
            Var("x").name = "y"  # type: ignore[misc]

    def test_compare_frozen(self):
        c = Compare(CmpOp.EQ, LInt(1), LInt(2))
        with pytest.raises(AttributeError):
            c.op = CmpOp.NE  # type: ignore[misc]


class TestHashable:
    def test_literals_hashable(self):
        s = {LBool(True), LInt(42), LStr("a"), LFloat(1.0)}
        assert len(s) == 4

    def test_compound_hashable(self):
        expr = Compare(CmpOp.EQ, Var("x"), LInt(1))
        assert hash(expr) == hash(Compare(CmpOp.EQ, Var("x"), LInt(1)))

    def test_set_dedup(self):
        a = And(LBool(True), LBool(False))
        b = And(LBool(True), LBool(False))
        assert len({a, b}) == 1


class TestEquality:
    def test_same_literal(self):
        assert LInt(42) == LInt(42)
        assert LStr("a") == LStr("a")

    def test_different_literal(self):
        assert LInt(1) != LInt(2)

    def test_compound_equality(self):
        a = Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))
        b = Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))
        assert a == b

    def test_compound_inequality(self):
        a = Compare(CmpOp.GE, Var("x"), LInt(0))
        b = Compare(CmpOp.LT, Var("x"), LInt(0))
        assert a != b


class TestNodeVariety:
    """Verify all node types construct without error."""

    def test_variables(self):
        assert Var("x").name == "x"
        assert Field(Var("a"), "b").name == "b"
        assert Index(Var("list"), 0).idx == 0
        assert EventField("type").name == "type"
        assert Actual("balance").field == "balance"
        assert Intended("balance").field == "balance"

    def test_logic(self):
        And(LBool(True), LBool(False))
        Or(LBool(True), LBool(False))
        Not(LBool(True))
        If(LBool(True), LInt(1), LInt(2))
        Implies(LBool(True), LBool(False))

    def test_arithmetic(self):
        Arith(ArithOp.ADD, LInt(1), LInt(2))
        Mod(LInt(10), LInt(3))
        Negate(LInt(5))
        Abs(LInt(-5))
        Min(LInt(1), LInt(2))
        Max(LInt(1), LInt(2))

    def test_option_ops(self):
        IsSome(Var("x"))
        UnwrapOr(Var("x"), LInt(0))

    def test_temporal(self):
        Before("status")
        After("balance")
        Always(LBool(True))
        Eventually(LBool(True))
        Within(LBool(True), n=5)
        Until(LBool(True), LBool(False))

    def test_collections(self):
        ForAll("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        Exists("x", Var("items"), Compare(CmpOp.EQ, Var("x"), LInt(1)))
        Length(Var("items"))
        Contains(Var("items"), LInt(1))
        Map("x", Var("items"), Arith(ArithOp.MUL, Var("x"), LInt(2)))
        Filter("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        Fold(
            LInt(0), Var("items"), "acc", "x", Arith(ArithOp.ADD, Var("acc"), Var("x"))
        )

    def test_string_ops(self):
        Concat(LStr("a"), LStr("b"))
        Trim(LStr("  hi  "))
        Slice(LStr("hello"), LInt(0), LInt(3))
        Matches(LStr("abc"), r"\w+")

    def test_record(self):
        Record(fields=(("x", LInt(1)), ("y", LInt(2))))
        With(Var("base"), updates=(("x", LInt(99)),))

    def test_annotation(self):
        Named("my_expr", LInt(42))
        Described("A test", LInt(42))


class TestEnums:
    def test_cmp_op_values(self):
        assert CmpOp.EQ == "Eq"
        assert CmpOp.GE == "Ge"
        assert len(CmpOp) == 6

    def test_arith_op_values(self):
        assert ArithOp.ADD == "Add"
        assert ArithOp.DIV == "Div"
        assert len(ArithOp) == 4
