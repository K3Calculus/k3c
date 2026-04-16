"""
Example 09: Isolation -- Multiple independent sessions from one spec.

IsolatedUniverse provides physically isolated execution contexts:
  - No shared state between original and copies
  - No shared Python objects (all deep-copied)
  - Each IsolatedUniverse is an independent causal world

Use cases:
  - Parallel fuzz workers
  - Multi-tenant session handling
  - Speculative execution (try an event, discard if unwanted)

Demonstrates: Universe.isolate(), IsolatedUniverse, speculative execution,
independent fuzz.
"""

from k3c import (
    Always,
    CmpOp,
    Compare,
    EventField,
    Field,
    Impossible,
    LInt,
    Maintain,
    Ok,
    Permit,
    Spec,
    Universe,
    Var,
)


# -- Spec (declarative, frozen dataclass) --------------------------------------

session_spec = Spec(
    name="user_session",
    state0={"balance": 1000, "transactions": 0, "last_action": ""},
    permits=(
        Permit(
            name="has_funds",
            when=Compare(
                CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
            ),
            on="Spend",
        ),
        Permit(name="earn_ok", when=Compare(CmpOp.GE, LInt(1), LInt(0)), on="Earn"),
    ),
    maintains=(
        Maintain(
            name="non_negative",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
        ),
    ),
)


# -- Transition function -------------------------------------------------------


def session_transition(state: dict, event: dict) -> dict:
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


# -- Usage ---------------------------------------------------------------------


def main():
    u = Universe(spec=session_spec, transition=session_transition)

    # -- 1. Basic isolation via u.isolate() ------------------------------------
    print("=== 1. Basic Isolation ===")
    u.apply({"type": "Spend", "amount": 100})
    print(f"Original after spend: balance={u.state['balance']}")

    iso = u.isolate()
    print(f"Isolated created: {iso}")

    iso.apply({"type": "Spend", "amount": 200})
    print(f"Isolated after spend: balance={iso.state['balance']}")
    print(f"Original unchanged:   balance={u.state['balance']}")
    assert u.state["balance"] == 900
    assert iso.state["balance"] == 700

    # -- 2. Multiple isolated sessions -----------------------------------------
    print("\n=== 2. Multi-Session ===")
    sessions = []
    for i in range(5):
        session = u.isolate()
        session.apply({"type": "Earn", "amount": (i + 1) * 100})
        sessions.append(session)
        print(f"  Session {i}: balance={session.state['balance']}")

    balances = [s.state["balance"] for s in sessions]
    print(f"  All balances: {balances}")
    assert len(set(balances)) == 5
    print(f"  Original still: balance={u.state['balance']}")

    # -- 3. Speculative execution ----------------------------------------------
    print("\n=== 3. Speculative Execution ===")
    u.reset()
    u.apply({"type": "Earn", "amount": 500})
    print(f"Before speculation: balance={u.state['balance']}")

    speculative = u.isolate()
    r = speculative.apply({"type": "Spend", "amount": 1400})
    if isinstance(r, Ok):
        print(
            f"  Speculative spend 1400: would leave balance={speculative.state['balance']}"
        )
        print("  Decision: too risky, discarding speculative result")
    elif isinstance(r, Impossible):
        print(f"  Speculative spend 1400: REJECTED -- {r.why.rule}")

    speculative2 = u.isolate()
    r2 = speculative2.apply({"type": "Spend", "amount": 300})
    if isinstance(r2, Ok):
        print(
            f"  Speculative spend 300: would leave balance={speculative2.state['balance']}"
        )
        u.apply({"type": "Spend", "amount": 300})
        print(f"  Committed: real balance={u.state['balance']}")

    print(f"  Original after speculation: balance={u.state['balance']}")

    # -- 4. Isolated fuzz ------------------------------------------------------
    print("\n=== 4. Isolated Fuzz ===")
    u.reset()
    u.apply({"type": "Earn", "amount": 200})

    u_fuzz = Universe(spec=session_spec, transition=session_transition)
    report = u_fuzz.fuzz(sequences=50, steps=20, seed=42)
    print(f"  Fuzz result: passed={report.passed}")
    print(f"  Original balance unchanged: {u.state['balance']}")

    # -- 5. Isolated reset -----------------------------------------------------
    print("\n=== 5. Isolated Reset ===")
    iso2 = u.isolate()
    iso2.apply({"type": "Spend", "amount": 500})
    print(f"  Isolated after spend: balance={iso2.state['balance']}")
    iso2.reset()
    print(f"  Isolated after reset: balance={iso2.state['balance']}")

    print("\nIsolation example passed.")


if __name__ == "__main__":
    main()
