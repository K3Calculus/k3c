"""Tests for k3c.spec.serde — full Spec round-trip serialization."""

from __future__ import annotations

import json

from k3c.ir.expr import (
    AllOf,
    Always,
    AnyOf,
    Arith,
    ArithOp,
    CmpOp,
    Compare,
    EventField,
    Field,
    In,
    LBool,
    LInt,
    LStr,
    Matches,
    Var,
    With,
)
from k3c.ir.serde import from_dict, to_dict
from k3c.ir.types import TInt, TString
from k3c.spec.extract import (
    ByteSlice,
    Computed,
    DecodeDispatch,
    DecodeFields,
    DecodeIdentity,
    Identity,
    JsonPath,
    MapKey,
    TextEncoding,
)
from k3c.spec.model import (
    CompareMode,
    FieldDef,
    Korrelator,
    Maintain,
    Output,
    Permit,
    Projection,
    Require,
    Severity,
    Spec,
    Validate,
)
from k3c.spec.serde import (
    decode_from_dict,
    decode_to_dict,
    extractor_from_dict,
    extractor_to_dict,
    spec_from_dict,
    spec_to_dict,
)


class TestExprSerdeNewNodes:
    """AllOf, AnyOf, In round-trip through IR serde."""

    def test_allof_round_trip(self):
        expr = AllOf(exprs=(LBool(True), LInt(1), LStr("x")))
        d = to_dict(expr)
        assert d["type"] == "AllOf"
        assert len(d["exprs"]) == 3
        assert from_dict(d) == expr

    def test_anyof_round_trip(self):
        expr = AnyOf(exprs=(LBool(False), LBool(True)))
        d = to_dict(expr)
        assert d["type"] == "AnyOf"
        assert from_dict(d) == expr

    def test_in_round_trip(self):
        expr = In(
            expr=Field(Var("state"), "status"),
            values=(LStr("a"), LStr("b"), LStr("c")),
        )
        d = to_dict(expr)
        assert d["type"] == "In"
        assert len(d["values"]) == 3
        assert from_dict(d) == expr

    def test_empty_allof(self):
        expr = AllOf(exprs=())
        assert from_dict(to_dict(expr)) == expr


class TestExtractorSerde:
    def test_byte_slice(self):
        ext = ByteSlice(start=10, length=5, encoding=TextEncoding.UTF8, trim=False, cast="int")
        d = extractor_to_dict(ext)
        assert d["cast"] == "int"
        assert d["encoding"] == "UTF-8"
        assert extractor_from_dict(d) == ext

    def test_byte_slice_defaults(self):
        ext = ByteSlice(start=0, length=3)
        d = extractor_to_dict(ext)
        assert "encoding" not in d  # default omitted
        assert "trim" not in d
        assert "cast" not in d
        assert extractor_from_dict(d) == ext

    def test_map_key(self):
        ext = MapKey(key="amount")
        assert extractor_from_dict(extractor_to_dict(ext)) == ext

    def test_json_path(self):
        ext = JsonPath(path="$.data.value")
        assert extractor_from_dict(extractor_to_dict(ext)) == ext

    def test_identity(self):
        ext = Identity()
        assert extractor_from_dict(extractor_to_dict(ext)) == ext

    def test_computed(self):
        ext = Computed(expr=LStr("RT1"))
        d = extractor_to_dict(ext)
        assert d["type"] == "Computed"
        assert extractor_from_dict(d) == ext


class TestDecodePlanSerde:
    def test_identity(self):
        plan = DecodeIdentity()
        assert decode_from_dict(decode_to_dict(plan)) == plan

    def test_fields(self):
        plan = DecodeFields(fields=(
            ("type", ByteSlice(start=0, length=3)),
            ("amount", MapKey(key="amount")),
        ))
        d = decode_to_dict(plan)
        assert d["type"] == "DecodeFields"
        assert decode_from_dict(d) == plan

    def test_dispatch_with_skip(self):
        plan = DecodeDispatch(
            discriminant=ByteSlice(start=0, length=1),
            cases=(
                ("1", DecodeIdentity()),
                ("2", DecodeFields(fields=(("x", MapKey(key="x")),))),
            ),
            default="skip",
        )
        d = decode_to_dict(plan)
        assert d["default"] == "skip"
        assert decode_from_dict(d) == plan

    def test_dispatch_with_fallback_plan(self):
        plan = DecodeDispatch(
            discriminant=MapKey(key="type"),
            cases=(("a", DecodeIdentity()),),
            default=DecodeIdentity(),
        )
        d = decode_to_dict(plan)
        assert isinstance(d["default"], dict)
        assert decode_from_dict(d) == plan

    def test_dispatch_no_default(self):
        plan = DecodeDispatch(
            discriminant=MapKey(key="type"),
            cases=(("a", DecodeIdentity()),),
        )
        d = decode_to_dict(plan)
        assert "default" not in d
        assert decode_from_dict(d) == plan


class TestSpecSerde:
    def _bank_spec(self):
        return Spec(
            name="bank",
            state0={"balance": 100},
            permits=(
                Permit(
                    name="has_funds",
                    on="Withdraw",
                    when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
                ),
            ),
            maintains=(
                Maintain(
                    name="non_negative",
                    expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
                ),
            ),
        )

    def test_basic_round_trip(self):
        spec = self._bank_spec()
        d = spec_to_dict(spec)
        restored = spec_from_dict(d)
        assert restored.name == spec.name
        assert restored.state0 == spec.state0
        assert len(restored.permits) == 1
        assert restored.permits[0].name == "has_funds"
        assert restored.permits[0].on == "Withdraw"
        assert len(restored.maintains) == 1
        assert restored.maintains[0].name == "non_negative"

    def test_json_round_trip(self):
        """Full JSON serialization round-trip."""
        spec = self._bank_spec()
        json_str = json.dumps(spec_to_dict(spec), indent=2)
        restored = spec_from_dict(json.loads(json_str))
        assert restored.name == spec.name
        assert restored.state0 == spec.state0

    def test_severity_round_trip(self):
        spec = Spec(
            name="warn",
            state0={"x": 0},
            maintains=(
                Maintain(name="strict", expr=Always(LBool(True)), severity=Severity.ERROR),
                Maintain(name="soft", expr=Always(LBool(True)), severity=Severity.WARNING),
            ),
        )
        d = spec_to_dict(spec)
        # ERROR is default — omitted
        assert "severity" not in d["maintains"][0]
        # WARNING is explicit
        assert d["maintains"][1]["severity"] == "warning"
        restored = spec_from_dict(d)
        assert restored.maintains[0].severity == Severity.ERROR
        assert restored.maintains[1].severity == Severity.WARNING

    def test_validate_round_trip(self):
        spec = Spec(
            name="validated",
            state0={"x": 0},
            validates=(
                Validate(
                    name="valid_code",
                    on="SetCode",
                    check=Matches(EventField("code"), r"^[A-Z]{3}$"),
                    severity=Severity.WARNING,
                    field="code",
                    constraint="^[A-Z]{3}$",
                ),
            ),
        )
        d = spec_to_dict(spec)
        assert len(d["validates"]) == 1
        v = d["validates"][0]
        assert v["name"] == "valid_code"
        assert v["on"] == "SetCode"
        assert v["field"] == "code"
        assert v["constraint"] == "^[A-Z]{3}$"
        assert v["severity"] == "warning"
        restored = spec_from_dict(d)
        assert restored.validates[0] == spec.validates[0]

    def test_full_spec_round_trip(self):
        """Comprehensive spec with all clause types."""
        spec = Spec(
            name="full",
            state0={"count": 0, "status": "idle"},
            fields=(
                FieldDef(name="count", type=TInt(), description="counter"),
                FieldDef(name="status", type=TString(), required=False),
            ),
            decode=DecodeFields(fields=(
                ("type", ByteSlice(start=0, length=3)),
                ("n", ByteSlice(start=3, length=3, cast="int")),
            )),
            permits=(
                Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),
                Permit(name="inc_only", on="Inc", when=LBool(True)),
            ),
            requires=(
                Require(
                    name="track",
                    on="Inc",
                    transition=With(
                        Var("spec_state"),
                        (("count", Arith(ArithOp.ADD, Field(Var("spec_state"), "count"), LInt(1))),),
                    ),
                ),
            ),
            maintains=(
                Maintain(name="positive", expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0)))),
                Maintain(name="soft_limit", expr=Always(Compare(CmpOp.LE, Field(Var("state"), "count"), LInt(1000))), severity=Severity.WARNING),
            ),
            validates=(
                Validate(
                    name="valid_phase",
                    on="SetPhase",
                    check=In(EventField("phase"), (LStr("idle"), LStr("active"))),
                    field="phase",
                ),
            ),
            projections=(
                Projection(name="double", expr=Arith(ArithOp.MUL, Field(Var("state"), "count"), LInt(2))),
            ),
            outputs=(
                Output(name="ack", expr=LBool(True), on="Inc"),
            ),
            korrelator=Korrelator(
                actual=Field(Var("state"), "count"),
                intended=Field(Var("spec_state"), "count"),
                mode=CompareMode.EXACT,
            ),
            protocol_start="idle",
        )

        d = spec_to_dict(spec)
        json_str = json.dumps(d, indent=2)
        restored = spec_from_dict(json.loads(json_str))

        assert restored.name == "full"
        assert restored.state0 == {"count": 0, "status": "idle"}
        assert len(restored.fields) == 2
        assert restored.fields[0].name == "count"
        assert restored.fields[1].required is False
        assert restored.decode is not None
        assert len(restored.permits) == 2
        assert len(restored.requires) == 1
        assert len(restored.maintains) == 2
        assert restored.maintains[1].severity == Severity.WARNING
        assert len(restored.validates) == 1
        assert restored.validates[0].field == "phase"
        assert len(restored.projections) == 1
        assert len(restored.outputs) == 1
        assert restored.outputs[0].on == "Inc"
        assert restored.korrelator is not None
        assert restored.korrelator.mode == CompareMode.EXACT
        assert restored.protocol_start == "idle"

    def test_empty_spec_round_trip(self):
        spec = Spec(name="empty", state0={"x": 0})
        d = spec_to_dict(spec)
        restored = spec_from_dict(d)
        assert restored.name == "empty"
        assert restored.state0 == {"x": 0}
        assert restored.permits == ()
        assert restored.maintains == ()
        assert restored.validates == ()

    def test_defaults_omitted_in_output(self):
        """Default values should not appear in serialized output."""
        spec = Spec(
            name="minimal",
            state0={"x": 0},
            permits=(Permit(name="ok", when=LBool(True)),),
        )
        d = spec_to_dict(spec)
        assert "fields" not in d
        assert "decode" not in d
        assert "requires" not in d
        assert "maintains" not in d
        assert "validates" not in d
        assert "projections" not in d
        assert "outputs" not in d
        assert "korrelator" not in d
        assert "protocol_start" not in d  # default "__start__" omitted
