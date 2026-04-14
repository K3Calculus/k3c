"""Tests for k3c.universe.compose — parallel composition <||>."""

from __future__ import annotations


from k3c.lang.ir import Always, CmpOp, Compare, Field, LBool, LInt, Var
from k3c.spec.builder import Spec
from k3c.spec.result import Impossible, Ok, Violated
from k3c.universe.compose import ComposedUniverse
from k3c.universe.universe import universe


class _LeftSystem:
    def transition(self, s, e):
        return {**s, "x": s["x"] + e.get("n", 1)}


class _RightSystem:
    def transition(self, s, e):
        return {**s, "y": s["y"] + e.get("n", 1)}


def _left_spec():
    return Spec("left").state0({"x": 0}).permit("ok", when=LBool(True)).build()


def _right_spec():
    return Spec("right").state0({"y": 0}).permit("ok", when=LBool(True)).build()


def _router(event):
    tag = event.get("tag", "left")
    if tag == "both":
        return "both"
    return "right" if tag == "right" else "left"


def _composed():
    left = universe(_LeftSystem(), _left_spec())
    right = universe(_RightSystem(), _right_spec())
    return left.compose(right, _router)


class TestComposedApply:
    def test_route_left(self):
        c = _composed()
        r = c.apply({"tag": "left", "n": 10})
        assert isinstance(r, Ok)
        assert c.state["left"]["x"] == 10
        assert c.state["right"]["y"] == 0

    def test_route_right(self):
        c = _composed()
        r = c.apply({"tag": "right", "n": 5})
        assert isinstance(r, Ok)
        assert c.state["left"]["x"] == 0
        assert c.state["right"]["y"] == 5

    def test_route_both(self):
        c = _composed()
        r = c.apply({"tag": "both", "n": 3})
        assert isinstance(r, Ok)
        assert c.state["left"]["x"] == 3
        assert c.state["right"]["y"] == 3

    def test_default_routes_left(self):
        c = _composed()
        r = c.apply({"n": 7})
        assert isinstance(r, Ok)
        assert c.state["left"]["x"] == 7

    def test_sequential_events(self):
        c = _composed()
        c.apply({"tag": "left", "n": 10})
        c.apply({"tag": "right", "n": 20})
        c.apply({"tag": "left", "n": 5})
        assert c.state["left"]["x"] == 15
        assert c.state["right"]["y"] == 20


class TestComposedMerge:
    def test_violated_left_wins(self):
        bad_spec = (
            Spec("bad")
            .state0({"x": 10})
            .permit("ok", when=LBool(True))
            .maintain(
                "pos", expr=Always(Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0)))
            )
            .build()
        )

        class BadLeft:
            def transition(self, s, e):
                return {"x": -1}

        left = universe(BadLeft(), bad_spec)
        right = universe(_RightSystem(), _right_spec())
        c = left.compose(right, lambda e: "both")

        r = c.apply({"n": 1})
        assert isinstance(r, Violated)

    def test_impossible_left_propagates(self):
        guarded = (
            Spec("guarded").state0({"x": 0}).permit("no", when=LBool(False)).build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        left = universe(Noop(), guarded)
        right = universe(_RightSystem(), _right_spec())
        c = left.compose(right, lambda e: "both")

        r = c.apply({"n": 1})
        assert isinstance(r, Impossible)


class TestComposedReduce:
    def test_reduce_all_ok(self):
        c = _composed()
        r = c.reduce(
            [
                {"tag": "left", "n": 1},
                {"tag": "right", "n": 2},
                {"tag": "both", "n": 3},
            ]
        )
        assert isinstance(r, Ok)

    def test_reduce_stops_on_failure(self):
        guarded = (
            Spec("guarded").state0({"x": 0}).permit("no", when=LBool(False)).build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        left = universe(Noop(), guarded)
        right = universe(_RightSystem(), _right_spec())
        c = left.compose(right, lambda e: "left")

        r = c.reduce([{"n": 1}])
        assert isinstance(r, Impossible)


class TestAlgebraClosed:
    def test_compose_composed(self):
        c1 = _composed()
        third = universe(_LeftSystem(), _left_spec())
        c2 = c1.compose(third, lambda e: "left")
        assert isinstance(c2, ComposedUniverse)

    def test_bridge_composed(self):
        from k3c.universe.bridge import BridgedUniverse

        c = _composed()
        target = universe(_RightSystem(), _right_spec())
        b = c.bridge(target, lambda s, e, ns: {"tag": "right", "n": 1})
        assert isinstance(b, BridgedUniverse)
