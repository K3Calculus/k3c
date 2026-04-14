"""
Example 04: Inventory System — Conservation invariant + korrelator.

An inventory system where items are received and sold.
The spec ensures:
  - Stock never goes negative
  - Total units is conserved (received - sold = current stock)
  - Korrelator checks impl state matches spec state

Demonstrates: require (spec_state advancement), korrelate, Before/After, ForAll.
"""

from k3c import (
    Spec,
    universe,
    Ok,
    Impossible,
    Always,
    Compare,
    CmpOp,
    Arith,
    ArithOp,
    Field,
    Var,
    EventField,
    LInt,
    With,
)


# ── Spec ────────────────────────────────────────────────────────────────────

inventory_spec = (
    Spec("inventory")
    .state0(
        {
            "stock": 50,
            "total_received": 50,
            "total_sold": 0,
        }
    )
    # Guards
    .permit(
        "can_sell",
        when=Compare(CmpOp.GE, Field(Var("state"), "stock"), EventField("qty")),
        on="Sell",
    )
    .permit(
        "positive_receive",
        when=Compare(CmpOp.GT, EventField("qty"), LInt(0)),
        on="Receive",
    )
    # Require: advance spec_state to track intended stock
    .require(
        "track_receive",
        on="Receive",
        transition=With(
            Var("spec_state"),
            (
                (
                    "stock",
                    Arith(
                        ArithOp.ADD,
                        Field(Var("spec_state"), "stock"),
                        EventField("qty"),
                    ),
                ),
                (
                    "total_received",
                    Arith(
                        ArithOp.ADD,
                        Field(Var("spec_state"), "total_received"),
                        EventField("qty"),
                    ),
                ),
            ),
        ),
    )
    .require(
        "track_sell",
        on="Sell",
        transition=With(
            Var("spec_state"),
            (
                (
                    "stock",
                    Arith(
                        ArithOp.SUB,
                        Field(Var("spec_state"), "stock"),
                        EventField("qty"),
                    ),
                ),
                (
                    "total_sold",
                    Arith(
                        ArithOp.ADD,
                        Field(Var("spec_state"), "total_sold"),
                        EventField("qty"),
                    ),
                ),
            ),
        ),
    )
    # Safety: stock never negative
    .maintain(
        "non_negative_stock",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "stock"), LInt(0))),
    )
    # Conservation: received - sold = stock
    .maintain(
        "conservation",
        expr=Always(
            Compare(
                CmpOp.EQ,
                Field(Var("state"), "stock"),
                Arith(
                    ArithOp.SUB,
                    Field(Var("state"), "total_received"),
                    Field(Var("state"), "total_sold"),
                ),
            )
        ),
    )
    # Korrelator: impl stock matches spec stock
    .korrelate(
        lift=lambda s: {"stock": s["stock"]},
    )
    # Projections
    .project("stock_level", lambda s: s["stock"])
    .project(
        "utilization",
        lambda s: (
            round(s["total_sold"] / s["total_received"] * 100, 1)
            if s["total_received"] > 0
            else 0.0
        ),
        kind="metric",
    )
    .build()
)


# ── System ──────────────────────────────────────────────────────────────────


class InventorySystem:
    def transition(self, state, event):
        match event.get("type"):
            case "Receive":
                qty = event["qty"]
                return {
                    **state,
                    "stock": state["stock"] + qty,
                    "total_received": state["total_received"] + qty,
                }
            case "Sell":
                qty = event["qty"]
                return {
                    **state,
                    "stock": state["stock"] - qty,
                    "total_sold": state["total_sold"] + qty,
                }
            case _:
                return state


# ── Usage ───────────────────────────────────────────────────────────────────


def main():
    u = universe(InventorySystem(), inventory_spec)

    # Receive stock
    r = u.apply({"type": "Receive", "qty": 30})
    assert isinstance(r, Ok)
    print(
        f"Received 30: stock={r.projections['stock_level']}, utilization={r.projections['utilization']}%"
    )

    # Sell some
    r = u.apply({"type": "Sell", "qty": 20})
    assert isinstance(r, Ok)
    print(
        f"Sold 20: stock={r.projections['stock_level']}, utilization={r.projections['utilization']}%"
    )

    # Try to oversell
    r = u.apply({"type": "Sell", "qty": 100})
    assert isinstance(r, Impossible)
    print(f"Oversell: {r.why.rule} — REJECTED")

    # Try to receive 0 items
    r = u.apply({"type": "Receive", "qty": 0})
    assert isinstance(r, Impossible)
    print(f"Zero receive: {r.why.rule} — REJECTED")

    # Verify conservation holds
    print("\nConservation check:")
    print(
        f"  received={u.state['total_received']}, sold={u.state['total_sold']}, stock={u.state['stock']}"
    )
    print(
        f"  {u.state['total_received']} - {u.state['total_sold']} = {u.state['stock']} (correct)"
    )

    # Fuzz
    u.reset()
    report = u.fuzz(sequences=200, steps=30, seed=42)
    print(
        f"\nFuzz: passed={report.passed}, steps={report.total_steps}, impossible={report.impossible_count}"
    )

    print("\nInventory example passed.")


if __name__ == "__main__":
    main()
