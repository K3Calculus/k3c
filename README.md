# k3c — Kulkarni Calculus (K3) Python SDK

Design causality, and the system emerges.

```bash
pip install k3c
```

Python 3.12+ | Zero dependencies

---

## What is K3?

K3 is a minimal causal calculus for discrete systems. A system is fully determined by specifying:

- What events are **permitted** (guards)
- How state **transforms** (transitions)
- What must **always** be true (invariants)
- What must **eventually** become true (liveness)

The spec IS the implementation. `universe()` compiles the spec into the system's own guards, transitions, and invariants. Drift is structurally impossible.

## Quick Start

```python
from k3c import (
    Spec, universe, Ok, Impossible, Violated,
    Compare, CmpOp, Field, Var, EventField, Always, LInt, LBool,
)

# 1. Define the spec (I, U, K)
spec = (
    Spec("bank_account")
    .state0({"balance": 100})
    .permit("has_funds",
        when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
        on="Withdraw")
    .maintain("non_negative",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))))
    .project("balance_view", lambda s: s["balance"])
    .build()
)

# 2. Implement the system (just the transition function)
class BankSystem:
    def transition(self, state, event):
        if event.get("type") == "Withdraw":
            return {**state, "balance": state["balance"] - event["amount"]}
        if event.get("type") == "Deposit":
            return {**state, "balance": state["balance"] + event["amount"]}
        return state

# 3. Create a Universe
u = universe(BankSystem(), spec)

# 4. Apply events — the spec enforces everything
match u.apply({"type": "Withdraw", "amount": 50}):
    case Ok(state=s):
        print(f"Balance: {s['balance']}")        # Balance: 50
    case Impossible(why):
        print(f"Rejected: {why.message}")         # Guard denied
    case Violated(why):
        print(f"BUG: {why.message}")              # Invariant broken
        why.raise_()                              # Escalate if desired
```

## The Three Variants

| Variant                     | Meaning                                                | Bug?    |
| --------------------------- | ------------------------------------------------------ | ------- |
| `Ok(state, ctx, step_hash)` | Success. Guards passed, invariants held.               | No      |
| `Impossible(why)`           | Guard rejected. Precondition not met. State unchanged. | No      |
| `Violated(why)`             | Invariant broken. Implementation diverged from spec.   | **Yes** |

## K3.Specs = (I, U, K)

Every spec is a triplet:

| Element            | What it defines                          | Builder method                           |
| ------------------ | ---------------------------------------- | ---------------------------------------- |
| **I** (Initial)    | Domain vocabulary, decode, initial state | `.state0()`, `.field()`, `.decode()`     |
| **U** (Unfolding)  | Permitted and required dynamics          | `.permit()`, `.require()`, `.maintain()` |
| **K** (Korrelator) | Correctness measurement                  | `.korrelate()`                           |

```python
spec = (
    Spec("order_system")
    .state0({"status": "pending", "total": 0})

    # Guards — what events are allowed
    .permit("can_confirm",
        when=Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("pending")),
        on="Confirm")

    # Invariants — what must always hold
    .maintain("positive_total",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "total"), LInt(0))))

    # Liveness — what must eventually happen
    .maintain("eventually_ships",
        expr=Always(Implies(
            Compare(CmpOp.EQ, EventField("type"), LStr("Confirm")),
            Eventually(Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("shipped"))))))

    # Projections — derived views
    .project("summary", lambda s: {"status": s["status"], "total": s["total"]})

    # Outputs — post-causal events
    .output("notify", lambda s, e, ns: {"type": "Notification", "order": ns["status"]},
            on="Confirm")

    .build()
)
```

## Universe Algebra

Universes compose and bridge. The algebra is closed.

### Compose (parallel)

```python
order_u = universe(OrderSystem(), order_spec)
payment_u = universe(PaymentSystem(), payment_spec)

# Route events to left or right
commerce = order_u.compose(payment_u,
    router=lambda e: "right" if e.get("type", "").startswith("Pay") else "left")

commerce.apply({"type": "PlaceOrder", "amount": 100})   # routes to order_u
commerce.apply({"type": "PayInvoice", "amount": 100})    # routes to payment_u
```

### Bridge (cross-universe)

```python
from k3c import BridgeMode

# Every order event triggers an audit event
audited = order_u.bridge(
    audit_u,
    mapper=lambda s, e, ns: {"type": "AuditEvent", "data": e},
    mode=BridgeMode.SYNCHRONOUS,
)
```

Bridge modes: `SYNCHRONOUS` (atomic), `ASYNC` (source first), `BEST_EFFORT` (fire and forget).

## Property-Based Testing (KC-5)

```python
# Fuzz to discharge well-formedness rule 8
report = u.fuzz(sequences=1000, steps=100, seed=42)

if not report.passed:
    v = report.violations[0]
    print(f"Found violation: {v.violated.why.rule}")
    print(f"Minimal sequence: {v.shrunk_sequence}")
```

## Explain (Debugging)

```python
# Dry-run without mutating state
result = u.explain({"type": "Withdraw", "amount": 500})

print(result.summary())
# ExplainResult: Impossible
#   - [guard] has_funds: fail — denied
#   + [safety] non_negative: pass — invariant holds
```

## Parallel Processing

One unified spec, derived slices for parallel chunks:

```python
from k3c import parallel_reduce

# Derive specs from DFA checkpoints
chunks = partition(records, workers=8)
specs = [unified_spec.slice(from_state=checkpoint(chunk)) for chunk in chunks]

result = parallel_reduce(MySystem(), specs, chunks, workers=8)
print(f"Processed {result.total_processed} events")
```

## Hash Chain

Every step produces a tamper-evident chained hash:

```text
step_hash = SHA-256(state, event, prev_step_hash)
```

Pluggable: `sha256` (default, KC-6), `blake2b` (2x faster), `blake3` (4-6x, optional dep).

```python
u = universe(system, spec, hash_fn="blake2b")
```

## KC Compliance Levels

| Level | Name           | What it adds             |
| ----- | -------------- | ------------------------ |
| KC-1  | Core Semantics | S, S0, E, G, T, N        |
| KC-2  | Observable     | + Projections (P)        |
| KC-3  | Traceable      | + Replay (Samsara)       |
| KC-4  | Compositional  | + Compose, Bridge        |
| KC-5  | Verified       | + Fuzz, Verify           |
| KC-6  | Certified      | + Signed step_hash chain |

## Domain Examples

K3 applies to any system with discrete causal dynamics:

- **Banking** — balance guards, transaction invariants
- **Protocols** — TCP sequence monotonicity, MQTT QoS delivery
- **Distributed systems** — Raft term monotonicity, election liveness
- **Scheduling** — SSIM airline schedules, serial continuity
- **State machines** — order lifecycles, workflow engines

## Architecture

```text
k3c.lang     — K3l expression IR, eval(), serde, compile
k3c.spec     — (I, U, K) builder, SpecCtx, K3Result, extractors
k3c.universe — engine, Universe, compose, bridge, fuzz, explain
```

The spec IS the implementation. There is no gap to drift.

---

k3c.dev | Python 3.12+ | Zero dependencies | MIT License
