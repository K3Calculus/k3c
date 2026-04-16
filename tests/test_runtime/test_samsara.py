"""Tests for k3c.runtime.samsara -- Samsara (<?>) operator (KC-3)."""

from __future__ import annotations

import pytest

from k3c.engine.result import Impossible, Ok, Violated
from k3c.ir.expr import Always, CmpOp, Compare, EventField, Field, LInt, Var
from k3c.runtime.samsara import ReplayResult, RunResult, TraceRecord
from k3c.runtime.universe import Universe
from k3c.spec.model import Maintain, Permit, Spec


# -- Fixtures ------------------------------------------------------------------


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
    )


def _bank_transition(state, event):
    match event.get("type"):
        case "Deposit":
            return {**state, "balance": state["balance"] + event["amount"]}
        case "Withdraw":
            return {**state, "balance": state["balance"] - event["amount"]}
        case _:
            return state


def _bank_universe(**kwargs):
    return Universe(spec=_bank_spec(), transition=_bank_transition, **kwargs)


# -- simulate() ----------------------------------------------------------------


class TestSimulate:
    def test_basic_trajectory(self):
        u = _bank_universe()
        result = u.simulate(
            [
                {"type": "Deposit", "amount": 50},
                {"type": "Withdraw", "amount": 30},
            ]
        )
        assert isinstance(result, RunResult)
        assert result.passed
        assert result.processed == 2
        assert result.skipped == 0
        assert result.final_state["balance"] == 120

    def test_trajectory_records_each_state(self):
        u = _bank_universe()
        result = u.simulate(
            [
                {"type": "Deposit", "amount": 10},
                {"type": "Deposit", "amount": 20},
                {"type": "Deposit", "amount": 30},
            ]
        )
        assert len(result.trajectory) == 3
        assert result.trajectory[0]["balance"] == 110
        assert result.trajectory[1]["balance"] == 130
        assert result.trajectory[2]["balance"] == 160

    def test_state_at(self):
        u = _bank_universe()
        result = u.simulate(
            [
                {"type": "Deposit", "amount": 10},
                {"type": "Deposit", "amount": 20},
            ]
        )
        assert result.state_at(0)["balance"] == 110
        assert result.state_at(1)["balance"] == 130

    def test_state_at_out_of_range(self):
        u = _bank_universe()
        result = u.simulate([{"type": "Deposit", "amount": 10}])
        with pytest.raises(IndexError):
            result.state_at(5)

    def test_traces_match_events(self):
        u = _bank_universe()
        events = [
            {"type": "Deposit", "amount": 50},
            {"type": "Withdraw", "amount": 30},
        ]
        result = u.simulate(events)
        assert len(result.traces) == 2
        assert result.traces[0].event == events[0]
        assert result.traces[1].event == events[1]

    def test_trace_record_fields(self):
        u = _bank_universe()
        result = u.simulate([{"type": "Deposit", "amount": 50}])
        rec = result.traces[0]
        assert isinstance(rec, TraceRecord)
        assert rec.t == 0
        assert rec.state_before == {"balance": 100}
        assert rec.state_after == {"balance": 150}
        assert rec.result_kind == "ok"
        assert rec.guard_result == (True, "")
        assert rec.invariant_result == (True, "")
        assert rec.step_hash != ""

    def test_trace_at(self):
        u = _bank_universe()
        result = u.simulate(
            [
                {"type": "Deposit", "amount": 10},
                {"type": "Deposit", "amount": 20},
            ]
        )
        assert result.trace_at(0).t == 0
        assert result.trace_at(1).t == 1

    def test_trace_at_out_of_range(self):
        u = _bank_universe()
        result = u.simulate([{"type": "Deposit", "amount": 10}])
        with pytest.raises(IndexError):
            result.trace_at(5)

    def test_step_hashes_extracted(self):
        u = _bank_universe()
        result = u.simulate(
            [
                {"type": "Deposit", "amount": 10},
                {"type": "Deposit", "amount": 20},
            ]
        )
        hashes = result.step_hashes
        assert len(hashes) == 2
        assert all(isinstance(h, str) and len(h) > 0 for h in hashes)
        assert hashes[0] != hashes[1]

    def test_events_extracted(self):
        u = _bank_universe()
        events = [
            {"type": "Deposit", "amount": 10},
            {"type": "Deposit", "amount": 20},
        ]
        result = u.simulate(events)
        assert result.events == tuple(events)

    def test_skips_impossible(self):
        u = _bank_universe()
        result = u.simulate(
            [
                {"type": "Deposit", "amount": 50},
                {"type": "Withdraw", "amount": 999},  # impossible
                {"type": "Deposit", "amount": 10},
            ]
        )
        assert result.passed
        assert result.processed == 2
        assert result.skipped == 1
        assert result.final_state["balance"] == 160

    def test_impossible_trace_recorded(self):
        u = _bank_universe()
        result = u.simulate(
            [
                {"type": "Withdraw", "amount": 999},  # impossible
            ]
        )
        assert len(result.traces) == 1
        rec = result.traces[0]
        assert rec.result_kind == "impossible"
        assert rec.state_after is None
        assert rec.guard_result[0] is False

    def test_stops_on_violated(self):
        spec = Spec(
            name="strict",
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
        u = Universe(spec=spec, transition=_bank_transition)
        result = u.simulate(
            [
                {"type": "Withdraw", "amount": 200},  # violated
                {"type": "Deposit", "amount": 10},  # not reached
            ]
        )
        assert not result.passed
        assert len(result.traces) == 1
        assert result.traces[0].result_kind == "violated"

    def test_violated_trace_fields(self):
        spec = Spec(
            name="strict",
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
        u = Universe(spec=spec, transition=_bank_transition)
        result = u.simulate([{"type": "Withdraw", "amount": 200}])
        rec = result.traces[0]
        assert rec.result_kind == "violated"
        assert rec.invariant_result[0] is False
        assert rec.guard_result[0] is True

    def test_empty_events(self):
        u = _bank_universe()
        result = u.simulate([])
        assert result.passed
        assert result.processed == 0
        assert result.skipped == 0
        assert len(result.trajectory) == 0
        assert len(result.traces) == 0
        assert result.final_state["balance"] == 100

    def test_to_dict(self):
        u = _bank_universe()
        result = u.simulate([{"type": "Deposit", "amount": 50}])
        d = result.to_dict()
        assert d["passed"] is True
        assert d["processed"] == 1
        assert len(d["traces"]) == 1
        assert len(d["trajectory"]) == 1

    def test_trace_record_to_dict(self):
        u = _bank_universe()
        result = u.simulate([{"type": "Deposit", "amount": 50}])
        d = result.traces[0].to_dict()
        assert d["t"] == 0
        assert d["result_kind"] == "ok"
        assert isinstance(d["guard_result"], list)


# -- replay() ------------------------------------------------------------------


class TestReplay:
    def test_deterministic_replay(self):
        events = [
            {"type": "Deposit", "amount": 50},
            {"type": "Withdraw", "amount": 30},
        ]

        # First run -- collect hashes
        u = _bank_universe()
        run = u.simulate(events)

        # Replay -- verify determinism
        u2 = _bank_universe()
        result = u2.replay(events, expected_hashes=run.step_hashes)
        assert isinstance(result, ReplayResult)
        assert result.passed
        assert result.matched
        assert result.steps == 2
        assert len(result.mismatches) == 0

    def test_replay_detects_mismatch(self):
        events = [
            {"type": "Deposit", "amount": 50},
            {"type": "Withdraw", "amount": 30},
        ]

        u = _bank_universe()
        result = u.replay(events, expected_hashes=["wrong_hash_1", "wrong_hash_2"])
        assert not result.passed
        assert len(result.mismatches) == 2

    def test_replay_mismatch_details(self):
        events = [{"type": "Deposit", "amount": 50}]

        u = _bank_universe()
        result = u.replay(events, expected_hashes=["wrong_hash"])
        assert len(result.mismatches) == 1
        m = result.mismatches[0]
        assert m.t == 0
        assert m.expected_hash == "wrong_hash"
        assert m.actual_hash != "wrong_hash"
        assert m.event == events[0]

    def test_replay_resets_universe(self):
        u = _bank_universe()
        # Advance state first
        u.apply({"type": "Deposit", "amount": 500})
        assert u.state["balance"] == 600

        events = [{"type": "Deposit", "amount": 50}]
        # Get expected hashes from clean run
        u2 = _bank_universe()
        run = u2.simulate(events)

        # Replay on the modified universe -- should reset
        result = u.replay(events, expected_hashes=run.step_hashes)
        assert result.passed

    def test_replay_with_impossible_events(self):
        events = [
            {"type": "Deposit", "amount": 50},
            {"type": "Withdraw", "amount": 999},  # impossible
            {"type": "Deposit", "amount": 10},
        ]

        u1 = _bank_universe()
        run = u1.simulate(events)

        u2 = _bank_universe()
        result = u2.replay(events, expected_hashes=run.step_hashes)
        assert result.passed
        assert result.steps == 3


# -- Universe.simulate() and Universe.replay() integration --------------------


class TestUniverseIntegration:
    def test_simulate_via_universe(self):
        u = _bank_universe()
        result = u.simulate([{"type": "Deposit", "amount": 50}])
        assert isinstance(result, RunResult)
        assert result.passed

    def test_replay_via_universe(self):
        events = [{"type": "Deposit", "amount": 50}]
        u1 = _bank_universe()
        run = u1.simulate(events)

        u2 = _bank_universe()
        result = u2.replay(events, expected_hashes=run.step_hashes)
        assert result.passed

    def test_full_samsara_cycle(self):
        """Simulate, extract hashes, replay, verify -- the full KC-3 workflow."""
        events = [
            {"type": "Deposit", "amount": 50},
            {"type": "Withdraw", "amount": 30},
            {"type": "Deposit", "amount": 100},
            {"type": "Withdraw", "amount": 20},
        ]

        # Simulate with trajectory
        u = _bank_universe()
        run = u.simulate(events)
        assert run.passed
        assert run.final_state["balance"] == 200
        assert len(run.trajectory) == 4
        assert len(run.traces) == 4

        # Verify trajectory progression
        assert run.trajectory[0]["balance"] == 150
        assert run.trajectory[1]["balance"] == 120
        assert run.trajectory[2]["balance"] == 220
        assert run.trajectory[3]["balance"] == 200

        # Replay for determinism verification
        u2 = _bank_universe()
        replay_result = u2.replay(events, expected_hashes=run.step_hashes)
        assert replay_result.passed

    def test_imports_from_top_level(self):
        """KC-3 types are accessible from k3c top-level."""
        from k3c import ReplayMismatch, ReplayResult, RunResult, TraceRecord

        assert TraceRecord is not None
        assert RunResult is not None
        assert ReplayResult is not None
        assert ReplayMismatch is not None
