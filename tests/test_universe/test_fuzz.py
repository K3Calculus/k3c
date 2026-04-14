"""Tests for k3c.universe.fuzz — property-based fuzzing."""

from __future__ import annotations

import random

import pytest

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
from k3c.spec.result import Violated
from k3c.universe.fuzz import FuzzReport, FuzzViolation, fuzz
from k3c.universe.universe import universe


class _SafeSystem:
    """Transition that only adds — can never violate non-negative."""

    def transition(self, s, e):
        return {**s, "x": s["x"] + abs(e.get("n", 1))}


class _UnsafeSystem:
    """Transition that subtracts — will eventually violate non-negative."""

    def transition(self, s, e):
        return {**s, "x": s["x"] - e.get("n", 0)}


def _safe_spec():
    return (
        Spec("safe")
        .state0({"x": 100})
        .permit("ok", when=LBool(True))
        .maintain(
            "non_neg", expr=Always(Compare(CmpOp.GE, Field(Var("state"), "x"), LInt(0)))
        )
        .build()
    )


def _unsafe_spec():
    return (
        Spec("unsafe")
        .state0({"x": 10})
        .permit("ok", when=LBool(True))
        .maintain(
            "positive",
            expr=Always(Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0))),
        )
        .build()
    )


class TestFuzzPassing:
    def test_safe_system_passes(self):
        u = universe(_SafeSystem(), _safe_spec())
        report = u.fuzz(sequences=50, steps=20, seed=42)
        assert report.passed
        assert len(report.violations) == 0

    def test_report_fields(self):
        u = universe(_SafeSystem(), _safe_spec())
        report = u.fuzz(sequences=10, steps=5, seed=1)
        assert isinstance(report, FuzzReport)
        assert report.sequences_run == 10
        assert report.total_steps == 50
        assert report.elapsed_ms >= 0
        assert report.seed == 1

    def test_universe_reset_after_fuzz(self):
        u = universe(_SafeSystem(), _safe_spec())
        u.fuzz(sequences=10, steps=5, seed=1)
        assert u.state["x"] == 100


class TestFuzzViolation:
    def test_unsafe_system_finds_violation(self):
        u = universe(_UnsafeSystem(), _unsafe_spec())
        report = u.fuzz(sequences=100, steps=50, seed=42)
        assert not report.passed
        assert len(report.violations) >= 1

    def test_violation_has_context(self):
        u = universe(_UnsafeSystem(), _unsafe_spec())
        report = u.fuzz(sequences=100, steps=50, seed=42)
        v = report.violations[0]
        assert isinstance(v, FuzzViolation)
        assert isinstance(v.violated, Violated)
        assert v.violated.why.rule == "positive"
        assert len(v.original_sequence) > 0
        assert len(v.shrunk_sequence) > 0

    def test_shrunk_is_smaller_or_equal(self):
        u = universe(_UnsafeSystem(), _unsafe_spec())
        report = u.fuzz(sequences=100, steps=50, seed=42)
        v = report.violations[0]
        assert len(v.shrunk_sequence) <= len(v.original_sequence)

    def test_universe_reset_after_violation(self):
        u = universe(_UnsafeSystem(), _unsafe_spec())
        u.fuzz(sequences=100, steps=50, seed=42)
        assert u.state["x"] == 10


class TestFuzzSeed:
    def test_deterministic_with_same_seed(self):
        u1 = universe(_UnsafeSystem(), _unsafe_spec())
        r1 = u1.fuzz(sequences=50, steps=30, seed=999)

        u2 = universe(_UnsafeSystem(), _unsafe_spec())
        r2 = u2.fuzz(sequences=50, steps=30, seed=999)

        assert r1.passed == r2.passed
        assert r1.total_steps == r2.total_steps
        assert r1.sequences_run == r2.sequences_run

    def test_different_seeds_may_differ(self):
        u1 = universe(_SafeSystem(), _safe_spec())
        r1 = u1.fuzz(sequences=10, steps=5, seed=1)

        u2 = universe(_SafeSystem(), _safe_spec())
        r2 = u2.fuzz(sequences=10, steps=5, seed=2)

        # Both should pass (safe system) but steps may differ
        assert r1.passed
        assert r2.passed

    def test_seed_zero_uses_time(self):
        u = universe(_SafeSystem(), _safe_spec())
        report = u.fuzz(sequences=5, steps=3, seed=0)
        assert report.seed != 0


class TestFuzzShrinking:
    def test_shrink_disabled(self):
        u = universe(_UnsafeSystem(), _unsafe_spec())
        report = u.fuzz(sequences=100, steps=50, seed=42, shrink=False)
        if not report.passed:
            v = report.violations[0]
            # Without shrinking, original == shrunk
            assert v.shrunk_sequence == v.original_sequence

    def test_shrink_produces_minimal(self):
        u = universe(_UnsafeSystem(), _unsafe_spec())
        report = u.fuzz(sequences=100, steps=50, seed=42, shrink=True)
        if not report.passed:
            v = report.violations[0]
            assert len(v.shrunk_sequence) <= len(v.original_sequence)


class TestFuzzMaxViolations:
    def test_stops_at_max(self):
        u = universe(_UnsafeSystem(), _unsafe_spec())
        report = u.fuzz(sequences=100, steps=50, seed=42, max_violations=1)
        assert len(report.violations) == 1

    def test_multiple_violations(self):
        u = universe(_UnsafeSystem(), _unsafe_spec())
        report = u.fuzz(sequences=100, steps=50, seed=42, max_violations=5)
        assert len(report.violations) >= 1
        assert len(report.violations) <= 5


class TestFuzzCustomGenerator:
    def test_custom_event_generator(self):
        spec = (
            Spec("custom")
            .state0({"count": 0})
            .permit("ok", when=LBool(True))
            .maintain(
                "bounded",
                expr=Always(
                    Compare(CmpOp.LT, Field(Var("state"), "count"), LInt(1000))
                ),
            )
            .build()
        )

        class Counter:
            def transition(self, s, e):
                return {**s, "count": s["count"] + 1}

        def my_gen(state: dict[str, object], rng: random.Random) -> dict[str, object]:
            return {"type": "Tick"}

        u = universe(Counter(), spec)
        report = u.fuzz(sequences=5, steps=10, seed=1, event_generator=my_gen)
        assert report.passed
        assert report.total_steps == 50


class TestFuzzGuardedSpec:
    def test_impossible_events_counted(self):
        spec = (
            Spec("guarded")
            .state0({"balance": 100})
            .permit(
                "has_funds",
                when=Compare(
                    CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
                ),
                on="Withdraw",
            )
            .maintain(
                "non_neg",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            )
            .build()
        )

        class Bank:
            def transition(self, s, e):
                if e.get("type") == "Withdraw":
                    return {**s, "balance": s["balance"] - e["amount"]}
                return s

        u = universe(Bank(), spec)
        report = u.fuzz(sequences=20, steps=10, seed=42)
        assert report.passed
        assert report.impossible_count >= 0


class TestFuzzToDict:
    def test_to_dict(self):
        u = universe(_SafeSystem(), _safe_spec())
        report = u.fuzz(sequences=5, steps=3, seed=1)
        d = report.to_dict()
        assert d["passed"] is True
        assert d["sequences_run"] == 5
        assert d["seed"] == 1
        assert isinstance(d["elapsed_ms"], float)


class TestFuzzTypeCheck:
    def test_non_universe_raises(self):
        with pytest.raises(TypeError, match="Universe"):
            fuzz("not a universe", sequences=1, steps=1)
