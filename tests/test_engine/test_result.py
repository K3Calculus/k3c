"""Tests for k3c.engine.result -- Ok, Impossible, Violated, Why."""

from __future__ import annotations

import pytest

from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Impossible, Ok, Violated, Why, WhyKind
from k3c.errors import K3ViolatedException


def _make_ctx():
    return SpecCtx.initial({"x": 0})


def _make_why(**overrides):
    defaults = {
        "rule": "test_rule",
        "kind": WhyKind.PERMIT,
        "messages": ("test message",),
        "before": {"x": 0},
        "after": None,
        "event": {"type": "test"},
        "ctx": _make_ctx(),
        "expected": None,
        "trace": (),
        "step_hash": "abc123",
    }
    return Why(**{**defaults, **overrides})


class TestWhy:
    def test_message_property(self):
        w = _make_why(messages=("first", "second"))
        assert w.message == "first"

    def test_message_empty(self):
        w = _make_why(messages=())
        assert w.message == ""

    def test_fingerprint_stable(self):
        w1 = _make_why()
        w2 = _make_why()
        assert w1.fingerprint == w2.fingerprint

    def test_fingerprint_differs_by_rule(self):
        w1 = _make_why(rule="rule_a")
        w2 = _make_why(rule="rule_b")
        assert w1.fingerprint != w2.fingerprint

    def test_to_dict(self):
        w = _make_why()
        d = w.to_dict()
        assert d["rule"] == "test_rule"
        assert d["kind"] == "permit"
        assert "fingerprint" in d
        assert "step_hash" in d

    def test_to_prompt(self):
        w = _make_why()
        prompt = w.to_prompt()
        assert "PERMIT" in prompt
        assert "test_rule" in prompt

    def test_to_log_record(self):
        w = _make_why(kind=WhyKind.MAINTAIN)
        record = w.to_log_record()
        assert record["severity"] == "ERROR"
        assert record["k3c.kind"] == "maintain"


class TestOk:
    def test_fields(self):
        ctx = _make_ctx()
        ok = Ok(state={"x": 1}, ctx=ctx, step_hash="abc")
        assert ok.state == {"x": 1}
        assert ok.step_hash == "abc"

    def test_projections_default_empty(self):
        ok = Ok(state={}, ctx=_make_ctx(), step_hash="h")
        assert ok.projections == {}

    def test_outputs_default_empty(self):
        ok = Ok(state={}, ctx=_make_ctx(), step_hash="h")
        assert ok.outputs == ()

    def test_map(self):
        ok = Ok(state={"x": 1}, ctx=_make_ctx(), step_hash="h")
        mapped = ok.map(lambda s: {**s, "y": 2})
        assert isinstance(mapped, Ok)
        assert mapped.state == {"x": 1, "y": 2}

    def test_unwrap(self):
        ctx = _make_ctx()
        ok = Ok(state={"x": 1}, ctx=ctx, step_hash="h")
        s, c = ok.unwrap()
        assert s == {"x": 1}
        assert c is ctx

    def test_repr(self):
        ok = Ok(state={"x": 1}, ctx=_make_ctx(), step_hash="abcdef12345678")
        assert "Ok" in repr(ok)
        assert "abcdef12" in repr(ok)


class TestImpossible:
    def test_carries_why(self):
        w = _make_why(kind=WhyKind.PERMIT)
        imp = Impossible(why=w)
        assert imp.why.kind == WhyKind.PERMIT

    def test_map_short_circuits(self):
        imp = Impossible(why=_make_why())
        result = imp.map(lambda _: pytest.fail("Should not be called"))
        assert result is imp


class TestViolated:
    def test_carries_why(self):
        w = _make_why(kind=WhyKind.MAINTAIN)
        v = Violated(why=w)
        assert v.why.kind == WhyKind.MAINTAIN

    def test_raise(self):
        v = Violated(why=_make_why(kind=WhyKind.MAINTAIN))
        with pytest.raises(K3ViolatedException):
            v.raise_()

    def test_map_short_circuits(self):
        v = Violated(why=_make_why())
        result = v.map(lambda _: pytest.fail("Should not be called"))
        assert result is v


class TestWhyKind:
    def test_all_values(self):
        assert len(WhyKind) == 6
        assert WhyKind.PERMIT == "permit"
        assert WhyKind.MISSING == "missing"
        assert WhyKind.MAINTAIN == "maintain"
        assert WhyKind.KORRELATE == "korrelate"
        assert WhyKind.TIMER == "timer"
        assert WhyKind.LIVENESS == "liveness"
