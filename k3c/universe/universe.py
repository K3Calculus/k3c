# k3c/universe/universe.py
"""
Universe — the public API for K3 causal systems.

A Universe is a self-contained causal world. Events enter. State evolves.
The causal laws hold. That is the complete picture.

Usage:
    u = universe(MySystem(), spec)
    match u.apply({"type": "Withdraw", "amount": 50}):
        case Ok(state=s):        print(s["balance"])
        case Impossible(why):    print(why.message)
        case Violated(why):      why.raise_()
"""

from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Protocol, cast

if TYPE_CHECKING:
    from k3c.universe.bridge import BridgedUniverse
    from k3c.universe.compose import Applyable, ComposedUniverse
    from k3c.universe.explain import ExplainResult
    from k3c.universe.fuzz import EventGenerator, FuzzReport
    from k3c.universe.isolate import IsolatedUniverse

import hashlib

from k3c.cache import K3Cache
from k3c.errors import K3WellFormednessError
from k3c.lang.compile import CompiledSpec, compile_spec
from k3c.lang.eval import k3_eval
from k3c.lang.ir import Nothing, Some
from k3c.spec.builder import K3Spec
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import Impossible, K3Result, Ok, Violated
from k3c.universe.engine import apply as engine_apply
from k3c.universe.retry import BridgeMode, FallbackStrategy, RetryPolicy

# ── System protocol ─────────────────────────────────────────────────────────


class System(Protocol):
    """Protocol for user-supplied system implementations.

    A System provides the transition function T(s, e) → s'.
    The spec provides everything else (G, N, L, K).
    """

    def transition(
        self, state: dict[str, object], event: dict[str, object]
    ) -> dict[str, object]:
        """T_impl: given current state and domain event, produce new state."""
        ...


# ── ReduceAllResult ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReduceAllResult:
    """Result of reduce_all — processes all events, skipping Impossible.

    final: the K3Result from the last processed event
    processed: number of events that produced Ok
    skipped: list of (index, Why) for events that were Impossible
    """

    final: K3Result[dict[str, object]]
    processed: int
    skipped: list[tuple[int, Impossible]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return isinstance(self.final, Ok)


# ── Well-formedness validation ───────────────────────────────────────────────


def _validate_well_formed(compiled: CompiledSpec) -> None:
    """Check well-formedness rules 1-4 at construction time.

    Rules 5-7 are structural (type system guarantees).
    Rule 8 is discharged by fuzz() or verify().
    """
    # Rule 1: S ≠ ∅ — state0 must be non-empty
    if not compiled.state0:
        raise K3WellFormednessError(rule=1, message="state0 must be a non-empty dict")

    # Rule 3: N(S₀) = true — initial state passes all safety invariants
    ctx = SpecCtx.initial(compiled.state0)
    eval_ctx: dict[str, object] = {
        "state": compiled.state0,
        "event": {},
        "__ctx__": ctx,
        "__new_state__": compiled.state0,
    }
    for clause in compiled.safety:
        result = k3_eval(clause.expr, eval_ctx, "")
        if isinstance(result, Some) and result.val is False:
            raise K3WellFormednessError(
                rule=3,
                message=f"Initial state violates safety invariant {clause.name!r}",
            )
        if isinstance(result, Nothing):
            # Temporal references (Before/After) are absent at construction
            # because there's no previous state yet — skip, not fail
            if result.field.startswith(("before.", "after.")):
                continue
            raise K3WellFormednessError(
                rule=3,
                message=f"Safety invariant {clause.name!r}: field {result.field!r} absent in initial state",
            )


# ── Universe ─────────────────────────────────────────────────────────────────


class Universe:
    """A self-contained K3 causal system.

    Holds the compiled spec, current state, ambient context, and transition
    function. All operations go through apply().

    Created via the universe() factory function.
    """

    _id: str
    _compiled: CompiledSpec
    _k3spec: K3Spec
    _state: dict[str, object]
    _ctx: SpecCtx
    _transition: Callable[[dict[str, object], dict[str, object]], dict[str, object]]
    _initial_state: dict[str, object]

    def __init__(
        self,
        *,
        id: str,
        compiled: CompiledSpec,
        k3spec: K3Spec,
        state: dict[str, object],
        ctx: SpecCtx,
        transition: Callable[[dict[str, object], dict[str, object]], dict[str, object]],
    ) -> None:
        self._id = id
        self._compiled = compiled
        self._k3spec = k3spec
        self._state = state
        self._ctx = ctx
        self._transition = transition
        self._initial_state = deepcopy(state)

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self) -> dict[str, object]:
        return self._state.copy()

    @property
    def ctx(self) -> SpecCtx:
        return self._ctx

    @property
    def spec(self) -> CompiledSpec:
        return self._compiled

    def cache_stats(self) -> dict[str, object]:
        """Return cache hit/miss statistics for this Universe."""
        return self._compiled.cache.stats()

    def apply(self, event: dict[str, object]) -> K3Result[dict[str, object]]:
        """Execute one causal step. Total — never throws.

        On Ok: state and ctx are advanced.
        On Impossible: state and ctx are unchanged.
        On Violated: state and ctx are unchanged (T ran but result is rejected).
        """
        result = engine_apply(
            self._state,
            self._ctx,
            event,
            self._compiled,
            self._transition,
        )
        if isinstance(result, Ok):
            self._state = cast("dict[str, object]", result.state)
            self._ctx = result.ctx
        return result

    def reduce(self, events: list[dict[str, object]]) -> K3Result[dict[str, object]]:
        """Fold event stream through apply(). Stops on first non-Ok.

        Returns the last K3Result — Ok if all succeeded, or the first
        Impossible/Violated that stopped the fold.
        """
        result: K3Result[dict[str, object]] = Ok(
            state=self._state, ctx=self._ctx, step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    def reduce_all(self, events: list[dict[str, object]]) -> ReduceAllResult:
        """Process all events. Skip Impossible, stop on Violated.

        Returns ReduceAllResult with final state, count of processed events,
        and list of skipped Impossible events with their indices.
        """
        skipped: list[tuple[int, Impossible]] = []
        processed = 0
        last_ok: K3Result[dict[str, object]] = Ok(
            state=self._state, ctx=self._ctx, step_hash=""
        )

        for i, event in enumerate(events):
            result = self.apply(event)
            if isinstance(result, Ok):
                processed += 1
                last_ok = result
            elif isinstance(result, Impossible):
                skipped.append((i, result))
            else:
                # Violated — stop
                return ReduceAllResult(
                    final=result, processed=processed, skipped=skipped
                )

        return ReduceAllResult(final=last_ok, processed=processed, skipped=skipped)

    def reset(self) -> None:
        """Reset state and ctx to initial. Start a new session."""
        self._state = deepcopy(self._initial_state)
        self._ctx = SpecCtx.initial(self._compiled.state0)

    def isolate(self) -> IsolatedUniverse:
        """Move this Universe into an isolated execution context.

        Returns an IsolatedUniverse with deep-copied state and no shared
        references. All communication is via serializable dicts.

        Used for: parallel fuzz workers, multi-session processing,
        physical isolation (own GIL on Python 3.14+).
        """
        from k3c.universe.isolate import IsolatedUniverse as _Isolated

        return _Isolated(
            spec=self._k3spec,
            state=self._state,
            transition=self._transition,
            id=f"{self._id}:isolated",
            hash_fn=self._compiled.hash_fn,
        )

    def explain(self, event: dict[str, object]) -> ExplainResult:
        """Dry-run an event with full eval trace. State is NOT mutated."""
        from k3c.universe.explain import explain as _explain

        return _explain(self._state, self._ctx, event, self._compiled, self._transition)

    def fuzz(
        self,
        *,
        sequences: int = 1000,
        steps: int = 100,
        seed: int = 0,
        event_generator: EventGenerator | None = None,
        max_violations: int = 1,
        shrink: bool = True,
    ) -> FuzzReport:
        """Property-based fuzz testing. Discharges well-formedness rule 8."""
        from k3c.universe.fuzz import fuzz as _fuzz

        return _fuzz(
            self,
            sequences=sequences,
            steps=steps,
            seed=seed,
            event_generator=event_generator,
            max_violations=max_violations,
            shrink=shrink,
        )

    def compose(
        self,
        other: Applyable,
        router: Callable[[dict[str, object]], str],
    ) -> ComposedUniverse:
        """Compose with another Universe via <||>. Algebra is closed."""
        from k3c.universe.compose import ComposedUniverse as _Composed

        return _Composed(left=self, right=other, router=router)

    def bridge(
        self,
        target: Applyable,
        mapper: Callable[
            [dict[str, object], dict[str, object], dict[str, object]],
            dict[str, object] | None,
        ],
        mode: BridgeMode = BridgeMode.SYNCHRONOUS,
        retry: RetryPolicy | None = None,
        fallback: FallbackStrategy = FallbackStrategy.FAIL,
    ) -> BridgedUniverse:
        """Bridge to another Universe via <->. Algebra is closed."""
        from k3c.universe.bridge import BridgedUniverse as _Bridged

        return _Bridged(
            source=self,
            target=target,
            mapper=mapper,
            mode=mode,
            retry=retry,
            fallback=fallback,
        )

    def __repr__(self) -> str:
        return f"Universe(id={self._id!r}, state_keys={list(self._state.keys())})"


# ── Factory function ─────────────────────────────────────────────────────────


def universe(
    system: System,
    spec: K3Spec,
    *,
    id: str = "",
    hash_fn: str = "sha256",
) -> Universe:
    """Create a Universe from a system implementation and a spec.

    system: provides transition(state, event) → new_state
    spec: K3Spec from the builder
    id: optional identifier (defaults to spec name)
    hash_fn: hash algorithm — 'sha256' (default), 'blake2b', 'blake3'

    Runs well-formedness validation at construction time.
    """
    # Check process-level compiled spec cache — content-addressed
    spec_repr = repr(
        (
            spec.name,
            spec.state0,
            repr(spec.permits),
            repr(spec.maintains),
            repr(spec.projections),
            repr(spec.outputs),
            hash_fn,
        )
    )
    cache_key = hashlib.sha256(spec_repr.encode()).hexdigest()[:32]
    cached_compiled = K3Cache.lang_compiled.get(cache_key)
    if isinstance(cached_compiled, CompiledSpec):
        compiled = cached_compiled
    else:
        compiled = compile_spec(spec, hash_fn=hash_fn)
        _validate_well_formed(compiled)
        K3Cache.lang_compiled.put(cache_key, compiled)

    return Universe(
        id=id or compiled.name,
        compiled=compiled,
        k3spec=spec,
        state=deepcopy(compiled.state0),
        ctx=SpecCtx.initial(compiled.state0),
        transition=system.transition,
    )


# ── ParallelReduceResult ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParallelReduceResult:
    """Result of parallel_reduce — N chunks processed in parallel.

    results: per-chunk ReduceAllResult, in chunk order
    violations: list of (chunk_index, Violated) for any chunk that failed
    total_processed: sum of processed across all chunks
    total_skipped: sum of skipped across all chunks
    """

    results: tuple[ReduceAllResult, ...]
    violations: tuple[tuple[int, Violated], ...]
    total_processed: int
    total_skipped: int

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    @property
    def states(self) -> list[dict[str, object]]:
        """Final states from all chunks that passed."""
        return [
            cast("dict[str, object]", r.final.state)
            for r in self.results
            if isinstance(r.final, Ok)
        ]


# ── Worker function (must be top-level for pickling) ────────────────────────


def _reduce_chunk(
    system: System,
    spec: K3Spec,
    chunk: list[dict[str, object]],
    hash_fn: str,
) -> ReduceAllResult:
    """Process one chunk in a worker. Creates its own Universe."""
    u = universe(system, spec, hash_fn=hash_fn)
    return u.reduce_all(chunk)


def _parallel_execute(
    system: System,
    specs: list[K3Spec],
    chunks: list[list[dict[str, object]]],
    workers: int,
    hash_fn: str,
) -> list[ReduceAllResult]:
    """Run chunks in parallel — version-adaptive executor.

    Python 3.14+: concurrent.interpreters.InterpreterPoolExecutor
    Python 3.13+: concurrent.futures.ProcessPoolExecutor
    Python 3.12+: concurrent.futures.ProcessPoolExecutor
    """
    max_workers = min(workers, len(chunks))

    if sys.version_info >= (3, 14):
        try:
            from concurrent.interpreters import InterpreterPoolExecutor

            with InterpreterPoolExecutor(max_workers=max_workers) as pool:
                futures = [
                    pool.submit(_reduce_chunk, system, spec, chunk, hash_fn)
                    for spec, chunk in zip(specs, chunks)
                ]
                return [f.result() for f in futures]
        except ImportError:
            pass  # fall through to ProcessPoolExecutor

    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_reduce_chunk, system, spec, chunk, hash_fn)
            for spec, chunk in zip(specs, chunks)
        ]
        return [f.result() for f in futures]


# ── parallel_reduce ─────────────────────────────────────────────────────────


def parallel_reduce(
    system: System,
    specs: list[K3Spec],
    chunks: list[list[dict[str, object]]],
    *,
    workers: int = 4,
    hash_fn: str = "sha256",
) -> ParallelReduceResult:
    """Process N chunks in parallel using derived specs.

    Each chunk gets its own Universe built from its spec (typically derived
    via spec.slice()). Chunks are processed independently — no shared state.

    system: provides transition(state, event) → new_state
    specs: one K3Spec per chunk (from spec.slice())
    chunks: one event list per spec
    workers: number of parallel workers
    hash_fn: hash algorithm for all workers

    Results merge deterministically:
      - Violated from any chunk is captured
      - Ok chunks produce independent final states

    Example:
        leg_specs = [unified_spec.slice(from_state=cp) for cp in checkpoints]
        result = parallel_reduce(MySystem(), leg_specs, chunks, workers=8)
        if result.passed:
            print(f"Processed {result.total_processed} events")
    """
    if len(specs) != len(chunks):
        msg = f"specs and chunks must have same length: {len(specs)} != {len(chunks)}"
        raise ValueError(msg)

    if workers <= 1 or len(chunks) <= 1:
        # Sequential fallback — no overhead
        results = [
            _reduce_chunk(system, spec, chunk, hash_fn)
            for spec, chunk in zip(specs, chunks)
        ]
    else:
        results = _parallel_execute(system, specs, chunks, workers, hash_fn)

    violations: list[tuple[int, Violated]] = []
    total_processed = 0
    total_skipped = 0

    for i, r in enumerate(results):
        total_processed += r.processed
        total_skipped += len(r.skipped)
        if isinstance(r.final, Violated):
            violations.append((i, r.final))

    return ParallelReduceResult(
        results=tuple(results),
        violations=tuple(violations),
        total_processed=total_processed,
        total_skipped=total_skipped,
    )
