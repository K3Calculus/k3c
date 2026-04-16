"""Tests for k3c.runtime.parallel -- parallel_reduce."""

from __future__ import annotations

import pytest

from k3c.ir.expr import Always, CmpOp, Compare, Field, LBool, LInt, Var
from k3c.runtime.parallel import ChunkSource, ParallelReduceResult, parallel_reduce
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
        assert result.total_skipped == 0
        assert len(result.states) == 2
