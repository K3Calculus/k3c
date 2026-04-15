#!/usr/bin/env python3
# examples/ssim/ssim_bench.py
"""
SSIM parsing benchmarks — measures throughput of each pipeline stage.

Usage:
    uv run python examples/ssim/ssim_bench.py
    uv run python examples/ssim/ssim_bench.py --quick

Measures:
    1. Raw decode throughput (bytes → dict)
    2. apply() throughput (single record through full pipeline)
    3. stream() throughput (end-to-end with outputs)
    4. Comparison: blake3 vs sha256 vs blake2b
    5. Real file throughput on available sample data
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from k3c import Ok, universe
from k3c.spec.result import Impossible

from ssim_extractors import (
    RECORD_WIDTH,
    decode_record,
    extract_rt1,
    extract_rt2,
    extract_rt3,
    extract_rt4,
    extract_rt5,
    records_from_file,
)
from ssim_spec import build_ssim_spec
from ssim_system import SSIMSystem

SAMPLE_DIR = Path(__file__).parent / "specs-json" / "sampledata"


# ── Harness ─────────────────────────────────────────────────────────────────


@dataclass
class BenchResult:
    name: str
    iterations: int
    total_ms: float
    ops_per_sec: float
    per_op_us: float

    def __str__(self) -> str:
        return (
            f"  {self.name:<45} "
            f"{self.ops_per_sec:>12,.0f} ops/s  "
            f"{self.per_op_us:>8.1f} us/op  "
            f"({self.iterations:,} iters, {self.total_ms:.0f}ms)"
        )


def bench(name: str, fn, iterations: int) -> BenchResult:
    # Warmup
    for _ in range(min(100, iterations // 10)):
        fn()

    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - start

    total_ms = elapsed * 1000
    ops = iterations / elapsed if elapsed > 0 else 0
    per = (elapsed / iterations) * 1_000_000 if iterations > 0 else 0

    return BenchResult(name, iterations, total_ms, ops, per)


def bench_file(name: str, path: str, hash_fn: str = "blake3") -> BenchResult:
    """Benchmark end-to-end processing of an SSIM file."""
    spec = build_ssim_spec()
    u = universe(SSIMSystem(), spec, hash_fn=hash_fn)

    start = time.perf_counter()
    count = 0
    for result in u.stream(records_from_file(path)):
        count += 1
    elapsed = time.perf_counter() - start

    total_ms = elapsed * 1000
    ops = count / elapsed if elapsed > 0 else 0
    per = (elapsed / count) * 1_000_000 if count > 0 else 0

    return BenchResult(name, count, total_ms, ops, per)


# ── Fixtures ────────────────────────────────────────────────────────────────

# Pre-built raw records for micro-benchmarks
RAW_RT1 = (
    b"1AIRLINE STANDARD SCHEDULE DATA SET"
    + b" " * 156
    + b"001000001"
)

RAW_RT2 = (
    b"2UXX "
    + b" " * 5
    + b"   "
    + b" "
    + b"07DEC2403MAR2503DEC24"
    + b"Created by k3c bench        "
    + b" " * 7
    + b"P"
)
# Pad RT2 to 200 bytes
RAW_RT2 = RAW_RT2 + b" " * (194 - len(RAW_RT2)) + b"000002"

RAW_RT3 = (
    b"3 XX  045010"
    + b"1J"
    + b"07DEC2402FEB25"
    + b"1234567"
    + b" "
    + b"BNE"
    + b"2350"
    + b"2350"
    + b"+1000"
    + b"I "
    + b"DPS"
    + b"0600"
    + b"0600"
    + b"+0800"
    + b"I "
    + b"7M8"
)
RAW_RT3 = RAW_RT3 + b" " * (194 - len(RAW_RT3)) + b"000003"

RAW_RT4 = (
    b"4 XX  045010"
    + b"1J"
    + b" " * 14
    + b"AB"
    + b"106"
    + b"BNE"
    + b"DPS"
    + b"JCDZYBWHKLREONVPQTISFUMAGX"
)
RAW_RT4 = RAW_RT4 + b" " * (194 - len(RAW_RT4)) + b"000004"

RAW_RT5 = (
    b"5 XX "
    + b"03DEC24"
)
RAW_RT5 = RAW_RT5 + b" " * (187 - len(RAW_RT5)) + b"000989" + b"E" + b"000990"

# Ensure all are exactly 200 bytes
assert len(RAW_RT1) == 200, f"RT1 len={len(RAW_RT1)}"
assert len(RAW_RT2) == 200, f"RT2 len={len(RAW_RT2)}"
assert len(RAW_RT3) == 200, f"RT3 len={len(RAW_RT3)}"
assert len(RAW_RT4) == 200, f"RT4 len={len(RAW_RT4)}"
assert len(RAW_RT5) == 200, f"RT5 len={len(RAW_RT5)}"


# ── Benchmarks ──────────────────────────────────────────────────────────────


def run_benchmarks(quick: bool = False) -> list[BenchResult]:
    results: list[BenchResult] = []
    n = 1_000 if quick else 10_000
    n_small = 100 if quick else 1_000

    # ── 1. Decode throughput ────────────────────────────────────────────
    results.append(bench("decode(RT1)", lambda: extract_rt1(RAW_RT1), n))
    results.append(bench("decode(RT2)", lambda: extract_rt2(RAW_RT2), n))
    results.append(bench("decode(RT3)", lambda: extract_rt3(RAW_RT3), n))
    results.append(bench("decode(RT4)", lambda: extract_rt4(RAW_RT4), n))
    results.append(bench("decode(RT5)", lambda: extract_rt5(RAW_RT5), n))
    results.append(bench("decode(dispatch)", lambda: decode_record(RAW_RT3), n))

    # ── 2. apply() throughput per record type ───────────────────────────
    # Single apply() — must be in correct DFA state

    # RT1 apply
    def bench_apply_rt1():
        spec = build_ssim_spec()
        u = universe(SSIMSystem(), spec, hash_fn="blake3")
        u.apply(extract_rt1(RAW_RT1))

    results.append(bench("apply(RT1, blake3)", bench_apply_rt1, n_small))

    # RT3 apply (set up state first, then measure RT3)
    def bench_apply_rt3():
        spec = build_ssim_spec()
        u = universe(SSIMSystem(), spec, hash_fn="blake3")
        u.apply(extract_rt1(RAW_RT1))
        u.apply(extract_rt2(RAW_RT2))
        # Measure RT3
        u.apply(extract_rt3(RAW_RT3))

    results.append(bench("apply(RT3, blake3)", bench_apply_rt3, n_small))

    # Steady-state: repeated RT3 apply (amortized setup)
    spec = build_ssim_spec()
    u_steady = universe(SSIMSystem(), spec, hash_fn="blake3")
    u_steady.apply(extract_rt1(RAW_RT1))
    u_steady.apply(extract_rt2(RAW_RT2))
    rt3_event = extract_rt3(RAW_RT3)

    # We need unique serials for each apply, so generate events
    def make_rt3_events(count: int) -> list[dict]:
        events = []
        for i in range(count):
            e = dict(rt3_event)
            e["record_serial_number"] = 3 + i
            events.append(e)
        return events

    rt3_batch = make_rt3_events(n)

    def bench_steady_rt3():
        nonlocal u_steady
        spec = build_ssim_spec()
        u_steady = universe(SSIMSystem(), spec, hash_fn="blake3")
        u_steady.apply(extract_rt1(RAW_RT1))
        u_steady.apply(extract_rt2(RAW_RT2))
        for e in rt3_batch[:100]:
            u_steady.apply(e)

    results.append(
        bench("apply(RT3x100, steady, blake3)", bench_steady_rt3, n_small)
    )

    # ── 3. Hash function comparison ─────────────────────────────────────
    for hf in ["blake3", "blake2b", "sha256"]:
        def bench_hash(hash_fn=hf):
            spec = build_ssim_spec()
            u = universe(SSIMSystem(), spec, hash_fn=hash_fn)
            u.apply(extract_rt1(RAW_RT1))
            u.apply(extract_rt2(RAW_RT2))
            batch = make_rt3_events(50)
            for e in batch:
                u.apply(e)

        results.append(bench(f"apply(RT3x50, {hf})", bench_hash, n_small))

    # ── 4. stream() throughput with outputs ─────────────────────────────
    def bench_stream_100():
        spec = build_ssim_spec()
        u = universe(SSIMSystem(), spec, hash_fn="blake3")
        events = [extract_rt1(RAW_RT1), extract_rt2(RAW_RT2)]
        events.extend(make_rt3_events(100))
        for _ in u.stream(iter(events)):
            pass

    results.append(bench("stream(102 events, blake3)", bench_stream_100, n_small))

    # ── 5. reduce_all() throughput ──────────────────────────────────────
    def bench_reduce_500():
        spec = build_ssim_spec()
        u = universe(SSIMSystem(), spec, hash_fn="blake3")
        events = [extract_rt1(RAW_RT1), extract_rt2(RAW_RT2)]
        events.extend(make_rt3_events(498))
        u.reduce_all(events)

    results.append(bench("reduce_all(500 events, blake3)", bench_reduce_500, n_small))

    # ── 6. Validation overhead ────────────────────────────────────────────
    from ssim_spec import validate_event

    rt3_ev = extract_rt3(RAW_RT3)
    rt4_ev = extract_rt4(RAW_RT4)
    results.append(bench("validate(RT3)", lambda: validate_event(rt3_ev), n))
    results.append(bench("validate(RT4)", lambda: validate_event(rt4_ev), n))

    # ── 7. Cost breakdown: decode + validate + apply ────────────────────
    def bench_decode_only():
        for _ in range(100):
            extract_rt3(RAW_RT3)

    def bench_decode_validate():
        for _ in range(100):
            e = extract_rt3(RAW_RT3)
            validate_event(e)

    results.append(bench("decode_only(RT3x100)", bench_decode_only, n_small))
    results.append(bench("decode+validate(RT3x100)", bench_decode_validate, n_small))

    # ── 8. Real file benchmarks ─────────────────────────────────────────
    sample = SAMPLE_DIR / "sample.ssim"
    if sample.exists():
        results.append(bench_file("file(sample.ssim, blake3)", str(sample), "blake3"))
        results.append(bench_file("file(sample.ssim, sha256)", str(sample), "sha256"))

    if not quick:
        ei = SAMPLE_DIR / "Multi Carrier" / "EI" / "EI.ssim"
        if ei.exists():
            results.append(bench_file("file(EI.ssim, blake3)", str(ei), "blake3"))

    # ── 9. Parallel benchmarks ──────────────────────────────────────────
    from ssim_parallel import parallel_process

    multi = SAMPLE_DIR / "complex-multi-carrier.ssim"
    if multi.exists():
        for w in [1, 2, 4]:
            start = time.perf_counter()
            summary = parallel_process(str(multi), workers=w)
            elapsed = time.perf_counter() - start
            total = summary.get("total_records", 0)
            ops = total / elapsed if elapsed > 0 else 0
            per = (elapsed / total) * 1_000_000 if total > 0 else 0
            results.append(
                BenchResult(
                    f"parallel(multi-carrier, {w}w)",
                    total,
                    elapsed * 1000,
                    ops,
                    per,
                )
            )

    return results


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    quick = "--quick" in sys.argv

    print(f"SSIM Benchmarks {'(quick mode)' if quick else ''}")
    print("=" * 90)

    results = run_benchmarks(quick=quick)

    for r in results:
        print(r)

    print(f"\n{'=' * 90}")
    print(f"Total benchmarks: {len(results)}")

    fastest = min(results, key=lambda r: r.per_op_us)
    slowest = max(results, key=lambda r: r.per_op_us)
    print(f"Fastest: {fastest.name} ({fastest.per_op_us:.1f} us/op)")
    print(f"Slowest: {slowest.name} ({slowest.per_op_us:.1f} us/op)")

    # Per-record cost summary for SSIM pipeline
    file_benches = [r for r in results if r.name.startswith("file(")]
    if file_benches:
        print(f"\n--- SSIM Pipeline Cost ---")
        for fb in file_benches:
            print(f"  {fb.name}: {fb.per_op_us:.1f} us/record ({fb.ops_per_sec:,.0f} records/s)")


if __name__ == "__main__":
    main()
