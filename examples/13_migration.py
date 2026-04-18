"""13 — Schema Migration

Specs accumulate fields over time. Migrations upgrade old state to the
current schema version automatically on Universe construction.

Demonstrates:
- Spec(version=N, migrations=(...))
- Migration(from_version, to_version, transform=Expr)
- Old state with __schema_version__ < spec.version is migrated automatically
- Chained migrations (v1 → v2 → v3)
"""

from __future__ import annotations

from k3c import (
    LStr,
    Migration,
    Permit,
    S,
    Spec,
    Universe,
    Var,
    With,
    k3,
)


# Spec at version 3:
#   v1 had only "balance"
#   v2 added "currency" (default "USD")
#   v3 added "tier" (default "standard")
spec_v3 = Spec(
    name="account",
    state0={
        "balance": 100,
        "currency": "USD",
        "tier": "standard",
        "__schema_version__": 3,
    },
    permits=(Permit(name="ok", when=k3(S.balance >= 0)),),
    version=3,
    migrations=(
        # v1 -> v2: add "currency"
        Migration(
            from_version=1,
            to_version=2,
            transform=With(Var("state"), (("currency", LStr("USD")),)),
        ),
        # v2 -> v3: add "tier"
        Migration(
            from_version=2,
            to_version=3,
            transform=With(Var("state"), (("tier", LStr("standard")),)),
        ),
    ),
)


def main() -> None:
    # Old v1 state from disk — only has "balance"
    v1_state = {"balance": 500, "__schema_version__": 1}
    print(f"v1 state from disk: {v1_state}")

    # Universe construction auto-migrates
    u = Universe(
        spec=spec_v3,
        transition=lambda s, e: s,
        state=v1_state,
        validate=False,
    )
    print(f"\nAfter migration to v3:")
    print(f"  state: {u.state}")
    print(f"  current schema version: {u.get('__schema_version__')}")

    # v2 state also gets upgraded
    print()
    v2_state = {"balance": 200, "currency": "EUR", "__schema_version__": 2}
    u2 = Universe(spec=spec_v3, transition=lambda s, e: s, state=v2_state, validate=False)
    print(f"v2 state: {v2_state}")
    print(f"After migration: {u2.state}")

    # Already-current state is unchanged
    print()
    v3_state = {"balance": 1000, "currency": "GBP", "tier": "premium", "__schema_version__": 3}
    u3 = Universe(spec=spec_v3, transition=lambda s, e: s, state=v3_state, validate=False)
    print(f"v3 state: {v3_state}")
    print(f"No migration needed: {u3.state}")


if __name__ == "__main__":
    main()
