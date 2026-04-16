# k3c/runtime/parallel.py
"""
Parallel reduce -- process N chunks in parallel using derived specs.

Each chunk gets its own Universe built from its spec (typically derived
via spec.slice()). Chunks are processed independently -- no shared state.

When on_error is provided with workers > 1, an error universe (supervisor)
mediates between workers and the client callback via multiprocessing queues:

    Workers ──StepError──► error_q ──► supervisor ──► on_error()
    Workers ◄──ErrorAction── response_q[i] ◄── supervisor

Usage:
    result = parallel_reduce(
        transition=my_transition,
        specs=leg_specs,
        chunks=chunks,
        workers=8,
        on_error=my_handler,   # works in both sequential and parallel mode
    )
"""

from __future__ import annotations

import multiprocessing as mp
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from threading import Thread
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
from k3c.runtime.universe import Universe
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


# -- Supervised worker (queue-based error streaming) ---------------------------

_SENTINEL = None  # signals worker completion on the error queue


def _supervised_worker(
    transition: TransitionFn,
    spec: Spec,
    chunk: list[object] | ChunkSource,
    chunk_index: int,
    hash_fn: str,
    error_q: mp.Queue,
    response_q: mp.Queue,
    result_q: mp.Queue,
) -> None:
    """Worker process that streams errors to supervisor via queues.

    On each non-Ok result:
      1. Puts StepError into error_q
      2. Blocks on response_q for ErrorAction from supervisor
      3. Acts on the action

    Sends _SENTINEL to error_q when done.
    Puts ChunkResult into result_q when finished.
    """
    events = chunk() if isinstance(chunk, ChunkSource) else chunk
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

        # Send error to supervisor and wait for decision
        error_q.put((chunk_index, step_error))
        action = response_q.get()

        match action:
            case ErrorAction.SKIP:
                continue
            case ErrorAction.ABORT_CHUNK:
                aborted = True
                break
            case ErrorAction.ABORT_ALL:
                aborted = True
                break

    # Signal completion
    error_q.put((chunk_index, _SENTINEL))

    result_q.put(
        ChunkResult(
            chunk_index=chunk_index,
            processed=processed,
            errors=tuple(errors),
            final_state=u.state if processed > 0 else None,
            aborted=aborted,
        )
    )


def _run_supervisor(
    on_error: ErrorHandler,
    error_q: mp.Queue,
    response_qs: list[mp.Queue],
    num_workers: int,
) -> None:
    """Supervisor loop — runs in a thread in the main process.

    Reads StepErrors from workers, calls on_error, sends ErrorAction back.
    On ABORT_ALL, sends abort to all workers that haven't finished yet.
    """
    finished = set()
    abort_all = False

    while len(finished) < num_workers:
        chunk_index, payload = error_q.get()

        if payload is _SENTINEL:
            finished.add(chunk_index)
            continue

        step_error: StepError = payload

        if abort_all:
            # Already aborting — tell this worker to stop
            response_qs[chunk_index].put(ErrorAction.ABORT_ALL)
            continue

        action = on_error(step_error)
        response_qs[chunk_index].put(action)

        if action == ErrorAction.ABORT_ALL:
            abort_all = True


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
              If None, defaults to skip Impossible and abort on Violated.

              Works in both sequential and parallel mode. In parallel mode,
              an error universe (supervisor) mediates between workers and the
              callback via multiprocessing queues — the callback always runs
              in the main process.

    Returns ParallelReduceResult with full error identity per step.
    """
    if len(specs) != len(chunks):
        msg = f"specs and chunks must have same length: {len(specs)} != {len(chunks)}"
        raise ValueError(msg)

    if workers <= 1 or len(chunks) <= 1:
        # Sequential -- on_error called inline within each worker
        chunk_results = [
            _run_chunk(transition, spec, chunk, i, hash_fn, on_error)
            for i, (spec, chunk) in enumerate(zip(specs, chunks))
        ]
    else:
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
    """Run chunks in parallel.

    Without on_error: workers use default policy (skip Impossible, abort on
    Violated). No queue overhead.

    With on_error: spawns an error universe (supervisor thread) that mediates
    between workers and the client callback via multiprocessing queues. Workers
    block on each error until the supervisor responds with an ErrorAction.
    """
    max_workers = min(workers, len(chunks))

    if on_error is not None:
        return _parallel_execute_supervised(
            transition, specs, chunks, hash_fn, on_error
        )

    # No on_error — simple dispatch, no queue overhead
    pool_cls = _get_pool_class()
    with pool_cls(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_run_chunk, transition, spec, chunk, i, hash_fn, None)
            for i, (spec, chunk) in enumerate(zip(specs, chunks))
        ]
        return [f.result() for f in futures]


def _parallel_execute_supervised(
    transition: TransitionFn,
    specs: list[Spec],
    chunks: list[list[object] | ChunkSource],
    hash_fn: str,
    on_error: ErrorHandler,
) -> list[ChunkResult]:
    """Run chunks in parallel with a supervisor mediating error flow.

    Architecture:
        Workers ──StepError──► error_q ──► supervisor thread ──► on_error()
        Workers ◄──ErrorAction── response_q[i] ◄── supervisor thread

    Uses fork context with mp.Process so queues and functions are inherited
    directly (no pickling). Falls back to sequential on platforms without
    fork (Windows).
    """
    try:
        ctx = mp.get_context("fork")
    except ValueError:
        # fork not available (Windows) — fall back to sequential
        return [
            _run_chunk(transition, spec, chunk, i, hash_fn, on_error)
            for i, (spec, chunk) in enumerate(zip(specs, chunks))
        ]

    num_chunks = len(chunks)

    error_q = ctx.Queue()
    response_qs = [ctx.Queue() for _ in range(num_chunks)]
    result_q = ctx.Queue()

    # Start worker processes BEFORE supervisor thread to avoid fork-after-thread
    processes: list[mp.process.BaseProcess] = []
    for i, (spec, chunk) in enumerate(zip(specs, chunks)):
        p = ctx.Process(
            target=_supervised_worker,
            args=(transition, spec, chunk, i, hash_fn, error_q, response_qs[i], result_q),
        )
        p.start()
        processes.append(p)

    # Start supervisor thread in main process (after fork)
    supervisor = Thread(
        target=_run_supervisor,
        args=(on_error, error_q, response_qs, num_chunks),
        daemon=True,
    )
    supervisor.start()

    # Collect results from result queue
    raw_results: list[ChunkResult] = []
    for _ in range(num_chunks):
        raw_results.append(result_q.get())

    # Wait for all processes and supervisor
    for p in processes:
        p.join(timeout=10.0)
    supervisor.join(timeout=5.0)

    # Sort by chunk_index to maintain deterministic order
    raw_results.sort(key=lambda cr: cr.chunk_index)
    return raw_results


def _get_pool_class():
    """Get the best available pool executor class."""
    if sys.version_info >= (3, 14):
        try:
            from concurrent.futures import InterpreterPoolExecutor

            return InterpreterPoolExecutor
        except ImportError:
            pass

    from concurrent.futures import ProcessPoolExecutor

    return ProcessPoolExecutor
