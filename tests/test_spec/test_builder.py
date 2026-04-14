"""Tests for k3c.spec.builder — Spec builder and (I, U, K) clause types."""

from __future__ import annotations

import pytest

from k3c.lang.ir import (
    After,
    Always,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    EventField,
    Eventually,
    Field,
    Implies,
    LBool,
    LInt,
    LStr,
    TInt,
    TString,
    Var,
    With,
    Within,
)
from k3c.spec.builder import (
    FieldDef,
    K3Spec,
    KorrelatorDef,
    MaintainClause,
    PermitClause,
    RequireClause,
    Spec,
)


class TestClauseTypes:
    def test_permit_clause_frozen(self):
        clause = PermitClause(name="guard", when=LBool(True))
        assert clause.name == "guard"
        assert clause.on is None
        with pytest.raises(AttributeError):
            clause.name = "x"  # type: ignore[misc]

    def test_permit_clause_with_on(self):
        clause = PermitClause(name="guard", when=LBool(True), on="Withdraw")
        assert clause.on == "Withdraw"

    def test_require_clause_frozen(self):
        clause = RequireClause(name="debit", on="Withdraw", transition=Var("new_state"))
        assert clause.name == "debit"
        assert clause.on == "Withdraw"

    def test_maintain_clause_frozen(self):
        clause = MaintainClause(name="positive", expr=Always(LBool(True)))
        assert clause.name == "positive"

    def test_field_def_defaults(self):
        f = FieldDef(name="balance", type=TInt())
        assert f.required is True
        assert f.description == ""

    def test_field_def_custom(self):
        f = FieldDef(
            name="notes", type=TString(), description="optional notes", required=False
        )
        assert f.required is False
        assert f.description == "optional notes"

    def test_korrelator_def_defaults(self):
        k = KorrelatorDef(lift=lambda s: s)
        assert k.correlate is None
        assert k.threshold is None

    def test_korrelator_def_custom(self):
        k = KorrelatorDef(
            lift=lambda s: {"x": s["x"]},
            correlate=lambda a, i: a == i,
            threshold=lambda c: c is True,
        )
        assert k.correlate is not None
        assert k.threshold is not None


class TestK3Spec:
    def test_frozen(self):
        spec = K3Spec(name="test", state0={})
        with pytest.raises(AttributeError):
            spec.name = "x"  # type: ignore[misc]

    def test_defaults(self):
        spec = K3Spec(name="test", state0={"x": 1})
        assert spec.fields == ()
        assert spec.decode is None
        assert spec.permits == ()
        assert spec.requires == ()
        assert spec.maintains == ()
        assert spec.korrelator is None
        assert spec.protocol_start == "__start__"


class TestSpecBuilder:
    def test_minimal(self):
        spec = Spec("minimal").state0({"x": 0}).build()
        assert spec.name == "minimal"
        assert spec.state0 == {"x": 0}

    def test_chaining_returns_self(self):
        builder = Spec("test")
        assert builder.state0({}) is builder
        assert builder.permit("g", when=LBool(True)) is builder
        assert builder.maintain("m", expr=Always(LBool(True))) is builder

    def test_field(self):
        spec = (
            Spec("test")
            .state0({})
            .field("balance", TInt(), description="account balance")
            .field("name", TString(), required=False)
            .build()
        )
        assert len(spec.fields) == 2
        assert spec.fields[0].name == "balance"
        assert spec.fields[0].type == TInt()
        assert spec.fields[1].required is False

    def test_decode(self):
        def fn(e):
            return {"amount": e.get("amt", 0)}

        spec = Spec("test").state0({}).decode(fn).build()
        assert spec.decode is fn

    def test_permit(self):
        expr = Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))
        spec = (
            Spec("test")
            .state0({})
            .permit("has_funds", when=expr)
            .permit("is_active", when=LBool(True), on="Withdraw")
            .build()
        )
        assert len(spec.permits) == 2
        assert spec.permits[0].name == "has_funds"
        assert spec.permits[0].when == expr
        assert spec.permits[0].on is None
        assert spec.permits[1].on == "Withdraw"

    def test_require(self):
        transition = With(
            Var("spec_state"),
            (
                (
                    "balance",
                    Arith(
                        ArithOp.SUB,
                        Field(Var("spec_state"), "balance"),
                        EventField("amount"),
                    ),
                ),
            ),
        )
        spec = (
            Spec("test")
            .state0({"balance": 0})
            .require("debit", on="Withdraw", transition=transition)
            .build()
        )
        assert len(spec.requires) == 1
        assert spec.requires[0].name == "debit"
        assert spec.requires[0].on == "Withdraw"
        assert spec.requires[0].transition == transition

    def test_maintain_safety(self):
        expr = Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0)))
        spec = Spec("test").state0({}).maintain("non_negative", expr=expr).build()
        assert len(spec.maintains) == 1
        assert spec.maintains[0].name == "non_negative"
        assert spec.maintains[0].expr == expr

    def test_maintain_bounded_liveness(self):
        expr = Always(
            Within(
                Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("shipped")),
                n=10,
            )
        )
        spec = Spec("test").state0({}).maintain("ship_in_10", expr=expr).build()
        assert spec.maintains[0].expr == expr

    def test_maintain_unbounded_liveness(self):
        expr = Always(
            Eventually(
                Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("completed")),
            )
        )
        spec = (
            Spec("test").state0({}).maintain("eventually_complete", expr=expr).build()
        )
        assert spec.maintains[0].expr == expr

    def test_korrelate(self):
        def lift(s):
            return {"balance": s["balance"]}

        spec = Spec("test").state0({}).korrelate(lift=lift).build()
        assert spec.korrelator is not None
        assert spec.korrelator.lift is lift
        assert spec.korrelator.correlate is None
        assert spec.korrelator.threshold is None

    def test_korrelate_full(self):
        def lift(s):
            return s

        def correlate(a, i):
            return a == i

        def threshold(c):
            return c is True

        spec = (
            Spec("test")
            .state0({})
            .korrelate(lift=lift, correlate=correlate, threshold=threshold)
            .build()
        )

        assert spec.korrelator.correlate is correlate if spec.korrelator else False
        assert spec.korrelator.threshold is threshold if spec.korrelator else False

    def test_protocol_start(self):
        spec = Spec("test").state0({}).protocol_start("INIT").build()
        assert spec.protocol_start == "INIT"

    def test_protocol_start_default(self):
        spec = Spec("test").state0({}).build()
        assert spec.protocol_start == "__start__"


class TestBankAccountSpec:
    """Integration test — a complete bank account spec."""

    def _build_bank_spec(self) -> K3Spec:
        return (
            Spec("bank_account")
            .state0({"balance": 0, "status": "active"})
            .field("balance", TInt(), description="current balance")
            .field("status", TString(), description="account status")
            .permit(
                "has_funds",
                when=Compare(
                    CmpOp.GE,
                    Field(Var("state"), "balance"),
                    EventField("amount"),
                ),
                on="Withdraw",
            )
            .permit(
                "is_active",
                when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("active")),
            )
            .require(
                "debit",
                on="Withdraw",
                transition=With(
                    Var("spec_state"),
                    (
                        (
                            "balance",
                            Arith(
                                ArithOp.SUB,
                                Field(Var("spec_state"), "balance"),
                                EventField("amount"),
                            ),
                        ),
                    ),
                ),
            )
            .maintain(
                "non_negative",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            )
            .maintain(
                "response",
                expr=Always(
                    Implies(
                        Compare(CmpOp.EQ, EventField("type"), LStr("Withdraw")),
                        Eventually(
                            Compare(
                                CmpOp.EQ, Field(Var("state"), "status"), LStr("settled")
                            )
                        ),
                    )
                ),
            )
            .korrelate(lift=lambda s: {"balance": s["balance"]})
            .build()
        )

    def test_name(self):
        assert self._build_bank_spec().name == "bank_account"

    def test_state0(self):
        spec = self._build_bank_spec()
        assert spec.state0 == {"balance": 0, "status": "active"}

    def test_fields(self):
        spec = self._build_bank_spec()
        assert len(spec.fields) == 2
        names = [f.name for f in spec.fields]
        assert "balance" in names
        assert "status" in names

    def test_permits(self):
        spec = self._build_bank_spec()
        assert len(spec.permits) == 2
        assert spec.permits[0].name == "has_funds"
        assert spec.permits[0].on == "Withdraw"
        assert spec.permits[1].name == "is_active"
        assert spec.permits[1].on is None

    def test_requires(self):
        spec = self._build_bank_spec()
        assert len(spec.requires) == 1
        assert spec.requires[0].on == "Withdraw"

    def test_maintains(self):
        spec = self._build_bank_spec()
        assert len(spec.maintains) == 2
        assert spec.maintains[0].name == "non_negative"
        assert spec.maintains[1].name == "response"

    def test_korrelator(self):
        spec = self._build_bank_spec()
        assert spec.korrelator is not None
        assert spec.korrelator.lift({"balance": 100, "extra": "x"}) == {"balance": 100}

    def test_multiple_builds_independent(self):
        builder = Spec("test").state0({"x": 0})
        builder.permit("a", when=LBool(True))
        spec1 = builder.build()
        builder.permit("b", when=LBool(False))
        spec2 = builder.build()
        assert len(spec1.permits) == 1
        assert len(spec2.permits) == 2


class TestSpecSlice:
    """Tests for K3Spec.slice() — deriving parallel-safe sub-specs."""

    def _build_ssim_spec(self) -> K3Spec:
        return (
            Spec("ssim")
            .state0({"phase": "START", "serial": 0})
            .permit("rt2_from_start", when=LBool(True), on="ParseRT2")
            .permit("rt3_in_carrier", when=LBool(True), on="ParseRT3")
            .permit("rt4_in_carrier", when=LBool(True), on="ParseRT4")
            .permit("rt5_end", when=LBool(True), on="ParseRT5")
            .require("open_carrier", on="ParseRT2", transition=LStr("IN_CARRIER"))
            .maintain(
                "serial_continuity",
                expr=Always(Compare(CmpOp.GE, After("serial"), Before("serial"))),
            )
            .maintain("dates_valid", expr=Always(LBool(True)))
            .korrelate(lift=lambda s: {"serial": s.get("serial")})
            .build()
        )

    def test_slice_changes_state0(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER", "serial": 100})
        assert sliced.state0 == {"phase": "IN_CARRIER", "serial": 100}
        assert spec.state0 == {"phase": "START", "serial": 0}

    def test_slice_filters_permits_by_event_name(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(
            from_state={"phase": "IN_CARRIER"},
            events=["ParseRT3"],
        )
        assert len(sliced.permits) == 1
        assert sliced.permits[0].on == "ParseRT3"

    def test_slice_filters_permits_by_clause_name(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(
            from_state={"phase": "IN_CARRIER"},
            events=["rt3_in_carrier"],
        )
        assert len(sliced.permits) == 1
        assert sliced.permits[0].name == "rt3_in_carrier"

    def test_slice_no_events_filter_keeps_all(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER"})
        assert len(sliced.permits) == len(spec.permits)

    def test_slice_preserves_maintains(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER"}, events=["ParseRT3"])
        assert sliced.maintains == spec.maintains

    def test_slice_preserves_requires(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER"})
        assert sliced.requires == spec.requires

    def test_slice_preserves_korrelator(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER"})
        assert sliced.korrelator is spec.korrelator

    def test_slice_preserves_name(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER"})
        assert sliced.name == "ssim"

    def test_slice_updates_protocol_start_from_phase(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER"})
        assert sliced.protocol_start == "IN_CARRIER"

    def test_slice_keeps_protocol_start_when_no_phase(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"serial": 100})
        assert sliced.protocol_start == spec.protocol_start

    def test_slice_is_frozen(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER"})
        with pytest.raises(AttributeError):
            sliced.state0 = {}  # type: ignore[misc]

    def test_slice_multiple_events(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(
            from_state={"phase": "IN_CARRIER"},
            events=["ParseRT3", "ParseRT4"],
        )
        assert len(sliced.permits) == 2
        on_values = {p.on for p in sliced.permits}
        assert on_values == {"ParseRT3", "ParseRT4"}

    def test_slice_empty_events_list_filters_all(self):
        spec = self._build_ssim_spec()
        sliced = spec.slice(from_state={"phase": "IN_CARRIER"}, events=[])
        assert len(sliced.permits) == 0

    def test_original_spec_unchanged_after_slice(self):
        spec = self._build_ssim_spec()
        spec.slice(from_state={"phase": "IN_CARRIER"}, events=["ParseRT3"])
        assert len(spec.permits) == 4
        assert spec.state0 == {"phase": "START", "serial": 0}
