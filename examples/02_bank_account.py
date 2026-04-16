"""
Example 02: Bank Account -- Guards, invariants, projections, and outputs.

Demonstrates: permit with event filter, maintain, EmbeddedRuntime for
projection and output hooks, Impossible, fuzz.
"""

from k3c import (
    Always,
    CmpOp,
    Compare,
    EmbeddedRuntime,
    EventField,
    Field,
    Impossible,
    LInt,
    Maintain,
    Ok,
    Permit,
    Spec,
    Var,
)

# -- Spec (declarative, no callables) -----------------------------------------

bank_spec = Spec(
    name="bank_account",
    state0={"balance": 100, "txn_count": 0},
    permits=(
        Permit(
            name="has_funds",
            when=Compare(
                CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
            ),
            on="Withdraw",
        ),
    ),
    maintains=(
        Maintain(
            name="non_negative",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
        ),
    ),
)


# -- Transition ----------------------------------------------------------------


def bank_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Withdraw":
            return {
                **state,
                "balance": state["balance"] - event["amount"],
                "txn_count": state["txn_count"] + 1,
            }
        case "Deposit":
            return {
                **state,
                "balance": state["balance"] + event["amount"],
                "txn_count": state["txn_count"] + 1,
            }
        case _:
            return state


# -- EmbeddedRuntime (hooks at the boundary) -----------------------------------

runtime = EmbeddedRuntime(
    spec=bank_spec,
    transition=bank_transition,
    projection_hooks={
        "balance": lambda s, e, ctx: s["balance"],
        "is_healthy": lambda s, e, ctx: s["balance"] > 50,
    },
    output_hooks={
        "receipt": lambda s, e, ns: (
            {
                "type": "Receipt",
                "action": e.get("type"),
                "amount": e.get("amount", 0),
                "balance_after": ns["balance"],
            }
            if e.get("type") == "Withdraw"
            else None
        ),
        "low_balance_alert": lambda s, e, ns: (
            {"type": "LowBalanceAlert", "balance": ns["balance"]}
            if ns["balance"] < 20
            else None
        ),
    },
)


# -- Usage ---------------------------------------------------------------------


def main():
    u = runtime.universe()

    # 1. Deposit
    r = u.apply({"type": "Deposit", "amount": 200})
    assert isinstance(r, Ok)
    print(
        f"Deposit 200: balance={r.projections['balance']}, healthy={r.projections['is_healthy']}"
    )

    # 2. Withdraw with receipt
    r = u.apply({"type": "Withdraw", "amount": 50})
    assert isinstance(r, Ok)
    print(f"Withdraw 50: balance={r.projections['balance']}")
    receipt = next((o for o in r.outputs if o.get("type") == "Receipt"), None)
    if receipt:
        print(f"  Receipt: {receipt}")

    # 3. Overdraw attempt -- Impossible
    r = u.apply({"type": "Withdraw", "amount": 999})
    assert isinstance(r, Impossible)
    print(f"Overdraw: {r.why.rule} -- {r.why.messages[0]}")
    print(f"  Balance unchanged: {u.state['balance']}")

    # 4. Withdraw to trigger low balance alert
    r = u.apply({"type": "Withdraw", "amount": 240})
    assert isinstance(r, Ok)
    print(f"Large withdraw: balance={r.projections['balance']}")
    alert = next((o for o in r.outputs if o.get("type") == "LowBalanceAlert"), None)
    if alert:
        print(f"  Alert: {alert}")

    print("\nBank account example passed.")


if __name__ == "__main__":
    main()
