# k3c Rust Implementation Plan

This document defines the intended Rust architecture and public API for a ground-up implementation of `k3c`.

The goal is not to preserve the current Python API. The goal is to preserve the useful semantics while designing an API that is idiomatic in Rust, portable where it should be portable, and explicit at the system boundary.

## Objectives

- Make the semantic core declarative, serializable, and testable.
- Separate the portable kernel from host-language integration.
- Preserve the distinction between implementation state and intended/spec state.
- Keep the expression language, spec model, and engine deterministic.
- Support both embedded use in Rust programs and external spec storage/transport.
- Avoid callback-heavy design in the core model.

## Non-Objectives

- Exact API parity with Python.
- Recreating Python's fluent builder as the primary user interface.
- Encoding every possible behavior as Rust closures.
- Over-optimizing the first version for zero-cost abstractions at the expense of clarity.

## Design Position

The Rust version should be built around a declarative kernel with a narrow integration boundary.

That implies:

- Specs are data.
- Expressions are data.
- Extractors are data.
- Results and traces are data.
- Host-specific logic lives at explicit extension points.

The engine should be able to evaluate, serialize, validate, and replay a spec without needing arbitrary user code embedded inside the spec itself.

## Top-Level Architecture

Recommended workspace layout:

```text
k3c/
  Cargo.toml
  crates/
    k3c-ir/
    k3c-spec/
    k3c-extract/
    k3c-engine/
    k3c-runtime/
    k3c-fuzz/
    k3c-emit/          # optional in v1
    k3c-cli/           # optional in v1
  examples/
    bank_account/
    ssim/
```

Recommended dependency direction:

```text
k3c-ir
  └── k3c-spec
        ├── k3c-extract
        └── k3c-engine
              └── k3c-runtime
                    ├── k3c-fuzz
                    ├── k3c-emit
                    └── k3c-cli
```

Rules:

- `k3c-ir` should have no dependency on runtime concerns.
- `k3c-spec` should define declarative spec structures only.
- `k3c-engine` should implement the causal step and validation pipeline.
- `k3c-runtime` should provide the embedded ergonomic API for Rust users.
- Optional features such as fuzzing, emitters, and CLI should stay out of the engine core.

## Core Concepts To Preserve

These are worth preserving from the current implementation:

- Expression IR as a first-class semantic object.
- Total evaluation.
- `Some | Nothing` style expression-level outcomes.
- `Ok | Impossible | Violated` as step-level outcomes.
- Deterministic hash-chain per step.
- `SpecCtx` as an ambient witness distinct from implementation state.
- Maintain classification into safety, bounded liveness, and unbounded liveness.
- Korrelation between actual implementation state and intended spec state.

These should be redesigned rather than copied literally:

- Python closures in the spec model.
- Callback-centric projections/outputs/decode in the spec core.
- Builder-first API.
- Ad hoc decoding in examples that bypasses the extractor model.

## Crate Responsibilities

### `k3c-ir`

Owns the expression language and core values.

Primary contents:

- `Expr`
- `ExprType`
- `Value`
- `EvalOption<T>` or `EvalValue`
- operators and enums
- IR serde

Suggested public modules:

```rust
pub mod expr;
pub mod types;
pub mod value;
pub mod eval;
pub mod serde;
```

### `k3c-spec`

Owns declarative spec authoring and compilation.

Primary contents:

- `Spec`
- `FieldDef`
- `Permit`
- `Require`
- `Maintain`
- `Projection`
- `Output`
- `Korrelator`
- `CompiledSpec`
- maintain classification

Suggested public modules:

```rust
pub mod spec;
pub mod compile;
pub mod schema;
```

### `k3c-extract`

Owns portable event extraction and decode.

Primary contents:

- extractor data model
- extractor execution engine
- fixed-width, map, computed, switch extractors
- decode plans and dispatch

This crate exists because extraction should be a real runtime capability, not just a declared type hierarchy.

### `k3c-engine`

Owns the causal step pipeline.

Primary contents:

- `SpecCtx`
- `Why`
- `WhyKind`
- `StepResult`
- `apply`
- guard checks
- require advancement
- safety and liveness tracking
- korrelation checks
- hash chain

This crate should remain independent from high-level runtime ergonomics.

### `k3c-runtime`

Owns the embedded Rust API.

Primary contents:

- `Universe`
- `System` trait
- `reduce`
- `reduce_all`
- streaming ingestion and result emission
- composition/bridge
- convenience constructors

This crate is where Rust applications interact with the engine directly.

### `k3c-fuzz`

Owns randomized exploration and shrinking.

Primary contents:

- event generation traits
- shrinkers
- fuzz reports
- property helpers

### `k3c-emit`

Optional in v1.

Primary contents:

- TypeScript emission
- SQL emission
- maybe JSON Schema or policy-language emitters later

### `k3c-cli`

Optional in v1.

Primary contents:

- validate spec files
- replay event streams
- explain failures
- emit derived forms

## Public API Philosophy

The Rust API should support two authoring modes.

### 1. Portable Mode

Users define specs entirely as serializable data.

Characteristics:

- no embedded closures in the spec core
- specs can live in JSON/YAML/TOML or Rust literals
- ideal for registries, transport, replay, tooling, and static analysis

### 2. Embedded Mode

Users define specs declaratively and attach a Rust implementation boundary.

Characteristics:

- transition logic may be supplied as Rust code
- optional escape hatches for projections or outputs if needed
- ideal for integrating with existing Rust systems

The portable core should be the default. Embedded mode should be an explicit layer on top.

## Hook Model

The Rust implementation should support hooks, but only at the runtime boundary.

This needs to stay strict:

- hooks are allowed in embedded mode
- hooks are not part of the portable semantic core
- serialized specs must not depend on executable Rust code

### Allowed Hook Points

Hooks are acceptable at these boundaries:

- implementation transition via the `System` trait
- runtime-only projection adapters
- runtime-only output adapters
- runtime-only integration hooks for logging, explain enrichment, or metrics

These hooks exist to connect the declarative engine to a real Rust program.

### Disallowed Hook Points

Hooks should not appear in these core structures:

- `Expr`
- `Spec`
- `DecodePlan`
- `Extractor`
- `Permit`
- `Require`
- `Maintain`
- portable `Projection`
- portable `Output`
- portable `Korrelator`

If any of these require arbitrary Rust code to function, the design has regressed back into a callback-centric SDK.

### Two-Tier Representation

To make the boundary explicit, use two representations where needed:

1. Portable representation
   Pure data, serializable, replayable, suitable for registries and transport.

2. Embedded runtime representation
   Wraps the portable representation and may attach Rust hooks.

Example direction:

```rust
pub struct Spec { /* portable */ }

pub struct EmbeddedSpec<Sys> {
    pub spec: Spec,
    pub system: Sys,
    pub projection_hooks: Vec<Box<dyn ProjectionHook>>,
    pub output_hooks: Vec<Box<dyn OutputHook>>,
}
```

The exact shape can vary, but the separation should remain visible in the API.

### Default Rule

If a feature can be expressed declaratively, it should not be a hook.

Hooks are escape hatches for integration, not the primary authoring mechanism.

## Plugin System And Registry

The implementation should support a broad plugin system, but the boundary must remain disciplined.

The correct model is:

- broad extension around runtime, tooling, and packaging
- narrow and controlled extension around semantics
- no arbitrary executable code embedded inside portable specs

### Registry Model

The term `registry` should be used for a portable packaged unit that carries a complete K3 artifact set.

A registry package is not just a plugin. It is a total portable pack that may contain:

- one or more specs
- IR/schema artifacts
- extractor and decode definitions
- projections and outputs expressed declaratively
- example inputs and fixtures
- replay data or test vectors
- documentation and metadata
- compatibility and version information

This should be packaged as a `.k3` artifact and be OCI-compliant so it can be stored, versioned, distributed, and resolved through standard registry infrastructure.

### `.k3` Packaging Direction

The `.k3` package should represent a portable registry unit.

High-level properties:

- OCI-compliant packaging and distribution
- immutable versioned artifact identity
- portable across runtimes and environments
- no requirement for embedded executable Rust code
- suitable for replay, validation, transport, and deployment

Suggested conceptual contents:

```text
my-domain.k3
  manifest.json
  specs/
  ir/
  extractors/
  examples/
  fixtures/
  docs/
  metadata/
```

The exact archive/container representation can evolve, but the packaging model should be explicit from the start.

### Plugin Categories

The plugin system should be divided into categories.

#### Safe Runtime Plugins

These are strongly encouraged:

- event source adapters
- event sink adapters
- decoder/input adapters
- emitter backends
- explain renderers
- observability integrations
- storage and replay integrations
- CLI extensions

These extend the runtime around the semantic core without changing what a spec means.

#### Controlled Semantic Extensions

These are allowed only through explicit registries and stable identifiers:

- registered extractor engines
- registered decode/import adapters
- registered korrelation comparison modes
- registered schema importers

These affect interpretation and therefore need stricter controls.

#### Forbidden Core Plugins

These should not be part of the portable model:

- arbitrary Rust closures embedded in `Spec`
- opaque trait objects hidden inside serialized specs
- plugin-defined meaning for core `Expr` nodes without explicit registration
- any packaging model that requires local code injection to replay a stored spec

### Registry Resolution Rules

A portable spec may depend on:

- built-in semantic constructs, or
- named registered capabilities with stable IDs and serializable config

It must not depend on:

- anonymous executable code
- process-local closures
- runtime state that cannot be reconstructed from the package and runtime

Example direction:

```rust
pub struct RegistryRef {
    pub kind: String,
    pub version: String,
    pub config: serde_json::Value,
}
```

The registry/runtime resolves `kind` and `version` through a known capability registry.

### Determinism Requirements

Any registered extension that affects semantics must satisfy:

- deterministic execution for the same inputs
- explicit version identity
- explicit config schema
- replay compatibility expectations
- failure behavior that is representable in structured results

If an extension cannot satisfy these constraints, it should remain a runtime-only plugin and stay out of the portable registry model.

### Registry As Distribution Primitive

The registry should be treated as a first-class distribution mechanism for K3 systems.

Examples of what a `.k3` package may represent:

- a full SSIM pack with decode plans, validations, fixtures, and docs
- a banking pack with canonical invariants and replay samples
- an industry protocol pack with import adapters and example traces

This is broader and more useful than a loose plugin ecosystem because it gives:

- portability
- versioning
- reproducibility
- deployment compatibility
- a clean separation between data packages and runtime integrations

### Default Rule

If something can be expressed as a portable registry artifact, prefer that over a plugin requiring local executable code.

Use runtime plugins for operational integration.
Use registry packages for portable semantic assets.

## Proposed Core Types

### Expressions

The current Python implementation has a rich IR with literals, field access, logical operators, arithmetic, collections, record construction, and temporal wrappers. Rust should represent this as an `enum`.

Example shape:

```rust
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Expr {
    LBool(bool),
    LInt(i64),
    LFloat(OrderedFloat<f64>),
    LStr(String),
    LList(Vec<Expr>),

    Var(Symbol),
    Field(Box<Expr>, Symbol),
    Index(Box<Expr>, usize),
    EventField(Symbol),
    Actual(Symbol),
    Intended(Symbol),

    And(Box<Expr>, Box<Expr>),
    Or(Box<Expr>, Box<Expr>),
    Not(Box<Expr>),
    If {
        cond: Box<Expr>,
        then_: Box<Expr>,
        else_: Box<Expr>,
    },
    Implies(Box<Expr>, Box<Expr>),

    Compare {
        op: CmpOp,
        left: Box<Expr>,
        right: Box<Expr>,
    },
    Arith {
        op: ArithOp,
        left: Box<Expr>,
        right: Box<Expr>,
    },

    Record(Vec<(Symbol, Expr)>),
    With {
        base: Box<Expr>,
        updates: Vec<(Symbol, Expr)>,
    },

    Before(Symbol),
    After(Symbol),

    Always(Box<Expr>),
    Eventually(Box<Expr>),
    Within {
        expr: Box<Expr>,
        n: u32,
    },
    Until(Box<Expr>, Box<Expr>),

    Named {
        name: String,
        expr: Box<Expr>,
    },
    Described {
        description: String,
        expr: Box<Expr>,
    },
}
```

Notes:

- Use `Box` when recursion requires it.
- Use a `Symbol` newtype rather than raw `String` if interned names become useful later.
- Avoid trying to encode dynamic semantics in the Rust type system. Keep the IR simple and serializable.

### Expression-Level Outcome

The Python `Some | Nothing` split is useful and should remain conceptually intact.

Possible shape:

```rust
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum EvalOption<T> {
    Some(T),
    Nothing {
        field: String,
        step_hash: String,
    },
}
```

This is intentionally not `Option<T>`. `Nothing` carries causal context and should remain distinguishable from ordinary absence.

### Runtime Values

Avoid tying evaluation directly to `serde_json::Value`. Define a first-class runtime value type.

Possible shape:

```rust
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Value {
    Bool(bool),
    Int(i64),
    Float(OrderedFloat<f64>),
    Str(String),
    List(Vec<Value>),
    Record(BTreeMap<String, Value>),
    Unit,
}
```

Why:

- clearer evaluator semantics
- better control over comparisons and hashing
- easier future typed APIs

Use conversions to and from JSON as a boundary concern, not as the runtime representation.

## Spec Model

The spec should be explicit and mostly data-driven.

Example shape:

```rust
pub struct Spec {
    pub name: String,
    pub state0: BTreeMap<String, Value>,
    pub fields: Vec<FieldDef>,
    pub decode: Option<DecodePlan>,
    pub permits: Vec<Permit>,
    pub requires: Vec<Require>,
    pub maintains: Vec<Maintain>,
    pub projections: Vec<Projection>,
    pub outputs: Vec<Output>,
    pub korrelator: Option<Korrelator>,
    pub protocol_start: String,
}
```

Key design decision:

- `decode` should not be an arbitrary closure in the core spec type.
- It should be a `DecodePlan`, a dispatcher, or another serializable representation.

### Decode Model

Recommended shape:

```rust
pub enum DecodePlan {
    Identity,
    ExtractFields(Vec<FieldDef>),
    Dispatch {
        discriminant: Extractor,
        cases: BTreeMap<String, DecodePlan>,
    },
}
```

This makes fixed-width and tagged-message formats much easier to support in a portable way.

### Require

In Rust v1, keep `Require` declarative.

```rust
pub struct Require {
    pub name: String,
    pub on: String,
    pub transition: Expr,
}
```

This preserves the intended state machine in `SpecCtx` and enables korrelation without embedding host code.

### Projections and Outputs

Do not make these closures by default.

Recommended v1:

```rust
pub struct Projection {
    pub name: String,
    pub expr: Expr,
    pub kind: ProjectionKind,
}

pub struct Output {
    pub name: String,
    pub on: Option<String>,
    pub expr: Expr, // expected to evaluate to a record or unit
}
```

If a user truly needs custom behavior, allow an embedded-mode adapter later, but keep the core model declarative.

### Korrelator

Recommended v1:

```rust
pub struct Korrelator {
    pub actual: Expr,
    pub intended: Expr,
    pub compare: CompareMode,
}
```

Example `CompareMode` values:

- `Exact`
- `Subset`
- `Custom(String)` only if there is a registry-driven semantics story

If a closure-based comparator is ever supported, it should live in embedded mode only.

## Extractor Model

The extractor system should be first-class.

Suggested shape:

```rust
pub enum Extractor {
    ByteSlice {
        start: usize,
        length: usize,
        encoding: TextEncoding,
        trim: bool,
    },
    BitField {
        byte_offset: usize,
        bit_offset: u8,
        width: u8,
    },
    MapKey {
        key: String,
    },
    JsonPath {
        path: String,
    },
    Computed {
        expr: Expr,
    },
    Switch {
        discriminant: Box<Extractor>,
        cases: Vec<(Value, Extractor)>,
    },
    Identity,
}
```

Important:

- `Extractor` execution should operate over a raw input model.
- For v1, support a small number of raw forms cleanly: `Bytes`, `Map`, and already-decoded `Value`.

Possible raw input type:

```rust
pub enum RawInput {
    Bytes(Vec<u8>),
    Map(BTreeMap<String, Value>),
    Value(Value),
}
```

## Engine API

The engine should expose a small deterministic step function.

Example:

```rust
pub fn apply<S, Sys>(
    state: &S,
    ctx: &SpecCtx,
    raw_event: RawInput,
    compiled: &CompiledSpec,
    system: &Sys,
) -> StepResult<S>
where
    Sys: System<State = S>;
```

Or more practically:

```rust
pub struct Engine;

impl Engine {
    pub fn apply<S, Sys>(
        &self,
        state: &S,
        ctx: &SpecCtx,
        event: Event,
        compiled: &CompiledSpec,
        system: &Sys,
    ) -> StepResult<S>
    where
        Sys: System<State = S>;
}
```

Keep the pipeline explicit:

1. compute `step_hash`
2. decode raw event into domain event
3. guard evaluation
4. invoke implementation transition
5. advance intended spec state
6. safety check
7. korrelation check
8. liveness update/check
9. compute projections/outputs
10. advance `SpecCtx`

## Runtime API

This is where an idiomatic Rust API matters.

Suggested `System` trait:

```rust
pub trait System {
    type State;

    fn transition(
        &self,
        state: &Self::State,
        event: &Event,
    ) -> Self::State;
}
```

Suggested `Universe`:

```rust
pub struct Universe<S, Sys> {
    id: String,
    compiled: CompiledSpec,
    state: S,
    ctx: SpecCtx,
    system: Sys,
}
```

Suggested methods:

```rust
impl<S, Sys> Universe<S, Sys>
where
    Sys: System<State = S>,
{
    pub fn apply(&mut self, event: Event) -> StepResult<S>;
    pub fn reduce<I>(&mut self, events: I) -> StepResult<S>
    where
        I: IntoIterator<Item = Event>;
    pub fn reduce_all<I>(&mut self, events: I) -> ReduceAllResult<S>
    where
        I: IntoIterator<Item = Event>;
    pub fn stream<I>(&mut self, events: I) -> impl Iterator<Item = StepResult<S>>
    where
        I: IntoIterator<Item = Event>;
    pub fn reset(&mut self);
    pub fn state(&self) -> &S;
    pub fn ctx(&self) -> &SpecCtx;
}
```

Notes:

- `Universe` should be the ergonomic embedded API.
- The pure engine should still be available separately for deterministic testing and replay.
- Streaming should be a first-class runtime capability, not just a convenience wrapper.

## Streaming Model

The runtime must support streaming as a primary operating mode.

This includes both:

- finite replay from iterators, files, or decoded record streams
- unbounded live ingestion from channels, sockets, queues, or adapters

The streaming model should preserve the same semantics as repeated `apply()` calls while avoiding the need to materialize a full event sequence in memory.

### Runtime Vocabulary

The runtime API should use these terms consistently:

- `apply`
  Execute one causal step for one event.

- `replay`
  Process a finite historical event sequence or file-backed event source.

- `stream`
  Process events incrementally and emit per-step results as they occur.

- `ingest`
  Accept events from an external producer such as a decoder, channel, queue, or socket.

- `emit`
  Produce outputs, step results, explanations, or telemetry incrementally during processing.

- `sink`
  A consumer of outputs or results produced during streaming.

These terms should not be used interchangeably. In particular:

- replay is finite and historical
- stream is incremental and may be finite or unbounded
- apply is always one event at a time

### Streaming Requirements

The runtime should support:

- incremental event ingestion
- per-step result emission
- incremental output emission
- clean stop on `Violated`
- inspection of `Impossible` events without collapsing the stream model
- replay and live processing using the same underlying step semantics
- explicit integration with external decoders and sinks

### Runtime Position

Streaming belongs in `k3c-runtime`, not in `k3c-engine`.

The engine remains a deterministic single-step function.
The runtime owns orchestration over many steps, including replay and live streaming.

### V1 Recommendation

For v1:

- support synchronous iterator-based streaming directly on `Universe`
- support replay helpers over iterators, files, and decoder-backed sources
- defer async streaming adapters to an optional later feature

That keeps the core simple while still making streaming a real runtime concern.

## Result Types

Keep step results value-oriented, not exception-oriented.

Recommended shape:

```rust
pub enum StepResult<S> {
    Ok(OkStep<S>),
    Impossible(Why),
    Violated(Why),
}

pub struct OkStep<S> {
    pub state: S,
    pub ctx: SpecCtx,
    pub step_hash: String,
    pub projections: BTreeMap<String, Value>,
    pub outputs: Vec<Event>,
}
```

`Why` should remain richly structured.

Recommended shape:

```rust
pub struct Why {
    pub rule: String,
    pub kind: WhyKind,
    pub messages: Vec<String>,
    pub before: Option<Value>,
    pub after: Option<Value>,
    pub event: Event,
    pub expected: Option<Value>,
    pub trace: Vec<Event>,
    pub step_hash: String,
    pub fingerprint: String,
}
```

You may choose to store `before` and `after` as snapshots of implementation state via a conversion trait rather than directly as generic `S`.

## State Representation

This is a major design choice.

There are two viable models.

### Model A: Dynamic Core State

Represent implementation state and event payloads as `BTreeMap<String, Value>`.

Pros:

- maximum portability
- easiest match to current semantics
- easiest IR evaluation and serialization story
- easiest CLI and replay tooling

Cons:

- loses some Rust type power
- more runtime checks at the system boundary

### Model B: Typed Host State with Snapshot Conversion

Allow user systems to use typed Rust structs while the spec engine operates on snapshot views.

Example:

```rust
pub trait Snapshot {
    fn to_value(&self) -> Value;
}
```

Pros:

- better Rust ergonomics for real applications
- easier integration with existing domain models

Cons:

- more API complexity
- more conversion overhead

Recommendation for v1:

- keep the engine centered on dynamic `Value`/record state
- add typed host adapters later if needed

This keeps the first version coherent and makes parity with the current semantics much easier.

## Builder Strategy

Do not make a fluent builder the primary abstraction.

Instead provide:

- plain structs with `Default` where sensible
- constructor helpers
- optional macro or builder convenience layer later

Example:

```rust
let spec = Spec {
    name: "bank".into(),
    state0: record! { "balance" => 100 },
    permits: vec![
        Permit {
            name: "has_funds".into(),
            on: Some("Withdraw".into()),
            when: cmp_ge(field(var("state"), "balance"), event_field("amount")),
        }
    ],
    maintains: vec![
        Maintain {
            name: "non_negative".into(),
            expr: always(cmp_ge(field(var("state"), "balance"), int(0))),
        }
    ],
    ..Spec::empty("bank")
};
```

If ergonomics become important, add:

- a `spec! { ... }` macro
- small constructor functions

That is likely better than trying to recreate a chainable OO builder.

## Serialization Strategy

Serialization is central, not auxiliary.

Requirements:

- every portable spec should round-trip through serde
- every expression should round-trip
- every extractor should round-trip
- result records should serialize cleanly for logs and replay

Recommendations:

- use adjacently tagged or externally tagged enums consistently
- define stable schema versions from the start
- add golden tests for JSON representations

Suggested top-level version tags:

- `k3c_ir_version`
- `k3c_spec_version`

Do not make schema stability an afterthought.

## Liveness and Context

`SpecCtx` remains important and should stay explicit.

Suggested shape:

```rust
pub struct SpecCtx {
    pub spec_state: BTreeMap<String, Value>,
    pub protocol_pos: String,
    pub prev_state: Option<BTreeMap<String, Value>>,
    pub prev_event: Option<Event>,
    pub timers: BTreeMap<String, u32>,
    pub active_obligations: BTreeSet<String>,
    pub obligation_steps: Vec<(String, u32)>,
    pub bridge_ctx: BTreeMap<String, Value>,
    pub prev_step_hash: String,
    pub trace_ring: VecDeque<Event>,
}
```

Rules:

- keep it immutable by convention even if internal mutation is used for performance
- expose persistent-style update methods
- keep trace size bounded

## Composition and Bridge

These belong in runtime, not engine.

Recommended approach:

- composition should operate on `Universe` or a smaller `Apply` trait
- bridge should be explicit about delivery semantics
- retry and dead-letter behavior should be runtime concerns

Suggested traits:

```rust
pub trait Apply {
    type State;
    fn apply(&mut self, event: Event) -> StepResult<Self::State>;
    fn state_snapshot(&self) -> Value;
}
```

Then:

- `ComposedUniverse<L, R>`
- `BridgedUniverse<Src, Dst>`

Keep them separate from the semantic kernel.

## Explain and Replay

The Rust version should support explainability from the start.

Recommended v1:

- evaluator traces for guard and maintain clauses
- clear explanation records for `Impossible` and `Violated`
- event replay over a stored spec and event stream

This does not need a full debugger in v1, but the model should preserve enough data to build one.

## Fuzzing Strategy

Rust is a good fit for property-based testing.

Suggested approach:

- use `proptest` or a lightweight internal generator layer
- treat event generation as an explicit trait or strategy
- implement shrinking for sequences and individual fields

Keep fuzzing in a separate crate so engine dependencies stay lean.

## Emission Strategy

Emitters should be clearly secondary to the semantic engine.

Recommended v1 stance:

- do not block core delivery on TypeScript/SQL emitters
- if emitters are implemented, keep them best-effort and clearly scoped

The engine, IR, and spec portability matter more than code generation in v1.

## SSIM as the Primary Validation Example

The SSIM example is a useful design benchmark because it exercises:

- fixed-width extraction
- record dispatch
- declarative validation
- protocol sequencing
- accumulator-style transitions
- outputs with nested records

In the Rust version, SSIM should be used to validate these design goals:

1. fixed-width records can be decoded declaratively
2. record type dispatch is part of the decode plan
3. simple field validation can be expressed in IR
4. transition logic is handwritten only where accumulation is genuinely stateful
5. outputs are expressible declaratively where possible

If SSIM still requires large amounts of ad hoc glue, the API is not yet right.

## V1 Scope

What should exist in v1:

- `Expr`, operators, serde
- total evaluator
- `Spec`, `CompiledSpec`, maintain classification
- extractor execution for core forms
- `SpecCtx`
- `Why`, `WhyKind`, `StepResult`
- `Engine::apply`
- `Universe`
- reduce/reduce_all/reset
- deterministic hash chain
- basic explain support
- one complete end-to-end example, ideally bank + SSIM subset

What can wait until v2:

- advanced typed host-state integration
- bridge and compose if timeline is tight
- all emitters
- CLI
- broad plugin system
- exotic extractor types not needed by first examples

## Implementation Order

Recommended sequence:

1. `k3c-ir`
   Define `Expr`, `Value`, operators, serde.

2. evaluator
   Make evaluation total and deterministic before anything else.

3. `k3c-spec`
   Define spec structures and compiled maintain classification.

4. `k3c-extract`
   Implement real extractor execution and decode plans.

5. `k3c-engine`
   Implement `SpecCtx`, `Why`, hash chain, and `apply`.

6. `k3c-runtime`
   Add `Universe`, reduce methods, and embedded API.

7. examples
   Rebuild a simple example, then SSIM subset.

8. fuzz/explain/compose/bridge
   Add operational layers after the engine is stable.

## Testing Strategy

Tests should be layered.

### Unit tests

- every `Expr` evaluation branch
- every extractor variant
- maintain classification
- hash-chain determinism
- result fingerprint stability

### Golden tests

- IR JSON round-trip
- spec JSON round-trip
- explanation snapshots

### Semantic tests

- bank-account style guard/invariant flows
- korrelation failures
- bounded liveness expiry
- replay determinism

### Example tests

- SSIM sample decode
- SSIM sample sequencing and output shape

### Differential tests

If useful, run the same small scenarios in Python and Rust and compare:

- guard outcomes
- step hashes
- `Impossible` and `Violated` classification
- final intended/spec state

This is useful early, even if the long-term API is different.

## Open Design Questions

These should be decided early:

1. Should v1 engine state be fully dynamic `Value`-based, or should typed host state be supported immediately?

Recommendation:
Use dynamic engine state in v1.

2. Should outputs and projections be pure expressions in v1?

Recommendation:
Yes. Add embedded escape hatches later if needed.

3. Should decode support raw bytes in v1?

Recommendation:
Yes. It is required to make SSIM a real benchmark instead of a special case.

4. Should compose/bridge ship in v1?

Recommendation:
Only if the engine is already stable. They are not part of the minimum semantic kernel.

5. Should the spec file format be finalized before implementation?

Recommendation:
Stabilize a minimal IR/spec schema early and evolve with explicit versioning.

## Final Recommendation

The Rust implementation should be built as a declarative kernel first and an embedded runtime second.

That means:

- no Python API emulation
- no closures in the core spec model
- real extractor execution
- serialization-first design
- dynamic semantic core with explicit integration boundaries

If this is done correctly, the Rust version will not just be a port of the Python repo. It will be the cleaner reference implementation that the Python code was moving toward but did not fully reach.
