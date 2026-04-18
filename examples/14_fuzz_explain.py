"""14 — Fuzz testing + Explain (debugging)

KC-5 verification: random event sequences with automatic shrinking.
Explain: dry-run an event with full eval trace.

Demonstrates:
- u.fuzz() — property-based testing of invariants
- u.explain() — dry-run trace without mutating state
- Sub-expression diagnostics on Maintain failure
"""

from __future__ import annotations

from k3c import (
    Always,
    Implies,
    Maintain,
    Permit,
    S,
    Spec,
    Universe,
    Violated,
    k3,
)


# Spec with a non-trivial invariant
spec = Spec(
    name="bounded_counter",
    state0={"count": 0, "max_seen": 0},
    permits=(Permit(name="any", when=k3(S.count >= -1000)),),
    maintains=(
        # max_seen is monotonic AND tracks count
        Maintain(
            name="max_tracking",
            expr=Always(Implies(
                k3(S.count > 0),
                k3(S.max_seen >= S.count),
            )),
        ),
    ),
)


def transition(state: dict, event: dict) -> dict:
    n = event.get("n", 0)
    new_count = state["count"] + n
    # BUG: forgets to update max_seen on positive deltas
    return {**state, "count": new_count}


def main() -> None:
    u = Universe(spec=spec, transition=transition)

    # 1. Explain — see full eval trace for a single event without mutating
    print("== Explain (dry-run trace) ==")
    trace = u.explain({"type": "Inc", "n": 5})
    print(trace.summary())

    # 2. Fuzz — random event sequences hunt for the bug
    print("\n== Fuzz (1000 sequences x 50 steps) ==")

    def gen_event(state, rnd):
        return {"type": "Inc", "n": rnd.randint(-3, 5)}

    report = u.fuzz(sequences=20, steps=10, seed=42, event_generator=gen_event, shrink=False)
    print(f"  passed: {report.passed}")
    print(f"  sequences run: {report.sequences_run}")

    if not report.passed and report.violations:
        v = report.violations[0]
        print(f"\n  Found violation of: {v.violated.why.rule}")
        print(f"  Original sequence length: {len(v.original_sequence)}")
        print(f"  Shrunk to: {len(v.shrunk_sequence)} events")
        print(f"  Minimal reproducer: {v.shrunk_sequence}")

    # 3. Manually trigger the violation to see sub-expression diagnostics
    print("\n== Sub-expression diagnostics on failure ==")
    u.reset()
    r = u.apply({"type": "Inc", "n": 10})
    if isinstance(r, Violated):
        for line in r.why.messages:
            print(f"  {line}")


if __name__ == "__main__":
    main()
