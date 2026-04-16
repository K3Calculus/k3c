#!/usr/bin/env python3
# examples/ssim/ssim_parallel.py
"""
Parallel SSIM parser -- carrier-block-level processing with parallel_reduce.

Architecture:
    1. Sequential scan identifies carrier block boundaries (byte offsets)
    2. Each carrier block gets a sliced Spec via spec.slice()
    3. All blocks processed in parallel via parallel_reduce()
    4. Results merged deterministically

Usage:
    uv run python examples/ssim/ssim_parallel.py <file> [--workers N]
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from k3c import Ok, parallel_reduce, ChunkSource

from ssim_extractors import RECORD_WIDTH, decode_record
from ssim_spec import INITIAL_STATE, ssim_spec
from ssim_system import ssim_transition

SAMPLE_DIR = Path(__file__).parent / "specs-json" / "sampledata"


# -- Carrier block boundary ----------------------------------------------------


@dataclass
class CarrierBlock:
    """A carrier block boundary found during the index scan."""

    airline: str
    time_mode: str
    rt2_serial: int
    start_offset: int
    end_offset: int = -1
    record_count: int = 0


# -- Index scan ----------------------------------------------------------------


def index_carrier_blocks(path: str) -> tuple[list[CarrierBlock], int]:
    """Single-pass byte-offset scan for carrier block boundaries."""
    blocks: list[CarrierBlock] = []
    current: CarrierBlock | None = None
    total_lines = 0
    records_in_block = 0

    with open(path, "rb") as f:
        while True:
            offset = f.tell()
            raw = f.readline()
            if not raw:
                break
            line = raw.rstrip(b"\r\n")
            if len(line) < RECORD_WIDTH:
                continue
            total_lines += 1

            rt = line[0]
            if rt == ord("2"):
                airline = line[2:5].decode("ascii", errors="replace")
                time_mode = chr(line[1])
                serial = int(line[194:200].decode("ascii", errors="replace"))
                current = CarrierBlock(
                    airline=airline,
                    time_mode=time_mode,
                    rt2_serial=serial,
                    start_offset=offset,
                )
                records_in_block = 1
            elif rt == ord("5") and current is not None:
                current.end_offset = f.tell()
                current.record_count = records_in_block + 1
                blocks.append(current)
                current = None
                records_in_block = 0
            elif current is not None:
                records_in_block += 1

    return blocks, total_lines


# -- Chunk reader (top-level for pickling) -------------------------------------


def _read_chunk_from_disk(
    path: str, start_offset: int, end_offset: int
) -> list[dict[str, object]]:
    """Read and decode a byte range from an SSIM file."""
    events: list[dict[str, object]] = []
    with open(path, "rb") as f:
        f.seek(start_offset)
        while f.tell() < end_offset:
            raw = f.readline()
            if not raw:
                break
            line = raw.rstrip(b"\r\n")
            if len(line) < RECORD_WIDTH:
                continue
            event = decode_record(line)
            if event is not None:
                events.append(event)
    return events


# -- Parallel carrier-block processing -----------------------------------------


def parallel_process(
    path: str,
    *,
    workers: int = 4,
    verbose: bool = False,
) -> dict:
    """Parse an SSIM file with parallel carrier-block processing.

    1. Index scan: find carrier block byte boundaries
    2. Build sliced specs per carrier block via spec.slice()
    3. parallel_reduce() processes all blocks (parallel or sequential)
    4. Results merged deterministically
    """
    t0 = time.perf_counter()

    # -- Index scan --------------------------------------------------------
    t_index = time.perf_counter()
    blocks, total_lines = index_carrier_blocks(path)
    index_ms = (time.perf_counter() - t_index) * 1000

    if verbose:
        print(
            f"  Indexed {len(blocks)} carrier blocks from {total_lines:,} lines in {index_ms:.0f}ms"
        )
        for b in blocks[:10]:
            print(
                f"    {b.airline.strip():>3}: "
                f"offset {b.start_offset:>12,}-{b.end_offset:>12,} "
                f"({b.record_count:>8,} records)"
            )
        if len(blocks) > 10:
            print(f"    ...and {len(blocks) - 10} more")

    if not blocks:
        return {"error": "No carrier blocks found", "lines": total_lines}

    # -- Build sliced specs and chunks -------------------------------------
    specs = []
    chunks: list[list[dict[str, object]] | ChunkSource] = []

    for block in blocks:
        from_state = {
            **INITIAL_STATE,
            "phase": "AFTER_RT1",
            "serial": block.rt2_serial - 1,
        }
        chunk_spec = ssim_spec.slice(from_state=from_state)
        specs.append(chunk_spec)

        # Materialize events for this block
        chunk_events = _read_chunk_from_disk(path, block.start_offset, block.end_offset)
        chunks.append(chunk_events)

    # -- parallel_reduce ---------------------------------------------------
    t_par = time.perf_counter()
    result = parallel_reduce(
        transition=ssim_transition,
        specs=specs,
        chunks=chunks,
        workers=workers,
        hash_fn="blake3",
    )
    par_ms = (time.perf_counter() - t_par) * 1000
    total_s = time.perf_counter() - t0

    # -- Collect results ---------------------------------------------------
    total_flights = 0
    total_segments = 0
    carriers_done = 0

    for chunk_result in result.results:
        if isinstance(chunk_result.final, Ok):
            state = chunk_result.final.state
            counts = state.get("counts", {})
            total_flights += counts.get("RT3", 0)
            total_segments += counts.get("RT4", 0)
            if state.get("phase") in ("END", "AFTER_RT5_CONTINUE"):
                carriers_done += 1

    total_records = sum(b.record_count for b in blocks)
    rps = total_records / total_s if total_s > 0 else 0

    summary = {
        "file": path,
        "total_lines": total_lines,
        "carrier_blocks": len(blocks),
        "total_records": total_records,
        "flights": total_flights,
        "segments": total_segments,
        "carriers_completed": carriers_done,
        "violations": len(result.violations),
        "passed": result.passed,
        "workers": workers,
        "index_ms": round(index_ms),
        "parallel_ms": round(par_ms),
        "total_seconds": round(total_s, 2),
        "records_per_second": round(rps),
    }

    if verbose:
        print("\n  --- Results ---")
        print(f"  Records:     {total_records:>12,}")
        print(f"  Flights:     {total_flights:>12,}")
        print(f"  Segments:    {total_segments:>12,}")
        print(f"  Carriers:    {carriers_done:>12,}")
        print(f"  Violations:  {len(result.violations):>12,}")
        print(f"  Workers:     {workers:>12,}")
        print(f"  Index:       {index_ms:>12,.0f} ms")
        print(f"  Processing:  {par_ms:>12,.0f} ms")
        print(f"  Total:       {total_s:>12,.2f} s")
        print(f"  Throughput:  {rps:>12,.0f} records/s")

        if result.violations:
            print("\n  Violations:")
            for chunk_idx, violated in result.violations:
                block = blocks[chunk_idx]
                print(
                    f"    Chunk {chunk_idx} ({block.airline.strip()}): {violated.why.message}"
                )

    return summary


# -- Main ----------------------------------------------------------------------


def main() -> None:
    args = sys.argv[1:]
    workers = 4
    files: list[str] = []

    i = 0
    while i < len(args):
        if args[i] == "--workers" and i + 1 < len(args):
            workers = int(args[i + 1])
            i += 2
        else:
            files.append(args[i])
            i += 1

    if not files:
        candidates = [
            "sample.ssim",
            "complex-multi-carrier.ssim",
            "Multi Carrier/EI/EI.ssim",
        ]
        files = [str(SAMPLE_DIR / f) for f in candidates if (SAMPLE_DIR / f).exists()]

    print("=" * 70)
    print(f"SSIM Parallel Parser -- k3c + blake3 ({workers} workers)")
    print("=" * 70)

    for path in files:
        p = Path(path)
        if not p.exists():
            print(f"\n--- {p.name} (not found) ---")
            continue

        size_mb = p.stat().st_size / (1024 * 1024)
        print(f"\n--- {p.name} ({size_mb:.1f} MB) ---")
        parallel_process(path, workers=workers, verbose=True)

    print(f"\n{'=' * 70}")
    print("Done.")


if __name__ == "__main__":
    main()
