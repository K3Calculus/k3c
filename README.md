# k3c — Kulkarni Calculus (K3) Python SDK

Design causality, and the system emerges.

```bash
pip install k3c
```

Python 3.12+ | Zero dependencies | MIT License

---

## What is K3?

K3 is a minimal causal calculus for discrete systems. A system is fully determined by specifying:

- What events are **permitted** (guards)
- How state **transforms** (transitions)
- What must **always** be true (invariants)
- What must **eventually** become true (liveness)

The spec IS the implementation. Drift between specification and implementation is structurally impossible because the spec compiles into the system's own guards, transitions, and invariants.

## Quick Start

```python
from k3c import (
    Spec, Permit, Maintain, Universe, Ok, Impossible, Violated,
    Always, Compare, CmpOp, Field, Var, EventField, LInt,
)

# 1. Define the spec (declarative, frozen, serializable)
spec = Spec(
    name="bank",
    state0={"balance": 100},
    permits=(
        Permit(
            name="has_funds",
            on="Withdraw",
            when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
        ),
    ),
    maintains=(
        Maintain(
            name="non_negative",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
        ),
    ),
)

# 2. Write a pure transition function
def bank_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Deposit":
            return {**state, "balance": state["balance"] + event["amount"]}
        case "Withdraw":
            return {**state, "balance": state["balance"] - event["amount"]}
        case _:
            return state

# 3. Create a Universe and apply events
u = Universe(spec=spec, transition=bank_transition)

match u.apply({"type": "Deposit", "amount": 50}):
    case Ok(state=s):       print(s["balance"])      # 150
    case Impossible(why=w): print(w.message)
    case Violated(why=w):   w.raise_()

match u.apply({"type": "Withdraw", "amount": 200}):
    case Ok(state=s):       print(s["balance"])
    case Impossible(why=w): print(w.rule)            # "has_funds"
```

## The Three Results

`apply()` is total — it never raises. It always returns one of:

| Result                      | Meaning                                      | Bug?    |
| --------------------------- | -------------------------------------------- | ------- |
| `Ok(state, ctx, step_hash)` | Guards passed, invariants held               | No      |
| `Impossible(why)`           | Guard rejected event. State unchanged        | No      |
| `Violated(why)`             | Invariant broken. Implementation diverged    | **Yes** |

## The 9-Tuple

A system is a 9-tuple `K3d = (S, S0, E, G, T, N, P, Ctx, L)`:

| Element | Role                        | Defined by                                |
| ------- | --------------------------- | ----------------------------------------- |
| S, S0   | State space & initial state | `state0` dict                             |
| E       | Event space                 | Dicts with `"type"` key                   |
| G       | Guards (admissibility)      | `Permit` clauses                          |
| T       | Transition function         | Pure `(state, event) -> state`            |
| N       | Safety invariants           | `Maintain(expr=Always(...))`              |
| P       | Projections (derived views) | `Projection` clauses                      |
| Ctx     | Spec context (witness)      | `Require` clauses                         |
| L       | Liveness obligations        | `Maintain(expr=Always(Eventually(...)))`  |

## Universe Algebra

### Compose (parallel)

```python
def router(event):
    return "right" if event.get("type", "").startswith("Pay") else "left"

composed = order_u.compose(payment_u, router)
composed.apply({"type": "PlaceOrder", "amount": 100})  # routes to order_u
composed.apply({"type": "PayInvoice", "amount": 100})  # routes to payment_u
```

### Bridge (cross-universe)

```python
from k3c import BridgeMode

audited = order_u.bridge(
    audit_u,
    mapper=lambda s, e, ns: {"type": "AuditEntry", "action": e.get("type")},
    mode=BridgeMode.SYNCHRONOUS,
)
```

Bridge modes: `SYNCHRONOUS` (atomic), `ASYNC` (source first), `BEST_EFFORT` (fire and forget).

## Fuzz Testing (KC-5)

```python
report = u.fuzz(sequences=1000, steps=100, seed=42)

if not report.passed:
    v = report.violations[0]
    print(f"Violation: {v.violated.why.rule}")
    print(f"Minimal reproducer: {v.shrunk_sequence}")
```

## Explain (Debugging)

```python
trace = u.explain({"type": "Withdraw", "amount": 500})
print(trace.summary())

for entry in trace.trace:
    print(f"{entry.phase}: {entry.clause} -> {entry.verdict}")
```

## Simulate + Replay (KC-3)

```python
run = u.simulate(events)
for t in range(run.processed):
    print(f"Step {t}: {run.state_at(t)}")

# Replay for determinism verification
u2 = Universe(spec=spec, transition=bank_transition)
replay = u2.replay(events, expected_hashes=run.step_hashes)
assert replay.passed
```

## Parallel Processing

```python
from k3c import parallel_reduce

specs = [spec.slice(from_state=checkpoint, events=["RT3"]) for checkpoint in checkpoints]
result = parallel_reduce(transition=fn, specs=specs, chunks=chunks, workers=8)
assert result.passed
```

## Hash Chain

Every step produces a tamper-evident chained hash:

```
step_hash = SHA-256(state, event, prev_step_hash)
```

Pluggable: `sha256` (default), `blake2b` (2x faster), `blake3` (4-6x, `pip install blake3`).

## KC Compliance Levels

| Level | Name           | What it adds             |
| ----- | -------------- | ------------------------ |
| KC-1  | Core Semantics | S, S0, E, G, T, N       |
| KC-2  | Observable     | + Projections (P)        |
| KC-3  | Traceable      | + Replay (Samsara)       |
| KC-4  | Compositional  | + Compose, Bridge        |
| KC-5  | Verified       | + Fuzz, Verify           |
| KC-6  | Certified      | + Signed step_hash chain |

## Architecture

```
k3c.ir       — K3l expression IR (43 nodes), eval(), serde, type system
k3c.spec     — Declarative Spec model, compile, extractors
k3c.engine   — Apply pipeline, SpecCtx, results, explain
k3c.runtime  — Universe, compose, bridge, isolate, parallel, samsara
k3c.emit     — Code emission (Python, TypeScript, SQL)
k3c.testing  — Fuzz testing with automatic shrinking
```

---

[k3c.dev](https://k3c.dev) | Python 3.12+ | Zero dependencies | MIT License
