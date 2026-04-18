"""10 — FIX Protocol

Financial Information eXchange — session lifecycle + order management.
Modeled with Protocol DSL for the session FSM, sugar for guards/invariants,
Validate for per-message field checks, and denied= for trader-friendly errors.

Demonstrates:
- Protocol DSL for session state machine (Disconnected → Connected → LoggedIn)
- Validate clauses with denied= for tag-level rejection messages
- After/Before for sequence number monotonicity
- compose_many to wire session + order-management universes
- Bridge for execution reports → position tracking
"""

from __future__ import annotations

from k3c import (
    Always,
    BridgedUniverse,
    BridgeMode,
    Concat,
    E,
    Field,
    Impossible,
    LStr,
    Maintain,
    Ok,
    Output,
    Permit,
    Protocol,
    Record,
    S,
    Spec,
    Universe,
    Validate,
    Var,
    after,
    before,
    compose_many,
    k3,
)


# -- FIX Session Layer ---------------------------------------------------------


session_proto = Protocol(
    name="session",
    state_field="status",
    states=("disconnected", "connecting", "logged_in", "logged_out"),
    transitions=(
        ("disconnected", "Connect", "connecting"),
        ("connecting",   "Logon",   "logged_in"),
        ("logged_in",    "Logout",  "logged_out"),
        ("logged_out",   "Connect", "connecting"),
    ),
)


session_spec = Spec(
    name="fix_session",
    state0={
        "status": "disconnected",
        "seq_send": 0,
        "seq_recv": 0,
    },
    events=session_proto.event_defs(),
    permits=session_proto.permits(),
    validates=(
        # Logon must include a SenderCompID
        Validate(
            name="logon_has_sender",
            on="Logon",
            check=k3(E.sender_comp_id != None),  # noqa: E711
            field="sender_comp_id",
            denied=k3(LStr("Logon (35=A) missing SenderCompID (49)")),
        ),
        # Heartbeat interval must be reasonable
        Validate(
            name="reasonable_heartbeat",
            on="Logon",
            check=k3((E.heartbeat >= 1) & (E.heartbeat <= 600)),
            field="heartbeat",
            constraint="1..600 seconds",
        ),
    ),
    maintains=(
        # SAFETY: sequence numbers never go backwards
        Maintain(name="seq_send_monotone", expr=Always(k3(after("seq_send") >= before("seq_send")))),
        Maintain(name="seq_recv_monotone", expr=Always(k3(after("seq_recv") >= before("seq_recv")))),
        *session_proto.maintains(),
    ),
)


SESSION_TABLE = session_proto.transition_table()


def session_transition(state: dict, event: dict) -> dict:
    new_status = SESSION_TABLE.get((state["status"], event["type"]))
    new_state = dict(state)
    if new_status:
        new_state["status"] = new_status
    if event.get("type") in ("Logon", "Heartbeat"):
        new_state["seq_send"] = state["seq_send"] + 1
    return new_state


# -- Order Management Layer ----------------------------------------------------


order_proto = Protocol(
    name="order",
    state_field="order_status",
    states=("none", "pending_new", "new", "partially_filled", "filled", "cancelled"),
    transitions=(
        ("none",             "NewOrderSingle", "pending_new"),
        ("pending_new",      "ExecAck",        "new"),
        ("new",              "PartialFill",    "partially_filled"),
        ("partially_filled", "PartialFill",    "partially_filled"),
        ("new",              "Fill",           "filled"),
        ("partially_filled", "Fill",           "filled"),
        ("new",              "Cancel",         "cancelled"),
        ("partially_filled", "Cancel",         "cancelled"),
    ),
)


order_spec = Spec(
    name="fix_order",
    state0={"order_status": "none", "qty": 0, "filled_qty": 0},
    events=order_proto.event_defs(),
    permits=order_proto.permits(),
    validates=(
        # Order quantity must be positive
        Validate(
            name="positive_qty",
            on="NewOrderSingle",
            check=k3(E.qty > 0),
            field="qty",
            constraint="> 0",
            denied=Concat(LStr("OrderQty (38) must be positive, got "), Field(Var("event"), "qty")),
        ),
    ),
    maintains=(
        # SAFETY: filled qty cannot exceed order qty
        Maintain(name="no_overfill", expr=Always(k3(S.filled_qty <= S.qty))),
    ),
    outputs=(
        # Emit ExecutionReport on every Fill/PartialFill
        Output(
            name="exec_report",
            on="Fill",
            expr=Record((
                ("type", LStr("ExecutionReport")),
                ("status", k3(S.order_status)),
            )),
        ),
    ),
)


def order_transition(state: dict, event: dict) -> dict:
    new_state = dict(state)
    match event.get("type"):
        case "NewOrderSingle":
            new_state["qty"] = event["qty"]
            new_state["order_status"] = "pending_new"
        case "ExecAck":
            new_state["order_status"] = "new"
        case "PartialFill":
            new_state["filled_qty"] = state["filled_qty"] + event["qty"]
            new_state["order_status"] = "partially_filled"
        case "Fill":
            new_state["filled_qty"] = state["qty"]
            new_state["order_status"] = "filled"
        case "Cancel":
            new_state["order_status"] = "cancelled"
    return new_state


# -- Composed FIX system + Position bridge ------------------------------------


def main() -> None:
    session_u = Universe(spec=session_spec, transition=session_transition, validate=False)
    order_u = Universe(spec=order_spec, transition=order_transition)

    # Route by event family
    SESSION_EVTS = set(session_proto.event_types()) | {"Heartbeat"}
    fix = compose_many(
        {"session": session_u, "order": order_u},
        router=lambda e: "session" if e["type"] in SESSION_EVTS else "order",
    )

    # Bridge order universe → position tracker (synchronous so we get exec reports back)
    position_u = Universe(
        spec=Spec(name="positions", state0={"open_qty": 0},
                  permits=(Permit(name="any", when=k3(S.open_qty >= 0)),)),
        transition=lambda s, e: {**s, "open_qty": s["open_qty"] + e.get("qty", 0)},
    )

    bridged_orders = BridgedUniverse(
        source=order_u,
        target=position_u,
        mapper=lambda s, e, ns: (
            {"type": "PositionUpdate", "qty": ns["filled_qty"] - s["filled_qty"]}
            if e["type"] in ("Fill", "PartialFill") else None
        ),
        mode=BridgeMode.SYNCHRONOUS,
    )

    print("== FIX session lifecycle ==")
    for evt in [
        {"type": "Connect"},
        {"type": "Logon", "sender_comp_id": "TRADER1", "heartbeat": 30},
        {"type": "Logon"},  # missing sender_comp_id — Validate denies
    ]:
        r = fix.apply(evt)
        marker = "ok      " if isinstance(r, Ok) else "rejected"
        msg = "" if isinstance(r, Ok) else f"({r.why.message})"
        print(f"  {marker} {evt['type']:20s} {msg}")

    print("\n== Order lifecycle (with position bridge) ==")
    for evt in [
        {"type": "NewOrderSingle", "qty": 0},  # Validate denies (positive_qty)
        {"type": "NewOrderSingle", "qty": 1000},
        {"type": "ExecAck"},
        {"type": "PartialFill", "qty": 400},
        {"type": "Fill"},
    ]:
        r = bridged_orders.apply(evt) if not evt["type"].startswith("Logon") else fix.apply(evt)
        marker = "ok      " if isinstance(r, Ok) else "BUG     " if not isinstance(r, Impossible) else "rejected"
        msg = "" if isinstance(r, Ok) else f"({r.why.message})"
        print(f"  {marker} {evt['type']:20s} {msg}")

    print(f"\nFinal positions: {position_u.state}")
    print(f"Final order: {order_u.state}")


if __name__ == "__main__":
    main()
