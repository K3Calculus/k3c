"""Tests for k3c.universe.bridge — cross-universe event propagation <->."""

from __future__ import annotations

import pytest

from k3c.errors import K3BridgeError
from k3c.lang.ir import Always, CmpOp, Compare, Field, LBool, LInt, Var
from k3c.spec.builder import Spec
from k3c.spec.result import Impossible, Ok, Violated
from k3c.universe.bridge import BridgedUniverse
from k3c.universe.retry import (
    BridgeMode,
    DeadLetterEntry,
    FallbackStrategy,
    RetryPolicy,
)
from k3c.universe.universe import universe


class _SourceSystem:
    def transition(self, s, e):
        return {**s, "count": s["count"] + 1}


class _TargetSystem:
    def transition(self, s, e):
        return {**s, "log": s["log"] + [e.get("data", "")]}


def _source_spec():
    return Spec("source").state0({"count": 0}).permit("ok", when=LBool(True)).build()


def _target_spec():
    return Spec("target").state0({"log": []}).permit("ok", when=LBool(True)).build()


def _mapper(src_state, event, new_state):
    return {"type": "Audit", "data": event.get("type", "unknown")}


def _bridged(mode=BridgeMode.SYNCHRONOUS, **kwargs):
    source = universe(_SourceSystem(), _source_spec())
    target = universe(_TargetSystem(), _target_spec())
    return source.bridge(target, _mapper, mode, **kwargs)


class TestBridgeSync:
    def test_basic_bridge(self):
        b = _bridged()
        r = b.apply({"type": "Action"})
        assert isinstance(r, Ok)
        assert b.state["source"]["count"] == 1
        assert b.state["target"]["log"] == ["Action"]

    def test_multiple_events(self):
        b = _bridged()
        b.apply({"type": "A"})
        b.apply({"type": "B"})
        b.apply({"type": "C"})
        assert b.state["source"]["count"] == 3
        assert b.state["target"]["log"] == ["A", "B", "C"]

    def test_source_impossible_no_bridge(self):
        guarded = (
            Spec("guarded").state0({"count": 0}).permit("no", when=LBool(False)).build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        source = universe(Noop(), guarded)
        target = universe(_TargetSystem(), _target_spec())
        b = source.bridge(target, _mapper, BridgeMode.SYNCHRONOUS)

        r = b.apply({"type": "X"})
        assert isinstance(r, Impossible)
        assert b.state["target"]["log"] == []

    def test_target_violated_propagates(self):
        bad_target_spec = (
            Spec("bad_target")
            .state0({"log": [], "count": -1})
            .permit("ok", when=LBool(True))
            .maintain(
                "negative",
                expr=Always(Compare(CmpOp.LT, Field(Var("state"), "count"), LInt(0))),
            )
            .build()
        )

        class BadTarget:
            def transition(self, s, e):
                return {**s, "log": s["log"] + ["x"], "count": 1}

        source = universe(_SourceSystem(), _source_spec())
        target = universe(BadTarget(), bad_target_spec)
        b = source.bridge(target, _mapper, BridgeMode.SYNCHRONOUS)

        r = b.apply({"type": "X"})
        assert isinstance(r, Violated)


class TestBridgeAsync:
    def test_async_source_always_ok(self):
        b = _bridged(mode=BridgeMode.ASYNC)
        r = b.apply({"type": "Action"})
        assert isinstance(r, Ok)
        assert b.state["source"]["count"] == 1
        assert b.state["target"]["log"] == ["Action"]


class TestBridgeBestEffort:
    def test_best_effort_ignores_target_failure(self):
        fail_spec = (
            Spec("fail").state0({"x": 0}).permit("no", when=LBool(False)).build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        source = universe(_SourceSystem(), _source_spec())
        target = universe(Noop(), fail_spec)
        b = source.bridge(target, _mapper, BridgeMode.BEST_EFFORT)

        r = b.apply({"type": "X"})
        assert isinstance(r, Ok)
        assert b.state["source"]["count"] == 1


class TestMapperNone:
    def test_mapper_returns_none_skips_bridge(self):
        source = universe(_SourceSystem(), _source_spec())
        target = universe(_TargetSystem(), _target_spec())
        b = source.bridge(target, lambda s, e, ns: None, BridgeMode.SYNCHRONOUS)

        r = b.apply({"type": "X"})
        assert isinstance(r, Ok)
        assert b.state["source"]["count"] == 1
        assert b.state["target"]["log"] == []


class TestRetryPolicy:
    def test_no_retry(self):
        p = RetryPolicy.no_retry()
        assert p.max_attempts == 1
        assert p.strategy == "none"

    def test_fixed_delay(self):
        p = RetryPolicy.fixed_delay(3, 100)
        assert p.max_attempts == 3
        assert p.base_delay_ms == 100
        assert p.strategy == "fixed"

    def test_exponential_backoff(self):
        p = RetryPolicy.exponential_backoff(5, 50)
        assert p.max_attempts == 5
        assert p.base_delay_ms == 50
        assert p.strategy == "exponential"


class TestFallbackStrategy:
    def test_dead_letter_on_sync_failure(self):
        fail_spec = (
            Spec("fail").state0({"x": 0}).permit("no", when=LBool(False)).build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        source = universe(_SourceSystem(), _source_spec())
        target = universe(Noop(), fail_spec)
        b = BridgedUniverse(
            source=source,
            target=target,
            mapper=_mapper,
            mode=BridgeMode.SYNCHRONOUS,
            retry=RetryPolicy.no_retry(),
            fallback=FallbackStrategy.DEAD_LETTER,
        )

        r = b.apply({"type": "X"})
        # Source succeeds, target fails → dead letter
        assert isinstance(r, Ok)
        assert len(b.dead_letters) == 1
        assert isinstance(b.dead_letters[0], DeadLetterEntry)

    def test_fail_strategy_raises(self):
        fail_spec = (
            Spec("fail").state0({"x": 0}).permit("no", when=LBool(False)).build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        source = universe(_SourceSystem(), _source_spec())
        target = universe(Noop(), fail_spec)
        b = BridgedUniverse(
            source=source,
            target=target,
            mapper=_mapper,
            mode=BridgeMode.SYNCHRONOUS,
            retry=RetryPolicy.no_retry(),
            fallback=FallbackStrategy.FAIL,
        )

        with pytest.raises(K3BridgeError):
            b.apply({"type": "X"})

    def test_ignore_strategy_swallows(self):
        fail_spec = (
            Spec("fail").state0({"x": 0}).permit("no", when=LBool(False)).build()
        )

        class Noop:
            def transition(self, s, e):
                return s

        source = universe(_SourceSystem(), _source_spec())
        target = universe(Noop(), fail_spec)
        b = BridgedUniverse(
            source=source,
            target=target,
            mapper=_mapper,
            mode=BridgeMode.SYNCHRONOUS,
            retry=RetryPolicy.no_retry(),
            fallback=FallbackStrategy.IGNORE,
        )

        r = b.apply({"type": "X"})
        assert isinstance(r, Ok)
        assert len(b.dead_letters) == 0


class TestBridgeReduce:
    def test_reduce_bridges_each_event(self):
        b = _bridged()
        r = b.reduce([{"type": "A"}, {"type": "B"}, {"type": "C"}])
        assert isinstance(r, Ok)
        assert b.state["target"]["log"] == ["A", "B", "C"]


class TestAlgebraClosed:
    def test_bridge_bridged(self):
        b1 = _bridged()
        third = universe(_TargetSystem(), _target_spec())
        b2 = b1.bridge(third, lambda s, e, ns: {"type": "Chain", "data": "x"})
        assert isinstance(b2, BridgedUniverse)

    def test_compose_bridged(self):
        from k3c.universe.compose import ComposedUniverse

        b = _bridged()
        other = universe(_SourceSystem(), _source_spec())
        c = b.compose(other, lambda e: "left")
        assert isinstance(c, ComposedUniverse)


class TestBridgeMode:
    def test_all_modes(self):
        assert BridgeMode.SYNCHRONOUS == "synchronous"
        assert BridgeMode.ASYNC == "async"
        assert BridgeMode.BEST_EFFORT == "best_effort"
