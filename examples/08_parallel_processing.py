"""
Example 08: SSIM-Style Parallel Processing — Unified spec, slice, parallel_reduce.

Models the canonical SSIM pattern from the reference doc:
  1. One unified spec covering ALL record types with full DFA + invariants
  2. Sequential processing of header (RT1 -> RT2) to establish DFA state
  3. spec.slice() derives per-chunk specs at the DFA boundary
  4. parallel_reduce() processes RT3 chunks independently
  5. Sequential trailer (RT5) validation using unified spec

This is the pattern for any partitionable domain:
  unified spec -> sequential header -> slice -> parallel chunks -> sequential trailer

Demonstrates: unified spec, spec.slice(), parallel_reduce(), reduce, DFA checkpoints.
"""

from k3c import (
    Spec,
    universe,
    parallel_reduce,
    Ok,
    Always,
    Compare,
    CmpOp,
    Field,
    Var,
    EventField,
    Before,
    After,
    LStr,
    With,
)


# ── Unified Spec — the single source of truth ──────────────────────────────
# Covers all 5 record types. Cross-record invariants live here.

unified_spec = (
    Spec("ssim_ch7")
    .state0(
        {
            "phase": "START",
            "serial": 0,
            "carrier": None,
            "record_count": 0,
            "leg_count": 0,
        }
    )
    # ── Protocol DFA — all record types ordered ─────────────────────────
    .permit(
        "rt1_from_start",
        when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("START")),
        on="RT1",
    )
    .permit(
        "rt2_from_header",
        when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("HEADER")),
        on="RT2",
    )
    .permit(
        "rt3_in_carrier",
        when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_CARRIER")),
        on="RT3",
    )
    .permit(
        "rt5_end",
        when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_CARRIER")),
        on="RT5",
    )
    # ── U.require — advance spec_state at DFA transitions ──────────────
    .require(
        "header_seen",
        on="RT1",
        transition=With(Var("spec_state"), (("phase", LStr("HEADER")),)),
    )
    .require(
        "open_carrier",
        on="RT2",
        transition=With(
            Var("spec_state"),
            (
                ("phase", LStr("IN_CARRIER")),
                ("carrier", EventField("airline")),
            ),
        ),
    )
    # ── Cross-record invariants — ONLY expressible in unified spec ──────
    # Serial continuity: serial always increases
    .maintain(
        "serial_continuity",
        expr=Always(Compare(CmpOp.GE, After("serial"), Before("serial"))),
    )
    # Record count always increases
    .maintain(
        "count_monotone",
        expr=Always(Compare(CmpOp.GE, After("record_count"), Before("record_count"))),
    )
    # Projections
    .project(
        "progress",
        lambda s: {
            "phase": s["phase"],
            "serial": s["serial"],
            "carrier": s["carrier"],
            "records": s["record_count"],
            "legs": s["leg_count"],
        },
    )
    .build()
)


# ── System ──────────────────────────────────────────────────────────────────


class SsimParser:
    def transition(self, state, event):
        match event.get("type"):
            case "RT1":
                return {
                    **state,
                    "phase": "HEADER",
                    "serial": event.get("serial", state["serial"] + 1),
                    "record_count": state["record_count"] + 1,
                }
            case "RT2":
                return {
                    **state,
                    "phase": "IN_CARRIER",
                    "carrier": event.get("airline"),
                    "serial": event.get("serial", state["serial"] + 1),
                    "record_count": state["record_count"] + 1,
                }
            case "RT3":
                return {
                    **state,
                    "serial": event.get("serial", state["serial"] + 1),
                    "record_count": state["record_count"] + 1,
                    "leg_count": state["leg_count"] + 1,
                }
            case "RT5":
                return {
                    **state,
                    "phase": "COMPLETE",
                    "serial": event.get("serial", state["serial"] + 1),
                    "record_count": state["record_count"] + 1,
                }
            case _:
                return state


# ── Usage ───────────────────────────────────────────────────────────────────


def main():
    # ── Simulate an SSIM file ────────────────────────────────────────────
    header = [
        {"type": "RT1", "serial": 1},
        {"type": "RT2", "serial": 2, "airline": "BA"},
    ]

    # 40 RT3 leg records
    rt3_records = [
        {"type": "RT3", "serial": 3 + i, "flight": f"BA{100 + i}"} for i in range(40)
    ]

    trailer = [
        {"type": "RT5", "serial": 43, "record_count": 43},
    ]

    # ═══════════════════════════════════════════════════════════════════════
    # MODE 1: Sequential — full DFA audit trail, KC-5 compliance
    # ═══════════════════════════════════════════════════════════════════════
    print("=== MODE 1: Sequential (full DFA) ===")
    u = universe(SsimParser(), unified_spec)

    r = u.reduce(header + rt3_records + trailer)
    assert isinstance(r, Ok)
    print(f"  Result: {type(r).__name__}")
    print(f"  Progress: {r.projections['progress']}")
    print(f"  Step hash: {r.step_hash[:16]}...")

    # ═══════════════════════════════════════════════════════════════════════
    # MODE 2: Parallel — same spec, derived slices, N workers
    # ═══════════════════════════════════════════════════════════════════════
    print("\n=== MODE 2: Parallel (4 workers) ===")

    # Step 1: Process header SEQUENTIALLY to establish DFA state
    u_header = universe(SsimParser(), unified_spec)
    r_header = u_header.reduce(header)
    assert isinstance(r_header, Ok)
    carrier_ctx = u_header.state
    print(
        f"  Header processed: phase={carrier_ctx['phase']}, carrier={carrier_ctx['carrier']}"
    )

    # Step 2: Partition RT3 records into chunks
    n_workers = 4
    chunk_size = len(rt3_records) // n_workers
    chunks = [
        rt3_records[i : i + chunk_size] for i in range(0, len(rt3_records), chunk_size)
    ]
    print(
        f"  Partitioned {len(rt3_records)} records into {len(chunks)} chunks of {chunk_size}"
    )

    # Step 3: Derive specs from unified spec at the DFA boundary
    # Each chunk starts from IN_CARRIER with its own serial start
    specs = []
    for chunk in chunks:
        start_serial = chunk[0]["serial"] - 1
        specs.append(
            unified_spec.slice(
                from_state={
                    "phase": "IN_CARRIER",
                    "serial": start_serial,
                    "carrier": carrier_ctx["carrier"],
                    "record_count": 0,
                    "leg_count": 0,
                },
                events=["RT3"],  # only RT3 permits active
            )
        )

    # Verify: derived spec has same maintains as unified
    print(f"  Unified maintains: {len(unified_spec.maintains)}")
    print(f"  Derived maintains: {len(specs[0].maintains)} (same causal laws)")
    assert specs[0].maintains == unified_spec.maintains

    # Verify: derived spec has filtered permits (only RT3)
    print(f"  Unified permits: {len(unified_spec.permits)}")
    print(f"  Derived permits: {len(specs[0].permits)} (only RT3)")

    # Step 4: Process chunks in parallel
    result = parallel_reduce(SsimParser(), specs, chunks, workers=1)
    print(f"\n  Parallel result: passed={result.passed}")
    print(f"  Total processed: {result.total_processed}")
    print(f"  Violations: {len(result.violations)}")

    # Step 5: Verify per-chunk results
    for i, chunk_result in enumerate(result.results):
        assert isinstance(chunk_result.final, Ok)
        s = chunk_result.final.state
        print(f"  Chunk {i}: legs={s['leg_count']}, serial={s['serial']}")

    # Step 6: Process trailer SEQUENTIALLY with unified spec
    # Resume from last chunk's serial
    max_serial = max(
        r.final.state["serial"] for r in result.results if isinstance(r.final, Ok)
    )
    total_records = sum(
        r.final.state["record_count"] for r in result.results if isinstance(r.final, Ok)
    )

    trailer_spec = unified_spec.slice(
        from_state={
            "phase": "IN_CARRIER",
            "serial": max_serial,
            "carrier": carrier_ctx["carrier"],
            "record_count": total_records + len(header),
            "leg_count": sum(
                r.final.state["leg_count"]
                for r in result.results
                if isinstance(r.final, Ok)
            ),
        },
        events=["RT5"],
    )
    u_trailer = universe(SsimParser(), trailer_spec)
    r_trailer = u_trailer.apply(trailer[0])
    assert isinstance(r_trailer, Ok)
    print(
        f"\n  Trailer: phase={u_trailer.state['phase']}, total_records={u_trailer.state['record_count']}"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # Verify: both modes produce consistent results
    # ═══════════════════════════════════════════════════════════════════════
    print("\n=== Verification ===")
    total_legs = sum(
        r.final.state["leg_count"] for r in result.results if isinstance(r.final, Ok)
    )
    print(f"  Sequential legs: {u.state['leg_count']}")
    print(f"  Parallel legs: {total_legs}")
    assert u.state["leg_count"] == total_legs

    print("\nSSIM parallel processing example passed.")


if __name__ == "__main__":
    main()
