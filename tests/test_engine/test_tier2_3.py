"""Tests for tier-2/3 improvements."""

from __future__ import annotations

from k3c.engine.result import Ok
from k3c.ir.expr import (
    Always,
    CmpOp,
    Compare,
    Concat,
    EventField,
    Field,
    LInt,
    LStr,
    Var,
)
from k3c.runtime.universe import Universe
from k3c.spec.extract import (
    ByteSlice,
    Computed,
    DecodeFields,
    DecodeIdentity,
    run_decode,
)
from k3c.spec.model import Maintain, Permit, Spec


def _counter_t(state, event):
    n = event.get("n", 1)
    if isinstance(n, str):
        n = int(n)
    return {**state, "count": state["count"] + n}


class TestByteSliceCast:
    def test_cast_int(self):
        plan = DecodeFields(fields=(
            ("n", ByteSlice(start=0, length=6, cast="int")),
        ))
        result = run_decode(plan, "000003rest")
        assert result["n"] == 3

    def test_cast_float(self):
        plan = DecodeFields(fields=(
            ("val", ByteSlice(start=0, length=5, cast="float")),
        ))
        result = run_decode(plan, "3.140rest")
        assert result["val"] == 3.14

    def test_cast_none_returns_string(self):
        plan = DecodeFields(fields=(
            ("s", ByteSlice(start=0, length=3)),
        ))
        result = run_decode(plan, "ABCrest")
        assert result["s"] == "ABC"
        assert isinstance(result["s"], str)

    def test_cast_invalid_returns_none(self):
        plan = DecodeFields(fields=(
            ("n", ByteSlice(start=0, length=3, cast="int")),
        ))
        result = run_decode(plan, "ABCrest")
        assert result["n"] is None

    def test_cast_in_universe(self):
        spec = Spec(
            name="cast_test",
            state0={"count": 0},
            decode=DecodeFields(fields=(
                ("type", ByteSlice(start=0, length=3)),
                ("n", ByteSlice(start=3, length=3, cast="int")),
            )),
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
        )
        u = Universe(spec=spec, transition=_counter_t)
        r = u.apply("Inc005")
        assert isinstance(r, Ok)
        assert r.state["count"] == 5


class TestComputedInDecode:
    def test_computed_expr_produces_value(self):
        plan = DecodeFields(fields=(
            ("raw_type", ByteSlice(start=0, length=1)),
            ("type", Computed(expr=Concat(LStr("RT"), Field(Var("event"), "raw_type")))),
        ))
        result = run_decode(plan, "3some_data")
        assert result["raw_type"] == "3"
        assert result["type"] == "RT3"

    def test_computed_literal(self):
        plan = DecodeFields(fields=(
            ("type", Computed(expr=LStr("RT1"))),
        ))
        result = run_decode(plan, "anything")
        assert result["type"] == "RT1"


class TestSpecSliceRelax:
    def test_relax_drops_named_maintains(self):
        spec = Spec(
            name="relax_test",
            state0={"count": 0, "serial": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
            maintains=(
                Maintain(name="positive", expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0)))),
                Maintain(name="serial_continuity", expr=Always(Compare(CmpOp.GE, Field(Var("state"), "serial"), LInt(0)))),
            ),
        )
        sliced = spec.slice(from_state={"count": 10, "serial": 100}, relax=["serial_continuity"])
        assert len(sliced.maintains) == 1
        assert sliced.maintains[0].name == "positive"
        assert sliced.state0 == {"count": 10, "serial": 100}

    def test_relax_none_keeps_all(self):
        spec = Spec(
            name="keep_all",
            state0={"x": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
            maintains=(
                Maintain(name="a", expr=Always(Compare(CmpOp.GE, LInt(1), LInt(0)))),
                Maintain(name="b", expr=Always(Compare(CmpOp.GE, LInt(1), LInt(0)))),
            ),
        )
        sliced = spec.slice(from_state={"x": 5})
        assert len(sliced.maintains) == 2


class TestUniverseGet:
    def test_get_field(self):
        spec = Spec(
            name="get_test",
            state0={"balance": 100, "name": "test"},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
        )
        u = Universe(spec=spec, transition=lambda s, e: s)
        assert u.get("balance") == 100
        assert u.get("name") == "test"
        assert u.get("missing") is None
        assert u.get("missing", "default") == "default"


class TestSpecDecodeEvent:
    def test_decode_without_apply(self):
        spec = Spec(
            name="decode_test",
            state0={"x": 0},
            decode=DecodeFields(fields=(
                ("type", ByteSlice(start=0, length=3)),
                ("value", ByteSlice(start=3, length=5, cast="int")),
            )),
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
        )
        result = spec.decode_event("Inc00042rest")
        assert result["type"] == "Inc"
        assert result["value"] == 42

    def test_decode_identity(self):
        spec = Spec(
            name="identity",
            state0={"x": 0},
            decode=DecodeIdentity(),
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
        )
        result = spec.decode_event({"type": "Inc", "n": 5})
        assert result == {"type": "Inc", "n": 5}

    def test_decode_no_plan(self):
        spec = Spec(
            name="no_plan",
            state0={"x": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
        )
        result = spec.decode_event({"type": "Inc"})
        assert result == {"type": "Inc"}


class TestHashFnNone:
    def test_none_skips_hashing(self):
        spec = Spec(
            name="no_hash",
            state0={"count": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, EventField("n"), LInt(0))),),
        )
        u = Universe(spec=spec, transition=_counter_t, hash_fn="none")
        r = u.apply({"type": "Inc", "n": 5})
        assert isinstance(r, Ok)
        assert r.step_hash == ""
        assert r.state["count"] == 5

    def test_none_faster_than_sha256(self):
        """Smoke test that none mode works for multiple steps."""
        spec = Spec(
            name="perf",
            state0={"count": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, EventField("n"), LInt(0))),),
        )
        u = Universe(spec=spec, transition=_counter_t, hash_fn="none")
        for i in range(100):
            r = u.apply({"type": "Inc", "n": 1})
            assert isinstance(r, Ok)
        assert u.get("count") == 100
