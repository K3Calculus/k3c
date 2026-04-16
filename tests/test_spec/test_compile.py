"""Tests for k3c.spec.compile -- maintain classification and CompiledSpec."""

from __future__ import annotations

from k3c.ir.expr import (
    Always,
    And,
    CmpOp,
    Compare,
    Eventually,
    Field,
    Implies,
    LBool,
    LInt,
    Var,
    Within,
)
from k3c.spec.compile import (
    CompiledSpec,
    MaintainKind,
    classify_maintain,
    compile_spec,
)
from k3c.spec.model import Maintain, Permit, Require, Spec


class TestClassifyMaintain:
    def test_safety_always(self):
        clause = Maintain(name="inv", expr=Always(Compare(CmpOp.GE, Var("x"), LInt(0))))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.SAFETY
        assert c.name == "inv"
        assert c.n is None
        # Inner expression is unwrapped from Always
        assert isinstance(c.expr, Compare)

    def test_safety_bare(self):
        clause = Maintain(name="inv", expr=Compare(CmpOp.GE, Var("x"), LInt(0)))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.SAFETY

    def test_bounded_within(self):
        clause = Maintain(name="timer", expr=Always(Within(LBool(True), n=5)))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.BOUNDED
        assert c.n == 5

    def test_bounded_implies_within(self):
        clause = Maintain(
            name="response",
            expr=Always(
                Implies(
                    Compare(CmpOp.EQ, Field(Var("event"), "type"), LInt(1)),
                    Within(LBool(True), n=10),
                )
            ),
        )
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.BOUNDED
        assert c.n == 10

    def test_liveness_eventually(self):
        clause = Maintain(name="live", expr=Always(Eventually(LBool(True))))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.LIVENESS
        assert c.n is None

    def test_liveness_implies_eventually(self):
        clause = Maintain(
            name="response",
            expr=Always(Implies(LBool(True), Eventually(LBool(True)))),
        )
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.LIVENESS

    def test_safety_and_compound(self):
        clause = Maintain(
            name="compound",
            expr=Always(
                And(
                    Compare(CmpOp.GE, Var("x"), LInt(0)),
                    Compare(CmpOp.LE, Var("x"), LInt(100)),
                )
            ),
        )
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.SAFETY


class TestCompileSpec:
    def test_basic_compile(self):
        spec = Spec(
            name="bank",
            state0={"balance": 100},
            permits=(
                Permit(
                    name="has_funds",
                    on="Withdraw",
                    when=Compare(CmpOp.GE, Var("balance"), LInt(0)),
                ),
                Permit(
                    name="valid_deposit", when=Compare(CmpOp.GT, Var("amount"), LInt(0))
                ),
            ),
            requires=(Require(name="debit", on="Withdraw", transition=LInt(0)),),
            maintains=(
                Maintain(
                    name="non_negative",
                    expr=Always(Compare(CmpOp.GE, Var("balance"), LInt(0))),
                ),
                Maintain(name="timer", expr=Always(Within(LBool(True), n=5))),
                Maintain(name="live", expr=Always(Eventually(LBool(True)))),
            ),
        )
        compiled = compile_spec(spec)

        assert compiled.name == "bank"
        assert compiled.state0 == {"balance": 100}
        assert len(compiled.permits) == 2
        assert "Withdraw" in compiled.requires
        assert len(compiled.safety) == 1
        assert len(compiled.bounded) == 1
        assert len(compiled.liveness) == 1
        assert compiled.hash_fn == "sha256"

    def test_custom_hash_fn(self):
        spec = Spec(name="test", state0={"x": 0})
        compiled = compile_spec(spec, hash_fn="blake2b")
        assert compiled.hash_fn == "blake2b"

    def test_empty_spec(self):
        spec = Spec(name="empty", state0={})
        compiled = compile_spec(spec)
        assert compiled.permits == ()
        assert compiled.requires == {}
        assert compiled.safety == ()
        assert compiled.bounded == ()
        assert compiled.liveness == ()

    def test_compiled_spec_is_frozen(self):
        spec = Spec(name="test", state0={"x": 0})
        compiled = compile_spec(spec)
        assert isinstance(compiled, CompiledSpec)
