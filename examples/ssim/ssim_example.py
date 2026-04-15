#!/usr/bin/env python3
# examples/ssim/ssim_example.py
"""
SSIM Chapter 7 parser — end-to-end demo with k3c.

Parses real SSIM files through a k3c Universe with:
  - DFA guard enforcement (structural validation)
  - Field-level validation (from JSON-LD specs)
  - Serial continuity invariant (integrity)
  - Streaming outputs: complete flights (RT3 + nested RT4 segments)
  - blake3 hashing for performance

Usage:
    uv run python examples/ssim/ssim_example.py
    uv run python examples/ssim/ssim_example.py --json     # output parsed JSON
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from k3c import Impossible, Ok, Violated, universe

from ssim_extractors import records_from_file
from ssim_spec import build_ssim_spec
from ssim_system import SSIMSystem

SAMPLE_DIR = Path(__file__).parent / "specs-json" / "sampledata"


def process_file(
    path: str, *, verbose: bool = False, json_output: bool = False
) -> dict | None:
    """Parse an SSIM file through a k3c Universe with streaming output."""
    spec = build_ssim_spec()
    u = universe(SSIMSystem(), spec, hash_fn="blake3")

    header: dict | None = None
    carrier_records: list[dict] = []
    flights: list[dict] = []
    carrier_completions: list[dict] = []
    impossible_count = 0
    record_count = 0

    t0 = time.perf_counter()

    for result in u.stream(records_from_file(path)):
        record_count += 1

        match result:
            case Ok(outputs=outputs):
                for out in outputs:
                    otype = out.get("output_type")
                    if otype == "Header":
                        header = out
                        if verbose:
                            print(
                                f"  Header: serial={out['data_set_serial_number']} "
                                f"seasons={out['number_of_seasons']!r}"
                            )
                    elif otype == "Carrier":
                        carrier_records.append(out)
                        if verbose:
                            print(
                                f"  Carrier: "
                                f"{str(out.get('airline_designator','')).strip()} "
                                f"time_mode={out['time_mode']} "
                                f"{out['period_of_validity_from']}"
                                f"-{out['period_of_validity_to']} "
                                f"status={out['schedule_status']}"
                            )
                    elif otype == "Flights":
                        flights.append(out)
                        if verbose and len(flights) <= 3:
                            segs = out.get("segments", [])
                            print(
                                f"  Flight: "
                                f"{str(out.get('airline_designator','')).strip()}"
                                f"{str(out.get('flight_number','')).strip()} "
                                f"{out.get('departure_station')}"
                                f"->{out.get('arrival_station')} "
                                f"({out.get('aircraft_type')}) "
                                f"[{len(segs)} segments]"
                            )
                            for seg in segs[:2]:
                                print(
                                    f"    DEI {seg.get('data_element_identifier')}: "
                                    f"{seg.get('board_point')}->{seg.get('off_point')} "
                                    f"{str(seg.get('segment_data', '')).strip()[:40]}"
                                )
                    elif otype == "CarrierComplete":
                        carrier_completions.append(out)
                        if verbose:
                            print(
                                f"  Carrier done: "
                                f"{str(out.get('airline_designator','')).strip()} "
                                f"({out['flight_count']} flights, "
                                f"{out['segment_count']} segments, "
                                f"cont={out['continuation_end_code']})"
                            )

            case Impossible(why=why):
                impossible_count += 1
                if verbose:
                    print(f"  SKIP: {why.message}")

            case Violated(why=why):
                elapsed = time.perf_counter() - t0
                print(f"  VIOLATED at record {record_count}: {why.message}")
                print(f"  Processed {record_count} records in {elapsed:.2f}s")
                return None

    elapsed = time.perf_counter() - t0
    rps = record_count / elapsed if elapsed > 0 else 0

    state = u.state
    val_errors = state.get("validation_errors", [])

    seg_total = sum(len(f.get("segments", [])) for f in flights)

    if not json_output:
        print(f"  Records:    {record_count:>10,}")
        print(f"  Flights:    {len(flights):>10,}")
        print(f"  Segments:   {seg_total:>10,}")
        print(f"  Carriers:   {len(carrier_records):>10,}")
        print(f"  Skipped:    {impossible_count:>10,}")
        print(f"  Val errors: {len(val_errors):>10,}")
        print(f"  Phase:      {state.get('phase')!s:>10}")
        print(f"  Time:       {elapsed:>10.2f}s")
        print(f"  Throughput: {rps:>10,.0f} records/s")

    return {
        "header": header,
        "carriers": carrier_records,
        "flights": flights,
        "carrier_completions": carrier_completions,
        "summary": {
            "total_records": record_count,
            "record_counts": dict(state.get("counts", {})),  # type: ignore[arg-type]
            "phase": state.get("phase"),
            "flights": len(flights),
            "segments": seg_total,
            "carriers": len(carrier_records),
            "skipped": impossible_count,
            "validation_errors": list(val_errors),  # type: ignore[arg-type]
            "time_seconds": round(elapsed, 3),
            "records_per_second": round(rps),
        },
    }


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    json_mode = "--json" in sys.argv

    if json_mode:
        # JSON mode: parse sample.ssim, output full parsed JSON
        sample = SAMPLE_DIR / "sample.ssim"
        if not sample.exists():
            print(f"File not found: {sample}", file=sys.stderr)
            sys.exit(1)
        result = process_file(str(sample), json_output=True)
        if result:
            print(json.dumps(result, indent=2, default=str))
        return

    files: list[tuple[str, bool]] = [
        ("sample.ssim", True),
    ]

    large_files = [
        "complex-multi-carrier.ssim",
        "Multi Carrier/EI/EI.ssim",
    ]
    for lf in large_files:
        if (SAMPLE_DIR / lf).exists():
            files.append((lf, False))

    print("=" * 70)
    print("SSIM Chapter 7 Parser — k3c + blake3")
    print("=" * 70)

    for filename, verbose in files:
        path = SAMPLE_DIR / filename
        if not path.exists():
            print(f"\n--- {filename} (not found, skipping) ---")
            continue

        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"\n--- {filename} ({size_mb:.1f} MB) ---")
        process_file(str(path), verbose=verbose)

    print(f"\n{'=' * 70}")
    print("Done.")


if __name__ == "__main__":
    main()
