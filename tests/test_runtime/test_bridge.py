"""Tests for k3c.runtime.bridge -- BridgedUniverse."""

from __future__ import annotations


from k3c.engine.result import Ok
from k3c.ir.expr import Always, CmpOp, Compare, EventField, Field, LInt, Var
from k3c.runtime.bridge import BridgeMode, BridgedUniverse, FallbackStrategy
from k3c.runtime.universe import Universe
from k3c.ir.expr import LStr, Record
from k3c.spec.model import Maintain, Output, Permit, Projection, Spec


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


def _mapper(source_state, event, new_state):
    return {"n": event.get("n", 0), "type": "bridged"}


class TestBridgeSync:
    def test_basic_bridge(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=_counter_spec("target"), transition=_counter_transition)
        bridged = BridgedUniverse(source=source, target=target, mapper=_mapper)

        r = bridged.apply({"n": 5})
        assert isinstance(r, Ok)
        assert source.state["count"] == 5
        assert target.state["count"] == 5

    def test_mapper_returns_none_skips(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=_counter_spec("target"), transition=_counter_transition)
        bridged = BridgedUniverse(
            source=source,
            target=target,
            mapper=lambda s, e, ns: None,
        )
        r = bridged.apply({"n": 5})
        assert isinstance(r, Ok)
        assert target.state["count"] == 0  # not bridged


class TestBridgeAsync:
    def test_async_source_commits(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=_counter_spec("target"), transition=_counter_transition)
        bridged = BridgedUniverse(
            source=source,
            target=target,
            mapper=_mapper,
            mode=BridgeMode.ASYNC,
        )
        r = bridged.apply({"n": 3})
        assert isinstance(r, Ok)
        assert source.state["count"] == 3


class TestBridgeBestEffort:
    def test_best_effort(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=_counter_spec("target"), transition=_counter_transition)
        bridged = BridgedUniverse(
            source=source,
            target=target,
            mapper=_mapper,
            mode=BridgeMode.BEST_EFFORT,
        )
        r = bridged.apply({"n": 2})
        assert isinstance(r, Ok)


class TestDeadLetter:
    def test_dead_letter_on_target_reject(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=_counter_spec("target"), transition=_counter_transition)

        def bad_mapper(s, e, ns):
            return {"n": -1}  # will be rejected by target guard

        bridged = BridgedUniverse(
            source=source,
            target=target,
            mapper=bad_mapper,
            mode=BridgeMode.SYNCHRONOUS,
            fallback=FallbackStrategy.DEAD_LETTER,
        )
        r = bridged.apply({"n": 5})
        assert isinstance(r, Ok)
        assert len(bridged.dead_letters) == 1


class TestBridgeState:
    def test_composite_state(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=_counter_spec("target"), transition=_counter_transition)
        bridged = BridgedUniverse(source=source, target=target, mapper=_mapper)
        bridged.apply({"n": 5})
        state = bridged.state
        assert state["source"]["count"] == 5
        assert state["target"]["count"] == 5


class TestBridgeReduce:
    def test_reduce(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=_counter_spec("target"), transition=_counter_transition)
        bridged = BridgedUniverse(source=source, target=target, mapper=_mapper)
        r = bridged.reduce([{"n": 1}, {"n": 2}, {"n": 3}])
        assert isinstance(r, Ok)
        assert source.state["count"] == 6
        assert target.state["count"] == 6


class TestBridgeSyncReturnsTarget:
    """Synchronous bridge returns target outputs and projections."""

    def _target_spec(self):
        return Spec(
            name="target",
            state0={"count": 0},
            permits=(
                Permit(name="valid", when=Compare(CmpOp.GE, EventField("n"), LInt(0))),
            ),
            maintains=(
                Maintain(
                    name="non_negative",
                    expr=Always(
                        Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))
                    ),
                ),
            ),
            projections=(
                Projection(
                    name="double", expr=Field(Var("state"), "count")
                ),
            ),
            outputs=(
                Output(
                    name="ack",
                    expr=Record((("status", LStr("ok")),)),
                ),
            ),
        )

    def test_target_outputs_in_result(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=self._target_spec(), transition=_counter_transition)
        bridged = BridgedUniverse(source=source, target=target, mapper=_mapper)

        r = bridged.apply({"n": 5})
        assert isinstance(r, Ok)
        # Target output flows back
        assert any(o.get("status") == "ok" for o in r.outputs)

    def test_target_projections_namespaced(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=self._target_spec(), transition=_counter_transition)
        bridged = BridgedUniverse(source=source, target=target, mapper=_mapper)

        r = bridged.apply({"n": 5})
        assert isinstance(r, Ok)
        # Target projections are namespaced with "target."
        assert "target.double" in r.projections

    def test_combined_state(self):
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=self._target_spec(), transition=_counter_transition)
        bridged = BridgedUniverse(source=source, target=target, mapper=_mapper)

        r = bridged.apply({"n": 5})
        assert isinstance(r, Ok)
        assert r.state["source"]["count"] == 5
        assert r.state["target"]["count"] == 5

    def test_async_still_returns_source_only(self):
        """Async mode returns source result (target may not be done)."""
        source = Universe(spec=_counter_spec("source"), transition=_counter_transition)
        target = Universe(spec=self._target_spec(), transition=_counter_transition)
        bridged = BridgedUniverse(
            source=source, target=target, mapper=_mapper, mode=BridgeMode.ASYNC
        )

        r = bridged.apply({"n": 5})
        assert isinstance(r, Ok)
        # Async returns source result — no target outputs
        assert len(r.outputs) == 0
