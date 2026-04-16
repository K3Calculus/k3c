# k3c/engine/ctx.py
"""
SpecCtx -- the ambient witness of a Universe (the Purusha).

Flows through every causal step alongside state S.
G, T, and N never read or write any field of SpecCtx.
The implementation has zero awareness it exists.
It observes. It does not cause.

Always frozen. The engine constructs a new SpecCtx
via advance() -- never mutates in place.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from typing import Any

TRACE_RING_SIZE = 16


class TimerTickResult(NamedTuple):
    ctx: SpecCtx
    expired: list[str]


@dataclass(frozen=True)
class SpecCtx:
    """The ambient witness -- flows through every causal step."""

    # Spec state (I + U)
    spec_state: dict[str, object]
    protocol_pos: str

    # Cross-step memory
    prev_state: dict[str, object] | None
    prev_event: dict[str, object] | None

    # Liveness and timers
    ob_timers: dict[str, int]
    active_obligations: frozenset[str]
    obligation_steps: tuple[tuple[str, int], ...]

    # Bridge context
    bridge_ctx: dict[str, object]

    # Audit and hash chain
    prev_step_hash: str
    trace_ring: tuple[dict[str, object], ...]

    def _with(self, **overrides: Any) -> SpecCtx:
        return SpecCtx(**{**self.__dict__, **overrides})

    @staticmethod
    def initial(state0: dict[str, object]) -> SpecCtx:
        """Construct Ctx0 -- the chain root."""
        return SpecCtx(
            spec_state=deepcopy(state0),
            protocol_pos="__start__",
            prev_state=None,
            prev_event=None,
            ob_timers={},
            bridge_ctx={},
            active_obligations=frozenset(),
            obligation_steps=(),
            prev_step_hash="",
            trace_ring=(),
        )

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
        """Produce the next SpecCtx. Always returns new frozen instance."""
        new_ring = (self.trace_ring + (event,))[-TRACE_RING_SIZE:]
        return SpecCtx(
            spec_state=new_spec_state,
            protocol_pos=new_pos,
            prev_state=self.spec_state,
            prev_event=event,
            ob_timers=new_timers,
            bridge_ctx=self.bridge_ctx,
            active_obligations=new_obligations
            if new_obligations is not None
            else self.active_obligations,
            obligation_steps=new_obligation_steps
            if new_obligation_steps is not None
            else self.obligation_steps,
            prev_step_hash=step_hash,
            trace_ring=new_ring,
        )

    def snapshot_trace(self) -> tuple[dict[str, object], ...]:
        """Immutable snapshot of the ring buffer."""
        return self.trace_ring

    def add_activate_obligation(self, name: str, step: int) -> SpecCtx:
        """Add an Eventually(phi) obligation. Pure."""
        return self._with(
            active_obligations=self.active_obligations | {name},
            obligation_steps=self.obligation_steps + ((name, step),),
        )

    def discharge_obligation(self, name: str) -> SpecCtx:
        """Remove a satisfied Eventually(phi) obligation. Pure."""
        return self._with(
            active_obligations=self.active_obligations - {name},
            obligation_steps=tuple(
                (n, s) for n, s in self.obligation_steps if n != name
            ),
        )

    def tick_timers(self) -> TimerTickResult:
        """Decrement all Within(phi, n) timers by one step."""
        expired = [n for n, t in self.ob_timers.items() if t <= 1]
        new_timers = {n: t - 1 for n, t in self.ob_timers.items() if t > 1}
        return TimerTickResult(self._with(ob_timers=new_timers), expired)
