"""
Example 09: Isolation — Multiple independent sessions from one Universe.

isolate() creates a physically isolated copy of a Universe:
  - No shared state between original and isolated
  - No shared Python objects
  - Each isolated Universe is an independent causal world
  - Communication only through serializable events (bridge pattern)

Use cases:
  - Parallel fuzz workers
  - Multi-tenant session handling
  - Speculative execution (try an event, discard if unwanted)

Demonstrates: isolate(), independent state, speculative execution.
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
    IsolatedUniverse,
)


# ── Spec ────────────────────────────────────────────────────────────────────

session_spec = (
    Spec("user_session")
    .state0({"balance": 1000, "transactions": 0, "last_action": ""})
    .permit(
        "has_funds",
        when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
        on="Spend",
    )
    .maintain(
        "non_negative",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
    )
    .project(
        "summary",
        lambda s: {
            "balance": s["balance"],
            "txns": s["transactions"],
            "last": s["last_action"],
        },
    )
    .build()
)


class SessionSystem:
    def transition(self, state, event):
        match event.get("type"):
            case "Spend":
                return {
                    **state,
                    "balance": state["balance"] - event["amount"],
                    "transactions": state["transactions"] + 1,
                    "last_action": f"spent {event['amount']}",
                }
            case "Earn":
                return {
                    **state,
                    "balance": state["balance"] + event.get("amount", 0),
                    "transactions": state["transactions"] + 1,
                    "last_action": f"earned {event.get('amount', 0)}",
                }
            case _:
                return state


# ── Usage ───────────────────────────────────────────────────────────────────


def main():
    u = universe(SessionSystem(), session_spec)

    # ── 1. Basic isolation — no shared state ─────────────────────────────
    print("=== 1. Basic Isolation ===")
    u.apply({"type": "Spend", "amount": 100})
    print(f"Original after spend: balance={u.state['balance']}")

    iso = u.isolate()
    assert isinstance(iso, IsolatedUniverse)
    print(f"Isolated created: {iso}")

    iso.apply({"type": "Spend", "amount": 200})
    print(f"Isolated after spend: balance={iso.state['balance']}")
    print(f"Original unchanged:   balance={u.state['balance']}")
    assert u.state["balance"] == 900  # original unchanged
    assert iso.state["balance"] == 700  # isolated advanced

    # ── 2. Multiple isolated sessions ────────────────────────────────────
    print("\n=== 2. Multi-Session ===")
    sessions = []
    for i in range(5):
        session = u.isolate()
        session.apply({"type": "Earn", "amount": (i + 1) * 100})
        sessions.append(session)
        print(f"  Session {i}: balance={session.state['balance']}")

    # All sessions are independent
    balances = [s.state["balance"] for s in sessions]
    print(f"  All balances: {balances}")
    assert len(set(balances)) == 5  # all different
    print(f"  Original still: balance={u.state['balance']}")

    # ── 3. Speculative execution ─────────────────────────────────────────
    print("\n=== 3. Speculative Execution ===")
    u.reset()
    u.apply({"type": "Earn", "amount": 500})
    print(f"Before speculation: balance={u.state['balance']}")

    # Try a big purchase speculatively
    speculative = u.isolate()
    r = speculative.apply({"type": "Spend", "amount": 1400})
    if isinstance(r, Ok):
        print(
            f"  Speculative spend 1400: would leave balance={speculative.state['balance']}"
        )
        # Decide not to commit — just discard the isolated universe
        print("  Decision: too risky, discarding speculative result")
    elif isinstance(r, Impossible):
        print(f"  Speculative spend 1400: REJECTED — {r.why.rule}")

    # Try a smaller purchase
    speculative2 = u.isolate()
    r2 = speculative2.apply({"type": "Spend", "amount": 300})
    if isinstance(r2, Ok):
        print(
            f"  Speculative spend 300: would leave balance={speculative2.state['balance']}"
        )
        # Commit by applying the same event to the real universe
        u.apply({"type": "Spend", "amount": 300})
        print(f"  Committed: real balance={u.state['balance']}")

    print(f"  Original after speculation: balance={u.state['balance']}")

    # ── 4. Isolated fuzz — test without affecting main state ─────────────
    print("\n=== 4. Isolated Fuzz ===")
    u.reset()
    u.apply({"type": "Earn", "amount": 200})
    snapshot_balance = u.state["balance"]

    # Fuzz on the original (it resets after)
    report = u.fuzz(sequences=50, steps=20, seed=42)
    print(f"  Fuzz result: passed={report.passed}")
    print(f"  State after fuzz: balance={u.state['balance']} (reset to initial)")

    # ── 5. Reset isolation ───────────────────────────────────────────────
    print("\n=== 5. Isolated Reset ===")
    iso2 = u.isolate()
    iso2.apply({"type": "Spend", "amount": 500})
    print(f"  Isolated after spend: balance={iso2.state['balance']}")
    iso2.reset()
    print(f"  Isolated after reset: balance={iso2.state['balance']}")

    print("\nIsolation example passed.")


if __name__ == "__main__":
    main()
