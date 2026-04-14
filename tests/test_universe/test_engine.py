"""Tests for k3c.universe.engine — the apply() causal step."""

from __future__ import annotations

import pytest

from k3c.lang.compile import compile_spec
from k3c.lang.ir import (
    After,
    Always,
    ArithOp,
    Arith,
    Before,
    CmpOp,
    Compare,
    EventField,
    Field,
    Implies,
    LBool,
    LInt,
    LStr,
    Var,
    With,
)
from k3c.spec.builder import Spec
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import Impossible, Ok, Violated, WhyKind
from k3c.universe.engine import apply, _hash_step


def _bank_spec():
    return (
        Spec("bank")
        .state0({"balance": 100})
        .permit(
            "has_funds",
            when=Compare(
                CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
            ),
        )
        .maintain(
            "non_negative",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
        )
        .build()
    )


def _bank_transition(state, event):
    if event.get("type") == "Withdraw":
        return {**state, "balance": state["balance"] - event["amount"]}
    if event.get("type") == "Deposit":
        return {**state, "balance": state["balance"] + event["amount"]}
    return state


def _apply_bank(state, ctx, event):
    compiled = compile_spec(_bank_spec())
    return apply(state, ctx, event, compiled, _bank_transition)


class TestApplyOk:
    def test_simple_withdrawal(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 100}, ctx, {"type": "Withdraw", "amount": 30})
        assert isinstance(result, Ok)
        assert result.state["balance"] == 70

    def test_returns_new_ctx(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 100}, ctx, {"type": "Withdraw", "amount": 10})
        assert isinstance(result, Ok)
        assert result.ctx is not ctx

    def test_step_hash_present(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 100}, ctx, {"type": "Withdraw", "amount": 10})
        assert isinstance(result, Ok)
        assert len(result.step_hash) == 64  # SHA-256 hex

    def test_step_hash_chained(self):
        ctx = SpecCtx.initial({"balance": 100})
        r1 = _apply_bank({"balance": 100}, ctx, {"type": "Withdraw", "amount": 10})
        r2 = _apply_bank(r1.state, r1.ctx, {"type": "Withdraw", "amount": 10})
        assert isinstance(r1, Ok)
        assert isinstance(r2, Ok)
        assert r1.step_hash != r2.step_hash

    def test_deposit(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 100}, ctx, {"type": "Deposit", "amount": 50})
        assert isinstance(result, Ok)
        assert result.state["balance"] == 150

    def test_noop_event(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 100}, ctx, {"type": "Other", "amount": 0})
        assert isinstance(result, Ok)
        assert result.state["balance"] == 100


class TestApplyImpossible:
    def test_insufficient_funds(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 20}, ctx, {"type": "Withdraw", "amount": 50})
        assert isinstance(result, Impossible)
        assert result.why.rule == "has_funds"
        assert result.why.kind == WhyKind.PERMIT

    def test_impossible_has_step_hash(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 20}, ctx, {"type": "Withdraw", "amount": 50})
        assert isinstance(result, Impossible)
        assert len(result.why.step_hash) == 64

    def test_impossible_has_event(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 20}, ctx, {"type": "Withdraw", "amount": 50})
        assert isinstance(result, Impossible)
        assert result.why.event["amount"] == 50

    def test_impossible_after_is_none(self):
        ctx = SpecCtx.initial({"balance": 100})
        result = _apply_bank({"balance": 20}, ctx, {"type": "Withdraw", "amount": 50})
        assert isinstance(result, Impossible)
        assert result.why.after is None


class TestApplyViolated:
    def test_invariant_violated(self):
        ctx = SpecCtx.initial({"balance": 100})
        compiled = compile_spec(_bank_spec())
        result = apply(
            {"balance": 100},
            ctx,
            {"type": "Other", "amount": 0},
            compiled,
            lambda s, e: {**s, "balance": -1},
        )
        assert isinstance(result, Violated)
        assert result.why.rule == "non_negative"
        assert result.why.kind == WhyKind.MAINTAIN

    def test_violated_has_before_and_after(self):
        ctx = SpecCtx.initial({"balance": 100})
        compiled = compile_spec(_bank_spec())
        result = apply(
            {"balance": 100},
            ctx,
            {"type": "Other", "amount": 0},
            compiled,
            lambda s, e: {**s, "balance": -1},
        )
        assert isinstance(result, Violated)
        assert result.why.after is not None
        assert result.why.after["balance"] == -1


class TestHashStep:
    def test_deterministic(self):
        h1 = _hash_step({"x": 1}, {"e": 1}, "")
        h2 = _hash_step({"x": 1}, {"e": 1}, "")
        assert h1 == h2

    def test_different_state_different_hash(self):
        h1 = _hash_step({"x": 1}, {"e": 1}, "")
        h2 = _hash_step({"x": 2}, {"e": 1}, "")
        assert h1 != h2

    def test_chained(self):
        h1 = _hash_step({"x": 1}, {"e": 1}, "")
        h2 = _hash_step({"x": 1}, {"e": 1}, h1)
        assert h1 != h2

    def test_sha256_default(self):
        h = _hash_step({"x": 1}, {"e": 1}, "")
        assert len(h) == 64

    def test_blake2b(self):
        h = _hash_step({"x": 1}, {"e": 1}, "", hash_fn="blake2b")
        assert len(h) == 128  # blake2b produces 128 hex chars

    def test_unknown_hash_fn_raises(self):
        with pytest.raises(ValueError, match="Unknown hash_fn"):
            _hash_step({"x": 1}, {"e": 1}, "", hash_fn="bogus")


class TestDecode:
    def test_decode_transforms_event(self):
        spec = (
            Spec("decoded")
            .state0({"x": 0})
            .decode(lambda e: {"type": e.get("t"), "amount": e.get("a", 0)})
            .permit("always", when=LBool(True))
            .build()
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = apply(
            {"x": 0},
            ctx,
            {"t": "Deposit", "a": 50},
            compiled,
            lambda s, e: {**s, "x": e.get("amount", 0)},
        )
        assert isinstance(result, Ok)
        assert result.state["x"] == 50

    def test_no_decode_passes_event_through(self):
        spec = Spec("raw").state0({"x": 0}).permit("ok", when=LBool(True)).build()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = apply(
            {"x": 0},
            ctx,
            {"type": "A", "val": 42},
            compiled,
            lambda s, e: {**s, "x": e.get("val", 0)},
        )
        assert isinstance(result, Ok)
        assert result.state["x"] == 42


class TestKorrelation:
    def test_korrelation_pass(self):
        spec = (
            Spec("korr")
            .state0({"balance": 100})
            .permit("ok", when=LBool(True))
            .korrelate(lift=lambda s: {"balance": s["balance"]})
            .build()
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = apply(
            {"balance": 100},
            ctx,
            {"type": "X"},
            compiled,
            lambda s, e: s,
        )
        assert isinstance(result, Ok)

    def test_korrelation_fail(self):
        spec = (
            Spec("korr")
            .state0({"balance": 100})
            .permit("ok", when=LBool(True))
            .korrelate(lift=lambda s: {"balance": s["balance"]})
            .build()
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = apply(
            {"balance": 100},
            ctx,
            {"type": "X"},
            compiled,
            lambda s, e: {**s, "balance": 999},
        )
        assert isinstance(result, Violated)
        assert result.why.kind == WhyKind.KORRELATE
        assert result.why.expected is not None


class TestRequire:
    def test_require_advances_spec_state(self):
        spec = (
            Spec("req")
            .state0({"phase": "START"})
            .permit("ok", when=LBool(True))
            .require(
                "advance",
                on="Next",
                transition=With(Var("spec_state"), (("phase", LStr("DONE")),)),
            )
            .build()
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = apply(
            {"x": 1},
            ctx,
            {"type": "Next"},
            compiled,
            lambda s, e: s,
        )
        assert isinstance(result, Ok)
        assert result.ctx.spec_state["phase"] == "DONE"

    def test_no_matching_require_leaves_spec_state(self):
        spec = (
            Spec("req")
            .state0({"phase": "START"})
            .permit("ok", when=LBool(True))
            .require(
                "advance",
                on="Next",
                transition=With(Var("spec_state"), (("phase", LStr("DONE")),)),
            )
            .build()
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = apply(
            {"x": 1},
            ctx,
            {"type": "Other"},
            compiled,
            lambda s, e: s,
        )
        assert isinstance(result, Ok)
        assert result.ctx.spec_state["phase"] == "START"


class TestBeforeAfter:
    def test_before_after_maintain(self):
        """After(balance) == Before(balance) - event.amount"""
        spec = (
            Spec("ba")
            .state0({"balance": 100})
            .permit("ok", when=LBool(True))
            .maintain(
                "debit_rule",
                expr=Always(
                    Implies(
                        Compare(CmpOp.EQ, EventField("type"), LStr("Withdraw")),
                        Compare(
                            CmpOp.EQ,
                            After("balance"),
                            Arith(ArithOp.SUB, Before("balance"), EventField("amount")),
                        ),
                    )
                ),
            )
            .build()
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)

        # Correct transition
        result = apply(
            {"balance": 100},
            ctx,
            {"type": "Withdraw", "amount": 30},
            compiled,
            lambda s, e: {**s, "balance": s["balance"] - e["amount"]},
        )
        assert isinstance(result, Ok)

        # Incorrect transition
        result2 = apply(
            {"balance": 100},
            ctx,
            {"type": "Withdraw", "amount": 30},
            compiled,
            lambda s, e: {**s, "balance": 999},
        )
        assert isinstance(result2, Violated)


class TestTraceRing:
    def test_trace_accumulates(self):
        spec = Spec("trace").state0({"x": 0}).permit("ok", when=LBool(True)).build()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)

        r1 = apply({"x": 0}, ctx, {"type": "A"}, compiled, lambda s, e: s)
        assert isinstance(r1, Ok)
        r2 = apply({"x": 0}, r1.ctx, {"type": "B"}, compiled, lambda s, e: s)
        assert isinstance(r2, Ok)

        assert len(r2.ctx.trace_ring) == 2
        assert r2.ctx.trace_ring[0]["type"] == "A"
        assert r2.ctx.trace_ring[1]["type"] == "B"


class TestMultiplePermits:
    def test_all_permits_must_pass(self):
        spec = (
            Spec("multi")
            .state0({"balance": 100, "active": True})
            .permit(
                "has_funds",
                when=Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0)),
            )
            .permit(
                "is_active",
                when=Compare(CmpOp.EQ, Field(Var("state"), "active"), LBool(True)),
            )
            .build()
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)

        # Both pass
        r1 = apply(
            {"balance": 100, "active": True},
            ctx,
            {"type": "X"},
            compiled,
            lambda s, e: s,
        )
        assert isinstance(r1, Ok)

        # Second fails
        r2 = apply(
            {"balance": 100, "active": False},
            ctx,
            {"type": "X"},
            compiled,
            lambda s, e: s,
        )
        assert isinstance(r2, Impossible)
        assert r2.why.rule == "is_active"
