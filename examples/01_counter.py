"""
Example 01: Counter — The simplest possible K3 system.

A counter that increments. One state field, one event type, one invariant.
Demonstrates: Spec, universe, apply, Ok, maintain.
"""

from k3c import (
    Always,
    CmpOp,
    Compare,
    Field,
    Impossible,
    LBool,
    LInt,
    Ok,
    Spec,
    Var,
    Violated,
    universe,
)

# ── Spec ────────────────────────────────────────────────────────────────────

spec = (
    Spec("counter")
    .state0({"count": 0})
    .permit("always_ok", when=LBool(True), on="Inc")
    .maintain(
        "non_negative",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
    )
    .build()
)

# ── System ──────────────────────────────────────────────────────────────────


class CounterSystem:
    def transition(self, state, event):
        match event.get("type"):
            case "Inc":
                return {**state, "count": state["count"] + event.get("n", 1)}


# ── Usage ───────────────────────────────────────────────────────────────────


def main():
    u = universe(CounterSystem(), spec)
    print(f"Initial: {u.state}")

    # Increment by 1
    r = u.apply({"type": "Inc", "n": 1})
    if isinstance(r, Impossible):
        print("impossible")
        return

    if isinstance(r, Violated):
        print("violated")
        return

    assert isinstance(r, Ok)
    print(f"After +1: {u.state}")

    # Increment by 5
    r = u.apply({"type": "Inc", "n": 5})
    assert isinstance(r, Ok)
    print(f"After +5: {u.state}")

    # Reduce a batch
    u.reset()
    r = u.reduce([{"type": "Inc", "n": i} for i in range(1, 6)])
    assert isinstance(r, Ok)
    print(f"After 1+2+3+4+5: {u.state}")  # count = 15

    print("Counter example passed.")


if __name__ == "__main__":
    main()
