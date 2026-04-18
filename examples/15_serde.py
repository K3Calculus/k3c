"""15 — Spec Serde (portable JSON wire format)

Specs are 100% data — no Python callables. They round-trip through JSON.
Useful for cross-language deployment, config files, spec registries.

Demonstrates:
- spec_to_dict / spec_from_dict — full Spec round-trip
- expr_to_dict / expr_from_dict — individual expressions
- All clause types preserved (Permit, Maintain, Validate, Output, Migration)
- IR sugar produces the same dict as hand-written IR
"""

from __future__ import annotations

import json

from k3c import (
    Always,
    E,
    EventDef,
    FieldDef,
    LStr,
    Maintain,
    Output,
    Permit,
    Record,
    S,
    Severity,
    Spec,
    Universe,
    Validate,
    expr_from_dict,
    expr_to_dict,
    k3,
    spec_from_dict,
    spec_to_dict,
)
from k3c.ir.types import TInt, TString


def main() -> None:
    # 1. Build a rich spec using sugar
    spec = Spec(
        name="bank",
        state0={"balance": 100, "currency": "USD"},
        events=(
            EventDef(name="Deposit", fields=(FieldDef(name="amount", type=TInt()),)),
            EventDef(name="Withdraw", fields=(FieldDef(name="amount", type=TInt()),)),
        ),
        permits=(
            Permit(name="has_funds", on="Withdraw", when=k3(S.balance >= E.amount)),
        ),
        validates=(
            Validate(
                name="positive_amount",
                on="Withdraw",
                check=k3(E.amount > 0),
                field="amount",
                constraint="> 0",
                severity=Severity.WARNING,
            ),
        ),
        maintains=(
            Maintain(name="non_neg", expr=Always(k3(S.balance >= 0))),
        ),
        outputs=(
            Output(name="receipt", on="Withdraw",
                   expr=Record((("type", LStr("Receipt")),))),
        ),
    )

    # 2. Serialize to plain dict / JSON
    d = spec_to_dict(spec)
    json_str = json.dumps(d, indent=2)
    print(f"Serialized spec: {len(json_str)} bytes")
    print(f"Top-level keys: {list(d.keys())}")

    # 3. Round-trip back to a Spec
    restored = spec_from_dict(json.loads(json_str))
    print(f"\nRestored: name={restored.name}")
    print(f"  permits: {len(restored.permits)}")
    print(f"  validates: {len(restored.validates)}  (severity preserved: {restored.validates[0].severity})")
    print(f"  maintains: {len(restored.maintains)}")
    print(f"  outputs: {len(restored.outputs)}")
    print(f"  events: {[e.name for e in restored.events]}")

    # 4. Use the restored spec — should behave identically
    print("\n== Behavior of restored spec ==")

    def transition(s, e):
        if e["type"] == "Deposit":
            return {**s, "balance": s["balance"] + e["amount"]}
        if e["type"] == "Withdraw":
            return {**s, "balance": s["balance"] - e["amount"]}
        return s

    u = Universe(spec=restored, transition=transition)
    for evt in [{"type": "Withdraw", "amount": 30}, {"type": "Withdraw", "amount": 200}]:
        result = u.apply(evt)
        print(f"  {evt}  -> {type(result).__name__}")

    # 5. Individual expression round-trip
    print("\n== Expression round-trip ==")
    expr = k3((S.balance >= E.amount) & (S.balance > 0))
    expr_dict = expr_to_dict(expr)
    print(f"Expression as dict (first 80 chars):")
    print(f"  {json.dumps(expr_dict)[:80]}...")

    restored_expr = expr_from_dict(expr_dict)
    print(f"Restored expression equal: {expr == restored_expr}")


if __name__ == "__main__":
    main()
