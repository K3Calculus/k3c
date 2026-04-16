"""Tests for AllOf, AnyOf, In expression nodes."""

from k3c.ir.eval import k3_eval
from k3c.ir.expr import (
    AllOf,
    AnyOf,
    CmpOp,
    Compare,
    EventField,
    Field,
    In,
    LBool,
    LInt,
    LStr,
    Var,
)
from k3c.ir.value import Nothing, Some


class TestAllOf:
    def test_all_true(self):
        expr = AllOf(exprs=(LBool(True), LBool(True), LBool(True)))
        assert k3_eval(expr, {}, "") == Some(True)

    def test_one_false(self):
        expr = AllOf(exprs=(LBool(True), LBool(False), LBool(True)))
        assert k3_eval(expr, {}, "") == Some(False)

    def test_short_circuits_on_false(self):
        # Third expr would fail if evaluated, but short-circuit prevents it
        expr = AllOf(exprs=(LBool(False), Field(Var("missing"), "x")))
        assert k3_eval(expr, {}, "") == Some(False)

    def test_nothing_propagates(self):
        expr = AllOf(exprs=(LBool(True), Field(Var("missing"), "x")))
        result = k3_eval(expr, {}, "")
        assert isinstance(result, Nothing)

    def test_empty_is_true(self):
        assert k3_eval(AllOf(exprs=()), {}, "") == Some(True)

    def test_with_comparisons(self):
        ctx = {"state": {"a": 1, "b": 2, "c": 3}}
        expr = AllOf(exprs=(
            Compare(CmpOp.GT, Field(Var("state"), "a"), LInt(0)),
            Compare(CmpOp.GT, Field(Var("state"), "b"), LInt(0)),
            Compare(CmpOp.GT, Field(Var("state"), "c"), LInt(0)),
        ))
        assert k3_eval(expr, ctx, "") == Some(True)


class TestAnyOf:
    def test_all_false(self):
        expr = AnyOf(exprs=(LBool(False), LBool(False)))
        assert k3_eval(expr, {}, "") == Some(False)

    def test_one_true(self):
        expr = AnyOf(exprs=(LBool(False), LBool(True), LBool(False)))
        assert k3_eval(expr, {}, "") == Some(True)

    def test_short_circuits_on_true(self):
        expr = AnyOf(exprs=(LBool(True), Field(Var("missing"), "x")))
        assert k3_eval(expr, {}, "") == Some(True)

    def test_empty_is_false(self):
        assert k3_eval(AnyOf(exprs=()), {}, "") == Some(False)


class TestIn:
    def test_in_match(self):
        ctx = {"state": {"status": "pending"}}
        expr = In(
            expr=Field(Var("state"), "status"),
            values=(LStr("pending"), LStr("confirmed"), LStr("shipped")),
        )
        assert k3_eval(expr, ctx, "") == Some(True)

    def test_in_no_match(self):
        ctx = {"state": {"status": "cancelled"}}
        expr = In(
            expr=Field(Var("state"), "status"),
            values=(LStr("pending"), LStr("confirmed")),
        )
        assert k3_eval(expr, ctx, "") == Some(False)

    def test_in_with_integers(self):
        ctx = {"event": {"code": 3}}
        expr = In(
            expr=EventField("code"),
            values=(LInt(1), LInt(2), LInt(3)),
        )
        assert k3_eval(expr, ctx, "") == Some(True)

    def test_in_nothing_propagates(self):
        expr = In(
            expr=Field(Var("missing"), "x"),
            values=(LStr("a"),),
        )
        result = k3_eval(expr, {}, "")
        assert isinstance(result, Nothing)
