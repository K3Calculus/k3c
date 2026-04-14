"""Tests for k3c.universe.explain — dry-run with full eval trace."""

from __future__ import annotations


from k3c.lang.ir import (
    Always,
    CmpOp,
    Compare,
    EventField,
    Field,
    LBool,
    LInt,
    Var,
)
from k3c.spec.builder import Spec
from k3c.spec.result import Impossible, Ok, Violated
from k3c.universe.explain import ExplainResult, TracePhase, TraceVerdict
from k3c.universe.universe import universe


class _BankSystem:
    def transition(self, s, e):
        if e.get("type") == "Withdraw":
            return {**s, "balance": s["balance"] - e["amount"]}
        if e.get("type") == "Deposit":
            return {**s, "balance": s["balance"] + e["amount"]}
        return s


def _bank_spec():
    return (
        Spec("bank")
        .state0({"balance": 100})
        .permit(
            "has_funds",
            when=Compare(
                CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
            ),
            on="Withdraw",
        )
        .maintain(
            "non_negative",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
        )
        .build()
    )


def _bank():
    return universe(_BankSystem(), _bank_spec())


class TestExplainOk:
    def test_ok_event(self):
        u = _bank()
        result = u.explain({"type": "Withdraw", "amount": 30})
        assert isinstance(result, ExplainResult)
        assert result.passed
        assert isinstance(result.result, Ok)

    def test_state_unchanged(self):
        u = _bank()
        u.explain({"type": "Withdraw", "amount": 30})
        assert u.state["balance"] == 100

    def test_has_step_hash(self):
        u = _bank()
        result = u.explain({"type": "Deposit", "amount": 10})
        assert len(result.step_hash) == 64

    def test_decoded_event(self):
        u = _bank()
        result = u.explain({"type": "Withdraw", "amount": 50})
        assert result.decoded_event["type"] == "Withdraw"
        assert result.decoded_event["amount"] == 50


class TestExplainTrace:
    def test_trace_has_decode(self):
        u = _bank()
        result = u.explain({"type": "Deposit", "amount": 10})
        decode_entries = [e for e in result.trace if e.phase == TracePhase.DECODE]
        assert len(decode_entries) == 1

    def test_trace_has_guards(self):
        u = _bank()
        result = u.explain({"type": "Withdraw", "amount": 30})
        guard_entries = [e for e in result.trace if e.phase == TracePhase.GUARD]
        assert len(guard_entries) >= 1

    def test_guard_pass_on_ok(self):
        u = _bank()
        result = u.explain({"type": "Withdraw", "amount": 30})
        guard = next(
            e
            for e in result.trace
            if e.phase == TracePhase.GUARD and e.clause == "has_funds"
        )
        assert guard.verdict == TraceVerdict.PASS

    def test_guard_skip_wrong_event_type(self):
        u = _bank()
        result = u.explain({"type": "Deposit", "amount": 10})
        guard_entries = [e for e in result.trace if e.phase == TracePhase.GUARD]
        for g in guard_entries:
            if g.clause == "has_funds":
                assert g.verdict == TraceVerdict.SKIP

    def test_trace_has_safety(self):
        u = _bank()
        result = u.explain({"type": "Deposit", "amount": 10})
        safety_entries = [e for e in result.trace if e.phase == TracePhase.SAFETY]
        assert len(safety_entries) >= 1

    def test_safety_pass(self):
        u = _bank()
        result = u.explain({"type": "Deposit", "amount": 10})
        safety = next(e for e in result.trace if e.phase == TracePhase.SAFETY)
        assert safety.verdict == TraceVerdict.PASS

    def test_trace_has_korrelation(self):
        u = _bank()
        result = u.explain({"type": "Deposit", "amount": 10})
        korr_entries = [e for e in result.trace if e.phase == TracePhase.KORRELATION]
        assert len(korr_entries) == 1
        assert korr_entries[0].verdict == TraceVerdict.SKIP

    def test_trace_has_transition(self):
        u = _bank()
        result = u.explain({"type": "Deposit", "amount": 10})
        trans_entries = [e for e in result.trace if e.phase == TracePhase.TRANSITION]
        assert len(trans_entries) == 1
        assert trans_entries[0].verdict == TraceVerdict.PASS


class TestExplainImpossible:
    def test_impossible_event(self):
        u = _bank()
        result = u.explain({"type": "Withdraw", "amount": 200})
        assert not result.passed
        assert isinstance(result.result, Impossible)

    def test_guard_fail_in_trace(self):
        u = _bank()
        result = u.explain({"type": "Withdraw", "amount": 200})
        guard = next(
            e
            for e in result.trace
            if e.phase == TracePhase.GUARD and e.clause == "has_funds"
        )
        assert guard.verdict == TraceVerdict.FAIL

    def test_state_unchanged_on_impossible(self):
        u = _bank()
        u.explain({"type": "Withdraw", "amount": 200})
        assert u.state["balance"] == 100


class TestExplainViolated:
    def test_violated_event(self):
        spec = (
            Spec("bad")
            .state0({"x": 10})
            .permit("ok", when=LBool(True))
            .maintain(
                "positive",
                expr=Always(Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0))),
            )
            .build()
        )

        class Bad:
            def transition(self, s, e):
                return {"x": -1}

        u = universe(Bad(), spec)
        result = u.explain({"type": "X"})
        assert not result.passed
        assert isinstance(result.result, Violated)

    def test_safety_fail_in_trace(self):
        spec = (
            Spec("bad")
            .state0({"x": 10})
            .permit("ok", when=LBool(True))
            .maintain(
                "positive",
                expr=Always(Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0))),
            )
            .build()
        )

        class Bad:
            def transition(self, s, e):
                return {"x": -1}

        u = universe(Bad(), spec)
        result = u.explain({"type": "X"})
        safety = next(e for e in result.trace if e.phase == TracePhase.SAFETY)
        assert safety.verdict == TraceVerdict.FAIL


class TestExplainSummary:
    def test_summary_contains_result_type(self):
        u = _bank()
        result = u.explain({"type": "Deposit", "amount": 10})
        s = result.summary()
        assert "Ok" in s

    def test_summary_contains_trace_entries(self):
        u = _bank()
        result = u.explain({"type": "Withdraw", "amount": 30})
        s = result.summary()
        assert "guard" in s
        assert "has_funds" in s

    def test_summary_markers(self):
        u = _bank()
        result = u.explain({"type": "Withdraw", "amount": 200})
        s = result.summary()
        assert "-" in s  # fail marker


class TestExplainNoKorrelator:
    def test_skip_when_no_korrelator(self):
        spec = Spec("nokorr").state0({"x": 1}).permit("ok", when=LBool(True)).build()

        class Noop:
            def transition(self, s, e):
                return s

        u = universe(Noop(), spec)
        result = u.explain({"type": "X"})
        korr = next(e for e in result.trace if e.phase == TracePhase.KORRELATION)
        assert korr.verdict == TraceVerdict.SKIP


class TestExplainDecode:
    def test_with_decode(self):
        spec = (
            Spec("decoded")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .decode(lambda e: {"type": e.get("t"), "val": e.get("v", 0)})
            .build()
        )

        class Sys:
            def transition(self, s, e):
                return {**s, "x": e.get("val", 0)}

        u = universe(Sys(), spec)
        result = u.explain({"t": "A", "v": 42})
        decode = next(e for e in result.trace if e.phase == TracePhase.DECODE)
        assert decode.verdict == TraceVerdict.PASS
        assert result.decoded_event["val"] == 42

    def test_without_decode(self):
        spec = Spec("raw").state0({"x": 0}).permit("ok", when=LBool(True)).build()

        class Noop:
            def transition(self, s, e):
                return s

        u = universe(Noop(), spec)
        result = u.explain({"type": "X"})
        decode = next(e for e in result.trace if e.phase == TracePhase.DECODE)
        assert decode.verdict == TraceVerdict.SKIP
