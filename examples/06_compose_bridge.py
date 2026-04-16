"""
Example 06: Commerce System -- Compose + Bridge.

Two Universes: OrderSystem and PaymentSystem, composed via <||>.
Bridged to an AuditSystem that logs every event.

Demonstrates: Spec (frozen dataclass), Universe constructor,
              compose, bridge, BridgeMode, routing.
"""

from k3c import (
    Spec,
    Permit,
    Maintain,
    Universe,
    Ok,
    Always,
    Compare,
    CmpOp,
    Field,
    Var,
    LInt,
    LBool,
    BridgeMode,
)
from k3c.runtime.bridge import BridgedUniverse


# -- Order Universe ------------------------------------------------------------

order_spec = Spec(
    name="orders",
    state0={"status": "empty", "total": 0, "item_count": 0},
    permits=(Permit(name="ok", when=LBool(True)),),
    maintains=(
        Maintain(
            name="positive_total",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "total"), LInt(0))),
        ),
    ),
)


def order_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "AddItem":
            return {
                **state,
                "status": "open",
                "total": state["total"] + event.get("price", 0),
                "item_count": state["item_count"] + 1,
            }
        case "Checkout":
            return {**state, "status": "checked_out"}
        case _:
            return state


# -- Payment Universe ----------------------------------------------------------

payment_spec = Spec(
    name="payments",
    state0={"paid": 0, "pending": 0},
    permits=(Permit(name="ok", when=LBool(True)),),
    maintains=(
        Maintain(
            name="non_negative",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "paid"), LInt(0))),
        ),
    ),
)


def payment_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Pay":
            amount = event.get("amount", 0)
            return {
                **state,
                "paid": state["paid"] + amount,
                "pending": max(0, state["pending"] - amount),
            }
        case "Invoice":
            return {
                **state,
                "pending": state["pending"] + event.get("amount", 0),
            }
        case _:
            return state


# -- Audit Universe ------------------------------------------------------------

audit_spec = Spec(
    name="audit",
    state0={"log": [], "count": 0},
    permits=(Permit(name="ok", when=LBool(True)),),
)


def audit_transition(state: dict, event: dict) -> dict:
    return {
        **state,
        "log": state["log"] + [{"action": event.get("type"), "data": event}],
        "count": state["count"] + 1,
    }


# -- Usage ---------------------------------------------------------------------


def main():
    # Create Universes via constructor (no factory function)
    order_u = Universe(spec=order_spec, transition=order_transition)
    payment_u = Universe(spec=payment_spec, transition=payment_transition)
    audit_u = Universe(spec=audit_spec, transition=audit_transition)

    # -- Compose: orders <||> payments -----------------------------------------
    def router(event):
        t = event.get("type", "")
        if t.startswith("Pay") or t == "Invoice":
            return "right"
        return "left"

    commerce = order_u.compose(payment_u, router)

    # Add items (routes to orders)
    r = commerce.apply({"type": "AddItem", "price": 25})
    assert isinstance(r, Ok)
    print(f"AddItem: {commerce.state}")

    r = commerce.apply({"type": "AddItem", "price": 35})
    assert isinstance(r, Ok)
    print(f"AddItem: orders.total={commerce.state['left']['total']}")

    # Invoice (routes to payments)
    r = commerce.apply({"type": "Invoice", "amount": 60})
    assert isinstance(r, Ok)
    print(f"Invoice: payments.pending={commerce.state['right']['pending']}")

    # Pay (routes to payments)
    r = commerce.apply({"type": "Pay", "amount": 60})
    assert isinstance(r, Ok)
    print(f"Pay: payments.paid={commerce.state['right']['paid']}")

    # -- Parallel compose: both sides run simultaneously -----------------------
    order_u3 = Universe(spec=order_spec, transition=order_transition)
    payment_u3 = Universe(spec=payment_spec, transition=payment_transition)
    parallel_commerce = order_u3.compose(payment_u3, lambda e: "both")

    r_par = parallel_commerce.apply({"type": "AddItem", "price": 99}, mode="parallel")
    assert isinstance(r_par, Ok)
    print(
        f"\nParallel both: left={parallel_commerce.state['left']}, right={parallel_commerce.state['right']}"
    )

    # -- Bridge: commerce <-> audit --------------------------------------------
    def commerce_to_audit(src_state, event, new_state):
        return {
            "type": "AuditEntry",
            "source_event": event.get("type"),
            "timestamp": "2026-04-15",
        }

    audited = BridgedUniverse(
        source=commerce,
        target=audit_u,
        mapper=commerce_to_audit,
        mode=BridgeMode.SYNCHRONOUS,
    )

    # Events now flow through commerce AND audit
    r = audited.apply({"type": "AddItem", "price": 15})
    assert isinstance(r, Ok)
    print("\nAudited AddItem:")
    print(f"  Commerce state: {audited.state['source']}")
    print(f"  Audit log count: {audited.state['target']['count']}")

    r = audited.apply({"type": "Pay", "amount": 15})
    assert isinstance(r, Ok)
    print("Audited Pay:")
    print(f"  Audit log count: {audited.state['target']['count']}")

    print("\nCompose + Bridge example passed.")


if __name__ == "__main__":
    main()
