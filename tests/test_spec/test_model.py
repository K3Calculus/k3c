"""Tests for k3c.spec.model -- declarative Spec construction."""

from __future__ import annotations

import pytest

from k3c.ir.expr import (
    Always,
    Arith,
    ArithOp,
    CmpOp,
    Compare,
    EventField,
    Field,
    LInt,
    Record,
    Var,
)
from k3c.ir.types import TInt, TString
from k3c.spec.model import (
    CompareMode,
    FieldDef,
    Korrelator,
    Maintain,
    Output,
    Permit,
    Projection,
    Require,
    Spec,
)


class TestSpecConstruction:
    def test_minimal_spec(self):
        spec = Spec(name="test", state0={"x": 0})
        assert spec.name == "test"
        assert spec.state0 == {"x": 0}
        assert spec.permits == ()
        assert spec.maintains == ()
        assert spec.protocol_start == "__start__"

    def test_full_spec(self):
        spec = Spec(
            name="bank",
            state0={"balance": 100},
            fields=(
                FieldDef(name="balance", type=TInt()),
                FieldDef(name="status", type=TString(), required=False),
            ),
            permits=(
                Permit(
                    name="has_funds",
                    on="Withdraw",
                    when=Compare(
                        CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
                    ),
                ),
            ),
            requires=(
                Require(
                    name="debit",
                    on="Withdraw",
                    transition=Record(
                        fields=(
                            (
                                "balance",
                                Arith(
                                    ArithOp.SUB,
                                    Field(Var("spec_state"), "balance"),
                                    EventField("amount"),
                                ),
                            ),
                        )
                    ),
                ),
            ),
            maintains=(
                Maintain(
                    name="non_negative",
                    expr=Always(
                        Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))
                    ),
                ),
            ),
            projections=(
                Projection(name="balance_view", expr=Field(Var("state"), "balance")),
            ),
            outputs=(
                Output(
                    name="low_balance",
                    expr=Compare(CmpOp.LT, Field(Var("state"), "balance"), LInt(10)),
                    on="Withdraw",
                ),
            ),
            korrelator=Korrelator(
                actual=Field(Var("state"), "balance"),
                intended=Field(Var("spec_state"), "balance"),
                mode=CompareMode.EXACT,
            ),
        )
        assert len(spec.permits) == 1
        assert len(spec.requires) == 1
        assert len(spec.maintains) == 1
        assert len(spec.projections) == 1
        assert len(spec.outputs) == 1
        assert spec.korrelator is not None

    def test_frozen(self):
        spec = Spec(name="test", state0={"x": 0})
        with pytest.raises(AttributeError):
            spec.name = "other"  # type: ignore[misc]


class TestPermit:
    def test_permit_with_on(self):
        p = Permit(name="check", when=LInt(1), on="Deposit")
        assert p.on == "Deposit"

    def test_permit_without_on(self):
        p = Permit(name="check", when=LInt(1))
        assert p.on is None


class TestRequire:
    def test_require_fields(self):
        r = Require(name="debit", on="Withdraw", transition=LInt(0))
        assert r.on == "Withdraw"


class TestMaintain:
    def test_maintain_with_always(self):
        m = Maintain(name="inv", expr=Always(LInt(1)))
        assert isinstance(m.expr, Always)


class TestProjection:
    def test_default_kind(self):
        p = Projection(name="view", expr=LInt(1))
        assert p.kind == "derived"

    def test_custom_kind(self):
        p = Projection(name="metric", expr=LInt(1), kind="metric")
        assert p.kind == "metric"


class TestOutput:
    def test_output_with_on(self):
        o = Output(name="out", expr=LInt(1), on="Withdraw")
        assert o.on == "Withdraw"


class TestKorrelator:
    def test_default_mode(self):
        k = Korrelator(actual=LInt(1), intended=LInt(1))
        assert k.mode == CompareMode.EXACT

    def test_subset_mode(self):
        k = Korrelator(actual=LInt(1), intended=LInt(1), mode=CompareMode.SUBSET)
        assert k.mode == CompareMode.SUBSET


class TestSlice:
    def test_slice_filters_permits(self):
        spec = Spec(
            name="test",
            state0={"x": 0},
            permits=(
                Permit(name="a", when=LInt(1), on="TypeA"),
                Permit(name="b", when=LInt(1), on="TypeB"),
                Permit(name="c", when=LInt(1), on="TypeC"),
            ),
        )
        sliced = spec.slice(from_state={"x": 5}, events=["TypeA", "TypeC"])
        assert len(sliced.permits) == 2
        assert sliced.state0 == {"x": 5}

    def test_slice_preserves_maintains(self):
        spec = Spec(
            name="test",
            state0={"x": 0},
            maintains=(Maintain(name="inv", expr=Always(LInt(1))),),
        )
        sliced = spec.slice(from_state={"x": 5})
        assert len(sliced.maintains) == 1

    def test_slice_updates_protocol_start_from_phase(self):
        spec = Spec(name="test", state0={"x": 0})
        sliced = spec.slice(from_state={"x": 5, "phase": "IN_CARRIER"})
        assert sliced.protocol_start == "IN_CARRIER"

    def test_slice_keeps_protocol_start_without_phase(self):
        spec = Spec(name="test", state0={"x": 0}, protocol_start="INIT")
        sliced = spec.slice(from_state={"x": 5})
        assert sliced.protocol_start == "INIT"

    def test_slice_no_event_filter(self):
        spec = Spec(
            name="test",
            state0={"x": 0},
            permits=(
                Permit(name="a", when=LInt(1), on="TypeA"),
                Permit(name="b", when=LInt(1), on="TypeB"),
            ),
        )
        sliced = spec.slice(from_state={"x": 5})
        assert len(sliced.permits) == 2
