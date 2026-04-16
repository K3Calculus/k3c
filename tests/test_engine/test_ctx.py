"""Tests for k3c.engine.ctx -- SpecCtx witness."""

from __future__ import annotations

import pytest

from k3c.engine.ctx import TRACE_RING_SIZE, SpecCtx, TimerTickResult


class TestInitial:
    def test_factory(self):
        ctx = SpecCtx.initial({"x": 1})
        assert ctx.spec_state == {"x": 1}
        assert ctx.protocol_pos == "__start__"
        assert ctx.prev_state is None
        assert ctx.prev_event is None
        assert ctx.ob_timers == {}
        assert ctx.active_obligations == frozenset()
        assert ctx.prev_step_hash == ""
        assert ctx.trace_ring == ()

    def test_deepcopy_state(self):
        state = {"x": [1, 2]}
        ctx = SpecCtx.initial(state)
        state["x"].append(3)
        assert ctx.spec_state == {"x": [1, 2]}


class TestFrozen:
    def test_immutable(self):
        ctx = SpecCtx.initial({"x": 0})
        with pytest.raises(AttributeError):
            ctx.spec_state = {}  # type: ignore[misc]


class TestAdvance:
    def test_advances_state(self):
        ctx = SpecCtx.initial({"x": 0})
        ctx2 = ctx.advance(
            new_spec_state={"x": 1},
            event={"type": "inc"},
            new_timers={},
            new_pos="__start__",
            step_hash="abc123",
        )
        assert ctx2.spec_state == {"x": 1}
        assert ctx2.prev_state == {"x": 0}
        assert ctx2.prev_event == {"type": "inc"}
        assert ctx2.prev_step_hash == "abc123"

    def test_trace_ring_bounded(self):
        ctx = SpecCtx.initial({"x": 0})
        for i in range(TRACE_RING_SIZE + 5):
            ctx = ctx.advance(
                new_spec_state={"x": i},
                event={"i": i},
                new_timers={},
                new_pos="__start__",
                step_hash=f"hash_{i}",
            )
        assert len(ctx.trace_ring) == TRACE_RING_SIZE


class TestObligations:
    def test_add_obligation(self):
        ctx = SpecCtx.initial({"x": 0})
        ctx2 = ctx.add_activate_obligation("ob1", 0)
        assert "ob1" in ctx2.active_obligations
        assert ("ob1", 0) in ctx2.obligation_steps

    def test_discharge_obligation(self):
        ctx = SpecCtx.initial({"x": 0})
        ctx2 = ctx.add_activate_obligation("ob1", 0)
        ctx3 = ctx2.discharge_obligation("ob1")
        assert "ob1" not in ctx3.active_obligations
        assert len(ctx3.obligation_steps) == 0


class TestTimers:
    def test_tick_decrements(self):
        ctx = SpecCtx.initial({"x": 0})
        ctx = ctx._with(ob_timers={"t1": 3, "t2": 1})
        result = ctx.tick_timers()
        assert isinstance(result, TimerTickResult)
        assert result.ctx.ob_timers == {"t1": 2}
        assert result.expired == ["t2"]

    def test_tick_no_timers(self):
        ctx = SpecCtx.initial({"x": 0})
        result = ctx.tick_timers()
        assert result.expired == []
        assert result.ctx.ob_timers == {}
