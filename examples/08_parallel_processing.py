"""08 — Parallel Processing with Error Streaming

Process N chunks in parallel, with errors streaming back to a callback in
the main process via the supervisor architecture.

Demonstrates:
- parallel_reduce(specs, chunks, workers, on_error=...)
- Spec.slice(from_state=..., relax=[...]) for sub-spec derivation
- StepError, ErrorAction (SKIP / ABORT_CHUNK / ABORT_ALL)
- The error universe pattern: workers stream errors → main process callback
"""

from __future__ import annotations

from k3c import (
    Always,
    E,
    ErrorAction,
    Maintain,
    Permit,
    S,
    Spec,
    StepError,
    Validate,
    k3,
    parallel_reduce,
)


# Base spec — counter with a per-event bound and an invariant
base_spec = Spec(
    name="counter",
    state0={"count": 0, "serial": 0},
    permits=(
        Permit(name="any_inc", on="Inc", when=k3(S.count >= 0)),
    ),
    validates=(
        # Reject Inc events with n > 100 — produces Violated
        Validate(
            name="reasonable_n",
            on="Inc",
            check=k3(E.n <= 100),
            field="n",
            constraint="<= 100",
        ),
    ),
    maintains=(
        Maintain(name="non_negative", expr=Always(k3(S.count >= 0))),
        Maintain(name="serial_continuity", expr=Always(k3(S.serial >= 0))),
    ),
)


def transition(state: dict, event: dict) -> dict:
    if event.get("type") == "Inc":
        n = event.get("n", 1)
        return {**state, "count": state["count"] + n, "serial": state["serial"] + 1}
    return state


def main() -> None:
    # 4 chunks, each starting from a different checkpoint.
    # Use slice(relax=...) to drop serial_continuity — sub-chunks would otherwise
    # fail because their state[serial] doesn't continue from the previous chunk.
    checkpoints = [
        {"count": 0,    "serial": 0},
        {"count": 100,  "serial": 1000},
        {"count": 200,  "serial": 2000},
        {"count": 300,  "serial": 3000},
    ]
    specs = [
        base_spec.slice(from_state=cp, relax=["serial_continuity"])
        for cp in checkpoints
    ]

    # 4 chunks of events, with one bad event in chunk 1
    chunks = [
        [{"type": "Inc", "n": 1} for _ in range(50)],
        [{"type": "Inc", "n": 1} for _ in range(20)] + [{"type": "Inc", "n": 9999}],
        [{"type": "Inc", "n": 1} for _ in range(30)],
        [{"type": "Inc", "n": 1} for _ in range(10)],
    ]

    # Error handler runs in the main process — full per-event flow control.
    def on_error(err: StepError) -> ErrorAction:
        # Decide: skip rejections, abort the chunk on actual violations.
        kind = "violation" if err.is_violation else "rejected"
        print(f"  [error] chunk={err.chunk_index} offset={err.offset} {kind}: {err.why.message}")
        return ErrorAction.ABORT_CHUNK if err.is_violation else ErrorAction.SKIP

    result = parallel_reduce(
        transition=transition,
        specs=specs,
        chunks=chunks,
        workers=4,
        on_error=on_error,
    )

    print(f"\nProcessed {result.total_processed} events across {len(chunks)} chunks")
    print(f"Errors: {len(result.errors)} ({len(result.violations)} violations, {len(result.impossible)} rejections)")
    print(f"Passed chunks: {sum(1 for cr in result.chunk_results if cr.passed)}/{len(chunks)}")

    print("\nFinal counts per chunk:")
    for cr in result.chunk_results:
        if cr.final_state:
            print(f"  chunk {cr.chunk_index}: count={cr.final_state['count']}  processed={cr.processed}")


if __name__ == "__main__":
    main()
