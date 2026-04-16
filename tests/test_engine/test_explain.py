"""Tests for k3c.engine.explain -- dry-run with full eval trace."""

from __future__ import annotations

from k3c.engine.explain import ExplainResult, TracePhase, TraceVerdict, explain
from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Impossible, Ok
from k3c.ir.expr import Always, CmpOp, Compare, EventField, Field, LInt, Var
from k3c.spec.compile import compile_spec
from k3c.spec.model import Maintain, Permit, Projection, Spec


def _bank_spec():
    return Spec(
        name="bank",
        state0={"balance": 100},
        permits=(
            Permit(
                name="has_funds",
                on="Withdraw",
                when=Compare(
                    CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
                ),
            ),
        ),
        maintains=(
            Maintain(
                name="non_negative",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            ),
        ),
        projections=(Projection(name="balance", expr=Field(Var("state"), "balance")),),
    )


def _transition(state, event):
    match event.get("type"):
        case "Deposit":
            return {**state, "balance": state["balance"] + event["amount"]}
        case "Withdraw":
            return {**state, "balance": state["balance"] - event["amount"]}
        case _:
            return state


class TestExplain:
    def test_ok_deposit(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = explain(
            {"balance": 100},
            ctx,
            {"type": "Deposit", "amount": 50},
            compiled,
            _transition,
        )

        assert isinstance(result, ExplainResult)
        assert result.passed
        assert isinstance(result.result, Ok)
        assert len(result.trace) > 0
        assert result.step_hash != ""

    def test_impossible_withdrawal(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = explain(
            {"balance": 100},
            ctx,
            {"type": "Withdraw", "amount": 999},
            compiled,
            _transition,
        )

        assert not result.passed
        assert isinstance(result.result, Impossible)

        # Find guard trace entry
        guard_entries = [e for e in result.trace if e.phase == TracePhase.GUARD]
        assert any(e.verdict == TraceVerdict.FAIL for e in guard_entries)

    def test_guard_skip_non_matching_type(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = explain(
            {"balance": 100},
            ctx,
            {"type": "Deposit", "amount": 50},
            compiled,
            _transition,
        )

        guard_entries = [e for e in result.trace if e.phase == TracePhase.GUARD]
        assert any(e.verdict == TraceVerdict.SKIP for e in guard_entries)

    def test_decode_skip_when_no_plan(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = explain(
            {"balance": 100},
            ctx,
            {"type": "Deposit", "amount": 50},
            compiled,
            _transition,
        )

        decode_entries = [e for e in result.trace if e.phase == TracePhase.DECODE]
        assert len(decode_entries) == 1
        assert decode_entries[0].verdict == TraceVerdict.SKIP

    def test_safety_trace(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = explain(
            {"balance": 100},
            ctx,
            {"type": "Deposit", "amount": 50},
            compiled,
            _transition,
        )

        safety_entries = [e for e in result.trace if e.phase == TracePhase.SAFETY]
        assert len(safety_entries) == 1
        assert safety_entries[0].verdict == TraceVerdict.PASS

    def test_projection_trace(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = explain(
            {"balance": 100},
            ctx,
            {"type": "Deposit", "amount": 50},
            compiled,
            _transition,
        )

        proj_entries = [e for e in result.trace if e.phase == TracePhase.PROJECTION]
        assert len(proj_entries) == 1
        assert proj_entries[0].clause == "balance"
        assert proj_entries[0].value == 150

    def test_summary_output(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        result = explain(
            {"balance": 100},
            ctx,
            {"type": "Deposit", "amount": 50},
            compiled,
            _transition,
        )

        summary = result.summary()
        assert "ExplainResult" in summary
        assert "step_hash" in summary

    def test_state_not_mutated(self):
        spec = _bank_spec()
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)
        state = {"balance": 100}
        explain(state, ctx, {"type": "Deposit", "amount": 50}, compiled, _transition)
        assert state == {"balance": 100}

    def test_transition_error(self):
        spec = Spec(name="test", state0={"x": 1})
        compiled = compile_spec(spec)
        ctx = SpecCtx.initial(spec.state0)

        def bad_transition(s, e):
            raise RuntimeError("boom")

        result = explain({"x": 1}, ctx, {"type": "test"}, compiled, bad_transition)
        transition_entries = [
            e for e in result.trace if e.phase == TracePhase.TRANSITION
        ]
        assert any(e.verdict == TraceVerdict.ERROR for e in transition_entries)
