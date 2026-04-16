"""
Example 03: Order State Machine -- Protocol DFA with permitted transitions.

An order lifecycle: Pending -> Confirmed -> Shipped -> Delivered.
Guards enforce valid state transitions. Invariants ensure no backwards movement.

Demonstrates: Spec (frozen dataclass), Permit with on filter, Implies,
              EmbeddedRuntime for projection hooks, Universe for explain.
"""

from k3c import (
    Spec,
    Permit,
    Maintain,
    Universe,
    Ok,
    Impossible,
    EmbeddedRuntime,
    Always,
    Implies,
    Compare,
    CmpOp,
    Field,
    Var,
    LStr,
    LInt,
)


# -- Spec (declarative, frozen dataclass) --------------------------------------

order_spec = Spec(
    name="order",
    state0={"status": "pending", "total": 0, "items": 0},
    permits=(
        Permit(
            name="confirm_from_pending",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("pending")),
            on="Confirm",
        ),
        Permit(
            name="ship_from_confirmed",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("confirmed")),
            on="Ship",
        ),
        Permit(
            name="deliver_from_shipped",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("shipped")),
            on="Deliver",
        ),
        Permit(
            name="cancel_allowed",
            when=Compare(CmpOp.NE, Field(Var("state"), "status"), LStr("delivered")),
            on="Cancel",
        ),
        Permit(
            name="add_item_when_pending",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("pending")),
            on="AddItem",
        ),
    ),
    maintains=(
        # Invariant: total is always non-negative
        Maintain(
            name="positive_total",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "total"), LInt(0))),
        ),
        # Invariant: items count matches total relationship
        Maintain(
            name="items_match_total",
            expr=Always(
                Implies(
                    Compare(CmpOp.GT, Field(Var("state"), "items"), LInt(0)),
                    Compare(CmpOp.GT, Field(Var("state"), "total"), LInt(0)),
                )
            ),
        ),
    ),
)


# -- Transition function (plain function, no System class) ---------------------


def order_transition(state: dict, event: dict) -> dict:
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


# -- Usage ---------------------------------------------------------------------


def main():
    # EmbeddedRuntime for projection hooks
    runtime = EmbeddedRuntime(
        spec=order_spec,
        transition=order_transition,
        projection_hooks={
            "summary": lambda state, event, ctx: {
                "status": state["status"],
                "total": state["total"],
                "items": state["items"],
            },
        },
    )
    u = runtime.universe()

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
    print(f"\n  Ship delivered order: {r.why.rule} -- REJECTED")

    # Invalid transition: try to add item after confirmation
    u.reset()
    u.apply({"type": "AddItem", "price": 10})
    u.apply({"type": "Confirm"})
    r = u.apply({"type": "AddItem", "price": 20})
    assert isinstance(r, Impossible)
    print(f"  Add item after confirm: {r.why.rule} -- REJECTED")

    # Cancel path
    u.reset()
    u.apply({"type": "AddItem", "price": 50})
    u.apply({"type": "Confirm"})
    r = u.apply({"type": "Cancel"})
    assert isinstance(r, Ok)
    print(f"\n  Cancel confirmed order: status={u.state['status']}")

    # Explain a rejection (Universe supports explain)
    u2 = Universe(spec=order_spec, transition=order_transition)
    u2.apply({"type": "AddItem", "price": 10})
    u2.apply({"type": "Confirm"})
    u2.apply({"type": "Ship"})
    explanation = u2.explain({"type": "Confirm"})
    print("\n  Explain re-confirm shipped order:")
    print(f"  {explanation.summary()}")

    print("\nOrder state machine example passed.")


if __name__ == "__main__":
    main()
