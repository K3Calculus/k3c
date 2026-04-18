"""02 — Bank Account

Permits with rich denial messages, invariants with severity, sugar.

Demonstrates:
- Permit with `denied=` IR Expression (rich rejection messages)
- Maintain with severity (ERROR vs WARNING)
- IR sugar: S, E, k3, AnyOf via |
- Warning result: state advances, processing continues
"""

from __future__ import annotations

from k3c import (
    Always,
    Concat,
    E,
    EventDef,
    Field,
    FieldDef,
    Impossible,
    LStr,
    Maintain,
    Ok,
    Permit,
    S,
    Severity,
    Spec,
    Universe,
    Var,
    Violated,
    Warning,
    k3,
)
from k3c.ir.types import TInt


spec = Spec(
    name="bank",
    state0={"balance": 1000, "frozen": False},
    # Typed events — engine enforces shape (unknown types/missing fields rejected)
    events=(
        EventDef(name="Deposit",  fields=(FieldDef(name="amount", type=TInt()),)),
        EventDef(name="Withdraw", fields=(FieldDef(name="amount", type=TInt()),)),
        EventDef(name="Freeze"),
    ),
    permits=(
        # Withdraw needs sufficient funds; rich denial includes actual balance
        Permit(
            name="has_funds",
            on="Withdraw",
            when=k3(S.balance >= E.amount),
            denied=Concat(
                Concat(LStr("insufficient funds: balance="), Field(Var("state"), "balance")),
                Concat(LStr(", requested="), Field(Var("event"), "amount")),
            ),
        ),
        # Account must not be frozen for any debit/credit
        Permit(
            name="not_frozen",
            when=k3(~S.frozen),
            denied=k3(LStr("account is frozen")),
        ),
    ),
    maintains=(
        # ERROR: balance must never go negative
        Maintain(name="non_negative", expr=Always(k3(S.balance >= 0))),
        # WARNING: balance below 200 produces Warning, not Violated
        Maintain(
            name="low_balance",
            expr=Always(k3(S.balance >= 200)),
            severity=Severity.WARNING,
        ),
    ),
)


def transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Deposit":
            return {**state, "balance": state["balance"] + event["amount"]}
        case "Withdraw":
            return {**state, "balance": state["balance"] - event["amount"]}
        case "Freeze":
            return {**state, "frozen": True}
        case _:
            return state


def main() -> None:
    u = Universe(spec=spec, transition=transition)

    events = [
        {"type": "Deposit", "amount": 50},               # Ok
        {"type": "Withdraw", "amount": 950},              # Ok but Warning
        {"type": "Withdraw", "amount": 200},              # Impossible (denied=)
        {"type": "Withdraw", "amount": "lots"},           # Impossible (event_schema: wrong type)
        {"type": "BogusEvent"},                           # Impossible (event_schema: unknown type)
        {"type": "Freeze"},                               # Ok
        {"type": "Deposit", "amount": 100},               # Impossible (frozen)
    ]

    for event in events:
        result = u.apply(event)
        match result:
            case Ok(state=s):
                print(f"  ok        balance={s['balance']}")
            case Warning(state=s, why=w):
                print(f"  warning   balance={s['balance']}  ({w.rule}: {w.message})")
            case Impossible(why=w):
                print(f"  rejected  {w.message}")
            case Violated(why=w):
                print(f"  BUG       {w.message}")


if __name__ == "__main__":
    main()
