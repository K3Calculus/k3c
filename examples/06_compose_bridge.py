"""
Example 06: Commerce System — Compose + Bridge.

Two Universes: OrderSystem and PaymentSystem, composed via <||>.
Bridged to an AuditSystem that logs every event.

Demonstrates: compose, bridge, BridgeMode, routing, closed algebra.
"""

from k3c import (
    Spec,
    universe,
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


# ── Order Universe ──────────────────────────────────────────────────────────

order_spec = (
    Spec("orders")
    .state0({"status": "empty", "total": 0, "item_count": 0})
    .permit("ok", when=LBool(True))
    .maintain(
        "positive_total",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "total"), LInt(0))),
    )
    .project("order_summary", lambda s: {"status": s["status"], "total": s["total"]})
    .output(
        "order_event",
        lambda s, e, ns: {
            "type": "OrderEvent",
            "action": e.get("type"),
            "total": ns["total"],
        },
    )
    .build()
)


class OrderSystem:
    def transition(self, state, event):
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


# ── Payment Universe ────────────────────────────────────────────────────────

payment_spec = (
    Spec("payments")
    .state0({"paid": 0, "pending": 0})
    .permit("ok", when=LBool(True))
    .maintain(
        "non_negative",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "paid"), LInt(0))),
    )
    .project("payment_status", lambda s: {"paid": s["paid"], "pending": s["pending"]})
    .build()
)


class PaymentSystem:
    def transition(self, state, event):
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


# ── Audit Universe ──────────────────────────────────────────────────────────

audit_spec = (
    Spec("audit")
    .state0({"log": [], "count": 0})
    .permit("ok", when=LBool(True))
    .project("audit_count", lambda s: s["count"])
    .build()
)


class AuditSystem:
    def transition(self, state, event):
        return {
            **state,
            "log": state["log"] + [{"action": event.get("type"), "data": event}],
            "count": state["count"] + 1,
        }


# ── Usage ───────────────────────────────────────────────────────────────────


def main():
    order_u = universe(OrderSystem(), order_spec)
    payment_u = universe(PaymentSystem(), payment_spec)
    audit_u = universe(AuditSystem(), audit_spec)

    # ── Compose: orders <||> payments ────────────────────────────────────
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

    # ── Parallel compose: both sides run simultaneously ──────────────────
    # Create fresh composed universe for parallel demo
    order_u3 = universe(OrderSystem(), order_spec)
    payment_u3 = universe(PaymentSystem(), payment_spec)
    parallel_commerce = order_u3.compose(payment_u3, lambda e: "both")

    r_par = parallel_commerce.apply({"type": "AddItem", "price": 99}, mode="parallel")
    assert isinstance(r_par, Ok)
    print(
        f"\nParallel both: left={parallel_commerce.state['left']}, right={parallel_commerce.state['right']}"
    )

    # ── Bridge: commerce <-> audit ───────────────────────────────────────
    def commerce_to_audit(src_state, event, new_state):
        return {
            "type": "AuditEntry",
            "source_event": event.get("type"),
            "timestamp": "2026-04-14",
        }

    audited = commerce.bridge(
        audit_u,
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
