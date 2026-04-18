"""03 — State Machine via Protocol DSL

Linear FSMs are 60%+ of real specs. The Protocol DSL captures the pattern
in one place — auto-generates Permits, EventDefs, and a state-validity Maintain.

Demonstrates:
- Protocol DSL: states, transitions, transition_table()
- Auto-generated event_defs(), permits(), maintains()
- Protocol enforces state-ordered transitions automatically
"""

from __future__ import annotations

from k3c import Impossible, Ok, Protocol, Spec, Universe


# Define the protocol — states + ordered transitions
order_proto = Protocol(
    name="order",
    state_field="status",
    states=("draft", "placed", "paid", "shipped", "delivered"),
    transitions=(
        ("draft",   "Place",   "placed"),
        ("placed",  "Pay",     "paid"),
        ("paid",    "Ship",    "shipped"),
        ("shipped", "Deliver", "delivered"),
        # Cancel is allowed from draft or placed
        ("draft",   "Cancel",  "draft"),
        ("placed",  "Cancel",  "draft"),
    ),
)


# Build a Spec from the protocol
spec = Spec(
    name="order",
    state0={"status": "draft"},
    events=order_proto.event_defs(),
    permits=order_proto.permits(),
    maintains=order_proto.maintains(),
)


# Use the transition table inside the user transition function
TABLE = order_proto.transition_table()


def transition(state: dict, event: dict) -> dict:
    new_status = TABLE.get((state["status"], event["type"]))
    if new_status is not None:
        return {**state, "status": new_status}
    return state


def main() -> None:
    u = Universe(spec=spec, transition=transition)

    # Happy path
    for evt_type in ["Place", "Pay", "Ship", "Deliver"]:
        result = u.apply({"type": evt_type})
        marker = "ok       " if isinstance(result, Ok) else "rejected "
        print(f"  {marker} {evt_type:8s}  status={u.get('status')}")

    # Try wrong order — Pay after delivered should fail
    print("\nWrong-order attempts:")
    u.reset()
    for evt_type in ["Pay", "Ship", "Deliver"]:
        result = u.apply({"type": evt_type})
        if isinstance(result, Impossible):
            print(f"  rejected {evt_type:8s}  status={u.get('status')}  ({result.why.rule})")

    # Show generated artifacts
    print(f"\nGenerated permits ({len(spec.permits)}):")
    for p in spec.permits:
        print(f"  - {p.name}  on={p.on}")


if __name__ == "__main__":
    main()
