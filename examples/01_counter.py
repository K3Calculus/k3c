"""01 — Counter

The simplest possible Universe: a counter that can only go up.

Demonstrates:
- Spec, EventDef (typed events), Permit, Maintain, Universe
- IR sugar: S, E, k3, operator overloads
- Four result types: Ok, Warning, Impossible, Violated
- u.get(field) for cheap reads
- u.simulate() for trajectory collection
- Engine enforces declared event types and field shapes
"""

from __future__ import annotations

from k3c import (
    Always,
    EventDef,
    FieldDef,
    Impossible,
    Maintain,
    Ok,
    Permit,
    S,
    Spec,
    Universe,
    Violated,
    k3,
)
from k3c.ir.types import TInt


# 1. Define the spec — including typed events
spec = Spec(
    name="counter",
    state0={"count": 0},
    # Declared events: only Inc with an int n.
    # Engine enforces — unknown event types and bad field shapes -> Impossible.
    events=(
        EventDef(name="Inc", fields=(FieldDef(name="n", type=TInt()),)),
    ),
    permits=(
        Permit(name="positive_inc", on="Inc", when=k3(S.count >= 0)),
    ),
    maintains=(
        Maintain(name="non_negative", expr=Always(k3(S.count >= 0))),
    ),
)


# 2. Pure transition function
def transition(state: dict, event: dict) -> dict:
    if event.get("type") == "Inc":
        return {**state, "count": state["count"] + event.get("n", 1)}
    return state


# 3. Run
def main() -> None:
    u = Universe(spec=spec, transition=transition)

    # Mix valid + schema-rejected events
    for event in [
        {"type": "Inc", "n": 1},
        {"type": "Inc", "n": 5},
        {"type": "Other"},                    # event_schema: unknown type
        {"type": "Inc", "n": "five"},         # event_schema: n must be int
    ]:
        result = u.apply(event)
        match result:
            case Ok(state=s):
                print(f"  ok: count={s['count']}")
            case Impossible(why=w):
                print(f"  rejected: {w.message}")
            case Violated(why=w):
                print(f"  BUG: {w.message}")

    print(f"\nFinal count via u.get(): {u.get('count')}")

    # Simulate collects trajectory + step hashes (KC-3)
    u.reset()
    run = u.simulate([{"type": "Inc", "n": 10}, {"type": "Inc", "n": 3}])
    print(f"\nSimulated {run.processed} events, final={run.final_state}")
    print(f"Step hashes: {[h[:8] for h in run.step_hashes]}")


if __name__ == "__main__":
    main()
