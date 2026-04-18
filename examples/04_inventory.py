"""04 — Inventory with Validate clause

The Validate clause is event-scoped: it can read EventField AND state.
Use it for "permitted but invalid" cases where a Permit alone isn't enough.

Demonstrates:
- Validate clause with on=, EventField access, structured field/constraint
- Severity.WARNING for non-fatal validation issues
- Conservation invariant via Maintain
- Outputs (declarative, post-causal)
"""

from __future__ import annotations

from k3c import (
    Always,
    E,
    EventDef,
    EventField,
    FieldDef,
    LStr,
    Maintain,
    Ok,
    Output,
    Permit,
    Record,
    S,
    Severity,
    Spec,
    Universe,
    Validate,
    Violated,
    Warning,
    k3,
)
from k3c.ir.types import TInt


spec = Spec(
    name="inventory",
    state0={"sold": 0, "stock": 100, "total_received": 100},
    events=(
        EventDef(name="Sell",    fields=(FieldDef(name="qty", type=TInt()),)),
        EventDef(name="Restock", fields=(FieldDef(name="qty", type=TInt()),)),
    ),
    permits=(
        # Allow Sell only if stock available
        Permit(name="has_stock", on="Sell", when=k3(S.stock >= E.qty)),
        Permit(name="any", when=k3(S.stock >= 0)),
    ),
    validates=(
        # Sells > 50 produce a Warning (large order alert) — not fatal
        Validate(
            name="large_order",
            on="Sell",
            check=k3(E.qty <= 50),
            severity=Severity.WARNING,
            field="qty",
            constraint="<= 50",
        ),
        # SKU must match the expected pattern (regex via Matches still available)
        Validate(
            name="positive_qty",
            on="Sell",
            check=k3(E.qty > 0),
            field="qty",
            constraint="> 0",
        ),
    ),
    maintains=(
        # Conservation: sold + stock == total_received (always)
        Maintain(
            name="conservation",
            expr=Always(k3((S.sold + S.stock) == S.total_received)),
        ),
    ),
    outputs=(
        # Emit a "receipt" output for every Sell
        Output(
            name="receipt",
            on="Sell",
            expr=Record((
                ("type", LStr("Receipt")),
                ("qty_sold", EventField("qty")),
            )),
        ),
    ),
)


def transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Sell":
            qty = event.get("qty", 0)
            return {**state, "sold": state["sold"] + qty, "stock": state["stock"] - qty}
        case "Restock":
            qty = event.get("qty", 0)
            return {
                **state,
                "stock": state["stock"] + qty,
                "total_received": state["total_received"] + qty,
            }
        case _:
            return state


def main() -> None:
    u = Universe(spec=spec, transition=transition)

    events = [
        {"type": "Sell", "qty": 10},      # Ok + Receipt output
        {"type": "Sell", "qty": 75},      # Warning (large_order > 50)
        {"type": "Sell", "qty": -5},      # Violated (positive_qty failed)
    ]

    for event in events:
        result = u.apply(event)
        match result:
            case Ok(state=s, outputs=outputs):
                print(f"  ok       sold={s['sold']:3d} stock={s['stock']:3d}  outputs={list(outputs)}")
            case Warning(state=s, why=w, outputs=outputs):
                print(f"  warning  sold={s['sold']:3d} stock={s['stock']:3d}  ({w.rule})  outputs={list(outputs)}")
            case Violated(why=w):
                print(f"  BUG      {w.rule}: {w.message}")
                # Why also exposes the structured field/constraint detail
                for line in w.messages:
                    print(f"    - {line}")
                break


if __name__ == "__main__":
    main()
