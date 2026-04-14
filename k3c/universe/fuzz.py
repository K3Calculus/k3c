# k3c/universe/fuzz.py
"""
Property-based fuzzing for K3 Universes.

fuzz() generates random event sequences and runs them through a Universe,
looking for invariant violations. When a violation is found, it shrinks
the event sequence to the minimal reproducing case.

This is the primary mechanism for discharging well-formedness rule 8:
  N(S₀) ∧ G(s,e) ⇒ N(T(s,e))

Usage:
    report = u.fuzz(sequences=1000, steps=100, seed=42)
    if not report.passed:
        print(report.violations[0].shrunk_sequence)
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable

from k3c.spec.result import Impossible, Violated


# ── Event generator protocol ────────────────────────────────────────────────


type EventGenerator = Callable[[dict[str, object], random.Random], dict[str, object]]


# ── FuzzViolation ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FuzzViolation:
    """A violation found during fuzzing.

    original_sequence: the full event sequence that triggered the violation
    shrunk_sequence: the minimal reproducing subsequence (after shrinking)
    violated: the Violated result with full Why context
    step_index: which step in the sequence produced the violation
    """

    original_sequence: tuple[dict[str, object], ...]
    shrunk_sequence: tuple[dict[str, object], ...]
    violated: Violated
    step_index: int


# ── FuzzReport ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FuzzReport:
    """Result of a fuzz run.

    passed: True if no violations found
    violations: list of FuzzViolation (typically stops at first)
    sequences_run: how many event sequences were tested
    total_steps: total number of apply() calls across all sequences
    impossible_count: how many events were rejected by guards (not bugs)
    elapsed_ms: wall-clock time in milliseconds
    seed: the RNG seed used (for reproducibility)
    """

    passed: bool
    violations: tuple[FuzzViolation, ...]
    sequences_run: int
    total_steps: int
    impossible_count: int
    elapsed_ms: float
    seed: int

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "violations": len(self.violations),
            "sequences_run": self.sequences_run,
            "total_steps": self.total_steps,
            "impossible_count": self.impossible_count,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "seed": self.seed,
        }


# ── Default event generator ─────────────────────────────────────────────────


def _default_event_generator(
    event_types: list[str],
    field_ranges: dict[str, tuple[int, int]] | None = None,
) -> EventGenerator:
    """Create a default event generator from permit clause event types.

    Generates events with random type and random integer fields.
    """
    ranges = field_ranges or {"amount": (0, 1000), "n": (0, 100)}

    def generate(state: dict[str, object], rng: random.Random) -> dict[str, object]:
        event: dict[str, object] = {}
        if event_types:
            event["type"] = rng.choice(event_types)
        for name, (lo, hi) in ranges.items():
            event[name] = rng.randint(lo, hi)
        return event

    return generate


def _extract_event_types(compiled: object) -> list[str]:
    """Extract event types from permit clauses' `on` filters."""
    from k3c.lang.compile import CompiledSpec

    if not isinstance(compiled, CompiledSpec):
        return []
    types: list[str] = []
    for permit in compiled.permits:
        if permit.on is not None and permit.on not in types:
            types.append(permit.on)
    # If no typed permits, add a generic event
    if not types:
        types.append("Event")
    return types


# ── Shrinking ────────────────────────────────────────────────────────────────


def _shrink(
    events: list[dict[str, object]],
    apply_fn: Callable[[dict[str, object]], object],
    reset_fn: Callable[[], None],
) -> list[dict[str, object]]:
    """Shrink an event sequence to the minimal reproducing case.

    Binary search removal: try removing halves, then quarters, etc.
    Then try removing individual events.
    """
    current = list(events)

    # Phase 1: try removing contiguous blocks (large to small)
    block_size = len(current) // 2
    while block_size >= 1:
        i = 0
        while i + block_size <= len(current):
            candidate = current[:i] + current[i + block_size :]
            if _reproduces_violation(candidate, apply_fn, reset_fn):
                current = candidate
            else:
                i += 1
        block_size //= 2

    # Phase 2: try removing individual events
    i = 0
    while i < len(current):
        candidate = current[:i] + current[i + 1 :]
        if _reproduces_violation(candidate, apply_fn, reset_fn):
            current = candidate
        else:
            i += 1

    return current


def _reproduces_violation(
    events: list[dict[str, object]],
    apply_fn: Callable[[dict[str, object]], object],
    reset_fn: Callable[[], None],
) -> bool:
    """Check if an event sequence still produces a Violated result."""
    reset_fn()
    for event in events:
        result = apply_fn(event)
        if isinstance(result, Violated):
            return True
    return False


# ── Core fuzz loop ──────────────────────────────────────────────────────────


def fuzz(
    universe: object,
    *,
    sequences: int = 1000,
    steps: int = 100,
    seed: int = 0,
    event_generator: EventGenerator | None = None,
    max_violations: int = 1,
    shrink: bool = True,
) -> FuzzReport:
    """Run property-based fuzzing on a Universe.

    universe: the Universe to fuzz
    sequences: number of independent event sequences to generate
    steps: max events per sequence
    seed: RNG seed for reproducibility (0 = time-based)
    event_generator: custom event generator, or None for auto-detection
    max_violations: stop after this many violations (default: 1)
    shrink: whether to shrink failing sequences (default: True)

    Returns FuzzReport with violations, statistics, and timing.
    """
    from k3c.universe.universe import Universe

    if not isinstance(universe, Universe):
        msg = f"fuzz() requires a Universe, got {type(universe).__name__}"
        raise TypeError(msg)

    actual_seed = seed or int(time.time() * 1000) % (2**31)
    rng = random.Random(actual_seed)

    if event_generator is None:
        event_types = _extract_event_types(universe.spec)
        event_generator = _default_event_generator(event_types)

    start = time.monotonic()
    violations: list[FuzzViolation] = []
    total_steps = 0
    impossible_count = 0
    sequences_run = 0

    for _ in range(sequences):
        if len(violations) >= max_violations:
            break
        sequences_run += 1
        result = _run_sequence(universe, event_generator, rng, steps, shrink)
        total_steps += result[0]
        impossible_count += result[1]
        if result[2] is not None:
            violations.append(result[2])

    elapsed = (time.monotonic() - start) * 1000
    universe.reset()

    return FuzzReport(
        passed=len(violations) == 0,
        violations=tuple(violations),
        sequences_run=sequences_run,
        total_steps=total_steps,
        impossible_count=impossible_count,
        elapsed_ms=elapsed,
        seed=actual_seed,
    )


def _run_sequence(
    universe: object,
    generator: EventGenerator,
    rng: random.Random,
    steps: int,
    do_shrink: bool,
) -> tuple[int, int, FuzzViolation | None]:
    """Run one fuzz sequence. Returns (steps_run, impossible_count, violation_or_none)."""
    universe.reset()  # type: ignore[union-attr]
    sequence: list[dict[str, object]] = []
    impossible_count = 0

    for step_idx in range(steps):
        event = generator(universe.state, rng)  # type: ignore[union-attr]
        sequence.append(event)
        result = universe.apply(event)  # type: ignore[union-attr]

        if isinstance(result, Violated):
            shrunk = sequence
            if do_shrink:
                shrunk = _shrink(sequence, universe.apply, universe.reset)  # type: ignore[union-attr]
                universe.reset()  # type: ignore[union-attr]
            return (
                len(sequence),
                impossible_count,
                FuzzViolation(
                    original_sequence=tuple(sequence),
                    shrunk_sequence=tuple(shrunk),
                    violated=result,
                    step_index=step_idx,
                ),
            )

        if isinstance(result, Impossible):
            impossible_count += 1

    return len(sequence), impossible_count, None
