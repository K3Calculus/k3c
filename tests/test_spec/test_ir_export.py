"""Tests for K3Spec.to_ir() / from_ir() — k3l_ir JSON round-trip."""

from __future__ import annotations

import json


from k3c.lang.ir import (
    Always,
    Arith,
    ArithOp,
    CmpOp,
    Compare,
    EventField,
    Eventually,
    Field,
    Implies,
    LBool,
    LInt,
    LStr,
    Var,
    With,
)
from k3c.spec.builder import K3Spec, Spec


class TestToIr:
    def test_basic_structure(self):
        spec = Spec("test").state0({"x": 1}).permit("ok", when=LBool(True)).build()
        ir = spec.to_ir()
        assert ir["k3l_ir_version"] == "1.0"
        assert ir["name"] == "test"
        assert ir["state0"] == {"x": 1}
        assert ir["protocol_start"] == "__start__"

    def test_permits_serialized(self):
        spec = (
            Spec("test")
            .state0({"x": 0})
            .permit(
                "guard",
                when=Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0)),
                on="Inc",
            )
            .build()
        )
        ir = spec.to_ir()
        assert len(ir["permits"]) == 1
        assert ir["permits"][0]["name"] == "guard"
        assert ir["permits"][0]["on"] == "Inc"
        assert ir["permits"][0]["when"]["type"] == "Compare"

    def test_requires_serialized(self):
        spec = (
            Spec("test")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .require(
                "advance",
                on="Inc",
                transition=With(
                    Var("spec_state"),
                    (
                        (
                            "x",
                            Arith(ArithOp.ADD, Field(Var("spec_state"), "x"), LInt(1)),
                        ),
                    ),
                ),
            )
            .build()
        )
        ir = spec.to_ir()
        assert len(ir["requires"]) == 1
        assert ir["requires"][0]["on"] == "Inc"
        assert ir["requires"][0]["transition"]["type"] == "With"

    def test_maintains_serialized(self):
        spec = (
            Spec("test")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .maintain(
                "pos", expr=Always(Compare(CmpOp.GE, Field(Var("state"), "x"), LInt(0)))
            )
            .maintain("live", expr=Always(Eventually(LBool(True))))
            .build()
        )
        ir = spec.to_ir()
        assert len(ir["maintains"]) == 2
        assert ir["maintains"][0]["name"] == "pos"
        assert ir["maintains"][0]["expr"]["type"] == "Always"
        assert ir["maintains"][1]["name"] == "live"

    def test_has_ir_hash(self):
        spec = Spec("test").state0({"x": 1}).permit("ok", when=LBool(True)).build()
        ir = spec.to_ir()
        assert "ir_hash" in ir
        assert len(ir["ir_hash"]) == 64

    def test_ir_hash_deterministic(self):
        spec = Spec("test").state0({"x": 1}).permit("ok", when=LBool(True)).build()
        assert spec.to_ir()["ir_hash"] == spec.to_ir()["ir_hash"]

    def test_ir_hash_content_addressed(self):
        spec1 = Spec("a").state0({"x": 1}).permit("ok", when=LBool(True)).build()
        spec2 = Spec("b").state0({"x": 1}).permit("ok", when=LBool(True)).build()
        assert spec1.to_ir()["ir_hash"] != spec2.to_ir()["ir_hash"]

    def test_ir_hash_ignores_callables(self):
        spec1 = (
            Spec("test")
            .state0({"x": 1})
            .permit("ok", when=LBool(True))
            .project("v", lambda s: s["x"])
            .build()
        )
        spec2 = (
            Spec("test")
            .state0({"x": 1})
            .permit("ok", when=LBool(True))
            .project("v", lambda s: s["x"] * 2)
            .build()
        )
        assert spec1.to_ir()["ir_hash"] == spec2.to_ir()["ir_hash"]


class TestToIrJson:
    def test_valid_json(self):
        spec = Spec("test").state0({"x": 1}).permit("ok", when=LBool(True)).build()
        ir_json = spec.to_ir_json()
        parsed = json.loads(ir_json)
        assert parsed["name"] == "test"

    def test_indented(self):
        spec = Spec("test").state0({"x": 1}).permit("ok", when=LBool(True)).build()
        ir_json = spec.to_ir_json(indent=4)
        assert "\n    " in ir_json


class TestFromIr:
    def test_basic_round_trip(self):
        spec = (
            Spec("bank")
            .state0({"balance": 100})
            .permit("ok", when=LBool(True))
            .maintain(
                "pos",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            )
            .build()
        )
        ir = spec.to_ir()
        restored = K3Spec.from_ir(ir)
        assert restored.name == "bank"
        assert restored.state0 == {"balance": 100}
        assert len(restored.permits) == 1
        assert len(restored.maintains) == 1

    def test_json_round_trip(self):
        spec = (
            Spec("full")
            .state0({"x": 0, "y": "hello"})
            .permit("g1", when=Compare(CmpOp.GE, Field(Var("state"), "x"), LInt(0)))
            .permit("g2", when=LBool(True), on="Special")
            .require(
                "adv", on="Inc", transition=With(Var("spec_state"), (("x", LInt(1)),))
            )
            .maintain(
                "safety",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "x"), LInt(0))),
            )
            .maintain(
                "liveness",
                expr=Always(
                    Implies(
                        Compare(CmpOp.EQ, EventField("type"), LStr("Start")),
                        Eventually(
                            Compare(CmpOp.EQ, Field(Var("state"), "x"), LInt(10))
                        ),
                    )
                ),
            )
            .build()
        )
        ir_json = spec.to_ir_json()
        restored = K3Spec.from_ir(json.loads(ir_json))
        ir2 = restored.to_ir()
        assert spec.to_ir()["ir_hash"] == ir2["ir_hash"]

    def test_triple_round_trip(self):
        spec = (
            Spec("triple")
            .state0({"n": 0})
            .permit("ok", when=LBool(True))
            .maintain(
                "bounded",
                expr=Always(Compare(CmpOp.LE, Field(Var("state"), "n"), LInt(100))),
            )
            .build()
        )
        h1 = spec.to_ir()["ir_hash"]
        h2 = K3Spec.from_ir(spec.to_ir()).to_ir()["ir_hash"]
        h3 = K3Spec.from_ir(K3Spec.from_ir(spec.to_ir()).to_ir()).to_ir()["ir_hash"]
        assert h1 == h2 == h3

    def test_k3l_types_preserved(self):
        spec = (
            Spec("types")
            .state0({"x": 0})
            .permit("g", when=Compare(CmpOp.EQ, Field(Var("state"), "x"), LInt(0)))
            .maintain("m", expr=Always(Implies(LBool(True), Eventually(LBool(False)))))
            .require(
                "r",
                on="A",
                transition=With(
                    Var("spec_state"),
                    (
                        (
                            "x",
                            Arith(ArithOp.ADD, Field(Var("spec_state"), "x"), LInt(1)),
                        ),
                    ),
                ),
            )
            .build()
        )
        restored = K3Spec.from_ir(spec.to_ir())
        assert type(restored.permits[0].when).__name__ == "Compare"
        assert type(restored.maintains[0].expr).__name__ == "Always"
        assert type(restored.requires[0].transition).__name__ == "With"

    def test_protocol_start_preserved(self):
        spec = (
            Spec("proto")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .protocol_start("INIT")
            .build()
        )
        restored = K3Spec.from_ir(spec.to_ir())
        assert restored.protocol_start == "INIT"

    def test_callables_not_restored(self):
        spec = (
            Spec("callable")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .project("v", lambda s: s["x"])
            .output("out", lambda s, e, ns: {"type": "Out"})
            .korrelate(lift=lambda s: {"x": s["x"]})
            .decode(lambda e: e)
            .build()
        )
        restored = K3Spec.from_ir(spec.to_ir())
        assert restored.projections == ()
        assert restored.outputs == ()
        assert restored.korrelator is None
        assert restored.decode is None


class TestCallableSignatures:
    def test_projection_signature(self):
        def my_view(state: dict) -> int:
            """Return the count."""
            return state["count"]

        spec = (
            Spec("sig")
            .state0({"count": 0})
            .permit("ok", when=LBool(True))
            .project("view", my_view)
            .build()
        )
        ir = spec.to_ir()
        sig = ir["projections"][0]["signature"]
        assert sig["parameters"][0]["name"] == "state"
        assert sig["parameters"][0]["type"] == "Record"
        assert sig["returns"] == "Int"
        assert sig["description"] == "Return the count."

    def test_output_signature(self):
        def my_output(state: dict, event: dict, new_state: dict) -> dict:
            """Emit a receipt."""
            return {"type": "Receipt"}

        spec = (
            Spec("sig")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .output("receipt", my_output)
            .build()
        )
        ir = spec.to_ir()
        sig = ir["outputs"][0]["signature"]
        assert len(sig["parameters"]) == 3
        assert all(p["type"] == "Record" for p in sig["parameters"])
        assert sig["description"] == "Emit a receipt."

    def test_korrelator_signature(self):
        def my_lift(state: dict) -> dict:
            """Project for korrelation."""
            return {"x": state["x"]}

        spec = (
            Spec("sig")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .korrelate(lift=my_lift)
            .build()
        )
        ir = spec.to_ir()
        assert ir["korrelator"]["lift"]["parameters"][0]["type"] == "Record"
        assert ir["korrelator"]["lift"]["returns"] == "Record"
        assert ir["korrelator"]["correlate"] is None
        assert ir["korrelator"]["threshold"] is None

    def test_lambda_has_params_no_description(self):
        spec = (
            Spec("sig")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .project("v", lambda s: s["x"])
            .build()
        )
        ir = spec.to_ir()
        sig = ir["projections"][0]["signature"]
        assert sig["parameters"][0]["name"] == "s"
        assert "description" not in sig

    def test_decode_signature(self):
        spec = (
            Spec("sig")
            .state0({"x": 0})
            .permit("ok", when=LBool(True))
            .decode(lambda e: e)
            .build()
        )
        ir = spec.to_ir()
        assert ir["decode"]["parameters"][0]["name"] == "e"

    def test_no_decode_is_none(self):
        spec = Spec("sig").state0({"x": 0}).permit("ok", when=LBool(True)).build()
        ir = spec.to_ir()
        assert ir["decode"] is None

    def test_no_korrelator_is_none(self):
        spec = Spec("sig").state0({"x": 0}).permit("ok", when=LBool(True)).build()
        ir = spec.to_ir()
        assert ir["korrelator"] is None
