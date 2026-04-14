#!/usr/bin/env python3
"""
k3c Benchmarks — performance measurements for the core pipeline.

Usage:
    uv run python benchmarks/bench.py
    uv run python benchmarks/bench.py --quick     # fewer iterations
    uv run python benchmarks/bench.py --json      # machine-readable output

Measures:
    1. eval() throughput — K3l expression evaluation
    2. serde round-trip — to_dict/from_dict speed
    3. apply() throughput — full causal step pipeline
    4. reduce() throughput — event stream folding
    5. hash_step — chained hash computation
    6. compile — K3Spec → CompiledSpec
    7. fuzz — property-based testing throughput
    8. parallel_reduce — chunked parallel processing
    9. compose — routed apply through composed universes
    10. emit — K3l → TypeScript/SQL/Python generation
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass

from k3c import (
    Always,
    Arith,
    ArithOp,
    CmpOp,
    Compare,
    EventField,
    Field,
    LBool,
    LInt,
    LStr,
    Spec,
    Var,
    With,
    parallel_reduce,
    universe,
)
from k3c.lang.compile import compile_spec
from k3c.lang.emit import to_python, to_sql, to_typescript
from k3c.lang.eval import k3_eval
from k3c.lang.ir import And, IsSome, Not, Or
from k3c.lang.serde import from_dict, to_dict
from k3c.universe.engine import _hash_step

# ── Benchmark harness ───────────────────────────────────────────────────────


@dataclass
class BenchResult:
    name: str
    iterations: int
    total_ms: float
    ops_per_sec: float
    per_op_us: float

    def __str__(self) -> str:
        return (
            f"  {self.name:<35} "
            f"{self.ops_per_sec:>12,.0f} ops/s  "
            f"{self.per_op_us:>8.1f} us/op  "
            f"({self.iterations:,} iters, {self.total_ms:.0f}ms)"
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "total_ms": round(self.total_ms, 1),
            "ops_per_sec": round(self.ops_per_sec, 0),
            "per_op_us": round(self.per_op_us, 2),
        }


def bench(name: str, fn, iterations: int) -> BenchResult:
    # Warmup
    for _ in range(min(100, iterations // 10)):
        fn()

    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - start

    total_ms = elapsed * 1000
    ops_per_sec = iterations / elapsed if elapsed > 0 else 0
    per_op_us = (elapsed / iterations) * 1_000_000 if iterations > 0 else 0

    return BenchResult(
        name=name,
        iterations=iterations,
        total_ms=total_ms,
        ops_per_sec=ops_per_sec,
        per_op_us=per_op_us,
    )


# ── Benchmark fixtures ──────────────────────────────────────────────────────

# Simple expression
SIMPLE_EXPR = Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))

# Complex expression
COMPLEX_EXPR = And(
    Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
    And(
        Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("active")),
        Or(
            Compare(CmpOp.GT, Field(Var("state"), "balance"), LInt(1000)),
            IsSome(Field(Var("state"), "premium")),
        ),
    ),
)

# Deeply nested expression
DEEP_EXPR = Var("x")
for _ in range(10):
    DEEP_EXPR = Not(DEEP_EXPR)

EVAL_CTX: dict[str, object] = {
    "state": {"balance": 500, "status": "active", "premium": True},
    "event": {"type": "Withdraw", "amount": 100},
    "x": True,
}

# Bank spec
BANK_SPEC = (
    Spec("bench_bank")
    .state0({"balance": 1000})
    .permit(
        "has_funds",
        when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
        on="Withdraw",
    )
    .maintain(
        "non_negative",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
    )
    .project("balance", lambda s: s["balance"])
    .build()
)


class BenchBank:
    def transition(self, state, event):
        match event.get("type"):
            case "Withdraw":
                return {**state, "balance": state["balance"] - event["amount"]}
            case "Deposit":
                return {**state, "balance": state["balance"] + event["amount"]}
            case _:
                return state


# Complex spec with multiple clauses
COMPLEX_SPEC = (
    Spec("bench_complex")
    .state0({"balance": 1000, "count": 0, "items": []})
    .permit(
        "has_funds",
        when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
        on="Withdraw",
    )
    .permit("limit", when=Compare(CmpOp.LT, Field(Var("state"), "count"), LInt(10000)))
    .maintain(
        "non_negative",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
    )
    .maintain(
        "count_monotone",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
    )
    .project("balance", lambda s: s["balance"])
    .project("count", lambda s: s["count"])
    .output(
        "receipt",
        lambda s, e, ns: {"type": "Receipt", "balance": ns["balance"]},
        on="Withdraw",
    )
    .korrelate(lift=lambda s: {"balance": s["balance"]})
    .require(
        "track",
        on="Withdraw",
        transition=With(
            Var("spec_state"),
            (
                (
                    "balance",
                    Arith(
                        ArithOp.SUB,
                        Field(Var("spec_state"), "balance"),
                        EventField("amount"),
                    ),
                ),
            ),
        ),
    )
    .build()
)


# ── Benchmarks ──────────────────────────────────────────────────────────────


def run_benchmarks(quick: bool = False) -> list[BenchResult]:
    results = []
    n = 1_000 if quick else 10_000
    n_large = 100 if quick else 1_000

    # 1. eval() — simple expression
    results.append(
        bench(
            "eval(simple)",
            lambda: k3_eval(SIMPLE_EXPR, EVAL_CTX, "hash"),
            n,
        )
    )

    # 2. eval() — complex expression
    results.append(
        bench(
            "eval(complex)",
            lambda: k3_eval(COMPLEX_EXPR, EVAL_CTX, "hash"),
            n,
        )
    )

    # 3. eval() — deep nesting
    results.append(
        bench(
            "eval(deep_10)",
            lambda: k3_eval(DEEP_EXPR, EVAL_CTX, "hash"),
            n,
        )
    )

    # 4. serde round-trip — simple
    simple_dict = to_dict(SIMPLE_EXPR)
    results.append(
        bench(
            "serde(simple) to_dict",
            lambda: to_dict(SIMPLE_EXPR),
            n,
        )
    )
    results.append(
        bench(
            "serde(simple) from_dict",
            lambda: from_dict(simple_dict),
            n,
        )
    )

    # 5. serde round-trip — complex
    results.append(
        bench(
            "serde(complex) round-trip",
            lambda: from_dict(to_dict(COMPLEX_EXPR)),
            n,
        )
    )

    # 6. hash_step
    results.append(
        bench(
            "hash_step(sha256)",
            lambda: _hash_step({"x": 1}, {"type": "A"}, "prev_hash"),
            n,
        )
    )
    results.append(
        bench(
            "hash_step(blake2b)",
            lambda: _hash_step({"x": 1}, {"type": "A"}, "prev_hash", "blake2b"),
            n,
        )
    )

    # 7. compile
    results.append(
        bench(
            "compile(bank_spec)",
            lambda: compile_spec(BANK_SPEC),
            n_large,
        )
    )
    results.append(
        bench(
            "compile(complex_spec)",
            lambda: compile_spec(COMPLEX_SPEC),
            n_large,
        )
    )

    # 8. apply() — single step
    u_simple = universe(BenchBank(), BANK_SPEC)

    def apply_simple():
        u_simple.reset()
        u_simple.apply({"type": "Deposit", "amount": 10})

    results.append(bench("apply(simple)", apply_simple, n))

    u_complex = universe(BenchBank(), COMPLEX_SPEC)

    def apply_complex():
        u_complex.reset()
        u_complex.apply({"type": "Deposit", "amount": 10})

    results.append(bench("apply(complex)", apply_complex, n))

    # 9. reduce() — 100 events
    events_100 = [{"type": "Deposit", "amount": 1} for _ in range(100)]

    def reduce_100():
        u_simple.reset()
        u_simple.reduce(events_100)

    results.append(bench("reduce(100 events)", reduce_100, n_large))

    # 10. reduce() — 1000 events
    events_1000 = [{"type": "Deposit", "amount": 1} for _ in range(1000)]

    def reduce_1000():
        u_simple.reset()
        u_simple.reduce(events_1000)

    results.append(bench("reduce(1000 events)", reduce_1000, n_large // 10))

    # 11. fuzz
    def fuzz_quick():
        u_simple.fuzz(sequences=10, steps=10, seed=42)

    results.append(bench("fuzz(10x10)", fuzz_quick, n_large // 10))

    # 12. parallel_reduce
    chunks = [[{"type": "Deposit", "amount": 1}] * 25 for _ in range(4)]
    specs = [BANK_SPEC.slice(from_state={"balance": 0}) for _ in range(4)]

    def par_reduce():
        parallel_reduce(BenchBank(), specs, chunks, workers=1)

    results.append(bench("parallel_reduce(4x25)", par_reduce, n_large // 10))

    # 13. compose apply
    u_a = universe(BenchBank(), BANK_SPEC)
    u_b = universe(BenchBank(), BANK_SPEC)
    composed = u_a.compose(u_b, lambda e: "left")

    def compose_apply():
        composed.apply({"type": "Deposit", "amount": 1})

    results.append(bench("compose.apply(left)", compose_apply, n))

    # 14. isolate — creation
    def isolate_create():
        u_simple.isolate()

    results.append(bench("isolate(create)", isolate_create, n_large))

    # 15. isolate — apply
    iso = u_simple.isolate()

    def isolate_apply():
        iso.reset()
        iso.apply({"type": "Deposit", "amount": 1})

    results.append(bench("isolate.apply()", isolate_apply, n))

    # 16. isolate — reduce
    def isolate_reduce():
        iso.reset()
        iso.reduce(events_100)

    results.append(bench("isolate.reduce(100)", isolate_reduce, n_large))

    # 17. compose — parallel mode
    u_par_a = universe(BenchBank(), BANK_SPEC)
    u_par_b = universe(BenchBank(), BANK_SPEC)
    composed_par = u_par_a.compose(u_par_b, lambda e: "both")

    def compose_parallel():
        composed_par.apply({"type": "Deposit", "amount": 1}, mode="parallel")

    results.append(bench("compose.apply(parallel,trivial)", compose_parallel, n_large))

    # 17b. compose parallel — heavy computation (where parallel wins)
    HEAVY_SPEC = (
        Spec("bench_heavy")
        .state0({"data": list(range(500)), "result": 0})
        .permit("ok", when=LBool(True))
        .build()
    )

    class HeavySystem:
        """Simulates CPU-heavy transition — sort + reduce + sieve.
        Note: ThreadPoolExecutor doesn't bypass the GIL for CPU work.
        True parallel speedup requires InterpreterPoolExecutor (3.14+)
        or ProcessPoolExecutor. This benchmark shows the GIL limitation."""

        def transition(self, s, e):
            data = list(s["data"])
            sorted_data = sorted(data, reverse=True)
            result = sum(x * x for x in sorted_data[:200])
            # Heavier work to make the computation more visible
            for _ in range(5):
                sieve = [True] * 2000
                for i in range(2, 45):
                    if sieve[i]:
                        for j in range(i * i, 2000, i):
                            sieve[j] = False
                result += sum(1 for x in sieve if x)
            return {**s, "result": result}

    u_heavy_a = universe(HeavySystem(), HEAVY_SPEC)
    u_heavy_b = universe(HeavySystem(), HEAVY_SPEC)

    # Sequential heavy
    composed_heavy_seq = u_heavy_a.compose(u_heavy_b, lambda e: "both")

    def compose_heavy_seq_fn():
        composed_heavy_seq.apply({"type": "Compute"}, mode="sequential")

    results.append(bench("compose.heavy(sequential)", compose_heavy_seq_fn, n_large))

    # Parallel heavy
    u_heavy_c = universe(HeavySystem(), HEAVY_SPEC)
    u_heavy_d = universe(HeavySystem(), HEAVY_SPEC)
    composed_heavy_par = u_heavy_c.compose(u_heavy_d, lambda e: "both")

    def compose_heavy_par_fn():
        composed_heavy_par.apply({"type": "Compute"}, mode="parallel")

    results.append(bench("compose.heavy(parallel)", compose_heavy_par_fn, n_large))

    # ── Large state benchmarks — shows where overhead becomes real ─────

    # Build a spec with large state
    LARGE_STATE_SPEC = (
        Spec("bench_large")
        .state0(
            {
                "balance": 1000,
                "users": {
                    f"user_{i}": {"name": f"User {i}", "score": i * 10, "active": True}
                    for i in range(100)
                },
                "log": [{"ts": i, "action": "init"} for i in range(50)],
                "counters": {f"c_{i}": 0 for i in range(200)},
                "metadata": {
                    "version": "1.0",
                    "region": "us-east",
                    "tags": list(range(50)),
                },
            }
        )
        .permit("ok", when=LBool(True))
        .maintain(
            "balance_pos",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
        )
        .build()
    )

    class LargeSystem:
        def transition(self, s, e):
            return {**s, "balance": s["balance"] + e.get("amount", 0)}

    u_large = universe(LargeSystem(), LARGE_STATE_SPEC)

    def apply_large():
        u_large.reset()
        u_large.apply({"type": "Deposit", "amount": 1})

    results.append(bench("apply(large_state)", apply_large, n))

    # Isolate with large state — shows deep-copy overhead
    def isolate_create_large():
        u_large.isolate()

    results.append(bench("isolate.create(large)", isolate_create_large, n_large))

    iso_large = u_large.isolate()

    def isolate_apply_large():
        iso_large.reset()
        iso_large.apply({"type": "Deposit", "amount": 1})

    results.append(bench("isolate.apply(large)", isolate_apply_large, n))

    # Direct apply for comparison
    u_large_direct = universe(LargeSystem(), LARGE_STATE_SPEC)

    def apply_large_direct():
        u_large_direct.apply({"type": "Deposit", "amount": 1})

    results.append(bench("apply(large,no_reset)", apply_large_direct, n))

    # Hash with large state — json.dumps dominates
    large_state = u_large.state

    def hash_large():
        _hash_step(large_state, {"type": "A"}, "prev")

    results.append(bench("hash_step(large_state)", hash_large, n))

    # 22. emit — TypeScript
    results.append(
        bench(
            "emit.to_typescript(complex)",
            lambda: to_typescript(COMPLEX_EXPR),
            n,
        )
    )
    results.append(
        bench(
            "emit.to_sql(complex)",
            lambda: to_sql(COMPLEX_EXPR),
            n,
        )
    )
    results.append(
        bench(
            "emit.to_python(complex)",
            lambda: to_python(COMPLEX_EXPR),
            n,
        )
    )

    # 15. IR export
    results.append(
        bench(
            "spec.to_ir()",
            lambda: COMPLEX_SPEC.to_ir(),
            n_large,
        )
    )
    results.append(
        bench(
            "spec.to_ir_json()",
            lambda: COMPLEX_SPEC.to_ir_json(),
            n_large,
        )
    )

    # ── JSON backend comparison ────────────────────────────────────────
    import json as stdlib_json

    from k3c.json import backend
    from k3c.json import dumps as k3c_dumps

    json_data = {"state": large_state, "event": {"type": "A"}, "prev": "hash"}

    results.append(
        bench(
            f"json.dumps(large) [{backend()}]",
            lambda: k3c_dumps(json_data),
            n,
        )
    )
    results.append(
        bench(
            "json.dumps(large) [stdlib]",
            lambda: stdlib_json.dumps(json_data, sort_keys=True, default=str).encode(),
            n,
        )
    )

    return results


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    quick = "--quick" in sys.argv
    json_out = "--json" in sys.argv

    if not json_out:
        print(f"k3c Benchmarks {'(quick mode)' if quick else ''}")
        print(f"{'=' * 80}")

    results = run_benchmarks(quick=quick)

    if json_out:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        for r in results:
            print(r)
        print(f"\n{'=' * 80}")
        print(f"Total benchmarks: {len(results)}")

        # Summary stats
        fastest = min(results, key=lambda r: r.per_op_us)
        slowest = max(results, key=lambda r: r.per_op_us)
        print(f"Fastest: {fastest.name} ({fastest.per_op_us:.1f} us/op)")
        print(f"Slowest: {slowest.name} ({slowest.per_op_us:.1f} us/op)")


if __name__ == "__main__":
    main()
    print(r)
    print(f"\n{'=' * 80}")
    print(f"Total benchmarks: {len(results)}")

    # Summary stats
    fastest = min(results, key=lambda r: r.per_op_us)
    slowest = max(results, key=lambda r: r.per_op_us)
    print(f"Fastest: {fastest.name} ({fastest.per_op_us:.1f} us/op)")
    print(f"Slowest: {slowest.name} ({slowest.per_op_us:.1f} us/op)")


if __name__ == "__main__":
    main()
