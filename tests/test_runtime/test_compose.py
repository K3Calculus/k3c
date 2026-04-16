"""Tests for k3c.runtime.compose -- ComposedUniverse."""

from __future__ import annotations

from k3c.engine.result import Impossible, Ok
from k3c.ir.expr import Always, CmpOp, Compare, EventField, Field, LInt, Var
from k3c.runtime.compose import ComposedUniverse
from k3c.runtime.universe import Universe
from k3c.spec.model import Maintain, Permit, Spec


def _counter_spec(name):
    return Spec(
        name=name,
        state0={"count": 0},
        permits=(
            Permit(name="valid", when=Compare(CmpOp.GE, EventField("n"), LInt(0))),
        ),
        maintains=(
            Maintain(
                name="non_negative",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
            ),
        ),
    )


def _counter_transition(state, event):
    return {**state, "count": state["count"] + event.get("n", 0)}


def _make_composed():
    u1 = Universe(spec=_counter_spec("left"), transition=_counter_transition)
    u2 = Universe(spec=_counter_spec("right"), transition=_counter_transition)

    def router(event):
        return event.get("target", "left")

    return ComposedUniverse(left=u1, right=u2, router=router)


class TestCompose:
    def test_route_left(self):
        c = _make_composed()
        r = c.apply({"n": 5, "target": "left"})
        assert isinstance(r, Ok)
        assert c.state["left"]["count"] == 5
        assert c.state["right"]["count"] == 0

    def test_route_right(self):
        c = _make_composed()
        r = c.apply({"n": 3, "target": "right"})
        assert isinstance(r, Ok)
        assert c.state["right"]["count"] == 3
        assert c.state["left"]["count"] == 0

    def test_route_both(self):
        c = _make_composed()
        r = c.apply({"n": 2, "target": "both"})
        assert isinstance(r, Ok)
        assert r.state["left"]["count"] == 2
        assert r.state["right"]["count"] == 2

    def test_impossible_propagates(self):
        c = _make_composed()
        r = c.apply({"n": -1, "target": "left"})
        assert isinstance(r, Impossible)

    def test_reduce(self):
        c = _make_composed()
        r = c.reduce(
            [
                {"n": 1, "target": "left"},
                {"n": 2, "target": "right"},
                {"n": 3, "target": "both"},
            ]
        )
        assert isinstance(r, Ok)
        assert c.state["left"]["count"] == 4
        assert c.state["right"]["count"] == 5

    def test_compose_closed(self):
        c = _make_composed()
        u3 = Universe(spec=_counter_spec("third"), transition=_counter_transition)
        c2 = c.compose(u3, router=lambda e: "left")
        assert isinstance(c2, ComposedUniverse)
