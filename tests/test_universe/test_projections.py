"""Tests for projections (P) and outputs on Ok results."""

from __future__ import annotations

import pytest

from k3c.lang.ir import LBool
from k3c.spec.builder import OutputDef, ProjectionDef, Spec
from k3c.spec.result import Impossible, Ok
from k3c.universe.universe import universe


class _BankSystem:
    def transition(self, s, e):
        if e.get("type") == "Withdraw":
            return {**s, "balance": s["balance"] - e["amount"]}
        if e.get("type") == "Deposit":
            return {**s, "balance": s["balance"] + e["amount"]}
        return s


def _bank_spec_with_projections():
    return (
        Spec("bank")
        .state0({"balance": 100})
        .permit("ok", when=LBool(True))
        .project("total", lambda s: s["balance"])
        .project("is_positive", lambda s: s["balance"] > 0, kind="metric")
        .project("public_view", lambda s: {"bal": s["balance"]}, kind="observable")
        .build()
    )


def _bank_spec_with_outputs():
    return (
        Spec("bank")
        .state0({"balance": 100})
        .permit("ok", when=LBool(True))
        .output(
            "audit",
            lambda s, e, ns: {
                "type": "AuditEvent",
                "action": e.get("type"),
                "balance": ns["balance"],
            },
        )
        .output(
            "low_balance_alert",
            lambda s, e, ns: (
                {"type": "LowBalance", "balance": ns["balance"]}
                if ns["balance"] < 20
                else None
            ),
        )
        .output(
            "withdraw_receipt",
            lambda s, e, ns: {"type": "Receipt", "amount": e.get("amount")},
            on="Withdraw",
        )
        .build()
    )


class TestProjectionDef:
    def test_frozen(self):
        p = ProjectionDef(name="x", fn=lambda s: s)
        with pytest.raises(AttributeError):
            p.name = "y"  # type: ignore[misc]

    def test_default_kind(self):
        p = ProjectionDef(name="x", fn=lambda s: s)
        assert p.kind == "derived"


class TestOutputDef:
    def test_frozen(self):
        o = OutputDef(name="x", fn=lambda s, e, ns: {})
        with pytest.raises(AttributeError):
            o.name = "y"  # type: ignore[misc]

    def test_default_on(self):
        o = OutputDef(name="x", fn=lambda s, e, ns: {})
        assert o.on is None


class TestProjections:
    def test_projections_on_ok(self):
        u = universe(_BankSystem(), _bank_spec_with_projections())
        r = u.apply({"type": "Deposit", "amount": 50})
        assert isinstance(r, Ok)
        assert r.projections["total"] == 150
        assert r.projections["is_positive"] is True
        assert r.projections["public_view"] == {"bal": 150}

    def test_projections_update_each_step(self):
        u = universe(_BankSystem(), _bank_spec_with_projections())
        r1 = u.apply({"type": "Withdraw", "amount": 30})
        assert r1.projections["total"] == 70
        r2 = u.apply({"type": "Withdraw", "amount": 60})
        assert r2.projections["total"] == 10
        assert r2.projections["is_positive"] is True

    def test_empty_projections_when_none_defined(self):
        spec = Spec("plain").state0({"x": 1}).permit("ok", when=LBool(True)).build()

        class Noop:
            def transition(self, s, e):
                return s

        u = universe(Noop(), spec)
        r = u.apply({"type": "X"})
        assert isinstance(r, Ok)
        assert r.projections == {}

    def test_projections_not_on_impossible(self):
        spec = (
            Spec("guarded")
            .state0({"x": 1})
            .permit("no", when=LBool(False))
            .project("val", lambda s: s["x"])
            .build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        u = universe(Noop(), spec)
        r = u.apply({"type": "X"})
        assert isinstance(r, Impossible)


class TestOutputs:
    def test_outputs_on_ok(self):
        u = universe(_BankSystem(), _bank_spec_with_outputs())
        r = u.apply({"type": "Withdraw", "amount": 30})
        assert isinstance(r, Ok)
        audit = next(o for o in r.outputs if o["type"] == "AuditEvent")
        assert audit["action"] == "Withdraw"
        assert audit["balance"] == 70

    def test_output_filtered_by_event_type(self):
        u = universe(_BankSystem(), _bank_spec_with_outputs())
        r = u.apply({"type": "Withdraw", "amount": 10})
        types = [o["type"] for o in r.outputs]
        assert "Receipt" in types

    def test_output_skipped_for_wrong_event_type(self):
        u = universe(_BankSystem(), _bank_spec_with_outputs())
        r = u.apply({"type": "Deposit", "amount": 10})
        types = [o["type"] for o in r.outputs]
        assert "Receipt" not in types
        assert "AuditEvent" in types

    def test_output_none_skipped(self):
        u = universe(_BankSystem(), _bank_spec_with_outputs())
        r = u.apply({"type": "Deposit", "amount": 10})
        types = [o["type"] for o in r.outputs]
        assert "LowBalance" not in types

    def test_output_emitted_when_condition_met(self):
        u = universe(_BankSystem(), _bank_spec_with_outputs())
        u.apply({"type": "Withdraw", "amount": 85})
        r = u.apply({"type": "Withdraw", "amount": 5})
        types = [o["type"] for o in r.outputs]
        assert "LowBalance" in types

    def test_empty_outputs_when_none_defined(self):
        spec = Spec("plain").state0({"x": 1}).permit("ok", when=LBool(True)).build()

        class Noop:
            def transition(self, s, e):
                return s

        u = universe(Noop(), spec)
        r = u.apply({"type": "X"})
        assert isinstance(r, Ok)
        assert r.outputs == ()

    def test_outputs_not_on_impossible(self):
        spec = (
            Spec("guarded")
            .state0({"x": 1})
            .permit("no", when=LBool(False))
            .output("audit", lambda s, e, ns: {"type": "Audit"})
            .build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        u = universe(Noop(), spec)
        r = u.apply({"type": "X"})
        assert isinstance(r, Impossible)


class TestProjectionsAndOutputsTogether:
    def test_both_on_same_spec(self):
        spec = (
            Spec("full")
            .state0({"count": 0})
            .permit("ok", when=LBool(True))
            .project("count", lambda s: s["count"])
            .project("is_even", lambda s: s["count"] % 2 == 0, kind="metric")
            .output("tick", lambda s, e, ns: {"type": "Tick", "n": ns["count"]})
            .build()
        )

        class Counter:
            def transition(self, s, e):
                return {**s, "count": s["count"] + 1}

        u = universe(Counter(), spec)
        r = u.apply({"type": "Inc"})
        assert isinstance(r, Ok)
        assert r.projections["count"] == 1
        assert r.projections["is_even"] is False
        assert len(r.outputs) == 1
        assert r.outputs[0]["n"] == 1

    def test_reduce_with_projections(self):
        spec = (
            Spec("counter")
            .state0({"count": 0})
            .permit("ok", when=LBool(True))
            .project("total", lambda s: s["count"])
            .build()
        )

        class Counter:
            def transition(self, s, e):
                return {**s, "count": s["count"] + 1}

        u = universe(Counter(), spec)
        r = u.reduce([{"type": "Inc"}] * 5)
        assert isinstance(r, Ok)
        assert r.projections["total"] == 5
