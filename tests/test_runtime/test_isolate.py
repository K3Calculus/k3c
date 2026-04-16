"""Tests for k3c.runtime.isolate -- IsolatedUniverse."""

from __future__ import annotations

from k3c.engine.result import Ok
from k3c.ir.expr import Always, CmpOp, Compare, Field, LBool, LInt, Var
from k3c.runtime.universe import Universe
from k3c.spec.model import Maintain, Permit, Spec


def _counter_spec():
    return Spec(
        name="counter",
        state0={"count": 0},
        permits=(Permit(name="ok", when=LBool(True), on="Inc"),),
        maintains=(
            Maintain(
                name="pos",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
            ),
        ),
    )


def _counter_t(s, e):
    return {**s, "count": s["count"] + e.get("n", 1)}


class TestIsolatedUniverse:
    def test_isolate_from_universe(self):
        u = Universe(spec=_counter_spec(), transition=_counter_t)
        u.apply({"type": "Inc", "n": 5})
        iso = u.isolate()
        assert iso.state["count"] == 5

    def test_isolation_no_shared_state(self):
        u = Universe(spec=_counter_spec(), transition=_counter_t)
        u.apply({"type": "Inc", "n": 5})
        iso = u.isolate()
        iso.apply({"type": "Inc", "n": 100})
        assert u.state["count"] == 5
        assert iso.state["count"] == 105

    def test_apply(self):
        u = Universe(spec=_counter_spec(), transition=_counter_t)
        iso = u.isolate()
        r = iso.apply({"type": "Inc", "n": 3})
        assert isinstance(r, Ok)
        assert iso.state["count"] == 3

    def test_reduce(self):
        u = Universe(spec=_counter_spec(), transition=_counter_t)
        iso = u.isolate()
        r = iso.reduce(
            [{"type": "Inc", "n": 1}, {"type": "Inc", "n": 2}, {"type": "Inc", "n": 3}]
        )
        assert isinstance(r, Ok)
        assert iso.state["count"] == 6

    def test_reset(self):
        u = Universe(spec=_counter_spec(), transition=_counter_t)
        u.apply({"type": "Inc", "n": 10})
        iso = u.isolate()
        iso.apply({"type": "Inc", "n": 5})
        assert iso.state["count"] == 15
        iso.reset()
        assert iso.state["count"] == 10  # reset to state at isolation time

    def test_repr(self):
        u = Universe(spec=_counter_spec(), transition=_counter_t)
        iso = u.isolate()
        assert "IsolatedUniverse" in repr(iso)
        assert "isolated=True" in repr(iso)
