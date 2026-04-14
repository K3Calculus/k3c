"""
Example 02: Bank Account — Guards, invariants, projections, and outputs.

A bank account with deposits and withdrawals. The spec ensures:
  - Withdrawals are only permitted when sufficient funds exist
  - Balance never goes negative
  - Every withdrawal produces a receipt output
  - Projections provide a public view of the balance

Demonstrates: permit with event filter, maintain, project, output, Impossible.
"""

from k3c import (
    Spec,
    universe,
    Ok,
    Impossible,
    Always,
    Compare,
    CmpOp,
    Field,
    Var,
    EventField,
    LInt,
)


# ── Spec ────────────────────────────────────────────────────────────────────

bank_spec = (
    Spec("bank_account")
    .state0({"balance": 100, "txn_count": 0})
    # Guard: withdrawals need sufficient funds
    .permit(
        "has_funds",
        when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
        on="Withdraw",
    )
    # Invariant: balance never negative
    .maintain(
        "non_negative",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
    )
    # Projections: derived views from state
    .project("balance", lambda s: s["balance"])
    .project("is_healthy", lambda s: s["balance"] > 50, kind="metric")
    # Outputs: post-causal events
    .output(
        "receipt",
        lambda s, e, ns: {
            "type": "Receipt",
            "action": e.get("type"),
            "amount": e.get("amount", 0),
            "balance_after": ns["balance"],
        },
        on="Withdraw",
    )
    .output(
        "low_balance_alert",
        lambda s, e, ns: (
            {"type": "LowBalanceAlert", "balance": ns["balance"]}
            if ns["balance"] < 20
            else None
        ),
    )
    .build()
)


# ── System ──────────────────────────────────────────────────────────────────


class BankSystem:
    def transition(self, state, event):
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


# ── Usage ───────────────────────────────────────────────────────────────────


def main():
    u = universe(BankSystem(), bank_spec)

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
    print(f"  Receipt: {r.outputs[0]}")

    # 3. Overdraw attempt — Impossible
    r = u.apply({"type": "Withdraw", "amount": 999})
    assert isinstance(r, Impossible)
    print(f"Overdraw: {r.why.rule} — {r.why.messages[0]}")
    print(f"  Balance unchanged: {u.state['balance']}")

    # 4. Withdraw to trigger low balance alert
    r = u.apply({"type": "Withdraw", "amount": 240})
    assert isinstance(r, Ok)
    print(f"Large withdraw: balance={r.projections['balance']}")
    alert = next((o for o in r.outputs if o["type"] == "LowBalanceAlert"), None)
    if alert:
        print(f"  Alert: {alert}")

    # 5. Fuzz test — verify the spec holds under random events
    u.reset()
    report = u.fuzz(sequences=100, steps=50, seed=42)
    print(
        f"\nFuzz: passed={report.passed}, sequences={report.sequences_run}, "
        f"steps={report.total_steps}, impossible={report.impossible_count}"
    )

    print("\nBank account example passed.")


if __name__ == "__main__":
    main()
