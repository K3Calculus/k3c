"""Tests for k3c.engine.step -- apply_step() causal pipeline."""

from __future__ import annotations

from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Impossible, Ok, Violated, WhyKind
from k3c.engine.step import apply_step
from k3c.ir.expr import (
    Always,
    Arith,
    ArithOp,
    CmpOp,
    Compare,
    EventField,
    Eventually,
    Field,
    LBool,
    LInt,
    Record,
    Var,
)
from k3c.spec.compile import compile_spec
from k3c.spec.model import (
    Korrelator,
    Maintain,
    Output,
    Permit,
    Projection,
    Require,
    Spec,
)


# -- Helpers -------------------------------------------------------------------


def _bank_spec():
    return Spec(
        name="bank",
        state0={"balance": 100},
        permits=(
            Permit(
                name="has_funds",
                on="Withdraw",
                when=Compare(
                    CmpOp.GE,
                    Field(Var("state"), "balance"),
                    EventField("amount"),
                ),
            ),
        ),
        maintains=(
            Maintain(
                name="non_negative",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            ),
        ),
    )


def _bank_transition(state, event):
    match event.get("type"):
        case "Deposit":
            return {**state, "balance": state["balance"] + event["amount"]}
        case "Withdraw":
            return {**state, "balance": state["balance"] - event["amount"]}
        case _:
            return state


def _apply(spec, event, state=None, transition=None):
    compiled = compile_spec(spec)
    s = state if state is not None else spec.state0
    ctx = SpecCtx.initial(spec.state0)
    return apply_step(
        state=s,
        ctx=ctx,
        raw_event=event,
        compiled=compiled,
        transition=transition or _bank_transition,
    )


# -- Basic pipeline ------------------------------------------------------------


class TestBasicPipeline:
    def test_ok_deposit(self):
        result = _apply(_bank_spec(), {"type": "Deposit", "amount": 50})
        assert isinstance(result, Ok)
        assert result.state["balance"] == 150

    def test_ok_withdraw(self):
        result = _apply(_bank_spec(), {"type": "Withdraw", "amount": 30})
        assert isinstance(result, Ok)
        assert result.state["balance"] == 70

    def test_impossible_insufficient_funds(self):
        result = _apply(
            _bank_spec(),
            {"type": "Withdraw", "amount": 200},
            state={"balance": 50},
        )
        assert isinstance(result, Impossible)
        assert result.why.kind == WhyKind.PERMIT

    def test_violated_negative_balance(self):
        spec = Spec(
            name="bank_no_guard",
            state0={"balance": 100},
            maintains=(
                Maintain(
                    name="non_negative",
                    expr=Always(
                        Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))
                    ),
                ),
            ),
        )
        result = _apply(
            spec,
            {"type": "Withdraw", "amount": 200},
            state={"balance": 50},
        )
        assert isinstance(result, Violated)
        assert result.why.kind == WhyKind.MAINTAIN


# -- Step hash -----------------------------------------------------------------


class TestStepHash:
    def test_deterministic(self):
        spec = _bank_spec()
        r1 = _apply(spec, {"type": "Deposit", "amount": 50})
        r2 = _apply(spec, {"type": "Deposit", "amount": 50})
        assert isinstance(r1, Ok) and isinstance(r2, Ok)
        assert r1.step_hash == r2.step_hash

    def test_different_events_different_hash(self):
        spec = _bank_spec()
        r1 = _apply(spec, {"type": "Deposit", "amount": 50})
        r2 = _apply(spec, {"type": "Deposit", "amount": 51})
        assert isinstance(r1, Ok) and isinstance(r2, Ok)
        assert r1.step_hash != r2.step_hash

    def test_hash_non_empty(self):
        result = _apply(_bank_spec(), {"type": "Deposit", "amount": 1})
        assert isinstance(result, Ok)
        assert len(result.step_hash) == 64  # SHA-256 hex


# -- Guard evaluation ----------------------------------------------------------


class TestGuards:
    def test_permit_skip_unmatched_type(self):
        spec = Spec(
            name="test",
            state0={"x": 0},
            permits=(Permit(name="only_a", on="TypeA", when=LBool(False)),),
        )
        # TypeB should not be checked against the TypeA guard
        result = _apply(spec, {"type": "TypeB"}, transition=lambda s, e: s)
        assert isinstance(result, Ok)

    def test_missing_field_impossible(self):
        spec = Spec(
            name="test",
            state0={"x": 0},
            permits=(Permit(name="needs_amount", when=EventField("amount")),),
        )
        result = _apply(spec, {"type": "Test"}, transition=lambda s, e: s)
        assert isinstance(result, Impossible)
        assert result.why.kind == WhyKind.MISSING


# -- Projections ---------------------------------------------------------------


class TestProjections:
    def test_declarative_projection(self):
        spec = Spec(
            name="test",
            state0={"balance": 100},
            projections=(
                Projection(name="balance", expr=Field(Var("state"), "balance")),
            ),
        )
        result = _apply(spec, {"type": "Deposit", "amount": 50})
        assert isinstance(result, Ok)
        assert result.projections["balance"] == 150


# -- Outputs -------------------------------------------------------------------


class TestOutputs:
    def test_declarative_output(self):
        spec = Spec(
            name="test",
            state0={"balance": 100},
            outputs=(
                Output(
                    name="balance_report",
                    expr=Record(
                        fields=(
                            ("balance", Field(Var("state"), "balance")),
                            ("event_type", EventField("type")),
                        )
                    ),
                ),
            ),
        )
        result = _apply(spec, {"type": "Deposit", "amount": 50})
        assert isinstance(result, Ok)
        assert len(result.outputs) == 1
        assert result.outputs[0]["balance"] == 150

    def test_output_on_filter(self):
        spec = Spec(
            name="test",
            state0={"balance": 100},
            outputs=(Output(name="only_withdraw", expr=LBool(True), on="Withdraw"),),
        )
        result = _apply(spec, {"type": "Deposit", "amount": 50})
        assert isinstance(result, Ok)
        assert len(result.outputs) == 0


# -- U.require ----------------------------------------------------------------


class TestRequire:
    def test_spec_state_advance(self):
        spec = Spec(
            name="test",
            state0={"balance": 100},
            requires=(
                Require(
                    name="track_balance",
                    on="Deposit",
                    transition=Record(
                        fields=(
                            (
                                "balance",
                                Arith(
                                    ArithOp.ADD,
                                    Field(Var("spec_state"), "balance"),
                                    EventField("amount"),
                                ),
                            ),
                        )
                    ),
                ),
            ),
        )
        result = _apply(spec, {"type": "Deposit", "amount": 50})
        assert isinstance(result, Ok)
        assert result.ctx.spec_state["balance"] == 150


# -- Korrelation ---------------------------------------------------------------


class TestKorrelation:
    def test_korrelation_pass(self):
        spec = Spec(
            name="test",
            state0={"balance": 100},
            requires=(
                Require(
                    name="track",
                    on="Deposit",
                    transition=Record(
                        fields=(
                            (
                                "balance",
                                Arith(
                                    ArithOp.ADD,
                                    Field(Var("spec_state"), "balance"),
                                    EventField("amount"),
                                ),
                            ),
                        )
                    ),
                ),
            ),
            korrelator=Korrelator(
                actual=Field(Var("state"), "balance"),
                intended=Field(Var("spec_state"), "balance"),
            ),
        )
        result = _apply(spec, {"type": "Deposit", "amount": 50})
        assert isinstance(result, Ok)

    def test_korrelation_fail(self):
        def bad_transition(state, event):
            return {**state, "balance": state["balance"] + 999}

        spec = Spec(
            name="test",
            state0={"balance": 100},
            requires=(
                Require(
                    name="track",
                    on="Deposit",
                    transition=Record(
                        fields=(
                            (
                                "balance",
                                Arith(
                                    ArithOp.ADD,
                                    Field(Var("spec_state"), "balance"),
                                    EventField("amount"),
                                ),
                            ),
                        )
                    ),
                ),
            ),
            korrelator=Korrelator(
                actual=Field(Var("state"), "balance"),
                intended=Field(Var("spec_state"), "balance"),
            ),
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = apply_step(
            state={"balance": 100},
            ctx=ctx,
            raw_event={"type": "Deposit", "amount": 50},
            compiled=compiled,
            transition=bad_transition,
        )
        assert isinstance(result, Violated)
        assert result.why.kind == WhyKind.KORRELATE


# -- Liveness ------------------------------------------------------------------


class TestLiveness:
    def test_eventually_discharged(self):
        spec = Spec(
            name="test",
            state0={"done": False},
            maintains=(
                Maintain(
                    name="must_finish",
                    expr=Always(
                        Eventually(
                            Compare(CmpOp.EQ, Field(Var("state"), "done"), LBool(True))
                        )
                    ),
                ),
            ),
        )
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)

        def transition(s, e):
            if e.get("type") == "Finish":
                return {**s, "done": True}
            return s

        # Apply a non-finishing event
        r1 = apply_step(
            state={"done": False},
            ctx=ctx,
            raw_event={"type": "Work"},
            compiled=compiled,
            transition=transition,
        )
        assert isinstance(r1, Ok)
        assert "must_finish" in r1.ctx.active_obligations

        # Apply the finishing event
        r2 = apply_step(
            state=r1.state,
            ctx=r1.ctx,
            raw_event={"type": "Finish"},
            compiled=compiled,
            transition=transition,
        )
        assert isinstance(r2, Ok)
        assert "must_finish" not in r2.ctx.active_obligations


# -- Chained apply -------------------------------------------------------------


class TestChained:
    def test_sequence_of_applies(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        state = {"balance": 100}

        events = [
            {"type": "Deposit", "amount": 50},
            {"type": "Withdraw", "amount": 30},
            {"type": "Deposit", "amount": 10},
        ]

        for event in events:
            result = apply_step(
                state=state,
                ctx=ctx,
                raw_event=event,
                compiled=compiled,
                transition=_bank_transition,
            )
            assert isinstance(result, Ok)
            state = result.state
            ctx = result.ctx

        assert state["balance"] == 130
