"""Tests for k3c.spec.ctx — SpecCtx, TimerTickResult."""

from __future__ import annotations

import pytest

from k3c.spec.ctx import TRACE_RING_SIZE, SpecCtx, TimerTickResult


# ── Helpers ──────────────────────────────────────────────────────────────────


def _initial() -> SpecCtx:
    return SpecCtx.initial({"balance": 100})


def _make_event(n: int) -> dict[str, object]:
    return {"type": "event", "n": n}


# ═══════════════════════════════════════════════════════════════════════════════
#  SpecCtx.initial
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpecCtxInitial:
    def test_creates_with_correct_defaults(self):
        ctx = _initial()
        assert ctx.spec_state == {"balance": 100}
        assert ctx.protocol_pos == "__start__"
        assert ctx.prev_state is None
        assert ctx.prev_event is None
        assert ctx.ob_timers == {}
        assert ctx.active_obligations == frozenset()
        assert ctx.obligation_steps == ()
        assert ctx.bridge_ctx == {}
        assert ctx.prev_step_hash == ""
        assert ctx.trace_ring == ()

    def test_deep_copies_initial_state(self):
        original = {"mutable": [1, 2, 3]}
        ctx = SpecCtx.initial(original)
        original["mutable"].append(4)
        assert ctx.spec_state["mutable"] == [1, 2, 3]

    def test_frozen(self):
        ctx = _initial()
        with pytest.raises(AttributeError):
            ctx.protocol_pos = "modified"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════════
#  SpecCtx._with
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpecCtxWith:
    def test_override_single_field(self):
        ctx = _initial()
        new_ctx = ctx._with(protocol_pos="step_1")
        assert new_ctx.protocol_pos == "step_1"
        assert new_ctx.spec_state == ctx.spec_state

    def test_override_multiple_fields(self):
        ctx = _initial()
        new_ctx = ctx._with(protocol_pos="step_2", prev_step_hash="abc")
        assert new_ctx.protocol_pos == "step_2"
        assert new_ctx.prev_step_hash == "abc"

    def test_no_overrides_returns_equal_copy(self):
        ctx = _initial()
        new_ctx = ctx._with()
        assert new_ctx == ctx
        assert new_ctx is not ctx

    def test_original_unchanged(self):
        ctx = _initial()
        ctx._with(protocol_pos="changed")
        assert ctx.protocol_pos == "__start__"


# ═══════════════════════════════════════════════════════════════════════════════
#  SpecCtx.advance
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpecCtxAdvance:
    def test_basic_advance(self):
        ctx = _initial()
        event = {"type": "deposit", "amount": 50}
        new_ctx = ctx.advance(
            new_spec_state={"balance": 150},
            event=event,
            new_timers={},
            new_pos="deposited",
            step_hash="hash1",
        )
        assert new_ctx.spec_state == {"balance": 150}
        assert new_ctx.protocol_pos == "deposited"
        assert new_ctx.prev_state == {"balance": 100}
        assert new_ctx.prev_event == event
        assert new_ctx.prev_step_hash == "hash1"
        assert new_ctx.bridge_ctx == ctx.bridge_ctx

    def test_advance_preserves_obligations_when_none_passed(self):
        ctx = _initial()._with(
            active_obligations=frozenset({"ob1"}),
            obligation_steps=(("ob1", 0),),
        )
        new_ctx = ctx.advance(
            new_spec_state=ctx.spec_state,
            event={"type": "tick"},
            new_timers={},
            new_pos=ctx.protocol_pos,
            step_hash="h",
        )
        assert new_ctx.active_obligations == frozenset({"ob1"})
        assert new_ctx.obligation_steps == (("ob1", 0),)

    def test_advance_replaces_obligations_when_passed(self):
        ctx = _initial()._with(active_obligations=frozenset({"old"}))
        new_ctx = ctx.advance(
            new_spec_state=ctx.spec_state,
            event={"type": "tick"},
            new_timers={},
            new_pos=ctx.protocol_pos,
            step_hash="h",
            new_obligations=frozenset({"new1", "new2"}),
            new_obligation_steps=(("new1", 0), ("new2", 0)),
        )
        assert new_ctx.active_obligations == frozenset({"new1", "new2"})

    def test_advance_with_empty_frozenset_does_not_fallback(self):
        """Regression: empty frozenset must not be swallowed by falsy check."""
        ctx = _initial()._with(active_obligations=frozenset({"should_be_gone"}))
        new_ctx = ctx.advance(
            new_spec_state=ctx.spec_state,
            event={"type": "clear"},
            new_timers={},
            new_pos=ctx.protocol_pos,
            step_hash="h",
            new_obligations=frozenset(),
            new_obligation_steps=(),
        )
        assert new_ctx.active_obligations == frozenset()
        assert new_ctx.obligation_steps == ()

    def test_advance_appends_to_trace_ring(self):
        ctx = _initial()
        event = {"type": "e1"}
        new_ctx = ctx.advance(
            new_spec_state=ctx.spec_state,
            event=event,
            new_timers={},
            new_pos=ctx.protocol_pos,
            step_hash="h",
        )
        assert new_ctx.trace_ring == (event,)

    def test_trace_ring_bounded_at_ring_size(self):
        ctx = _initial()
        for i in range(TRACE_RING_SIZE + 5):
            ctx = ctx.advance(
                new_spec_state=ctx.spec_state,
                event=_make_event(i),
                new_timers={},
                new_pos=ctx.protocol_pos,
                step_hash=f"h{i}",
            )
        assert len(ctx.trace_ring) == TRACE_RING_SIZE
        assert ctx.trace_ring[0] == _make_event(5)
        assert ctx.trace_ring[-1] == _make_event(TRACE_RING_SIZE + 4)

    def test_advance_returns_new_instance(self):
        ctx = _initial()
        new_ctx = ctx.advance(
            new_spec_state=ctx.spec_state,
            event={"type": "e"},
            new_timers={},
            new_pos=ctx.protocol_pos,
            step_hash="h",
        )
        assert new_ctx is not ctx


# ═══════════════════════════════════════════════════════════════════════════════
#  SpecCtx.snapshot_trace
# ═══════════════════════════════════════════════════════════════════════════════


class TestSnapshotTrace:
    def test_empty_trace(self):
        assert _initial().snapshot_trace() == ()

    def test_returns_trace_ring(self):
        ctx = _initial()
        ctx = ctx.advance(
            new_spec_state=ctx.spec_state,
            event={"type": "e"},
            new_timers={},
            new_pos=ctx.protocol_pos,
            step_hash="h",
        )
        assert ctx.snapshot_trace() == ({"type": "e"},)


# ═══════════════════════════════════════════════════════════════════════════════
#  SpecCtx.add_activate_obligation
# ═══════════════════════════════════════════════════════════════════════════════


class TestAddActivateObligation:
    def test_adds_obligation(self):
        ctx = _initial()
        new_ctx = ctx.add_activate_obligation("must_ship", 0)
        assert "must_ship" in new_ctx.active_obligations
        assert ("must_ship", 0) in new_ctx.obligation_steps

    def test_preserves_existing_obligations(self):
        ctx = _initial().add_activate_obligation("ob1", 0)
        new_ctx = ctx.add_activate_obligation("ob2", 1)
        assert new_ctx.active_obligations == frozenset({"ob1", "ob2"})
        assert new_ctx.obligation_steps == (("ob1", 0), ("ob2", 1))

    def test_original_unchanged(self):
        ctx = _initial()
        ctx.add_activate_obligation("ob", 0)
        assert ctx.active_obligations == frozenset()

    def test_other_fields_unchanged(self):
        ctx = _initial()
        new_ctx = ctx.add_activate_obligation("ob", 0)
        assert new_ctx.spec_state == ctx.spec_state
        assert new_ctx.protocol_pos == ctx.protocol_pos
        assert new_ctx.prev_step_hash == ctx.prev_step_hash
        assert new_ctx.trace_ring == ctx.trace_ring


# ═══════════════════════════════════════════════════════════════════════════════
#  SpecCtx.discharge_obligation
# ═══════════════════════════════════════════════════════════════════════════════


class TestDischargeObligation:
    def test_removes_obligation(self):
        ctx = _initial().add_activate_obligation("ob1", 0)
        new_ctx = ctx.discharge_obligation("ob1")
        assert "ob1" not in new_ctx.active_obligations
        assert new_ctx.obligation_steps == ()

    def test_preserves_other_obligations(self):
        ctx = (
            _initial()
            .add_activate_obligation("ob1", 0)
            .add_activate_obligation("ob2", 1)
        )
        new_ctx = ctx.discharge_obligation("ob1")
        assert new_ctx.active_obligations == frozenset({"ob2"})
        assert new_ctx.obligation_steps == (("ob2", 1),)

    def test_original_unchanged(self):
        ctx = _initial().add_activate_obligation("ob1", 0)
        ctx.discharge_obligation("ob1")
        assert "ob1" in ctx.active_obligations

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_discharge_nonexistent_is_noop(self):
        ctx = _initial()
        new_ctx = ctx.discharge_obligation("nonexistent")
        assert new_ctx.active_obligations == frozenset()
        assert new_ctx.obligation_steps == ()


# ═══════════════════════════════════════════════════════════════════════════════
#  SpecCtx.tick_timers
# ═══════════════════════════════════════════════════════════════════════════════


class TestTickTimers:
    def test_decrements_timers(self):
        ctx = _initial()._with(ob_timers={"t1": 5, "t2": 3})
        result = ctx.tick_timers()
        assert isinstance(result, TimerTickResult)
        assert result.ctx.ob_timers == {"t1": 4, "t2": 2}
        assert result.expired == []

    def test_expires_timer_at_one(self):
        ctx = _initial()._with(ob_timers={"t1": 1, "t2": 3})
        result = ctx.tick_timers()
        assert "t1" not in result.ctx.ob_timers
        assert "t1" in result.expired
        assert result.ctx.ob_timers == {"t2": 2}

    def test_expires_multiple_timers(self):
        ctx = _initial()._with(ob_timers={"t1": 1, "t2": 1, "t3": 5})
        result = ctx.tick_timers()
        assert set(result.expired) == {"t1", "t2"}
        assert result.ctx.ob_timers == {"t3": 4}

    def test_all_timers_expire(self):
        ctx = _initial()._with(ob_timers={"t1": 1, "t2": 1})
        result = ctx.tick_timers()
        assert result.ctx.ob_timers == {}
        assert set(result.expired) == {"t1", "t2"}

    def test_empty_timers(self):
        ctx = _initial()
        result = ctx.tick_timers()
        assert result.ctx.ob_timers == {}
        assert result.expired == []

    def test_returns_named_tuple(self):
        ctx = _initial()._with(ob_timers={"t1": 2})
        result = ctx.tick_timers()
        assert result.ctx.ob_timers == {"t1": 1}
        assert result.expired == []
        # Accessible by index too
        assert result[0].ob_timers == {"t1": 1}
        assert result[1] == []

    def test_original_unchanged(self):
        ctx = _initial()._with(ob_timers={"t1": 1})
        ctx.tick_timers()
        assert ctx.ob_timers == {"t1": 1}


# ═══════════════════════════════════════════════════════════════════════════════
#  Equality and hashing
# ═══════════════════════════════════════════════════════════════════════════════


class TestEquality:
    def test_equal_instances(self):
        a = _initial()
        b = _initial()
        assert a == b

    def test_unequal_after_advance(self):
        a = _initial()
        b = a.advance(
            new_spec_state=a.spec_state,
            event={"type": "e"},
            new_timers={},
            new_pos="next",
            step_hash="h",
        )
        assert a != b

    def test_not_hashable_due_to_dict_fields(self):
        ctx = _initial()
        with pytest.raises(TypeError, match="unhashable"):
            hash(ctx)
