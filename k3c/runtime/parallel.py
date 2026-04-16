# k3c/runtime/parallel.py
"""
Parallel reduce -- process N chunks in parallel using derived specs.

Each chunk gets its own Universe built from its spec (typically derived
via spec.slice()). Chunks are processed independently -- no shared state.

Usage:
    leg_specs = [unified_spec.slice(from_state=cp) for cp in checkpoints]
    result = parallel_reduce(
        transition=my_transition,
        specs=leg_specs,
        chunks=chunks,
        workers=8,
        on_error=lambda e: ErrorAction.SKIP,
    )
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Callable

from k3c.engine.result import (
    ErrorAction,
    ErrorHandler,
    Impossible,
    Ok,
    StepError,
    Violated,
)
from k3c.engine.step import TransitionFn
from k3c.runtime.universe import ReduceAllResult, Universe
from k3c.spec.model import Spec


# -- ChunkResult --------------------------------------------------------------


@dataclass(frozen=True)
class ChunkResult:
    """Result of processing a single chunk with error streaming."""

    chunk_index: int
    processed: int
    errors: tuple[StepError, ...]
    final_state: dict[str, object] | None
    aborted: bool

    @property
    def passed(self) -> bool:
        return not any(e.is_violation for e in self.errors) and not self.aborted


# -- ParallelReduceResult ------------------------------------------------------


@dataclass(frozen=True)
class ParallelReduceResult:
    """Result of parallel_reduce -- N chunks processed in parallel.

    chunk_results: per-chunk ChunkResult, in chunk order
    errors: all StepErrors across all chunks, in order
    violations: errors that are Violated (subset of errors)
    total_processed: sum of processed across all chunks
    """

    chunk_results: tuple[ChunkResult, ...]
    errors: tuple[StepError, ...]
    total_processed: int

    @property
    def passed(self) -> bool:
        return all(cr.passed for cr in self.chunk_results)

    @property
    def violations(self) -> tuple[StepError, ...]:
        return tuple(e for e in self.errors if e.is_violation)

    @property
    def impossible(self) -> tuple[StepError, ...]:
        return tuple(e for e in self.errors if not e.is_violation)

    @property
    def states(self) -> list[dict[str, object]]:
        """Final states from all chunks that passed."""
        return [
            cr.final_state
            for cr in self.chunk_results
            if cr.passed and cr.final_state is not None
        ]


# -- ChunkSource ---------------------------------------------------------------


@dataclass(frozen=True)
class ChunkSource:
    """A lazy event producer -- invoked by workers to stream events from disk.

    Each worker calls the ChunkSource to lazily stream events on demand.

    Example:
        def read_range(path, start, end, decode):
            with open(path, 'rb') as f:
                f.seek(start * 201)
                for _ in range(start, end):
                    yield decode(f.read(201)[:200])

        source = ChunkSource(produce=lambda: read_range(path, 0, 1000, decode))
    """

    produce: Callable[[], Iterable[object]]

    def __call__(self) -> Iterable[object]:
        return self.produce()


# -- Core chunk processing with error streaming --------------------------------


def _process_chunk(
    transition: TransitionFn,
    spec: Spec,
    events: Iterable[object],
    chunk_index: int,
    hash_fn: str,
    on_error: ErrorHandler | None,
) -> ChunkResult:
    """Process a chunk with per-step error streaming."""
    u = Universe(spec=spec, transition=transition, hash_fn=hash_fn, validate=False)
    processed = 0
    errors: list[StepError] = []
    aborted = False

    for offset, event in enumerate(events):
        result = u.apply(event)

        if isinstance(result, Ok):
            processed += 1
            continue

        step_error = StepError(
            chunk_index=chunk_index,
            offset=offset,
            result=result,
        )
        errors.append(step_error)

        if on_error is not None:
            action = on_error(step_error)
        else:
            # Default: skip Impossible, abort on Violated
            action = (
                ErrorAction.ABORT_CHUNK
                if isinstance(result, Violated)
                else ErrorAction.SKIP
            )

        match action:
            case ErrorAction.SKIP:
                continue
            case ErrorAction.ABORT_CHUNK:
                aborted = isinstance(result, Violated)
                break
            case ErrorAction.ABORT_ALL:
                aborted = True
                break

    return ChunkResult(
        chunk_index=chunk_index,
        processed=processed,
        errors=tuple(errors),
        final_state=u.state if processed > 0 else None,
        aborted=aborted,
    )


# -- Worker functions (top-level for pickling) ---------------------------------


def _run_chunk(
    transition: TransitionFn,
    spec: Spec,
    chunk: list[object] | ChunkSource,
    chunk_index: int,
    hash_fn: str,
    on_error: ErrorHandler | None,
) -> ChunkResult:
    """Run a single chunk -- handles both list and ChunkSource."""
    events = chunk() if isinstance(chunk, ChunkSource) else chunk
    return _process_chunk(transition, spec, events, chunk_index, hash_fn, on_error)


# -- parallel_reduce -----------------------------------------------------------


def parallel_reduce(
    transition: TransitionFn,
    specs: list[Spec],
    chunks: list[list[object] | ChunkSource],
    *,
    workers: int = 4,
    hash_fn: str = "sha256",
    on_error: ErrorHandler | None = None,
) -> ParallelReduceResult:
    """Process N chunks in parallel using derived specs.

    Each chunk gets its own Universe built from its spec (typically derived
    via spec.slice()). Chunks are processed independently -- no shared state.

    transition: T_impl -- user-supplied transition function
    specs: one Spec per chunk (from spec.slice())
    chunks: one event list or ChunkSource per spec
    workers: number of parallel workers
    hash_fn: hash algorithm for all workers
    on_error: callback receiving StepError, returns ErrorAction to control flow.
              Called per-event as errors happen. If None, defaults to skip
              Impossible and abort on Violated.

    Returns ParallelReduceResult with full error identity per step.
    """
    if len(specs) != len(chunks):
        msg = f"specs and chunks must have same length: {len(specs)} != {len(chunks)}"
        raise ValueError(msg)

    if workers <= 1 or len(chunks) <= 1:
        # Sequential -- on_error called inline
        chunk_results = [
            _run_chunk(transition, spec, chunk, i, hash_fn, on_error)
            for i, (spec, chunk) in enumerate(zip(specs, chunks))
        ]
    else:
        # Parallel -- on_error called within each worker process
        chunk_results = _parallel_execute(
            transition, specs, chunks, workers, hash_fn, on_error
        )

    all_errors: list[StepError] = []
    total_processed = 0

    for cr in chunk_results:
        total_processed += cr.processed
        all_errors.extend(cr.errors)

    return ParallelReduceResult(
        chunk_results=tuple(chunk_results),
        errors=tuple(all_errors),
        total_processed=total_processed,
    )


def _parallel_execute(
    transition: TransitionFn,
    specs: list[Spec],
    chunks: list[list[object] | ChunkSource],
    workers: int,
    hash_fn: str,
    on_error: ErrorHandler | None,
) -> list[ChunkResult]:
    """Run chunks in parallel -- version-adaptive executor."""
    max_workers = min(workers, len(chunks))

    if sys.version_info >= (3, 14):
        try:
            from concurrent.futures import InterpreterPoolExecutor

            with InterpreterPoolExecutor(max_workers=max_workers) as pool:
                futures = [
                    pool.submit(_run_chunk, transition, spec, chunk, i, hash_fn, on_error)
                    for i, (spec, chunk) in enumerate(zip(specs, chunks))
                ]
                return [f.result() for f in futures]
        except ImportError:
            pass

    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_run_chunk, transition, spec, chunk, i, hash_fn, on_error)
            for i, (spec, chunk) in enumerate(zip(specs, chunks))
        ]
        return [f.result() for f in futures]
