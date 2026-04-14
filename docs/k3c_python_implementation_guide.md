# k3c Python Implementation Guide

> Authoritative reference for the k3c Python SDK.
> Reflects the actual implementation — not aspirational, not outdated.
>
> k3c v0.1.0 | Python 3.12+ | Zero dependencies | 880 tests | 11 examples

---

## 1. Architecture

```text
k3c/
  __init__.py          Public API surface
  errors.py            7 exception classes
  cache.py             K3LRU, K3Cache, key helpers

  lang/                K3.Lang — the expression layer
    ir.py              43 K3l nodes, 14 K3lType nodes, 4 typed enums
    eval.py            Total interpreter (k3_eval) — truly total, TypeError -> Nothing
    serde.py           K3l + K3lType <-> JSON round-trip
    compile.py         K3Spec -> CompiledSpec with maintain routing
    emit.py            K3l -> TypeScript / SQL / Python emitters

  spec/                K3.Specs — the intent layer
    builder.py         (I, U, K) clause types + fluent Spec builder + to_ir/from_ir
    ctx.py             SpecCtx — the ambient witness (Purusha)
    result.py          K3Result (Ok | Impossible | Violated), Why
    extractor.py       12 extractor types for I.decode

  universe/            K3.Calc — the execution engine
    engine.py          apply() — the causal step pipeline
    universe.py        Universe class, universe() factory, parallel_reduce()
    compose.py         ComposedUniverse (<||>) with mode="parallel"
    bridge.py          BridgedUniverse (<->)
    retry.py           BridgeMode, RetryPolicy, FallbackStrategy
    fuzz.py            Property-based fuzzing with shrinking
    explain.py         Dry-run with full eval trace
    isolate.py         IsolatedUniverse — deep-copy physical isolation
```

---

## 2. The 9-Tuple

K3d (deterministic) is the 7-tuple: `(S, S0, E, G, T, N, P)`.
K3.Specs extends to 9: `(S, S0, E, G, T, N, P, Ctx, L)`.

| Element | Role | Implementation |
| ------- | ---- | -------------- |
| **S** | State space | `dict[str, object]` |
| **S0** | Initial state | `K3Spec.state0` -> `SpecCtx.initial()` |
| **E** | Event space | `dict[str, object]` with `type` field |
| **G** | Guard | `PermitClause.when` (K3l) evaluated by `k3_eval` |
| **T** | Transition | `System.transition(state, event) -> state` |
| **N** | Invariant | `MaintainClause.expr` (Always) + `KorrelatorDef` |
| **P** | Projections | `ProjectionDef.fn(state) -> value` |
| **Ctx** | Ambient witness | `SpecCtx` — flows through every step, never causes |
| **L** | Liveness | `MaintainClause.expr` (Eventually/Within) |

---

## 3. K3.Specs = (I, U, K)

### I -- Initial (domain vocabulary)

| Component | Builder method | What it produces |
| --------- | -------------- | ---------------- |
| Domain fields | `.field(name, type, extract=...)` | `FieldDef` with optional `Extractor` |
| Decode | `.decode(fn)` | `fn: raw_event -> domain_event` |
| Initial state | `.state0({...})` | `Ctx0.spec_state` |

### U -- Unfolding (dynamics)

| Component | Builder method | What it produces |
| --------- | -------------- | ---------------- |
| Permit | `.permit(name, when=K3l, on=...)` | Guard clause -> G |
| Require | `.require(name, on=..., transition=K3l)` | Advances `Ctx.spec_state` -> T |
| Maintain | `.maintain(name, expr=K3l)` | Routed by `compile.py` to N or L |

Maintain clause routing:

| Expression structure | Routes to | 9-tuple |
| -------------------- | --------- | ------- |
| `Always(phi)` | Safety | N |
| `Always(Implies(trigger, Within(phi, n)))` | Bounded liveness | Ctx + N |
| `Always(Implies(trigger, Eventually(phi)))` | Unbounded liveness | L |
| `Always(phi Until psi)` | Until liveness | L |

The classifier scans through `Always`, `Implies`, `And`, `Or`, `Not` to find temporal wrappers at any depth.

### K -- Korrelator (correctness measurement)

| Component | Builder method | What it does |
| --------- | -------------- | ------------ |
| lift | `.korrelate(lift=fn)` | Project impl state -> domain state |
| correlate | `.korrelate(correlate=fn)` | Compare actual vs intended (default: exact equality) |
| threshold | `.korrelate(threshold=fn)` | Pass/fail decision (default: bool identity) |

### P -- Projections

| Component | Builder method | What it does |
| --------- | -------------- | ------------ |
| Derived | `.project(name, fn)` | Pure `S -> value`, included in `Ok.projections` |
| Observable | `.project(name, fn, kind="observable")` | External-facing view |
| Metric | `.project(name, fn, kind="metric")` | Monitoring/alerting value |

### Outputs

| Component | Builder method | What it does |
| --------- | -------------- | ------------ |
| Output | `.output(name, fn, on=...)` | `(state, event, new_state) -> event or None` |

Outputs are post-causal -- computed after T runs and N holds. They appear in `Ok.outputs`.

---

## 4. The apply() Pipeline

```text
step_hash                                        (0. chained hash -- first)
  |
  v
I.decode(e) -> e'                                (1. raw -> domain)
  |
  v
G: eval(permit.when, ctx) -> Some(T)|Some(F)|Nothing   (2. guard check)
  |  Some(False) -> Impossible(Why(kind='permit'))
  |  Nothing     -> Impossible(Why(kind='missing'))
  v
T_impl(s, e') -> s'                              (3. user transition)
  |
  v
U.require(ctx, e') -> ctx'                       (4. advance spec_state)
  |
  v
N: eval(maintain.expr, ctx') -> pass|fail         (5. safety invariants)
  |  fail -> Violated(Why(kind='maintain'))
  v
K: correlate(lift(s'), ctx'.spec_state)           (5b. korrelation)
  |  fail -> Violated(Why(kind='korrelate'))
  v
L: tick_timers + step_obligations                 (6. liveness tracking)
  |  expired -> Violated(Why(kind='timer'))
  v
P: compute projections                           (7. derived views)
  |
  v
Outputs: compute output events                   (8. post-causal emission)
  |
  v
Ctx.advance(spec_state, event, timers, pos, hash) (9. advance context)
  |
  v
Ok(state=s', ctx=ctx', step_hash, projections, outputs)
```

---

## 5. K3l IR -- Expression Nodes

### Typed enums

```python
class CmpOp(StrEnum):   # EQ, NE, LT, LE, GT, GE
class ArithOp(StrEnum):  # ADD, SUB, MUL, DIV
class DateFormat(StrEnum): # ISO8601, YYYYMMDD, SSIM
class TimeFormat(StrEnum): # ISO8601, HHMM, HHMMSS
```

### Tier 1 -- K3lType (14 nodes)

```text
TBool | TInt | TString | TFloat | TUnit
TBytes(length) | TDate(format) | TTime(format) | TEnum(values)
TRecord(fields) | TVariant(variants) | TList(element) | TOption(inner) | TRef(name)
```

### Tier 2 -- K3l (43 nodes)

| Category | Nodes |
| -------- | ----- |
| Literals | `LBool(val)`, `LInt(val)`, `LFloat(val)`, `LStr(val)`, `LList(elements)` |
| Variables | `Var(name)`, `Field(expr, name)`, `Index(expr, idx)`, `EventField(name)`, `Actual(field)`, `Intended(field)` |
| Logic | `And(left, right)`, `Or(left, right)`, `Not(expr)`, `If(cond, then, else_)`, `Implies(left, right)` |
| Comparison | `Compare(op: CmpOp, left, right)` |
| Arithmetic | `Arith(op: ArithOp, left, right)`, `Mod(left, right)`, `Negate(expr)`, `Abs(expr)`, `Min(left, right)`, `Max(left, right)` |
| Option ops | `IsSome(expr)`, `UnwrapOr(expr, default)` |
| Collections | `ForAll(var, collection, predicate)`, `Exists(var, collection, predicate)`, `Length(expr)`, `Contains(collection, element)`, `Map(var, collection, body)`, `Filter(var, collection, predicate)`, `Fold(init, collection, acc_var, elem_var, body)` |
| String ops | `Concat(left, right)`, `Trim(expr)`, `Slice(expr, start, end)`, `Matches(expr, pattern)` |
| Record | `Record(fields)`, `With(base, updates)` |
| Temporal | `Before(field)`, `After(field)` |
| Spec | `Always(expr)`, `Eventually(expr)`, `Within(expr, n)`, `Until(left, right)` |
| Annotation | `Named(name, expr)`, `Described(description, expr)` |

All nodes are `@dataclass(frozen=True)` -- immutable, hashable, safe for pattern matching.

### Option types

```python
@dataclass(frozen=True)
class Some(Generic[T]):
    val: T
    # map, and_then, unwrap, unwrap_or, is_some, is_nothing

@dataclass(frozen=True)
class Nothing:
    field: str       # which field was absent
    step_hash: str   # which apply() call
    # map, and_then, unwrap_or (returns default), raise_()
    # Propagates like NaN -- never raises, short-circuits everything

type K3Option[T] = Some[T] | Nothing
```

### k3_eval()

```python
def k3_eval(expr: K3l, ctx: dict[str, object], step_hash: str = "") -> K3Option[object]
```

Total interpreter. Never raises. Boolean enforcement: `And`, `Or`, `Not`, `If`, `Implies` return `Nothing("expected-bool")` for non-boolean operands. Div by zero returns `Nothing("div-by-zero")`.

### Serde

```python
def to_dict(node: K3l) -> dict[str, object]     # K3l -> JSON-ready dict
def from_dict(data: dict[str, object]) -> K3l    # dict -> K3l (validates types)
def type_to_dict(node: K3lType) -> dict[str, object]
def type_from_dict(data: dict[str, object]) -> K3lType
```

---

## 6. K3Result -- Return Types

```python
type K3Result[T] = Ok[T] | Impossible | Violated
```

| Variant | Meaning | Bug? | State changed? |
| ------- | ------- | ---- | -------------- |
| `Ok(state, ctx, step_hash, projections, outputs)` | Success | No | Yes |
| `Impossible(why)` | Guard rejected | No | No |
| `Violated(why)` | Invariant broken | **Yes** | No |

### Ok fields

```python
state: T                           # new state S' after T ran
ctx: SpecCtx                      # new context for next apply()
step_hash: str                    # SHA-256 chained hash
projections: dict[str, object]    # P -- derived views (empty if none defined)
outputs: tuple[dict, ...]         # post-causal output events (empty if none)
```

### Why -- complete causal record

```python
rule: str              # which spec rule produced this
kind: WhyKind          # permit | missing | maintain | korrelate | timer | liveness
messages: tuple[str, ...]
before: dict[str, object]
after: dict[str, object] | None   # None for Impossible (T never ran)
event: dict[str, object]
ctx: SpecCtx
expected: dict[str, object] | None
trace: tuple[dict, ...]           # last 16 events (ring buffer)
step_hash: str
fingerprint: str                  # SHA-256[:16] stable dedup key
```

---

## 7. Universe API

### Factory

```python
u = universe(system, spec, id="", hash_fn="sha256")
```

Runs well-formedness validation (rules 1, 3) at construction. Caches compiled specs.

### Core operations

```python
u.apply(event)              # one causal step -> K3Result
u.reduce(events)            # fold, stops on first non-Ok
u.reduce_all(events)        # skips Impossible, stops on Violated -> ReduceAllResult
u.reset()                   # restore initial state and ctx
```

### Debugging and testing

```python
u.explain(event)            # dry-run with full eval trace -> ExplainResult
u.fuzz(sequences=1000, steps=100, seed=0)  # property-based testing -> FuzzReport
u.cache_stats()             # cache hit/miss statistics
```

### Algebra

```python
u.compose(other, router)    # <||> parallel composition -> ComposedUniverse
u.bridge(other, mapper, mode)  # <-> cross-universe -> BridgedUniverse
```

### Parallel processing

```python
parallel_reduce(system, specs, chunks, workers=4)  # -> ParallelReduceResult
spec.slice(from_state, events)                      # derive sub-spec from DFA checkpoint
```

---

## 8. System Protocol

```python
class System(Protocol):
    def transition(self, state: dict[str, object], event: dict[str, object]) -> dict[str, object]:
        ...
```

The implementor provides only the transition function. Everything else comes from the spec.

---

## 9. Composition Algebra

### Compose

```python
composed = u1.compose(u2, router=lambda e: "left" | "right" | "both")
```

Router returns `"left"`, `"right"`, or `"both"`. Result merging: `Violated > Impossible > Ok`. Product state: `{"left": ..., "right": ...}`.

### Bridge

```python
bridged = u1.bridge(u2, mapper, mode=BridgeMode.SYNCHRONOUS, retry=..., fallback=...)
```

Mapper: `(state, event, new_state) -> target_event | None`. Returns `None` to skip.

| Mode | Behavior |
| ---- | -------- |
| `SYNCHRONOUS` | Atomic -- both succeed or neither. Target Violated propagates. |
| `ASYNC` | Source commits first. Target failure -> dead letter (if configured). |
| `BEST_EFFORT` | Fire and forget. Target failure silently ignored. |

Failure handling:

| Strategy | Behavior |
| -------- | -------- |
| `FAIL` | Raise `K3BridgeError` |
| `IGNORE` | Swallow failure, source Ok stands |
| `DEAD_LETTER` | Record `DeadLetterEntry`, source Ok stands |

```python
RetryPolicy.no_retry()                    # 1 attempt
RetryPolicy.fixed_delay(n=3, delay_ms=100)
RetryPolicy.exponential_backoff(n=5, base_ms=50)
```

The algebra is closed: `ComposedUniverse` and `BridgedUniverse` both support `.compose()` and `.bridge()`.

---

## 10. Fuzz Testing (KC-5)

```python
report = u.fuzz(
    sequences=1000,    # independent event sequences
    steps=100,         # max events per sequence
    seed=42,           # RNG seed (0 = time-based)
    max_violations=1,  # stop after N violations
    shrink=True,       # minimize reproducing sequence
)
```

Auto-detects event types from permit `on` filters. Custom generator:

```python
def my_gen(state: dict, rng: random.Random) -> dict:
    return {"type": rng.choice(["A", "B"]), "n": rng.randint(0, 100)}

report = u.fuzz(event_generator=my_gen)
```

`FuzzReport` fields: `passed`, `violations`, `sequences_run`, `total_steps`, `impossible_count`, `elapsed_ms`, `seed`.

`FuzzViolation` fields: `original_sequence`, `shrunk_sequence`, `violated`, `step_index`.

---

## 11. Explain (Debugging)

```python
result = u.explain(event)  # state is NOT mutated
print(result.summary())
```

Traces every phase: `DECODE`, `GUARD`, `TRANSITION`, `SAFETY`, `KORRELATION`, `LIVENESS`.

Each `TraceEntry`: phase, clause name, verdict (`PASS`/`FAIL`/`SKIP`/`NOTHING`/`ERROR`), detail, value.

---

## 12. Hash Chain

Every step produces a chained hash:

```text
step_hash = hash(state, event, prev_step_hash)
```

Chain root is `""` (empty string). Altering any step changes all subsequent hashes.

| hash_fn | Source | Speed | KC-6 |
| ------- | ------ | ----- | ---- |
| `sha256` | stdlib | 1x baseline | Required |
| `blake2b` | stdlib | ~2x | No |
| `blake3` | pip install blake3 | ~4-6x | No |

---

## 13. Caching

Each `CompiledSpec` carries a `K3Cache` instance:

| Cache layer | Key | What's cached |
| ----------- | --- | ------------- |
| `spec_invariant` | step_hash | Safety check results |
| `lang_compiled` (process-level) | content hash | CompiledSpec from same K3Spec |

`u.cache_stats()` returns hit/miss/size/hit_rate for all layers.

---

## 14. Extractors (I.decode)

12 portable extractor types for field extraction from raw events:

| Type | Domain |
| ---- | ------ |
| `ByteSlice(start, length, encoding)` | SSIM, COBOL, binary |
| `BitField(byte_offset, bit_offset, width)` | CAN bus, TCP flags |
| `JsonPath(path)` | REST APIs |
| `XmlPath(path)` | SOAP, XML |
| `MapKey(key)` | HL7, generic dicts |
| `FieldNum(number)` | Protobuf |
| `AvroField(name)` | Kafka + Avro |
| `ColumnName(name)` / `ColumnIdx(index)` | SQL |
| `Computed(expr: K3l)` | Derived fields |
| `Switch(discriminant, cases)` | Multi-format protocols |
| `Identity()` | Already typed -- zero cost |

---

## 15. Well-Formedness Rules

| Rule | Statement | Checked at |
| ---- | --------- | ---------- |
| 1 | `S != {}` -- state0 non-empty | Construction |
| 3 | `N(S0) = true` -- initial state passes invariants | Construction |
| 5-7 | Guard/transition/invariant totality | Type system (Option, K3Result) |
| 8 | `N(S0) ^ G(s,e) => N(T(s,e))` -- preservation | `fuzz()` |

Temporal invariants (Before/After) are skipped during construction validation (no prev_state yet).

---

## 16. Concurrency Model

**Axiom: a single Universe is sequential.** Concurrency lives between Universes.

| Need | Expression |
| ---- | ---------- |
| Two systems run simultaneously | `u1.compose(u2, router)` |
| Fire-and-forget side effect | `u1.bridge(u2, mapper, ASYNC)` |
| Multiple sessions | `N x universe(...).isolate()` |
| Multiple invariants | Multiple `.maintain()` -- all enforced each step |
| Timer + events | `Within(phi, n)` -- all timers tick every step |

### parallel_reduce()

```python
chunks = partition(records, workers=8)
specs = [unified_spec.slice(from_state=checkpoint(chunk)) for chunk in chunks]
result = parallel_reduce(System(), specs, chunks, workers=8)
```

Version-adaptive: `InterpreterPoolExecutor` (3.14+) or `ProcessPoolExecutor` (3.12+). Sequential fallback for `workers=1`.

### spec.slice()

Derives a sub-spec from a DFA checkpoint. Same maintain/korrelate, new `state0`, filtered permits. The derived spec IS the unified spec, resumed.

---

## 17. Error Hierarchy

```text
K3Error (base)
  K3NothingException     Nothing.raise_() -- field absent
  K3ViolatedException    Violated.raise_() -- spec diverged
  K3WellFormednessError  universe() construction failed
  K3BridgeError          bridge delivery failed
  K3ComposeError         composition failed
  K3SchemaError          k3l_ir JSON invalid
  K3SerdeError           serde round-trip failed
```

The engine never raises. Exceptions are caller opt-in only.

---

## 18. KC Compliance Levels

| Level | Name | What it adds |
| ----- | ---- | ------------ |
| KC-1 | Core Semantics | S, S0, E, G, T, N |
| KC-2 | Observable | + P (projections) |
| KC-3 | Traceable | + Replay (Samsara) |
| KC-4 | Compositional | + Compose, Bridge |
| KC-5 | Verified | + Fuzz, Verify |
| KC-6 | Certified | + Signed step_hash chain (sha256 mandatory) |

---

## 19. Complete Examples

### Bank Account

```python
from k3c import (
    Spec, universe, Ok, Impossible, Violated,
    Compare, CmpOp, Field, Var, EventField, Always, LInt,
)

spec = (
    Spec("bank")
    .state0({"balance": 100})
    .permit("has_funds",
        when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
        on="Withdraw")
    .maintain("non_negative",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))))
    .project("balance", lambda s: s["balance"])
    .output("receipt",
        lambda s, e, ns: {"type": "Receipt", "balance": ns["balance"]},
        on="Withdraw")
    .build()
)

class BankSystem:
    def transition(self, state, event):
        match event.get("type"):
            case "Withdraw":
                return {**state, "balance": state["balance"] - event["amount"]}
            case "Deposit":
                return {**state, "balance": state["balance"] + event["amount"]}
            case _:
                return state

u = universe(BankSystem(), spec)

# Apply
r = u.apply({"type": "Withdraw", "amount": 30})
assert isinstance(r, Ok)
assert r.projections["balance"] == 70
assert r.outputs[0]["type"] == "Receipt"

# Reduce
u.reset()
r = u.reduce([
    {"type": "Deposit", "amount": 50},
    {"type": "Withdraw", "amount": 20},
])
assert u.state["balance"] == 130

# Fuzz
u.reset()
report = u.fuzz(sequences=100, steps=20, seed=42)
assert report.passed

# Explain
u.reset()
explanation = u.explain({"type": "Withdraw", "amount": 500})
assert not explanation.passed
print(explanation.summary())
```

### TCP (safety + liveness)

```python
from k3c import (
    Spec, universe,
    Always, Implies, Eventually, Within, Before, After,
    Compare, CmpOp, Field, Var, EventField, LStr,
)

tcp_spec = (
    Spec("tcp")
    .state0({"state": "CLOSED", "snd_nxt": 0, "snd_wnd": 65535})

    .permit("ok", when=LBool(True))

    # Safety: sequence monotone
    .maintain("seq_monotone",
        expr=Always(Compare(CmpOp.GE, After("snd_nxt"), Before("snd_nxt"))))

    # Bounded liveness: TIME_WAIT closes within 240 steps
    .maintain("time_wait_2msl",
        expr=Always(Implies(
            Compare(CmpOp.EQ, Field(Var("state"), "state"), LStr("TIME_WAIT")),
            Within(Compare(CmpOp.EQ, Field(Var("state"), "state"), LStr("CLOSED")), n=240))))

    # Unbounded liveness: handshake completes
    .maintain("handshake_completes",
        expr=Always(Implies(
            Compare(CmpOp.EQ, Field(Var("state"), "state"), LStr("SYN_SENT")),
            Eventually(Compare(CmpOp.EQ, Field(Var("state"), "state"), LStr("ESTABLISHED"))))))

    .build()
)
```

### Compose + Bridge

```python
from k3c import Spec, universe, BridgeMode, LBool

order_u = universe(OrderSystem(), order_spec)
payment_u = universe(PaymentSystem(), payment_spec)
audit_u = universe(AuditSystem(), audit_spec)

# Compose: route events
commerce = order_u.compose(payment_u,
    router=lambda e: "right" if e.get("type", "").startswith("Pay") else "left")

# Bridge: order events -> audit log
audited_commerce = commerce.bridge(
    audit_u,
    mapper=lambda s, e, ns: {"type": "AuditEvent", "data": e},
    mode=BridgeMode.ASYNC,
)

# The algebra is closed
audited_commerce.apply({"type": "PlaceOrder", "amount": 100})
```

### Parallel SSIM Processing

```python
from k3c import Spec, parallel_reduce

unified_spec = (
    Spec("ssim")
    .state0({"phase": "START", "serial": 0})
    .permit("rt3", when=LBool(True), on="ParseRT3")
    .maintain("serial_inc",
        expr=Always(Compare(CmpOp.GE, After("serial"), Before("serial"))))
    .build()
)

# Derive specs for each chunk
chunks = partition(rt3_records, workers=8)
specs = [
    unified_spec.slice(
        from_state={"phase": "IN_CARRIER", "serial": chunk[0]["serial"]},
        events=["ParseRT3"],
    )
    for chunk in chunks
]

result = parallel_reduce(SsimParser(), specs, chunks, workers=8)
assert result.passed
```

---

## 20. k3l_ir JSON Export

```python
# Export
ir = spec.to_ir()           # -> dict with all K3l expressions serialized
ir_json = spec.to_ir_json() # -> formatted JSON string

# Import
restored = K3Spec.from_ir(json.loads(ir_json))
```

The k3l_ir is the portable, version-controlled representation. It serializes all K3l expressions but NOT Python callables (projections, outputs, korrelator, decode). Those are marked with portable signatures:

```json
{
  "projections": [{
    "name": "balance",
    "kind": "derived",
    "portable": false,
    "signature": {
      "parameters": [{"name": "state", "type": "Record"}],
      "returns": "Int",
      "description": "Return the current balance."
    }
  }]
}
```

Content-addressed `ir_hash` (SHA-256) covers only the portable K3l parts. Same spec with different callable implementations produces the same hash. Round-trips are hash-stable.

---

## 21. Emitters — K3l to Target Languages

```python
from k3c.lang.emit import to_typescript, to_sql, to_python

expr = Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount"))
```

| Target | Output |
| ------ | ------ |
| TypeScript | `(state.balance >= event.amount)` |
| SQL | `(state.balance >= event.amount)` |
| Python | `(state["balance"] >= event["amount"])` |

Key mappings:

| K3l | TypeScript | SQL | Python |
| --- | ---------- | --- | ------ |
| `Compare(EQ)` | `===` | `=` | `==` |
| `And` | `&&` | `AND` | `and` |
| `IsSome` | `!= null` | `IS NOT NULL` | `is not None` |
| `UnwrapOr` | `??` | `COALESCE` | `if x is not None else` |
| `Before/After` | `before./after.` | `OLD./NEW.` | `prev_state[]/new_state[]` |
| `ForAll` | `.every()` | unsupported | `all()` |
| `Map` | `.map()` | unsupported | list comprehension |
| `Fold` | `.reduce()` | unsupported | `functools.reduce` |

---

## 22. Isolation

```python
isolated = u.isolate()  # deep-copy, no shared state
r = isolated.apply(event)
```

No Python objects shared between original and isolated. Used for:

- Parallel fuzz workers
- Multi-tenant sessions
- Speculative execution (try then discard)

---

## 23. Compose Parallel Mode

```python
composed = u1.compose(u2, router=lambda e: "both")
r = composed.apply(event, mode="parallel")  # ThreadPoolExecutor
```

Both sides run simultaneously. Safe because Universes share no state. Results merge deterministically: `Violated > Impossible > Ok`.

---

## 24. Hypothesis Testing

```python
# pip install hypothesis (dev dependency)
from hypothesis import given, strategies as st

@given(expr=st_k3l(2), ctx=st_eval_ctx)
def test_eval_never_raises(expr, ctx):
    result = k3_eval(expr, ctx, "hash")
    assert isinstance(result, (Some, Nothing))  # truly total
```

Properties verified:

1. `eval()` is total — never raises for ANY K3l expression + context
2. Serde round-trip — `from_dict(to_dict(x)) == x` for all nodes
3. Hash chain is deterministic — same inputs always produce same hash
4. `apply()` is total — always returns `K3Result`, never raises
5. Nothing propagation — empty context doesn't crash
6. IR hash is stable across round-trips

---

k3c.dev | "Design causality, and the system emerges."
