# k3c/specs/ctx.py
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from typing import Any

TRACE_RING_SIZE = 16  # bounded — never grows beyond this


class TimerTickResult(NamedTuple):
    ctx: SpecCtx
    expired: list[str]


@dataclass(frozen=True)
class SpecCtx:
    """
    The ambient witness of a Universe — the Purusha.

    Flows through every causal step alongside state `S`.
    `G`, `T`, and `N` never read or write any field of SpecCtx.
    The implementation has zero awareness it exists.
    It observes. It does not cause.

    Always frozen. The engine always constructs a new SpecCtx
    via advance() — never mutates in place. apply() stays pure.
    """

    # ── Spec state (I + U) ───────────────────────────────────────────────────
    spec_state: dict[str, object]
    # U.require: the intended domain state.
    # Advanced atomically alongside S in T.
    # K.correlate compares K.lift(S) against this.

    protocol_pos: str
    # U.permit: current DFA arc position.
    # Enforces event ordering — Confirm cannot
    # precede Place, Ship cannot precede Pay.

    # ── Cross-step memory (U.maintain Before/After) ──────────────────────────
    prev_state: dict[str, object] | None
    # Snapshot of spec_state from previous step.
    # Required for Before(field)/After(field) k3l nodes.

    prev_event: dict[str, object] | None
    # Domain event from previous step.
    # Required for cross-event maintain clauses.

    # ── Liveness and timers (U.maintain Within/Eventually) ───────────────────
    ob_timers: dict[str, int]
    # name → ticks_remaining for Within(φ, n).
    # Decremented on every step. Hits zero → Violated.

    active_obligations: frozenset[str]
    # Active Eventually(φ) obligations.
    # Trigger fires → added. Guarantee fires → removed.
    # Still present at termination → Violated.

    obligation_steps: tuple[tuple[str, int], ...]
    # (obligation_name, steps_elapsed_since_activation).
    # Carries audit trail for liveness violations.

    # ── Bridge context (U.require across boundaries) ─────────────────────────
    bridge_ctx: dict[str, object]
    # Causally relevant context propagated across
    # Bridge boundaries by U.require.

    # ── Audit and hash chain ─────────────────────────────────────────────────
    prev_step_hash: str
    # Hash from the previous apply() call.
    # _hash_step() incorporates this:
    #   step_hash = SHA-256(state, event, prev_step_hash)
    # Empty string "" = chain root (initial state).

    trace_ring: tuple[dict[str, object], ...]
    # Bounded ring buffer — last N domain events.
    # Capped at TRACE_RING_SIZE = 16. Never grows.
    # snapshot_trace() gives Why.trace at outcome time.

    # ── Internal ─────────────────────────────────────────────────────────────
    def _with(self, **overrides: Any) -> SpecCtx:
        return SpecCtx(**{**self.__dict__, **overrides})

    # ── Factory ──────────────────────────────────────────────────────────────
    @staticmethod
    def initial(state0: dict[str, object]) -> SpecCtx:
        """
        Construct Ctx₀ — the chain root.

        prev_step_hash = "" is the genesis of the hash chain.
        Every step_hash in this Universe's history ultimately
        incorporates this root.
        """
        return SpecCtx(
            spec_state=deepcopy(state0),
            protocol_pos="__start__",
            prev_state=None,
            prev_event=None,
            ob_timers={},
            bridge_ctx={},
            active_obligations=frozenset(),
            obligation_steps=(),
            prev_step_hash="",  # genesis — the chain root
            trace_ring=(),
        )

    # ── Step forward ─────────────────────────────────────────────────────────
    def advance(
        self,
        new_spec_state: dict[str, object],
        event: dict[str, object],
        new_timers: dict[str, int],
        new_pos: str,
        step_hash: str,
        new_obligations: frozenset[str] | None = None,
        new_obligation_steps: tuple[tuple[str, int], ...] | None = None,
    ) -> SpecCtx:
        """
        Produce the next SpecCtx from this one.
        Always returns a new frozen instance — never mutates self.

        Called by _apply_require() after U.require advances spec_state,
        and by step_liveness() after liveness obligations are updated.
        Both return a new SpecCtx; apply() chains them.
        """
        # Ring buffer: append current event, keep last TRACE_RING_SIZE
        new_ring = (self.trace_ring + (event,))[-TRACE_RING_SIZE:]

        return SpecCtx(
            spec_state=new_spec_state,
            protocol_pos=new_pos,
            prev_state=self.spec_state,  # snapshot for Before/After
            prev_event=event,
            ob_timers=new_timers,
            bridge_ctx=self.bridge_ctx,
            active_obligations=new_obligations
            if new_obligations is not None
            else self.active_obligations,
            obligation_steps=new_obligation_steps
            if new_obligation_steps is not None
            else self.obligation_steps,
            prev_step_hash=step_hash,  # chained into next step
            trace_ring=new_ring,
        )

    # ── Snapshot ─────────────────────────────────────────────────────────────
    def snapshot_trace(self) -> tuple[dict, ...]:
        """
        Immutable snapshot of the ring buffer.
        Called when constructing Why — gives Why.trace the
        exact event history at the moment of the outcome.
        """
        return self.trace_ring

    # ── Helpers for liveness ─────────────────────────────────────────────────
    def add_activate_obligation(self, name: str, step: int) -> SpecCtx:
        """Add an Eventually(φ) obligation. Pure — returns new SpecCtx."""
        return self._with(
            active_obligations=self.active_obligations | {name},
            obligation_steps=self.obligation_steps + ((name, step),),
        )

    def discharge_obligation(self, name: str) -> SpecCtx:
        """Remove a satisfied Eventually(φ) obligation. Pure."""
        return self._with(
            active_obligations=self.active_obligations - {name},
            obligation_steps=tuple(
                (n, s) for n, s in self.obligation_steps if n != name
            ),
        )

    def tick_timers(self) -> TimerTickResult:
        """
        Decrement all Within(φ, n) timers by one step.
        Returns TimerTickResult(ctx, expired).
        Expired timers are removed — check_invariants() will
        have already returned Violated for them before this runs.
        """
        expired = [n for n, t in self.ob_timers.items() if t <= 1]
        new_timers = {n: t - 1 for n, t in self.ob_timers.items() if t > 1}
        return TimerTickResult(self._with(ob_timers=new_timers), expired)
