# Changelog

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
