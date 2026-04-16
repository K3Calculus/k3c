# Changelog

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
