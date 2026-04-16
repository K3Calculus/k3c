# k3c/runtime/samsara.py
"""
Samsara (<?>) -- the replay and simulation meta-operator (KC-3).

Sanskrit: Samsara (संसार) -- cycle, world.

The Samsara operator provides simulation with full state trajectory
collection and deterministic replay verification.

    (<?>) : K3d × E* → RunResult

    RunResult = {
        final_state: S,
        trajectory: S*,
        traces: Trace*
    }

Trajectory collection is opt-in. The core simulate() operation collects
the full causal history; reduce/stream do not.

Usage:
    result = u.simulate(events)
    for rec in result.traces:
        print(rec.t, rec.state_before, rec.event, rec.state_after)

    # Replay verification -- deterministic replay
    ok = u.replay(events, expected_hashes=result.step_hashes)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from k3c.engine.result import Impossible, Ok, StepResult, Violated

if TYPE_CHECKING:
    pass


# -- TraceRecord ---------------------------------------------------------------


@dataclass(frozen=True)
class TraceRecord:
    """Per-step trace record.

    Matches the K3d calculus definition:
        TraceRecord = {
            t: N,
            event: E,
            state_before: S,
            state_after: S,
            guard_result: (Bool, String),
            invariant_result: (Bool, String),
            outputs: O*,
            metadata: Map<String, Any>
        }
    """

    t: int  # logical time (0-indexed step number)
    event: dict[str, object]
    state_before: dict[str, object]
    state_after: dict[str, object] | None  # None if guard rejected
    step_hash: str
    result_kind: str  # "ok" | "impossible" | "violated"
    guard_result: tuple[bool, str]  # (passed, message)
    invariant_result: tuple[bool, str]  # (passed, message)
    projections: dict[str, object]
    outputs: tuple[dict[str, object], ...]
    metadata: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "t": self.t,
            "event": self.event,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "step_hash": self.step_hash,
            "result_kind": self.result_kind,
            "guard_result": list(self.guard_result),
            "invariant_result": list(self.invariant_result),
            "projections": self.projections,
            "outputs": list(self.outputs),
            "metadata": self.metadata,
        }


# -- RunResult -----------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    """Result of simulate() -- the full Samsara output.

    RunResult = {
        final_state: S,
        trajectory: S*,
        traces: Trace*
    }
    """

    final_state: dict[str, object]
    final_result: StepResult[dict[str, object]]
    trajectory: tuple[dict[str, object], ...]  # state at each step (S*)
    traces: tuple[TraceRecord, ...]  # per-step trace records
    processed: int
    skipped: int  # Impossible events

    @property
    def passed(self) -> bool:
        return isinstance(self.final_result, Ok)

    @property
    def step_hashes(self) -> tuple[str, ...]:
        """Extract step hashes for replay verification."""
        return tuple(rec.step_hash for rec in self.traces)

    @property
    def events(self) -> tuple[dict[str, object], ...]:
        """Extract the event sequence from traces."""
        return tuple(rec.event for rec in self.traces)

    def trace_at(self, t: int) -> TraceRecord:
        """Get the trace record at logical time t."""
        if t < 0 or t >= len(self.traces):
            msg = f"Logical time {t} out of range [0, {len(self.traces)})"
            raise IndexError(msg)
        return self.traces[t]

    def state_at(self, t: int) -> dict[str, object]:
        """Get the state at logical time t (after step t executed)."""
        if t < 0 or t >= len(self.trajectory):
            msg = f"Logical time {t} out of range [0, {len(self.trajectory)})"
            raise IndexError(msg)
        return self.trajectory[t]

    def to_dict(self) -> dict[str, object]:
        return {
            "final_state": self.final_state,
            "trajectory": list(self.trajectory),
            "traces": [rec.to_dict() for rec in self.traces],
            "processed": self.processed,
            "skipped": self.skipped,
            "passed": self.passed,
        }


# -- ReplayResult --------------------------------------------------------------


@dataclass(frozen=True)
class ReplayResult:
    """Result of replay verification."""

    matched: bool  # all step hashes matched
    steps: int
    mismatches: tuple[ReplayMismatch, ...]

    @property
    def passed(self) -> bool:
        return self.matched


@dataclass(frozen=True)
class ReplayMismatch:
    """A single step where replay diverged from expected."""

    t: int
    expected_hash: str
    actual_hash: str
    event: dict[str, object]


# -- simulate() ----------------------------------------------------------------


def _trace_from_result(
    t: int,
    event: dict[str, object],
    state_before: dict[str, object],
    result: StepResult[dict[str, object]],
) -> TraceRecord:
    """Build a TraceRecord from a StepResult."""
    if isinstance(result, Ok):
        return TraceRecord(
            t=t,
            event=event,
            state_before=state_before,
            state_after=dict(result.state),
            step_hash=result.step_hash,
            result_kind="ok",
            guard_result=(True, ""),
            invariant_result=(True, ""),
            projections=result.projections,
            outputs=result.outputs,
            metadata={},
        )
    elif isinstance(result, Impossible):
        return TraceRecord(
            t=t,
            event=event,
            state_before=state_before,
            state_after=None,
            step_hash=result.why.step_hash,
            result_kind="impossible",
            guard_result=(False, result.why.message),
            invariant_result=(True, ""),
            projections={},
            outputs=(),
            metadata={},
        )
    else:  # Violated
        return TraceRecord(
            t=t,
            event=event,
            state_before=state_before,
            state_after=result.why.after,
            step_hash=result.why.step_hash,
            result_kind="violated",
            guard_result=(True, ""),
            invariant_result=(False, result.why.message),
            projections={},
            outputs=(),
            metadata={},
        )


def simulate(
    universe: object,
    events: Iterable[object],
) -> RunResult:
    """Run the Samsara operator: simulate with full trajectory collection.

    This is the core KC-3 operation. It processes all events (skipping
    Impossible, stopping on Violated) while collecting the complete state
    trajectory and per-step trace records.

    Args:
        universe: A Universe instance (uses apply, state, reset).
        events: The event sequence E*.

    Returns:
        RunResult with final_state, trajectory, and traces.
    """
    # Import here to avoid circular imports
    from k3c.runtime.universe import Universe

    u: Universe = universe  # type: ignore[assignment]

    trajectory: list[dict[str, object]] = []
    traces: list[TraceRecord] = []
    processed = 0
    skipped = 0
    last_result: StepResult[dict[str, object]] = Ok(
        state=u.state, ctx=u.ctx, step_hash=""
    )

    for t, event in enumerate(events):
        state_before = deepcopy(u.state)
        event_dict = event if isinstance(event, dict) else {"__raw__": event}

        result = u.apply(event)

        trace = _trace_from_result(t, event_dict, state_before, result)
        traces.append(trace)

        if isinstance(result, Ok):
            trajectory.append(deepcopy(result.state))
            processed += 1
            last_result = result
        elif isinstance(result, Impossible):
            skipped += 1
        else:  # Violated
            last_result = result
            break

    return RunResult(
        final_state=deepcopy(u.state),
        final_result=last_result,
        trajectory=tuple(trajectory),
        traces=tuple(traces),
        processed=processed,
        skipped=skipped,
    )


# -- replay() ------------------------------------------------------------------


def replay(
    universe: object,
    events: Sequence[object],
    *,
    expected_hashes: Sequence[str],
) -> ReplayResult:
    """Deterministic replay verification.

    Replays the event sequence and verifies that every step produces
    the same step_hash as the original run. In K3d, replay is
    deterministic -- same inputs always produce same outputs.

    Args:
        universe: A Universe instance.
        events: The event sequence to replay.
        expected_hashes: Step hashes from the original run.

    Returns:
        ReplayResult indicating whether all hashes matched.
    """
    from k3c.runtime.universe import Universe

    u: Universe = universe  # type: ignore[assignment]

    mismatches: list[ReplayMismatch] = []
    steps = 0

    for t, event in enumerate(events):
        event_dict = event if isinstance(event, dict) else {"__raw__": event}
        result = u.apply(event)

        if t < len(expected_hashes):
            if isinstance(result, Ok):
                actual_hash = result.step_hash
            elif isinstance(result, Impossible):
                actual_hash = result.why.step_hash
            else:
                actual_hash = result.why.step_hash

            if actual_hash != expected_hashes[t]:
                mismatches.append(
                    ReplayMismatch(
                        t=t,
                        expected_hash=expected_hashes[t],
                        actual_hash=actual_hash,
                        event=event_dict,
                    )
                )

        steps += 1

        if isinstance(result, Violated):
            break

    return ReplayResult(
        matched=len(mismatches) == 0,
        steps=steps,
        mismatches=tuple(mismatches),
    )
