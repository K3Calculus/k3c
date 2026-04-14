"""
Example 03: Order State Machine — Protocol DFA with permitted transitions.

An order lifecycle: Pending -> Confirmed -> Shipped -> Delivered.
Guards enforce valid state transitions. Invariants ensure no backwards movement.

Demonstrates: permit with on filter, protocol_start, Before/After, Implies.
"""

from k3c import (
    Spec,
    universe,
    Ok,
    Impossible,
    Always,
    Implies,
    Compare,
    CmpOp,
    Field,
    Var,
    LStr,
    LInt,
)


# ── Spec ────────────────────────────────────────────────────────────────────

# Allowed transitions
VALID_TRANSITIONS = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["shipped", "cancelled"],
    "shipped": ["delivered"],
    "delivered": [],
    "cancelled": [],
}

order_spec = (
    Spec("order")
    .state0({"status": "pending", "total": 0, "items": 0})
    # Guards: only valid transitions allowed
    .permit(
        "confirm_from_pending",
        when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("pending")),
        on="Confirm",
    )
    .permit(
        "ship_from_confirmed",
        when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("confirmed")),
        on="Ship",
    )
    .permit(
        "deliver_from_shipped",
        when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("shipped")),
        on="Deliver",
    )
    .permit(
        "cancel_allowed",
        when=Compare(CmpOp.NE, Field(Var("state"), "status"), LStr("delivered")),
        on="Cancel",
    )
    .permit(
        "add_item_when_pending",
        when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("pending")),
        on="AddItem",
    )
    # Invariant: total is always non-negative
    .maintain(
        "positive_total",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "total"), LInt(0))),
    )
    # Invariant: items count matches total relationship
    .maintain(
        "items_match_total",
        expr=Always(
            Implies(
                Compare(CmpOp.GT, Field(Var("state"), "items"), LInt(0)),
                Compare(CmpOp.GT, Field(Var("state"), "total"), LInt(0)),
            )
        ),
    )
    # Projections
    .project(
        "summary",
        lambda s: {
            "status": s["status"],
            "total": s["total"],
            "items": s["items"],
        },
    )
    .build()
)


# ── System ──────────────────────────────────────────────────────────────────


class OrderSystem:
    def transition(self, state, event):
        match event.get("type"):
            case "AddItem":
                return {
                    **state,
                    "items": state["items"] + 1,
                    "total": state["total"] + event.get("price", 0),
                }
            case "Confirm":
                return {**state, "status": "confirmed"}
            case "Ship":
                return {**state, "status": "shipped"}
            case "Deliver":
                return {**state, "status": "delivered"}
            case "Cancel":
                return {**state, "status": "cancelled"}
            case _:
                return state


# ── Usage ───────────────────────────────────────────────────────────────────


def main():
    u = universe(OrderSystem(), order_spec)

    # Happy path: pending -> confirmed -> shipped -> delivered
    events = [
        {"type": "AddItem", "price": 25},
        {"type": "AddItem", "price": 35},
        {"type": "Confirm"},
        {"type": "Ship"},
        {"type": "Deliver"},
    ]

    for event in events:
        r = u.apply(event)
        assert isinstance(r, Ok), f"Expected Ok for {event}, got {type(r).__name__}"
        print(f"  {event['type']:>10} -> {r.projections['summary']}")

    # Invalid transition: try to ship a delivered order
    r = u.apply({"type": "Ship"})
    assert isinstance(r, Impossible)
    print(f"\n  Ship delivered order: {r.why.rule} — REJECTED")

    # Invalid transition: try to add item after confirmation
    u.reset()
    u.apply({"type": "AddItem", "price": 10})
    u.apply({"type": "Confirm"})
    r = u.apply({"type": "AddItem", "price": 20})
    assert isinstance(r, Impossible)
    print(f"  Add item after confirm: {r.why.rule} — REJECTED")

    # Cancel path
    u.reset()
    u.apply({"type": "AddItem", "price": 50})
    u.apply({"type": "Confirm"})
    r = u.apply({"type": "Cancel"})
    assert isinstance(r, Ok)
    print(f"\n  Cancel confirmed order: status={u.state['status']}")

    # Explain a rejection
    u.reset()
    u.apply({"type": "AddItem", "price": 10})
    u.apply({"type": "Confirm"})
    u.apply({"type": "Ship"})
    explanation = u.explain({"type": "Confirm"})
    print("\n  Explain re-confirm shipped order:")
    print(f"  {explanation.summary()}")

    print("\nOrder state machine example passed.")


if __name__ == "__main__":
    main()
