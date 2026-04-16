# k3c — Implementation Context

> Reference for AI assistants working on the k3c Python SDK.
> Derived from docs/calculus/ — 8 markdown files, 4 docx references.

---

## 1. What K3 Is

K3 (Kulkarni Calculus) is a **minimal causal calculus** for discrete systems. A system is fully determined by specifying: what events are permitted, how state transforms, what must always be true, and what must eventually become true.

The core insight: **the spec IS the implementation**. `spec.wrap(system)` does not attach a monitor — it compiles the spec into the system's own G, T, N. The result has no seam. Drift is structurally impossible.

Philosophical root: **Satkaryavada** (Samkhya) — the effect pre-exists latent in the cause.

---

## 2. The Three Layers

| Layer | Package | Answers | Sanskrit |
|-------|---------|---------|----------|
| **K3.Lang** | `k3c.lang` | How to express? | Avyakta (unmanifest) |
| **K3.Specs** | `k3c.spec` | What should happen? | Prakriti (becoming) |
| **K3.Calc** | `k3c.universe` | How to execute? | Purusha (witness) |

---

## 3. The 9-Tuple

K3d (deterministic) is the 7-tuple: `(S, S₀, E, G, T, N, P)`.
K3.Specs extends to 9: `(S, S₀, E, G, T, N, P, Ctx, L)`.

| Element | Role | Python location |
|---------|------|-----------------|
| **S** | State space | User-defined dict |
| **S₀** | Initial state | `SpecCtx.initial(state0)` |
| **E** | Event space | User-defined dict |
| **G** | Guard (admissibility) | `U.permit` clauses → K3l expressions evaluated by `k3_eval` |
| **T** | Transition | User-supplied function + `U.require` advances `Ctx.spec_state` |
| **N** | Invariant | `U.maintain Always(φ)` + `K.correlate` — checked in `check_invariants` |
| **P** | Projections | `K.lift` views |
| **Ctx** | Ambient witness (Purusha) | `SpecCtx` — flows through every step, never causes |
| **L** | Liveness | `U.maintain Eventually(φ)` → temporal obligations |

---

## 4. K3.Specs = (I, U, K)

### I — Initial (domain vocabulary)
- `I.domain`: type definitions (K3lType nodes)
- `I.decode`: raw event → domain event (extractors)
- `I.state₀`: initial spec state → `Ctx₀.spec_state`

### U — Unfolding (permitted & required dynamics)
- `U.permit`: guard clauses — K3l expressions evaluated against `Ctx.spec_state`
- `U.require`: transition clauses — advance `Ctx.spec_state` alongside impl state
- `U.maintain`: invariant clauses, routed by structure:

| Expression | Routes to | Mechanism |
|------------|-----------|-----------|
| `Always(φ)` | **N** (safety) | Checked every step in `check_invariants` |
| `Always(Within(φ, n))` | **Ctx + N** | Timer in `Ctx.ob_timers`, expired = Violated |
| `Always(Eventually(φ))` | **L** (liveness) | Unbounded temporal obligation |

### K — Korrelator (correctness measurement)
- `K.lift`: project impl state → domain state
- `K.correlate`: compare `K.lift(S)` (actual) vs `Ctx.spec_state` (intended)
- `K.threshold`: pass/fail — KC level is a K preset

---

## 5. The apply() Pipeline

```
Apply₉(s, ctx, e) =
  1. step_hash = SHA-256(s, e, prev_step_hash)    # chained, tamper-evident
  2. e' = I.decode(e)                              # raw → domain
  3. G check: eval(permit.when_expr) → Some(True) | Some(False) | Nothing
     - Some(False) → Impossible(Why(kind='permit'))
     - Nothing     → Impossible(Why(kind='missing'))
  4. s' = T_impl(s, e)                             # user transition
  5. ctx' = U.require(ctx, e')                     # advance spec_state
  6. N check: U.maintain + K.correlate
     - Failed → Violated(Why(kind='maintain' | 'korrelate'))
  7. L track: step_liveness(ctx', obligations)
     - Timer expired → Violated(Why(kind='timer'))
  8. Return Ok(state=s', ctx=ctx', step_hash=h)
```

---

## 6. K3Result — Return Type of apply()

| Variant | Meaning | Bug? |
|---------|---------|------|
| `Ok(state, ctx, step_hash)` | Success. All guards passed, invariants held. | No |
| `Impossible(why)` | Guard rejected. Precondition not met. State unchanged. | No |
| `Violated(why)` | Invariant broken. T ran but spec diverged. | **Yes** |

`Why` carries: rule, kind (WhyKind enum), messages, before, after, event, ctx, expected, trace, step_hash, fingerprint.

---

## 7. Option[T] — Return Type of eval()

| Variant | Meaning |
|---------|---------|
| `Some(val)` | Value present |
| `Nothing(field, step_hash)` | Value absent — propagates like NaN |

Nothing propagates through all compound expressions. `IsSome` absorbs it → `Some(False)`. `UnwrapOr` recovers with a default. `raise_()` is caller opt-in only.

---

## 8. K3l IR — The Expression Nodes

### Typed enums
- `CmpOp`: EQ, NE, LT, LE, GT, GE — used by `Compare.op`
- `ArithOp`: ADD, SUB, MUL, DIV — used by `Arith.op`
- `DateFormat`: ISO8601, YYYYMMDD, SSIM — used by `TDate.format`
- `TimeFormat`: ISO8601, HHMM, HHMMSS — used by `TTime.format`

### Tier 1 — K3lType (what things ARE) — 14 nodes
`TBool | TInt | TString | TFloat | TUnit | TBytes | TDate | TTime | TEnum | TRecord | TVariant | TList | TOption | TRef`

### Tier 2 — K3l (what things DO) — 43 nodes
- **Literals**: `LBool`, `LInt`, `LFloat`, `LStr`, `LList`
- **Variables/access**: `Var`, `Field`, `Index`, `EventField`, `Actual`, `Intended`
- **Logic**: `And`, `Or`, `Not`, `If`, `Implies`
- **Comparison**: `Compare(op: CmpOp, ...)`
- **Arithmetic**: `Arith(op: ArithOp, ...)`, `Mod`, `Negate`, `Abs`, `Min`, `Max`
- **Option ops**: `IsSome`, `UnwrapOr`
- **Collections**: `ForAll`, `Exists`, `Length`, `Contains`, `Map`, `Filter`, `Fold`
- **String ops**: `Concat`, `Trim`, `Slice`, `Matches`
- **Record construction**: `Record`, `With`
- **Temporal**: `Before`, `After`
- **Spec nodes**: `Always`, `Eventually`, `Within`, `Until`
- **Annotation**: `Named`, `Described`

All nodes are `@dataclass(frozen=True)` — immutable, hashable.

Extractors are implemented separately in `k3c/spec/extractor.py` (12 extractor types). Not yet ported from OCaml: `Opaque` (non-portable OCaml source).

---

## 9. Hash Chain

Every step produces a chained hash: `step_hash = SHA-256(state, event, prev_step_hash)`. The chain root is `""` (empty string). Altering any step changes all subsequent hashes.

Pluggable via `hash_fn` parameter at `universe()` construction:
- `sha256` — default, KC-6 mandatory (FIPS 140-2)
- `blake2b` — ~2x faster, stdlib
- `blake3` — ~4-6x faster, requires `pip install blake3`

---

## 10. KC Compliance Levels

| Level | Name | Adds | K preset |
|-------|------|------|----------|
| KC-1 | Core Semantics | S, S₀, E, G, T, N | Local invariant per step |
| KC-2 | Observable | + P (projections) | + derived views |
| KC-3 | Traceable | + Samsara (replay) | + state trajectory tracking |
| KC-4 | Compositional | + compose, bridge | + cross-universe invariants |
| KC-5 | Verified | + fuzz, verify | All proof obligations discharged |
| KC-6 | Certified | + signed step_hash | Regulatory attestation |

---

## 11. Public API

```python
from k3c import Spec, universe, Ok, Impossible, Violated
from k3c import Compare, CmpOp, Field, Var, EventField, Always, LInt, LBool
```

### Universe API

```python
u = universe(system, spec, id="", hash_fn="sha256")

# Core operations
u.apply(event)           → K3Result[dict]       # Ok has .projections and .outputs
u.reduce(events)         → K3Result[dict]       # fold, stops on first non-Ok
u.reduce_all(events)     → ReduceAllResult      # skips Impossible, stops on Violated
u.reset()                → None                 # reset to initial state

# Debugging & testing
u.explain(event)         → ExplainResult        # dry-run with full eval trace
u.fuzz(sequences, steps, seed) → FuzzReport     # property-based testing (KC-5)
u.cache_stats()          → dict                 # cache hit/miss statistics

# Algebra
u.compose(other, router) → ComposedUniverse     # <||> parallel composition
u.bridge(other, mapper, mode) → BridgedUniverse  # <-> with BridgeMode + RetryPolicy

# Top-level functions
parallel_reduce(system, specs, chunks, workers=4) → ParallelReduceResult
spec.slice(from_state, events)                    → K3Spec
```

### Spec Builder API

```python
spec = (
    Spec("name")
    .state0({...})                               # I.state₀
    .field(name, type, extract=...)              # I.domain
    .decode(fn)                                  # I.decode
    .permit(name, when=K3l, on=...)              # U.permit → G
    .require(name, on=..., transition=K3l)       # U.require → T
    .maintain(name, expr=K3l)                    # U.maintain → N or L
    .project(name, fn, kind=...)                 # P — derived/observable/metric
    .output(name, fn, on=...)                    # post-causal output events
    .korrelate(lift=, correlate=, threshold=)    # K
    .protocol_start(pos)                         # DFA start
    .build()                                     # → K3Spec (frozen)
)
```

---

## 12. Well-Formedness Rules

1. `S ≠ ∅` — state0 must be non-empty dict
2. `S₀ ∈ S` — state0 satisfies domain schema
3. `N(S₀) = true` — initial state passes all invariants
4. `E ≠ ∅` — at least one permit clause
5. Guard total — eval() is total (guaranteed by Option)
6. Transition closed — N catches violations
7. Invariant total — check_invariants is total (guaranteed by K3Result)
8. Preservation — `N(S₀) ∧ G(s,e) ⇒ N(T(s,e))` — discharged by `fuzz()` or `verify()`

---

## 13. Implementation Status

### Implementation status — complete

| Module | Tests | Description |
|--------|-------|-------------|
| `k3c/__init__.py` | 21 | Public API: `from k3c import Spec, universe, Ok, ...` |
| `k3c/errors.py` | 30 | Exception hierarchy (7 classes) |
| `k3c/cache.py` | 44 | K3LRU, K3Cache. Wired into engine (invariant) and factory (compiled spec) |
| `k3c/lang/ir.py` | 159 | 14 K3lType + 43 K3l nodes, 4 typed enums |
| `k3c/lang/eval.py` | 223 | Total interpreter — truly total (TypeError → Nothing) |
| `k3c/lang/serde.py` | 65 | K3l + K3lType ↔ JSON round-trip |
| `k3c/lang/compile.py` | 28 | K3Spec → CompiledSpec with maintain routing |
| `k3c/lang/emit.py` | 62 | K3l → TypeScript / SQL / Python emitters |
| `k3c/spec/ctx.py` | 39 | SpecCtx witness |
| `k3c/spec/result.py` | 63 | K3Result (Ok with projections + outputs), Why, WhyKind |
| `k3c/spec/builder.py` | 45 | (I, U, K) builder + projections + outputs + slice + IR export/import |
| `k3c/spec/extractor.py` | 24 | 12 extractor types, TextEncoding enum |
| `k3c/spec/ir_export` | 23 | k3l_ir JSON export/import with portable callable signatures |
| `k3c/universe/engine.py` | 27 | `apply()` — 9-step pipeline (G → T → N → K → L → P → outputs) |
| `k3c/universe/universe.py` | 40 | Universe, `universe()`, `reduce`, `reduce_all`, `parallel_reduce` |
| `k3c/universe/compose.py` | 14 | `<||>` with router, `mode="parallel"`, result merging |
| `k3c/universe/bridge.py` | 17 | `<->` with Sync/Async/BestEffort, retry, fallback, dead letters |
| `k3c/universe/retry.py` | 0 | BridgeMode, FallbackStrategy, RetryPolicy (tested via bridge) |
| `k3c/universe/fuzz.py` | 18 | Property-based fuzzing with shrinking, seeded RNG |
| `k3c/universe/explain.py` | 23 | Dry-run with full eval trace per pipeline phase |
| `k3c/universe/isolate.py` | 0 | IsolatedUniverse — deep-copy isolation (tested via examples) |
| `k3c/universe/projections` | 17 | Projections (P) + outputs on Ok result |
| `hypothesis` | 10 | Property-based testing: eval totality, serde round-trip, hash determinism |

**Total: 880 tests passing. 11 examples.**

### Not yet implemented

| Module | What it does | Priority |
| ------ | ------------ | -------- |
| `k3c/universe/verify.py` | TLA+/Lean/Coq export from K3l | Low |

---

## 14. Determinism Rules

G, T, N must be pure. Forbidden in transitions:
- `now()` → timestamps must arrive in event payloads
- `random()` → use PRNG seed in state, advance deterministically
- `uuid()` → arrive via event payloads
- External I/O → all inputs must be events

---

## 15. Bridge Modes

| Mode | Consistency | Delivery |
|------|-------------|----------|
| Synchronous | Strong | Atomic — both succeed or neither |
| Async | Eventual | Source commits first, target later |
| BestEffort | Weak | No delivery guarantee |

Failure handling: `RetryPolicy` (NoRetry / FixedDelay / ExponentialBackoff) + `FallbackStrategy` (Fail / Ignore / DeadLetter / Compensate).

---

## 16. Concurrency & Parallelism

**Axiom: a single Universe is sequential.** One cause, one effect, one atomic `apply()`. This preserves step_hash determinism, exact replay, TLA+ verification, and formal proofs. Concurrency lives *between* Universes, not inside them.

### Where concurrency is expressed

| Concurrent need | K3 expression | Mechanism |
| --------------- | ------------- | --------- |
| Two systems run simultaneously | `u1.compose(u2, router)` | Each Universe sequential, composite concurrent |
| Fire-and-forget side effect | `u1.bridge(u2, mapper, Async)` | Source commits first, target later |
| Multiple sessions | N x `universe(...).isolate()` | Each own GIL, own memory |
| Multiple invariants hold | Multiple `.maintain()` clauses | All checked every step — concurrent obligations, sequential enforcement |
| Timer runs while events happen | `Within(φ, n)` | All timers tick simultaneously in `Ctx.ob_timers` |

### compose(mode="parallel")

When two composed Universes share no state (always true by construction), their `apply()` calls can run simultaneously. Uses subinterpreters (Python 3.14+) or ProcessPoolExecutor (3.12+). Results merge deterministically: `Violated > Impossible > Ok`.

### Unified spec and spec.slice()

One canonical **unified spec** per domain — the source of truth. Cross-record invariants (serial continuity, RT3 dates vs RT2 context) can only be expressed here.

`spec.slice(from_state, events)` derives a parallel-safe sub-spec from a DFA checkpoint:

- `from_state` becomes the new `state₀`
- `events` filters permits to the active event set
- Maintain clauses and korrelator are **unchanged** — same causal laws
- The derived spec IS the unified spec, resumed

### parallel_reduce()

Process chunks in parallel using derived specs:

```python
chunks = partition(records, workers=8)
leg_specs = [unified_spec.slice(from_state=checkpoint(chunk)) for chunk in chunks]
result = parallel_reduce(specs=leg_specs, chunks=chunks, workers=8)
```

---

## 17. Verification Templates

| Template | Pattern | K3.Specs clause |
|----------|---------|-----------------|
| Monotonicity | `x ≤ max` | `.permit()` + `.maintain(always=...)` |
| Conservation | `sum(field) = const` | `.maintain(always=...)` |
| State machine | `status ∈ reachable(s₀)` | `.permit(when=...)` |
| Referential integrity | `∀ref: ref ∈ targets` | `.permit(when=...)` |
| Response (causal) | `□(trigger ⇒ ◇guarantee)` | `.liveness(trigger=..., guarantee=...)` |

---

## 18. Key Design Decisions

1. **K3d first**: The Python SDK implements deterministic K3d. K3q (distributional) is a future extension.
2. **9-tuple, not 7**: Ctx and L are first-class — no composition hacks to attach monitoring.
3. **Total functions**: `eval()` never raises (returns Option). `apply()` never raises (returns K3Result). The two exception classes (`K3NothingException`, `K3ViolatedException`) are caller opt-in only.
4. **Frozen dataclasses**: All IR nodes and SpecCtx are `@dataclass(frozen=True)` — immutable, hashable.
5. **Content-addressed caching**: All cache keys are hashes — correctness unaffected by eviction.
6. **Zero dependencies**: Only Python stdlib. Optional `blake3` for faster hashing.
7. **Sequential Universe**: Each Universe is sequential — concurrency lives between Universes via compose/bridge/isolate, not inside them.
8. **Unified spec**: One canonical spec per domain. `spec.slice()` derives parallel-safe sub-specs from DFA checkpoints.
