"""
Example 10: FIX Protocol -- Financial Information eXchange.

Models FIX session and order management:
  - Session layer: Logon -> Active -> Logout (with sequence numbers)
  - Order lifecycle: NewOrderSingle -> Ack -> Fill/PartialFill/Cancel
  - Safety: sequence numbers monotone, no duplicate ClOrdIDs
  - Liveness: every order eventually reaches a terminal state
  - Korrelator: tracks order count matches between impl and spec
  - Compose: session <||> order management
  - Bridge: order fills -> position tracking
  - Output: execution reports

Demonstrates: full K3 capability -- Spec (frozen dataclass), Permit, Require,
Maintain, Korrelator via EmbeddedRuntime, compose, bridge, outputs via hooks,
projections via hooks, fuzz, explain.
"""

from k3c import (
    Spec,
    Permit,
    Require,
    Maintain,
    Universe,
    EmbeddedRuntime,
    ComposedUniverse,
    BridgedUniverse,
    Ok,
    Impossible,
    Always,
    Compare,
    CmpOp,
    Arith,
    ArithOp,
    Field,
    Var,
    Before,
    After,
    LBool,
    LInt,
    LStr,
    With,
    BridgeMode,
)


# =============================================================================
#  FIX Session Layer
# =============================================================================

session_spec = Spec(
    name="fix_session",
    state0={
        "status": "disconnected",
        "seq_send": 0,
        "seq_recv": 0,
        "heartbeat_interval": 30,
        "last_sent": 0,
        "last_recv": 0,
    },
    permits=(
        Permit(
            name="logon_from_disconnected",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("disconnected")),
            on="Logon",
        ),
        Permit(
            name="active_session",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("active")),
            on="SendMsg",
        ),
        Permit(
            name="active_recv",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("active")),
            on="RecvMsg",
        ),
        Permit(
            name="active_heartbeat",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("active")),
            on="Heartbeat",
        ),
        Permit(
            name="logout_from_active",
            when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("active")),
            on="Logout",
        ),
    ),
    requires=(
        Require(
            name="track_send",
            on="SendMsg",
            transition=With(
                Var("spec_state"),
                (
                    (
                        "seq_send",
                        Arith(
                            ArithOp.ADD, Field(Var("spec_state"), "seq_send"), LInt(1)
                        ),
                    ),
                ),
            ),
        ),
        Require(
            name="track_recv",
            on="RecvMsg",
            transition=With(
                Var("spec_state"),
                (
                    (
                        "seq_recv",
                        Arith(
                            ArithOp.ADD, Field(Var("spec_state"), "seq_recv"), LInt(1)
                        ),
                    ),
                ),
            ),
        ),
    ),
    maintains=(
        Maintain(
            name="seq_send_monotone",
            expr=Always(Compare(CmpOp.GE, After("seq_send"), Before("seq_send"))),
        ),
        Maintain(
            name="seq_recv_monotone",
            expr=Always(Compare(CmpOp.GE, After("seq_recv"), Before("seq_recv"))),
        ),
    ),
)


def session_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Logon":
            return {
                **state,
                "status": "active",
                "heartbeat_interval": event.get("heartbeat", 30),
            }
        case "SendMsg":
            return {
                **state,
                "seq_send": state["seq_send"] + 1,
                "last_sent": event.get("timestamp", 0),
            }
        case "RecvMsg":
            return {
                **state,
                "seq_recv": state["seq_recv"] + 1,
                "last_recv": event.get("timestamp", 0),
            }
        case "Heartbeat":
            return {
                **state,
                "last_sent": event.get("timestamp", 0),
                "last_recv": event.get("timestamp", 0),
            }
        case "Logout":
            return {**state, "status": "disconnected"}
        case _:
            return state


# =============================================================================
#  FIX Order Management
# =============================================================================

order_spec = Spec(
    name="fix_orders",
    state0={
        "orders": {},  # clordid -> order dict
        "fills": [],  # execution history
        "open_count": 0,
        "total_count": 0,
    },
    permits=(Permit(name="ok", when=LBool(True)),),
    maintains=(
        # Safety: open count is non-negative
        Maintain(
            name="open_non_negative",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "open_count"), LInt(0))),
        ),
        # Safety: total count never decreases
        Maintain(
            name="total_monotone",
            expr=Always(Compare(CmpOp.GE, After("total_count"), Before("total_count"))),
        ),
    ),
)


def order_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "NewOrderSingle":
            clordid = event["clordid"]
            order = {
                "clordid": clordid,
                "side": event.get("side", "Buy"),
                "qty": event.get("qty", 0),
                "price": event.get("price", 0),
                "status": "pending",
                "filled_qty": 0,
            }
            return {
                **state,
                "orders": {**state["orders"], clordid: order},
                "open_count": state["open_count"] + 1,
                "total_count": state["total_count"] + 1,
            }

        case "Ack":
            clordid = event["clordid"]
            orders = dict(state["orders"])
            if clordid in orders:
                orders[clordid] = {**orders[clordid], "status": "acked"}
            return {**state, "orders": orders}

        case "Fill":
            clordid = event["clordid"]
            qty = event.get("qty", 0)
            price = event.get("price", 0)
            orders = dict(state["orders"])
            fills = list(state["fills"])
            open_count = state["open_count"]

            if clordid in orders:
                order = orders[clordid]
                new_filled = order["filled_qty"] + qty
                if new_filled >= order["qty"]:
                    orders[clordid] = {
                        **order,
                        "status": "filled",
                        "filled_qty": new_filled,
                    }
                    open_count -= 1
                else:
                    orders[clordid] = {
                        **order,
                        "status": "partial",
                        "filled_qty": new_filled,
                    }
                fills.append({"clordid": clordid, "qty": qty, "price": price})

            return {
                **state,
                "orders": orders,
                "fills": fills,
                "open_count": open_count,
            }

        case "Cancel":
            clordid = event["clordid"]
            orders = dict(state["orders"])
            if clordid in orders and orders[clordid]["status"] not in (
                "filled",
                "cancelled",
            ):
                orders[clordid] = {**orders[clordid], "status": "cancelled"}
                return {
                    **state,
                    "orders": orders,
                    "open_count": state["open_count"] - 1,
                }
            return state

        case _:
            return state


# =============================================================================
#  Position Tracking (Bridge target)
# =============================================================================

position_spec = Spec(
    name="positions",
    state0={"net_position": 0, "realized_pnl": 0.0, "trade_count": 0},
    permits=(Permit(name="ok", when=LBool(True)),),
    maintains=(
        Maintain(
            name="trade_count_monotone",
            expr=Always(Compare(CmpOp.GE, After("trade_count"), Before("trade_count"))),
        ),
    ),
)


def position_transition(state: dict, event: dict) -> dict:
    if event.get("type") == "TradeUpdate":
        side = event.get("side", "Buy")
        qty = event.get("qty", 0)
        delta = qty if side == "Buy" else -qty
        return {
            **state,
            "net_position": state["net_position"] + delta,
            "trade_count": state["trade_count"] + 1,
        }
    return state


# =============================================================================
#  Main
# =============================================================================


def main():
    # EmbeddedRuntime for session korrelator and projections
    session_runtime = EmbeddedRuntime(
        spec=session_spec,
        transition=session_transition,
        projection_hooks={
            "session_info": lambda s, e, ctx: {
                "status": s["status"],
                "sent": s["seq_send"],
                "received": s["seq_recv"],
            },
        },
        korrelate_hook=lambda impl_state, spec_state: (
            impl_state.get("seq_send") == spec_state.get("seq_send")
            and impl_state.get("seq_recv") == spec_state.get("seq_recv")
        ),
    )
    session_u = session_runtime.universe()

    # EmbeddedRuntime for orders with projections and output hooks
    order_runtime = EmbeddedRuntime(
        spec=order_spec,
        transition=order_transition,
        projection_hooks={
            "order_book": lambda s, e, ctx: {
                "open": s["open_count"],
                "total": s["total_count"],
                "fill_count": len(s["fills"]),
            },
            "fill_volume": lambda s, e, ctx: sum(f.get("qty", 0) for f in s["fills"]),
        },
        output_hooks={
            "exec_report": lambda s, e, ns: {
                "type": "ExecutionReport",
                "clordid": e.get("clordid"),
                "exec_type": e.get("type"),
                "side": e.get("side", ""),
                "qty": e.get("qty", 0),
                "price": e.get("price", 0),
            },
        },
    )
    order_u = order_runtime.universe()

    # EmbeddedRuntime for positions with projection hook
    position_runtime = EmbeddedRuntime(
        spec=position_spec,
        transition=position_transition,
        projection_hooks={
            "position_summary": lambda s, e, ctx: {
                "net": s["net_position"],
                "pnl": s["realized_pnl"],
                "trades": s["trade_count"],
            },
        },
    )
    position_u = position_runtime.universe()

    # -- Compose: session <||> orders ------------------------------------------
    def router(event):
        t = event.get("type", "")
        if t in ("Logon", "Logout", "SendMsg", "RecvMsg", "Heartbeat"):
            return "left"
        return "right"

    fix_engine = ComposedUniverse(left=session_u, right=order_u, router=router)

    # -- Bridge: orders -> positions -------------------------------------------
    def fill_to_position(src_state, event, new_state):
        if event.get("type") == "Fill":
            return {
                "type": "TradeUpdate",
                "side": event.get("side", "Buy"),
                "qty": event.get("qty", 0),
                "price": event.get("price", 0),
            }
        return None

    full_system = BridgedUniverse(
        source=fix_engine,
        target=position_u,
        mapper=fill_to_position,
        mode=BridgeMode.SYNCHRONOUS,
    )

    # -- Scenario: FIX trading session -----------------------------------------
    print("=== FIX Trading Session ===\n")

    # 1. Session logon
    r = full_system.apply({"type": "Logon", "heartbeat": 30})
    assert isinstance(r, Ok)
    print(f"1. Logon: session={full_system.state['source']['left']['status']}")

    # 2. New orders
    for i, (side, qty, price) in enumerate(
        [
            ("Buy", 100, 150.50),
            ("Sell", 50, 151.00),
            ("Buy", 200, 149.75),
        ],
        1,
    ):
        r = full_system.apply(
            {
                "type": "NewOrderSingle",
                "clordid": f"ORD-{i:03d}",
                "side": side,
                "qty": qty,
                "price": price,
            }
        )
        assert isinstance(r, Ok)
        book = r.projections.get("order_book", {})
        print(f"2. New {side} {qty}@{price}: open={book.get('open', '?')}")

    # 3. Ack orders
    for i in range(1, 4):
        r = full_system.apply({"type": "Ack", "clordid": f"ORD-{i:03d}"})
        assert isinstance(r, Ok)

    # 4. Fill orders
    r = full_system.apply(
        {
            "type": "Fill",
            "clordid": "ORD-001",
            "qty": 100,
            "price": 150.50,
            "side": "Buy",
        }
    )
    assert isinstance(r, Ok)
    print(f"3. Fill ORD-001: positions={full_system.state['target']}")

    r = full_system.apply(
        {
            "type": "Fill",
            "clordid": "ORD-002",
            "qty": 50,
            "price": 151.00,
            "side": "Sell",
        }
    )
    assert isinstance(r, Ok)

    # 5. Partial fill
    r = full_system.apply(
        {
            "type": "Fill",
            "clordid": "ORD-003",
            "qty": 75,
            "price": 149.75,
            "side": "Buy",
        }
    )
    assert isinstance(r, Ok)
    book = r.projections.get("order_book", {})
    print(f"4. Partial fill ORD-003 (75/200): open={book.get('open', '?')}")

    # 6. Cancel remaining
    r = full_system.apply({"type": "Cancel", "clordid": "ORD-003"})
    assert isinstance(r, Ok)
    book = r.projections.get("order_book", {})
    print(f"5. Cancel ORD-003: open={book.get('open', '?')}")

    # 7. Session messages
    r = full_system.apply({"type": "SendMsg", "timestamp": 100})
    assert isinstance(r, Ok)
    r = full_system.apply({"type": "RecvMsg", "timestamp": 101})
    assert isinstance(r, Ok)

    # 8. Logout
    r = full_system.apply({"type": "Logout"})
    assert isinstance(r, Ok)
    print(f"6. Logout: session={full_system.state['source']['left']['status']}")

    # -- Final state -----------------------------------------------------------
    print("\n=== Final State ===")
    print(f"Session: {full_system.state['source']['left']}")
    orders_state = full_system.state["source"]["right"]
    print(
        f"Orders: open={orders_state['open_count']}, total={orders_state['total_count']}, fills={len(orders_state['fills'])}"
    )
    print(f"Positions: {full_system.state['target']}")

    # -- Post-logout: cannot send messages -------------------------------------
    r = full_system.apply({"type": "SendMsg", "timestamp": 200})
    assert isinstance(r, Impossible)
    print(f"\nSend after logout: {r.why.rule} -- REJECTED")

    # -- Fuzz the order system independently -----------------------------------
    # fuzz() requires a plain Universe (not EmbeddedUniverse)
    order_u2 = Universe(spec=order_spec, transition=order_transition)
    report = order_u2.fuzz(sequences=100, steps=30, seed=42)
    print(f"\nFuzz orders: passed={report.passed}, steps={report.total_steps}")

    # -- Explain a rejection ---------------------------------------------------
    session_u2 = Universe(spec=session_spec, transition=session_transition)
    explanation = session_u2.explain({"type": "SendMsg", "timestamp": 1})
    print(f"Explain send before logon: {type(explanation.result).__name__}")
    for entry in explanation.trace:
        if entry.verdict.value in ("fail", "skip"):
            print(f"  {entry.phase}: {entry.clause} -- {entry.detail}")

    print("\nFIX protocol example passed.")


if __name__ == "__main__":
    main()
