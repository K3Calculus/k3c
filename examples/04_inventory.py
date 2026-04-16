"""
Example 04: Inventory System -- Conservation invariant + korrelator.

An inventory system where items are received and sold.
The spec ensures:
  - Stock never goes negative
  - Total units is conserved (received - sold = current stock)
  - Korrelator checks impl state matches spec state

Demonstrates: Spec (frozen dataclass), Require with Expr transitions,
              EmbeddedRuntime with korrelate_hook and projection hooks,
              Universe for fuzz testing.
"""

from k3c import (
    Spec,
    Permit,
    Require,
    Maintain,
    Universe,
    Ok,
    Impossible,
    EmbeddedRuntime,
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


# -- Spec (declarative, frozen dataclass) --------------------------------------

inventory_spec = Spec(
    name="inventory",
    state0={
        "stock": 50,
        "total_received": 50,
        "total_sold": 0,
    },
    permits=(
        Permit(
            name="can_sell",
            when=Compare(CmpOp.GE, Field(Var("state"), "stock"), EventField("qty")),
            on="Sell",
        ),
        Permit(
            name="positive_receive",
            when=Compare(CmpOp.GT, EventField("qty"), LInt(0)),
            on="Receive",
        ),
    ),
    requires=(
        # Advance spec_state to track intended stock on Receive
        Require(
            name="track_receive",
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
        ),
        # Advance spec_state to track intended stock on Sell
        Require(
            name="track_sell",
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
        ),
    ),
    maintains=(
        # Safety: stock never negative
        Maintain(
            name="non_negative_stock",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "stock"), LInt(0))),
        ),
        # Conservation: received - sold = stock
        Maintain(
            name="conservation",
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
        ),
    ),
)


# -- Transition function (plain function, no System class) ---------------------


def inventory_transition(state: dict, event: dict) -> dict:
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


# -- Usage ---------------------------------------------------------------------


def main():
    # EmbeddedRuntime with korrelate_hook and projection hooks
    runtime = EmbeddedRuntime(
        spec=inventory_spec,
        transition=inventory_transition,
        projection_hooks={
            "stock_level": lambda state, event, ctx: state["stock"],
            "utilization": lambda state, event, ctx: (
                round(state["total_sold"] / state["total_received"] * 100, 1)
                if state["total_received"] > 0
                else 0.0
            ),
        },
        korrelate_hook=lambda actual, intended: actual["stock"] == intended["stock"],
    )
    u = runtime.universe()

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
    print(f"Oversell: {r.why.rule} -- REJECTED")

    # Try to receive 0 items
    r = u.apply({"type": "Receive", "qty": 0})
    assert isinstance(r, Impossible)
    print(f"Zero receive: {r.why.rule} -- REJECTED")

    # Verify conservation holds
    print("\nConservation check:")
    print(
        f"  received={u.state['total_received']}, sold={u.state['total_sold']}, stock={u.state['stock']}"
    )
    print(
        f"  {u.state['total_received']} - {u.state['total_sold']} = {u.state['stock']} (correct)"
    )

    # Fuzz (Universe supports fuzz; EmbeddedUniverse does not)
    u_fuzz = Universe(spec=inventory_spec, transition=inventory_transition)
    report = u_fuzz.fuzz(sequences=200, steps=30, seed=42)
    print(
        f"\nFuzz: passed={report.passed}, steps={report.total_steps}, impossible={report.impossible_count}"
    )

    print("\nInventory example passed.")


if __name__ == "__main__":
    main()
