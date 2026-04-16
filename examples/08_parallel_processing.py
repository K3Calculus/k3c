"""
Example 08: SSIM-Style Parallel Processing -- parallel_reduce with spec.slice().

Models the canonical SSIM pattern:
  1. One unified spec covering ALL record types with full DFA + invariants
  2. Sequential processing of header (RT1 -> RT2) to establish DFA state
  3. spec.slice() derives per-chunk specs at the DFA boundary
  4. parallel_reduce() processes RT3 chunks independently
  5. Sequential trailer (RT5) validation

Demonstrates: Spec.slice(), parallel_reduce, ChunkSource, ParallelReduceResult,
DFA checkpoints, unified spec -> derived specs.
"""

from k3c import (
    Always,
    Before,
    After,
    CmpOp,
    Compare,
    EmbeddedRuntime,
    EventField,
    Field,
    LStr,
    Maintain,
    Ok,
    Permit,
    Require,
    Spec,
    Universe,
    Var,
    With,
    parallel_reduce,
)


# -- Unified Spec -- the single source of truth --------------------------------

unified_spec = Spec(
    name="ssim_ch7",
    state0={
        "phase": "START",
        "serial": 0,
        "carrier": None,
        "record_count": 0,
        "leg_count": 0,
    },
    permits=(
        Permit(
            name="rt1_from_start",
            when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("START")),
            on="RT1",
        ),
        Permit(
            name="rt2_from_header",
            when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("HEADER")),
            on="RT2",
        ),
        Permit(
            name="rt3_in_carrier",
            when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_CARRIER")),
            on="RT3",
        ),
        Permit(
            name="rt5_end",
            when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_CARRIER")),
            on="RT5",
        ),
    ),
    requires=(
        Require(
            name="header_seen",
            on="RT1",
            transition=With(Var("spec_state"), (("phase", LStr("HEADER")),)),
        ),
        Require(
            name="open_carrier",
            on="RT2",
            transition=With(
                Var("spec_state"),
                (("phase", LStr("IN_CARRIER")), ("carrier", EventField("airline"))),
            ),
        ),
    ),
    maintains=(
        Maintain(
            name="serial_continuity",
            expr=Always(Compare(CmpOp.GE, After("serial"), Before("serial"))),
        ),
        Maintain(
            name="count_monotone",
            expr=Always(
                Compare(CmpOp.GE, After("record_count"), Before("record_count"))
            ),
        ),
    ),
)


# -- Transition function -------------------------------------------------------


def ssim_transition(state: dict, event: dict) -> dict:
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


# -- Usage ---------------------------------------------------------------------


def main():
    header = [
        {"type": "RT1", "serial": 1},
        {"type": "RT2", "serial": 2, "airline": "BA"},
    ]
    rt3_records = [
        {"type": "RT3", "serial": 3 + i, "flight": f"BA{100 + i}"} for i in range(40)
    ]
    trailer = [
        {"type": "RT5", "serial": 43, "record_count": 43},
    ]

    # =========================================================================
    # MODE 1: Sequential -- full DFA audit trail
    # =========================================================================
    print("=== MODE 1: Sequential (full DFA) ===")

    runtime = EmbeddedRuntime(
        spec=unified_spec,
        transition=ssim_transition,
        projection_hooks={
            "progress": lambda s, e, ctx: {
                "phase": s["phase"],
                "serial": s["serial"],
                "carrier": s["carrier"],
                "records": s["record_count"],
                "legs": s["leg_count"],
            },
        },
    )
    u = runtime.universe()

    r = u.reduce(header + rt3_records + trailer)
    assert isinstance(r, Ok)
    print(f"  Result: {type(r).__name__}")
    print(f"  Progress: {r.projections['progress']}")

    # =========================================================================
    # MODE 2: parallel_reduce -- same spec, derived slices
    # =========================================================================
    print("\n=== MODE 2: parallel_reduce (4 chunks) ===")

    # Step 1: Process header SEQUENTIALLY
    u_header = Universe(spec=unified_spec, transition=ssim_transition)
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
                events=["RT3"],
            )
        )

    print(f"  Unified maintains: {len(unified_spec.maintains)}")
    print(f"  Derived maintains: {len(specs[0].maintains)} (same causal laws)")
    assert specs[0].maintains == unified_spec.maintains

    # Step 4: parallel_reduce -- all chunks processed independently
    par_result = parallel_reduce(
        transition=ssim_transition,
        specs=specs,
        chunks=chunks,
        workers=n_workers,
    )

    print(f"\n  parallel_reduce result: passed={par_result.passed}")
    print(f"  Total processed: {par_result.total_processed}")
    print(f"  Violations: {len(par_result.violations)}")

    # Per-chunk results
    for i, state in enumerate(par_result.states):
        print(f"  Chunk {i}: legs={state['leg_count']}, serial={state['serial']}")

    total_legs = sum(s["leg_count"] for s in par_result.states)

    # Step 5: Process trailer SEQUENTIALLY
    max_serial = max(s["serial"] for s in par_result.states)
    total_records = sum(s["record_count"] for s in par_result.states)

    trailer_spec = unified_spec.slice(
        from_state={
            "phase": "IN_CARRIER",
            "serial": max_serial,
            "carrier": carrier_ctx["carrier"],
            "record_count": total_records + len(header),
            "leg_count": total_legs,
        },
        events=["RT5"],
    )
    u_trailer = Universe(spec=trailer_spec, transition=ssim_transition)
    r_trailer = u_trailer.apply(trailer[0])
    assert isinstance(r_trailer, Ok)
    print(
        f"\n  Trailer: phase={u_trailer.state['phase']}, total_records={u_trailer.state['record_count']}"
    )

    # =========================================================================
    # Verify: both modes produce consistent results
    # =========================================================================
    print("\n=== Verification ===")
    print(f"  Sequential legs: {u.state['leg_count']}")
    print(f"  Parallel legs: {total_legs}")
    assert u.state["leg_count"] == total_legs

    print("\nSSIM parallel processing example passed.")


if __name__ == "__main__":
    main()
