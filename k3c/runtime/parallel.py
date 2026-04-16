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
    )
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable, cast

from k3c.engine.result import Ok, Violated
from k3c.engine.step import TransitionFn
from k3c.runtime.universe import ReduceAllResult, Universe
from k3c.spec.model import Spec


# -- ParallelReduceResult ------------------------------------------------------


@dataclass(frozen=True)
class ParallelReduceResult:
    """Result of parallel_reduce -- N chunks processed in parallel.

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


# -- Worker functions (top-level for pickling) ---------------------------------


def _reduce_chunk(
    transition: TransitionFn,
    spec: Spec,
    chunk: list[object],
    hash_fn: str,
) -> ReduceAllResult:
    """Process one materialized chunk in a worker."""
    u = Universe(spec=spec, transition=transition, hash_fn=hash_fn, validate=False)
    return u.reduce_all(chunk)


def _reduce_chunk_source(
    transition: TransitionFn,
    spec: Spec,
    source: ChunkSource,
    hash_fn: str,
) -> ReduceAllResult:
    """Process a ChunkSource in a worker."""
    u = Universe(spec=spec, transition=transition, hash_fn=hash_fn, validate=False)
    return u.reduce_all(source())


def _run_chunk_sequential(
    transition: TransitionFn,
    spec: Spec,
    chunk: list[object] | ChunkSource,
    hash_fn: str,
) -> ReduceAllResult:
    """Run a single chunk sequentially."""
    if isinstance(chunk, ChunkSource):
        return _reduce_chunk_source(transition, spec, chunk, hash_fn)
    return _reduce_chunk(transition, spec, chunk, hash_fn)


def _parallel_execute(
    transition: TransitionFn,
    specs: list[Spec],
    chunks: list[list[object] | ChunkSource],
    workers: int,
    hash_fn: str,
) -> list[ReduceAllResult]:
    """Run chunks in parallel -- version-adaptive executor."""
    max_workers = min(workers, len(chunks))

    # Separate lists and sources for typed dispatch
    list_pairs: list[tuple[Spec, list[object]]] = []
    source_pairs: list[tuple[Spec, ChunkSource]] = []
    for spec, chunk in zip(specs, chunks):
        if isinstance(chunk, ChunkSource):
            source_pairs.append((spec, chunk))
        else:
            list_pairs.append((spec, chunk))

    if sys.version_info >= (3, 14):
        try:
            from concurrent.futures import InterpreterPoolExecutor

            with InterpreterPoolExecutor(max_workers=max_workers) as pool:
                list_futures = [
                    pool.submit(_reduce_chunk, transition, s, c, hash_fn)
                    for s, c in list_pairs
                ]
                source_futures = [
                    pool.submit(_reduce_chunk_source, transition, s, c, hash_fn)
                    for s, c in source_pairs
                ]
                return [f.result() for f in list_futures] + [
                    f.result() for f in source_futures
                ]
        except ImportError:
            pass

    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        list_futures = [
            pool.submit(_reduce_chunk, transition, s, c, hash_fn) for s, c in list_pairs
        ]
        source_futures = [
            pool.submit(_reduce_chunk_source, transition, s, c, hash_fn)
            for s, c in source_pairs
        ]
        return [f.result() for f in list_futures] + [f.result() for f in source_futures]


# -- parallel_reduce -----------------------------------------------------------


def parallel_reduce(
    transition: TransitionFn,
    specs: list[Spec],
    chunks: list[list[object] | ChunkSource],
    *,
    workers: int = 4,
    hash_fn: str = "sha256",
) -> ParallelReduceResult:
    """Process N chunks in parallel using derived specs.

    Each chunk gets its own Universe built from its spec (typically derived
    via spec.slice()). Chunks are processed independently -- no shared state.

    transition: T_impl -- user-supplied transition function
    specs: one Spec per chunk (from spec.slice())
    chunks: one event list or ChunkSource per spec
    workers: number of parallel workers
    hash_fn: hash algorithm for all workers

    Results merge deterministically:
      - Violated from any chunk is captured
      - Ok chunks produce independent final states
    """
    if len(specs) != len(chunks):
        msg = f"specs and chunks must have same length: {len(specs)} != {len(chunks)}"
        raise ValueError(msg)

    if workers <= 1 or len(chunks) <= 1:
        results = [
            _run_chunk_sequential(transition, spec, chunk, hash_fn)
            for spec, chunk in zip(specs, chunks)
        ]
    else:
        results = _parallel_execute(transition, specs, chunks, workers, hash_fn)

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
