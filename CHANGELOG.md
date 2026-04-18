# Changelog

## v0.4.2 (2026-04-18)

### Features

- **EventDef now enforced at runtime**: when `events=(...)` is declared on a Spec, the engine validates every event between decode and guards. Unknown event types, missing required fields, and wrong field types all produce `Impossible` with rule=`event_schema`. Backwards compatible — when `events` is empty, no enforcement.
- **`Str` IR node** for explicit string coercion in expressions.
- **`LNull` IR literal** for representing `None` in specs (`S.voted_for == None` now works).
- **`before()` / `after()` sugar helpers** for Before/After in temporal invariants.
- **`Concat` auto-coerces non-string operands** so `denied=Concat(LStr("balance="), Field(...))` works without explicit `Str()` wrapping.
- **`compute_step_hash()` exposed publicly** for external attestation verifiers.
- **All 15 examples rewritten** using sugar (S/E/k3), Protocol DSL, denied=, Validate, EventDef, Severity, etc. New examples for attestation, migration, fuzz/explain, and serde.
- **LLMs.txt rewritten** with current API, EventDef enforcement section, full sugar reference.

### Bug fixes

- **`BridgedUniverse` mapper now receives correct `(state_before, event, state_after)`**. Previously it received `state_after` for both before/after, breaking diff-based bridges.

## v0.4.1 (2026-04-18)

### Security

- **`verify_bundle` now performs two-layer verification**: content integrity (recompute step_hash from `prev_step_hash`, `state_before`, `event` and compare) AND authenticity (signature over canonical `(event, state_after, step_hash, result_kind)`). Previous version only checked signature against the recorded step_hash, so an attacker with bundle-write access could swap `event` or `state_after` while signatures still validated.
- **Tamper modes now caught**: `state_before`, `state_after`, `event`, `step_hash`, `prev_step_hash`, `result_kind`, `signature`, and `initial_state`.
- **Bundle wire format bumped to v2**: now records `state_before`, `prev_step_hash`, `result_kind`, and `hash_fn` per step. Required to recompute step hashes independently. Old v1 bundles fail verification.

### Features

- **JSON-primitive discipline**: `AttestationBundle.from_run()` now raises `ValueError` with the offending field path if state or event values contain opaque dataclasses or non-JSON primitives. Prevents silent `to_json()` failures and lossy serialization.
- **`EmbeddedUniverse.simulate()` and `replay()`**: `EmbeddedRuntime` users can now build attestation bundles directly without dropping to a plain `Universe`. Also added `EmbeddedUniverse.get(field)`.
- **`compute_step_hash()` exposed publicly** in `k3c.engine.step` for verifiers and external integrations.

## v0.4.0 (2026-04-18)

### Features (avic-feedback batch)

- **IR sugar** (`S`, `E`, `SS`, `k3()`): operator-overloaded expression building. `S.balance >= E.amount` instead of `Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount"))`. Includes `&`, `|`, `~`, `.in_()`, `all_of()`, `any_of()`, arithmetic.
- **`EventDef`**: declared event structure with typed fields. Round-trips through serde.
- **`Protocol` DSL**: linear FSM constructor. `Protocol(states, transitions)` auto-generates `event_defs()`, `permits()`, `maintains()`, and a `transition_table()`.
- **`denied=` IR Expression**: rich rejection messages on `Permit`, `Maintain`, `Validate`. Evaluates to a string with state/event context.
- **Keyed attestation (KC-6)**: `HmacSigner`, `Ed25519Signer`, `AttestationBundle.from_run()`, `verify_bundle()`. Round-trips to JSON.
- **`compose_many()` and `Pipeline`**: N-way composition. `compose_many` routes by name to one universe; `Pipeline` applies events to every stage in order.
- **Schema migrations**: `Spec(version=N, migrations=(Migration(from_version, to_version, transform),))`. Old state automatically migrated on Universe construction. State carries `__schema_version__`.
- **Sub-expression diagnostics**: failed Maintain clauses now include a diagnosis tree in `Why.messages` showing which sub-clause evaluated to what.

## v0.3.2 (2026-04-16)

### Features

- **Full Spec serde**: `spec_to_dict()` / `spec_from_dict()` for complete JSON round-trip of Spec with all clause types, extractors, decode plans, Validate, Severity
- **IR serde for `AllOf`/`AnyOf`/`In`**: new expression nodes serialize and deserialize
- **Top-level serde exports**: `expr_to_dict`, `expr_from_dict`, `type_to_dict`, `type_from_dict`, `spec_to_dict`, `spec_from_dict`

## v0.3.1 (2026-04-16)

### Features

- **`ByteSlice` cast**: `cast="int"|"float"|"bool"` for type coercion on extracted strings (e.g., `"000003"` -> `3`)
- **`Computed` in decode plans**: `Computed(expr=...)` now evaluates expressions against already-extracted fields during decode
- **`Spec.slice(relax=...)`**: drop named Maintain/Validate clauses for sub-chunks that would break specific invariants
- **`Universe.get(field)`**: read single state field without copying the entire dict
- **`Spec.decode_event(raw)`**: standalone decode without the full apply pipeline
- **`hash_fn="none"`**: skip JSON serialization + hashing for max throughput (no replay support)
- **Spec.slice() semantics documented**: hash chain reset, SpecCtx behavior, Before() on first step

## v0.3.0 (2026-04-16)

### Features

- **`Validate` clause**: event-scoped validation with `on=` filtering, `EventField` access, structured error detail (`field`, `constraint`), and severity levels
- **`Warning` result type**: non-fatal invariant issues — state advances, processing continues, causal record preserved
- **`Severity` on `Maintain`**: `Severity.ERROR` (Violated, default) or `Severity.WARNING` (Warning)
- **`AllOf` / `AnyOf`**: variadic AND/OR expressions — replaces nested `And`/`Or` chains
- **`In` expression**: membership test — `In(expr, (v1, v2, v3))` replaces verbose `Or(Compare(...), ...)`
- **`DecodeDispatch` default**: `default="skip"` produces `Impossible` for unmatched discriminants; `default=plan` uses a fallback decode plan
- Synchronous bridge returns target `Ok` with merged outputs and namespaced projections

## v0.2.1 (2026-04-16)

### Features

- **Error universe supervisor**: queue-based supervisor mediates between parallel workers and client `on_error` callback, giving full per-event flow control (`SKIP`, `ABORT_CHUNK`, `ABORT_ALL`) in parallel mode
- Uses fork-based multiprocessing; falls back to sequential on Windows

## v0.2.0 (2026-04-16)

### Features

- **Error streaming**: `StepError` with full identity (chunk index, offset, event, state, rule)
- **`ErrorAction`**: client controls flow per error (`SKIP`, `ABORT_CHUNK`, `ABORT_ALL`)
- **`Universe.stream_errors()`**: yield only errors from a single universe
- **`parallel_reduce` `on_error` callback**: per-event error streaming in parallel processing
- **`ChunkResult`**: per-chunk detail with processed count, errors, and abort status

## v0.1.0 (2026-04-16)

### Features

- Declarative `Spec` model with frozen dataclasses (no builder pattern)
- 9-tuple K3d system: `(S, S0, E, G, T, N, P, Ctx, L)`
- Expression IR (K3l) with 43 node types
- `Universe` with `apply`, `reduce`, `reduce_all`, `stream`
- Samsara (KC-3): `simulate`, `replay`, trajectory collection
- Composition (KC-4): `compose` (parallel), `bridge` (cross-universe)
- Fuzz testing (KC-5) with automatic shrinking
- `EmbeddedRuntime` for Python hook integration
- `parallel_reduce` for chunk-based parallel processing
- `explain` for dry-run debugging with full eval trace
- Code emission to Python, TypeScript, SQL
- Declarative extractors and decode plans (ByteSlice, BitField, JsonPath, etc.)
- Type system with 14 type nodes
- Hash chain with pluggable algorithms (SHA-256, blake2b, blake3)
- Option types (`Some`/`Nothing`) for total evaluation
- Domain examples (counter, bank, state machine, Raft consensus, and more)
