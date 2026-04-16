"""Tests for k3c.runtime.parallel -- parallel_reduce and error streaming."""

from __future__ import annotations

import pytest

from k3c.engine.result import ErrorAction, StepError
from k3c.ir.expr import (
    Always,
    CmpOp,
    Compare,
    EventField,
    Field,
    LBool,
    LInt,
    Var,
)
from k3c.runtime.parallel import (
    ChunkResult,
    ChunkSource,
    ParallelReduceResult,
    parallel_reduce,
)
from k3c.spec.model import Maintain, Permit, Spec


def _counter_spec(start=0):
    return Spec(
        name="counter",
        state0={"count": start},
        permits=(Permit(name="ok", when=LBool(True), on="Inc"),),
        maintains=(
            Maintain(
                name="pos",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
            ),
        ),
    )


def _guarded_spec(start=0):
    """Counter that rejects increments above 100."""
    return Spec(
        name="guarded_counter",
        state0={"count": start},
        permits=(
            Permit(
                name="not_too_large",
                when=Compare(CmpOp.LE, EventField("n"), LInt(100)),
                on="Inc",
            ),
        ),
        maintains=(
            Maintain(
                name="pos",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
            ),
        ),
    )


def _counter_t(s, e):
    return {**s, "count": s["count"] + e.get("n", 1)}


class TestParallelReduce:
    def test_basic(self):
        specs = [_counter_spec(0), _counter_spec(100)]
        chunks = [
            [{"type": "Inc", "n": 1}, {"type": "Inc", "n": 2}],
            [{"type": "Inc", "n": 10}, {"type": "Inc", "n": 20}],
        ]
        result = parallel_reduce(
            transition=_counter_t, specs=specs, chunks=chunks, workers=1
        )
        assert result.passed
        assert result.total_processed == 4
        assert result.states[0]["count"] == 3
        assert result.states[1]["count"] == 130

    def test_with_slice(self):
        base = _counter_spec(0)
        sliced = base.slice(from_state={"count": 50})
        result = parallel_reduce(
            transition=_counter_t,
            specs=[sliced],
            chunks=[[{"type": "Inc", "n": 5}]],
            workers=1,
        )
        assert result.passed
        assert result.states[0]["count"] == 55

    def test_length_mismatch(self):
        with pytest.raises(ValueError, match="same length"):
            parallel_reduce(
                transition=_counter_t, specs=[_counter_spec()], chunks=[[], []]
            )

    def test_empty_chunks(self):
        result = parallel_reduce(transition=_counter_t, specs=[], chunks=[], workers=1)
        assert result.passed
        assert result.total_processed == 0

    def test_chunk_source(self):
        specs = [_counter_spec(0)]
        source = ChunkSource(produce=lambda: [{"type": "Inc", "n": 10}])
        result = parallel_reduce(
            transition=_counter_t, specs=specs, chunks=[source], workers=1
        )
        assert result.passed
        assert result.states[0]["count"] == 10


class TestParallelReduceResult:
    def test_properties(self):
        specs = [_counter_spec(0), _counter_spec(0)]
        chunks = [
            [{"type": "Inc", "n": 1}],
            [{"type": "Inc", "n": 2}],
        ]
        result = parallel_reduce(
            transition=_counter_t, specs=specs, chunks=chunks, workers=1
        )
        assert isinstance(result, ParallelReduceResult)
        assert result.passed is True
        assert result.total_processed == 2
        assert len(result.errors) == 0
        assert len(result.states) == 2


class TestErrorStreaming:
    def test_impossible_yields_step_error(self):
        """Guard rejection produces StepError with correct identity."""
        specs = [_guarded_spec(0)]
        chunks = [
            [
                {"type": "Inc", "n": 5},
                {"type": "Inc", "n": 200},  # rejected
                {"type": "Inc", "n": 3},
            ]
        ]
        result = parallel_reduce(
            transition=_counter_t, specs=specs, chunks=chunks, workers=1
        )
        assert result.passed  # Impossible doesn't fail the chunk
        assert result.total_processed == 2
        assert len(result.errors) == 1
        assert len(result.impossible) == 1
        assert len(result.violations) == 0

        err = result.errors[0]
        assert err.chunk_index == 0
        assert err.offset == 1
        assert err.why.rule == "not_too_large"
        assert err.why.event == {"type": "Inc", "n": 200}
        assert not err.is_violation

    def test_violated_yields_step_error_and_aborts(self):
        """Invariant violation produces StepError and aborts chunk by default."""
        specs = [_counter_spec(0)]
        chunks = [
            [
                {"type": "Inc", "n": 5},
                {"type": "Inc", "n": -100},  # violates pos invariant
                {"type": "Inc", "n": 1},  # should not be reached
            ]
        ]
        result = parallel_reduce(
            transition=_counter_t, specs=specs, chunks=chunks, workers=1
        )
        assert not result.passed
        assert len(result.violations) == 1

        err = result.violations[0]
        assert err.chunk_index == 0
        assert err.offset == 1
        assert err.is_violation
        assert err.why.rule == "pos"
        assert err.why.before == {"count": 5}
        assert err.why.after == {"count": -95}
        assert err.why.event == {"type": "Inc", "n": -100}

    def test_on_error_skip_all(self):
        """Client can skip all errors including violations."""
        specs = [_counter_spec(0)]
        chunks = [
            [
                {"type": "Inc", "n": 5},
                {"type": "Inc", "n": -100},  # violation -- but client skips
                {"type": "Inc", "n": 1},  # should still be reached
            ]
        ]

        errors_seen: list[StepError] = []

        def handler(e: StepError) -> ErrorAction:
            errors_seen.append(e)
            return ErrorAction.SKIP

        res = parallel_reduce(
            transition=_counter_t,
            specs=specs,
            chunks=chunks,
            workers=1,
            on_error=handler,
        )
        # Client chose SKIP so chunk continues, but violation is recorded
        assert len(errors_seen) == 1
        assert errors_seen[0].is_violation
        assert res.total_processed == 2

    def test_on_error_abort_all(self):
        """Client can abort all chunks from any error."""
        specs = [_guarded_spec(0)]
        chunks = [
            [
                {"type": "Inc", "n": 200},  # rejected
                {"type": "Inc", "n": 5},  # should not be reached
            ]
        ]

        def handler(e: StepError) -> ErrorAction:
            return ErrorAction.ABORT_ALL

        res = parallel_reduce(
            transition=_counter_t,
            specs=specs,
            chunks=chunks,
            workers=1,
            on_error=handler,
        )
        assert res.total_processed == 0
        assert len(res.errors) == 1

    def test_multi_chunk_error_identity(self):
        """Errors carry correct chunk_index across multiple chunks."""
        specs = [_guarded_spec(0), _guarded_spec(0)]
        chunks = [
            [{"type": "Inc", "n": 5}, {"type": "Inc", "n": 200}],  # chunk 0, offset 1
            [{"type": "Inc", "n": 300}, {"type": "Inc", "n": 3}],  # chunk 1, offset 0
        ]
        result = parallel_reduce(
            transition=_counter_t, specs=specs, chunks=chunks, workers=1
        )
        assert result.total_processed == 2  # 1 per chunk (rejected events don't count)
        assert len(result.errors) == 2

        by_chunk = {e.chunk_index: e for e in result.errors}
        assert by_chunk[0].offset == 1
        assert by_chunk[0].why.event["n"] == 200
        assert by_chunk[1].offset == 0
        assert by_chunk[1].why.event["n"] == 300

    def test_chunk_result_properties(self):
        """ChunkResult carries per-chunk detail."""
        specs = [_guarded_spec(0)]
        chunks = [
            [
                {"type": "Inc", "n": 1},
                {"type": "Inc", "n": 200},
                {"type": "Inc", "n": 2},
            ]
        ]
        result = parallel_reduce(
            transition=_counter_t, specs=specs, chunks=chunks, workers=1
        )
        cr = result.chunk_results[0]
        assert isinstance(cr, ChunkResult)
        assert cr.chunk_index == 0
        assert cr.processed == 2
        assert len(cr.errors) == 1
        assert cr.passed  # Impossible doesn't fail the chunk
        assert cr.final_state["count"] == 3

    def test_step_error_repr(self):
        """StepError has a useful repr."""
        specs = [_guarded_spec(0)]
        chunks = [[{"type": "Inc", "n": 200}]]
        result = parallel_reduce(
            transition=_counter_t, specs=specs, chunks=chunks, workers=1
        )
        err = result.errors[0]
        r = repr(err)
        assert "chunk=0" in r
        assert "offset=0" in r
        assert "Impossible" in r
        assert "not_too_large" in r


class TestParallelErrorSupervisor:
    """Tests for on_error with workers > 1 (queue-based supervisor)."""

    def test_on_error_called_in_main_process(self):
        """on_error callback runs in the main process for parallel workers."""
        import os

        main_pid = os.getpid()
        callback_pids: list[int] = []

        def handler(e: StepError) -> ErrorAction:
            callback_pids.append(os.getpid())
            return ErrorAction.SKIP

        specs = [_guarded_spec(0), _guarded_spec(0)]
        chunks = [
            [{"type": "Inc", "n": 200}],  # rejected in chunk 0
            [{"type": "Inc", "n": 300}],  # rejected in chunk 1
        ]
        result = parallel_reduce(
            transition=_counter_t,
            specs=specs,
            chunks=chunks,
            workers=2,
            on_error=handler,
        )
        assert len(result.errors) == 2
        assert all(pid == main_pid for pid in callback_pids)

    def test_on_error_skip_parallel(self):
        """SKIP action allows workers to continue past errors."""
        specs = [_guarded_spec(0), _guarded_spec(0)]
        chunks = [
            [{"type": "Inc", "n": 5}, {"type": "Inc", "n": 200}, {"type": "Inc", "n": 3}],
            [{"type": "Inc", "n": 300}, {"type": "Inc", "n": 7}],
        ]

        errors_seen: list[StepError] = []

        def handler(e: StepError) -> ErrorAction:
            errors_seen.append(e)
            return ErrorAction.SKIP

        result = parallel_reduce(
            transition=_counter_t,
            specs=specs,
            chunks=chunks,
            workers=2,
            on_error=handler,
        )
        assert len(errors_seen) == 2
        assert result.total_processed == 3  # 2 from chunk 0, 1 from chunk 1

    def test_on_error_abort_chunk_parallel(self):
        """ABORT_CHUNK stops the erroring chunk, others continue."""
        specs = [_guarded_spec(0), _guarded_spec(0)]
        chunks = [
            [{"type": "Inc", "n": 200}, {"type": "Inc", "n": 5}],  # chunk 0 aborts
            [{"type": "Inc", "n": 7}, {"type": "Inc", "n": 3}],  # chunk 1 ok
        ]

        def handler(e: StepError) -> ErrorAction:
            return ErrorAction.ABORT_CHUNK

        result = parallel_reduce(
            transition=_counter_t,
            specs=specs,
            chunks=chunks,
            workers=2,
            on_error=handler,
        )
        assert result.total_processed == 2  # only chunk 1 processed
        assert len(result.errors) == 1
        assert result.chunk_results[0].aborted
        assert not result.chunk_results[1].aborted

    def test_on_error_abort_all_parallel(self):
        """ABORT_ALL stops all workers."""
        specs = [_guarded_spec(0), _guarded_spec(0)]
        chunks = [
            [{"type": "Inc", "n": 200}, {"type": "Inc", "n": 5}],
            [{"type": "Inc", "n": 300}, {"type": "Inc", "n": 7}],
        ]

        def handler(e: StepError) -> ErrorAction:
            return ErrorAction.ABORT_ALL

        result = parallel_reduce(
            transition=_counter_t,
            specs=specs,
            chunks=chunks,
            workers=2,
            on_error=handler,
        )
        # Both chunks should have aborted
        assert all(cr.aborted for cr in result.chunk_results)

    def test_error_identity_preserved_parallel(self):
        """StepError carries correct chunk_index and offset in parallel mode."""
        specs = [_guarded_spec(0), _guarded_spec(0)]
        chunks = [
            [{"type": "Inc", "n": 5}, {"type": "Inc", "n": 200}],  # error at offset 1
            [{"type": "Inc", "n": 300}, {"type": "Inc", "n": 3}],  # error at offset 0
        ]

        errors_seen: list[StepError] = []

        def handler(e: StepError) -> ErrorAction:
            errors_seen.append(e)
            return ErrorAction.SKIP

        parallel_reduce(
            transition=_counter_t,
            specs=specs,
            chunks=chunks,
            workers=2,
            on_error=handler,
        )
        assert len(errors_seen) == 2
        by_chunk = {e.chunk_index: e for e in errors_seen}
        assert by_chunk[0].offset == 1
        assert by_chunk[0].why.event["n"] == 200
        assert by_chunk[1].offset == 0
        assert by_chunk[1].why.event["n"] == 300

    def test_no_errors_no_supervisor_overhead(self):
        """Clean runs with on_error don't break."""
        specs = [_counter_spec(0), _counter_spec(0)]
        chunks = [
            [{"type": "Inc", "n": 1}],
            [{"type": "Inc", "n": 2}],
        ]

        def handler(e: StepError) -> ErrorAction:
            raise AssertionError("should not be called")

        result = parallel_reduce(
            transition=_counter_t,
            specs=specs,
            chunks=chunks,
            workers=2,
            on_error=handler,
        )
        assert result.passed
        assert result.total_processed == 2
        assert len(result.errors) == 0
