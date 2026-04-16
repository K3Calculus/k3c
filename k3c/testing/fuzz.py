# k3c/testing/fuzz.py
"""
Property-based fuzzing for K3 Universes.

fuzz() generates random event sequences and runs them through a Universe,
looking for invariant violations. When found, it shrinks to the minimal case.

Discharges well-formedness rule 8: N(S0) AND G(s,e) => N(T(s,e))
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable

from k3c.engine.result import Impossible, Violated

type EventGenerator = Callable[[dict[str, object], random.Random], dict[str, object]]


@dataclass(frozen=True)
class FuzzViolation:
    """A violation found during fuzzing."""

    original_sequence: tuple[dict[str, object], ...]
    shrunk_sequence: tuple[dict[str, object], ...]
    violated: Violated
    step_index: int


@dataclass(frozen=True)
class FuzzReport:
    """Result of a fuzz run."""

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


def _default_event_generator(
    event_types: list[str],
    field_ranges: dict[str, tuple[int, int]] | None = None,
) -> EventGenerator:
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
    from k3c.spec.compile import CompiledSpec

    if not isinstance(compiled, CompiledSpec):
        return []
    types: list[str] = []
    for permit in compiled.permits:
        if permit.on is not None and permit.on not in types:
            types.append(permit.on)
    if not types:
        types.append("Event")
    return types


def _shrink(
    events: list[dict[str, object]],
    apply_fn: Callable[[dict[str, object]], object],
    reset_fn: Callable[[], None],
) -> list[dict[str, object]]:
    current = list(events)

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

    i = 0
    while i < len(current):
        candidate = current[:i] + current[i + 1 :]
        if _reproduces_violation(candidate, apply_fn, reset_fn):
            current = candidate
        else:
            i += 1

    return current


def _reproduces_violation(events, apply_fn, reset_fn) -> bool:
    reset_fn()
    for event in events:
        result = apply_fn(event)
        if isinstance(result, Violated):
            return True
    return False


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
    """Run property-based fuzzing on a Universe."""
    from k3c.runtime.universe import Universe

    if not isinstance(universe, Universe):
        msg = f"fuzz() requires a Universe, got {type(universe).__name__}"
        raise TypeError(msg)

    actual_seed = seed or int(time.time() * 1000) % (2**31)
    rng = random.Random(actual_seed)

    if event_generator is None:
        event_types = _extract_event_types(universe.compiled)
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


def _run_sequence(universe, generator, rng, steps, do_shrink):
    universe.reset()
    sequence: list[dict[str, object]] = []
    impossible_count = 0

    for step_idx in range(steps):
        event = generator(universe.state, rng)
        sequence.append(event)
        result = universe.apply(event)

        if isinstance(result, Violated):
            shrunk = sequence
            if do_shrink:
                shrunk = _shrink(sequence, universe.apply, universe.reset)
                universe.reset()
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
