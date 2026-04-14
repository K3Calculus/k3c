"""Tests for k3c.universe.universe — Universe class and universe() factory."""

from __future__ import annotations

import pytest

from k3c.errors import K3WellFormednessError
from k3c.lang.ir import (
    After,
    Always,
    Before,
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
from k3c.universe.universe import (
    ParallelReduceResult,
    ReduceAllResult,
    Universe,
    parallel_reduce,
    universe,
)


class _BankSystem:
    def transition(self, state, event):
        if event.get("type") == "Withdraw":
            return {**state, "balance": state["balance"] - event["amount"]}
        if event.get("type") == "Deposit":
            return {**state, "balance": state["balance"] + event["amount"]}
        return state


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


class TestUniverseFactory:
    def test_creates_universe(self):
        u = _bank()
        assert isinstance(u, Universe)

    def test_default_id_from_spec(self):
        u = _bank()
        assert u.id == "bank"

    def test_custom_id(self):
        u = universe(_BankSystem(), _bank_spec(), id="my_bank")
        assert u.id == "my_bank"

    def test_initial_state(self):
        u = _bank()
        assert u.state == {"balance": 100}

    def test_repr(self):
        u = _bank()
        assert "bank" in repr(u)
        assert "balance" in repr(u)


class TestWellFormedness:
    def test_rule1_empty_state(self):
        spec = Spec("empty").state0({}).permit("ok", when=LBool(True)).build()

        class NoopSystem:
            def transition(self, s, e):
                return s

        with pytest.raises(K3WellFormednessError, match="non-empty"):
            universe(NoopSystem(), spec)

    def test_rule3_initial_violates_invariant(self):
        spec = (
            Spec("bad")
            .state0({"balance": -1})
            .permit("ok", when=LBool(True))
            .maintain(
                "non_negative",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            )
            .build()
        )

        class NoopSystem:
            def transition(self, s, e):
                return s

        with pytest.raises(K3WellFormednessError, match="non_negative"):
            universe(NoopSystem(), spec)

    def test_valid_spec_passes(self):
        u = _bank()
        assert u.state["balance"] == 100


class TestApply:
    def test_ok_withdrawal(self):
        u = _bank()
        result = u.apply({"type": "Withdraw", "amount": 30})
        assert isinstance(result, Ok)
        assert u.state["balance"] == 70

    def test_ok_deposit(self):
        u = _bank()
        result = u.apply({"type": "Deposit", "amount": 50})
        assert isinstance(result, Ok)
        assert u.state["balance"] == 150

    def test_impossible_insufficient_funds(self):
        u = _bank()
        result = u.apply({"type": "Withdraw", "amount": 200})
        assert isinstance(result, Impossible)
        assert u.state["balance"] == 100  # unchanged

    def test_state_unchanged_on_impossible(self):
        u = _bank()
        u.apply({"type": "Deposit", "amount": 50})
        assert u.state["balance"] == 150
        result = u.apply({"type": "Withdraw", "amount": 300})
        assert isinstance(result, Impossible)
        assert u.state["balance"] == 150  # still 150

    def test_violated_bad_transition(self):
        spec = (
            Spec("bad_t")
            .state0({"x": 10})
            .permit("ok", when=LBool(True))
            .maintain(
                "positive",
                expr=Always(Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0))),
            )
            .build()
        )

        class BadSystem:
            def transition(self, s, e):
                return {"x": -1}

        u = universe(BadSystem(), spec)
        result = u.apply({"type": "X"})
        assert isinstance(result, Violated)

    def test_step_hash_on_ok(self):
        u = _bank()
        result = u.apply({"type": "Deposit", "amount": 10})
        assert isinstance(result, Ok)
        assert len(result.step_hash) == 64

    def test_chained_step_hashes_differ(self):
        u = _bank()
        r1 = u.apply({"type": "Deposit", "amount": 10})
        r2 = u.apply({"type": "Deposit", "amount": 10})
        assert isinstance(r1, Ok)
        assert isinstance(r2, Ok)
        assert r1.step_hash != r2.step_hash

    def test_ctx_advances(self):
        u = _bank()
        ctx_before = u.ctx
        u.apply({"type": "Deposit", "amount": 10})
        assert u.ctx is not ctx_before


class TestReduce:
    def test_all_ok(self):
        u = _bank()
        result = u.reduce(
            [
                {"type": "Deposit", "amount": 50},
                {"type": "Withdraw", "amount": 20},
                {"type": "Withdraw", "amount": 10},
            ]
        )
        assert isinstance(result, Ok)
        assert u.state["balance"] == 120

    def test_stops_on_impossible(self):
        u = _bank()
        result = u.reduce(
            [
                {"type": "Withdraw", "amount": 200},
                {"type": "Deposit", "amount": 999},
            ]
        )
        assert isinstance(result, Impossible)
        assert u.state["balance"] == 100  # first event failed, nothing processed

    def test_stops_on_violated(self):
        spec = (
            Spec("v")
            .state0({"x": 10})
            .permit("ok", when=LBool(True))
            .maintain(
                "positive",
                expr=Always(Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0))),
            )
            .build()
        )

        class Dec:
            def transition(self, s, e):
                return {"x": s["x"] - e.get("d", 1)}

        u = universe(Dec(), spec)
        result = u.reduce(
            [
                {"type": "A", "d": 3},  # result: 7, ok
                {"type": "A", "d": 3},  # result: 4, ok
                {"type": "A", "d": 5},  # result: -1, violated
                {"type": "A", "d": 1},  # never reached
            ]
        )
        assert isinstance(result, Violated)

    def test_empty_events(self):
        u = _bank()
        result = u.reduce([])
        assert isinstance(result, Ok)
        assert u.state["balance"] == 100


class TestReduceAll:
    def test_skips_impossible(self):
        u = _bank()
        ra = u.reduce_all(
            [
                {"type": "Withdraw", "amount": 200},  # impossible
                {"type": "Deposit", "amount": 50},  # ok
                {"type": "Withdraw", "amount": 300},  # impossible
                {"type": "Withdraw", "amount": 10},  # ok
            ]
        )
        assert isinstance(ra, ReduceAllResult)
        assert ra.processed == 2
        assert len(ra.skipped) == 2
        assert ra.passed
        assert u.state["balance"] == 140

    def test_stops_on_violated(self):
        spec = (
            Spec("v")
            .state0({"x": 10})
            .permit("ok", when=LBool(True))
            .maintain(
                "positive",
                expr=Always(Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0))),
            )
            .build()
        )

        class Dec:
            def transition(self, s, e):
                return {"x": s["x"] - e.get("d", 1)}

        u = universe(Dec(), spec)
        ra = u.reduce_all(
            [
                {"type": "A", "d": 3},
                {"type": "A", "d": 20},  # violated
                {"type": "A", "d": 1},  # never reached
            ]
        )
        assert not ra.passed
        assert isinstance(ra.final, Violated)
        assert ra.processed == 1

    def test_empty_events(self):
        u = _bank()
        ra = u.reduce_all([])
        assert ra.passed
        assert ra.processed == 0
        assert ra.skipped == []

    def test_skipped_indices_correct(self):
        u = _bank()
        ra = u.reduce_all(
            [
                {"type": "Deposit", "amount": 10},  # 0: ok
                {"type": "Withdraw", "amount": 999},  # 1: impossible
                {"type": "Deposit", "amount": 20},  # 2: ok
            ]
        )
        assert ra.processed == 2
        assert len(ra.skipped) == 1
        assert ra.skipped[0][0] == 1  # index 1


class TestReset:
    def test_reset_restores_initial_state(self):
        u = _bank()
        u.apply({"type": "Withdraw", "amount": 50})
        assert u.state["balance"] == 50
        u.reset()
        assert u.state["balance"] == 100

    def test_reset_restores_ctx(self):
        u = _bank()
        u.apply({"type": "Deposit", "amount": 10})
        u.reset()
        assert u.ctx.prev_step_hash == ""
        assert u.ctx.trace_ring == ()

    def test_multiple_resets(self):
        u = _bank()
        u.apply({"type": "Withdraw", "amount": 10})
        u.reset()
        u.apply({"type": "Withdraw", "amount": 20})
        assert u.state["balance"] == 80
        u.reset()
        assert u.state["balance"] == 100


class TestHashFn:
    def test_default_sha256(self):
        u = _bank()
        r = u.apply({"type": "Deposit", "amount": 10})
        assert isinstance(r, Ok)
        assert len(r.step_hash) == 64  # SHA-256

    def test_blake2b(self):
        u = universe(_BankSystem(), _bank_spec(), hash_fn="blake2b")
        r = u.apply({"type": "Deposit", "amount": 10})
        assert isinstance(r, Ok)
        assert len(r.step_hash) == 128  # blake2b


class TestIntegration:
    def test_full_bank_lifecycle(self):
        u = _bank()

        # Deposit
        r1 = u.apply({"type": "Deposit", "amount": 200})
        assert isinstance(r1, Ok)
        assert u.state["balance"] == 300

        # Withdraw
        r2 = u.apply({"type": "Withdraw", "amount": 100})
        assert isinstance(r2, Ok)
        assert u.state["balance"] == 200

        # Overdraw attempt
        r3 = u.apply({"type": "Withdraw", "amount": 500})
        assert isinstance(r3, Impossible)
        assert u.state["balance"] == 200

        # Another withdraw
        r4 = u.apply({"type": "Withdraw", "amount": 200})
        assert isinstance(r4, Ok)
        assert u.state["balance"] == 0

        # Hash chain
        assert r1.step_hash != r2.step_hash != r4.step_hash

        # Trace ring
        assert len(u.ctx.trace_ring) >= 3


class _CounterSystem:
    def transition(self, state, event):
        return {**state, "count": state["count"] + event.get("n", 1)}


def _counter_spec():
    return (
        Spec("counter")
        .state0({"count": 0})
        .permit("ok", when=LBool(True))
        .maintain(
            "non_neg",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
        )
        .build()
    )


class TestParallelReduce:
    def test_basic_parallel(self):
        spec = _counter_spec()
        chunks = [
            [{"type": "Inc", "n": 1}] * 5,
            [{"type": "Inc", "n": 2}] * 5,
            [{"type": "Inc", "n": 3}] * 5,
        ]
        specs = [
            spec.slice(from_state={"count": 0}),
            spec.slice(from_state={"count": 100}),
            spec.slice(from_state={"count": 200}),
        ]
        result = parallel_reduce(_CounterSystem(), specs, chunks, workers=1)
        assert isinstance(result, ParallelReduceResult)
        assert result.passed
        assert result.total_processed == 15
        assert result.total_skipped == 0

    def test_states_from_chunks(self):
        spec = _counter_spec()
        chunks = [
            [{"type": "Inc", "n": 10}] * 3,
            [{"type": "Inc", "n": 20}] * 3,
        ]
        specs = [
            spec.slice(from_state={"count": 0}),
            spec.slice(from_state={"count": 0}),
        ]
        result = parallel_reduce(_CounterSystem(), specs, chunks, workers=1)
        assert result.states == [{"count": 30}, {"count": 60}]

    def test_violation_in_one_chunk(self):
        spec = _counter_spec()

        class BadCounter:
            def transition(self, state, event):
                if event.get("bad"):
                    return {**state, "count": -1}
                return {**state, "count": state["count"] + 1}

        chunks = [
            [{"type": "Inc"}] * 5,
            [{"type": "Inc"}, {"type": "Bad", "bad": True}],
        ]
        specs = [
            spec.slice(from_state={"count": 0}),
            spec.slice(from_state={"count": 0}),
        ]
        result = parallel_reduce(BadCounter(), specs, chunks, workers=1)
        assert not result.passed
        assert len(result.violations) == 1
        assert result.violations[0][0] == 1  # chunk index 1

    def test_all_chunks_pass(self):
        spec = _counter_spec()
        chunks = [[{"type": "Inc", "n": 1}]] * 4
        specs = [spec.slice(from_state={"count": i * 10}) for i in range(4)]
        result = parallel_reduce(_CounterSystem(), specs, chunks, workers=1)
        assert result.passed
        assert len(result.results) == 4

    def test_empty_chunks(self):
        result = parallel_reduce(_CounterSystem(), [], [], workers=1)
        assert result.passed
        assert result.total_processed == 0

    def test_single_chunk(self):
        spec = _counter_spec()
        chunks = [[{"type": "Inc", "n": 5}] * 3]
        specs = [spec.slice(from_state={"count": 0})]
        result = parallel_reduce(_CounterSystem(), specs, chunks, workers=1)
        assert result.passed
        assert result.total_processed == 3
        assert result.states == [{"count": 15}]

    def test_mismatched_specs_chunks_raises(self):
        spec = _counter_spec()
        with pytest.raises(ValueError, match="same length"):
            parallel_reduce(
                _CounterSystem(),
                [spec, spec],
                [[{"type": "Inc"}]],
                workers=1,
            )

    def test_skipped_events_in_parallel(self):
        spec = (
            Spec("guarded")
            .state0({"count": 0})
            .permit(
                "positive_n",
                when=Compare(CmpOp.GT, EventField("n"), LInt(0)),
            )
            .build()
        )

        class Adder:
            def transition(self, state, event):
                return {**state, "count": state["count"] + event.get("n", 0)}

        chunks = [
            [
                {"type": "Inc", "n": 5},
                {"type": "Inc", "n": -1},
                {"type": "Inc", "n": 3},
            ],
            [{"type": "Inc", "n": 2}, {"type": "Inc", "n": -5}],
        ]
        specs = [
            spec.slice(from_state={"count": 0}),
            spec.slice(from_state={"count": 0}),
        ]
        result = parallel_reduce(Adder(), specs, chunks, workers=1)
        assert result.passed
        assert result.total_processed == 3
        assert result.total_skipped == 2

    def test_ssim_pattern(self):
        """Unified spec → slice → parallel — the canonical SSIM pattern."""
        unified = (
            Spec("ssim")
            .state0({"phase": "START", "serial": 0})
            .permit("rt3", when=LBool(True), on="ParseRT3")
            .maintain(
                "serial_inc",
                expr=Always(Compare(CmpOp.GE, After("serial"), Before("serial"))),
            )
            .build()
        )

        class SsimParser:
            def transition(self, state, event):
                return {**state, "serial": state["serial"] + 1}

        # Simulate 3 chunks of RT3 records starting at different serials
        chunks = [
            [{"type": "ParseRT3"}] * 4,
            [{"type": "ParseRT3"}] * 4,
            [{"type": "ParseRT3"}] * 4,
        ]
        specs = [
            unified.slice(
                from_state={"phase": "IN_CARRIER", "serial": 0}, events=["ParseRT3"]
            ),
            unified.slice(
                from_state={"phase": "IN_CARRIER", "serial": 100}, events=["ParseRT3"]
            ),
            unified.slice(
                from_state={"phase": "IN_CARRIER", "serial": 200}, events=["ParseRT3"]
            ),
        ]

        result = parallel_reduce(SsimParser(), specs, chunks, workers=1)
        assert result.passed
        assert result.total_processed == 12
        assert result.states[0]["serial"] == 4
        assert result.states[1]["serial"] == 104
        assert result.states[2]["serial"] == 204
