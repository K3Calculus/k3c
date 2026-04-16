# k3c Python Implementation Plan

This document defines the intended Python architecture and public API for a redesigned `k3c`.

The goal is not to preserve the current API. The goal is to produce the right Python API for the semantics: explicit where correctness matters, ergonomic where Python is strong, and portable where the model should remain serializable.

## Objectives

- Preserve the semantic core of K3 in a clear Python implementation.
- Redesign the Python API around data-first specs instead of callback-heavy builder patterns.
- Keep the engine deterministic and testable.
- Make the Python version excellent for authoring, experimentation, analysis, and tooling.
- Support declarative specs, portable IR, and practical embedded use in Python systems.

## Non-Objectives

- Backward compatibility with the current API.
- Mimicking a Rust API exactly.
- Treating Python as only a thin wrapper around a lower-level implementation.
- Keeping host-language callbacks in the semantic core by default.

## Design Position

Python should be treated as a first-class implementation target, not as a compatibility layer.

That means:

- Specs should still be data.
- Expressions should still be data.
- The engine should still be total and deterministic.
- Python-specific ergonomics should exist at the authoring layer, not the semantic core.

Python is especially good at:

- concise data modeling
- pattern matching
- ergonomic authoring DSLs
- rapid iteration
- testability
- introspection and explain tooling

The redesigned Python API should lean into those strengths without sacrificing the declarative model.

## Top-Level Architecture

Recommended package layout:

```text
k3c/
  __init__.py
  ir/
    __init__.py
    expr.py
    types.py
    value.py
    eval.py
    serde.py
  spec/
    __init__.py
    model.py
    compile.py
    extract.py
    schema.py
  engine/
    __init__.py
    ctx.py
    result.py
    step.py
    explain.py
  runtime/
    __init__.py
    universe.py
    compose.py
    bridge.py
  testing/
    __init__.py
    fuzz.py
    strategies.py
  emit/
    __init__.py
    ts.py
    sql.py
  cli/
    __main__.py
```

Rules:

- `ir` must not depend on runtime concerns.
- `spec` must define declarative structures first.
- `engine` should contain the causal step and result model.
- `runtime` should provide ergonomic embedded APIs for normal application use.
- `testing`, `emit`, and `cli` should remain separate layers.

## Core Concepts To Preserve

These are worth preserving from the current implementation:

- expression IR as the primary semantic language
- total evaluation
- expression-level `Some | Nothing`
- step-level `Ok | Impossible | Violated`
- explicit `SpecCtx`
- maintain classification into safety and liveness forms
- deterministic per-step hashing
- separation of implementation state from intended/spec state

These should be redesigned:

- fluent builder as the dominant authoring mode
- specs embedding raw Python callables by default
- decode/projection/output design centered on Python functions
- examples bypassing the declarative extraction layer

## Python API Philosophy

The Python version should support two authoring modes.

### 1. Declarative Mode

Users define specs as plain data structures and expressions.

Characteristics:

- serializable
- portable
- excellent for spec registries, replay, analysis, and tooling
- preferred default

### 2. Embedded Mode

Users combine a declarative spec with Python implementation hooks at the runtime boundary.

Characteristics:

- practical for Python applications
- allows custom transition code
- allows optional Python hooks for projections/outputs if needed
- should be explicit and secondary to the declarative core

The current implementation implicitly mixes these modes. The redesigned version should separate them cleanly.

## Hook Model

The Python implementation should support hooks, but only at the runtime boundary.

This boundary needs to be explicit:

- hooks are allowed in embedded mode
- hooks are not part of the portable semantic core
- serialized specs must not depend on Python callables

### Allowed Hook Points

Hooks are acceptable at these boundaries:

- implementation transition passed into `Universe`
- runtime-only projection adapters
- runtime-only output adapters
- runtime-only explain enrichers
- runtime-only logging, metrics, or tracing callbacks

These hooks exist to integrate the declarative engine into a Python application.

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

If any of these require a Python callable to be meaningful, the design has slipped back into a callback-centric API.

### Two-Tier Representation

Where hooks are needed, use two explicit layers:

1. Portable representation
   Pure data, serializable, replayable, and tool-friendly.

2. Embedded runtime representation
   Wraps the portable structures and attaches Python callables where needed.

Example direction:

```python
@dataclass(frozen=True)
class Spec:
    ...


@dataclass
class EmbeddedRuntime:
    spec: Spec
    transition: TransitionFn
    projection_hooks: dict[str, Callable[..., object]] = field(default_factory=dict)
    output_hooks: dict[str, Callable[..., object]] = field(default_factory=dict)
```

The exact API can differ, but the separation must remain obvious.

### Default Rule

If a feature can be expressed declaratively, it should not be a hook.

Hooks are integration escape hatches, not the primary authoring model.

## Plugin System And Registry

The implementation should support a broad plugin system, but the boundary must remain disciplined.

The correct model is:

- broad extension around runtime, tooling, and packaging
- narrow and controlled extension around semantics
- no arbitrary executable Python code embedded inside portable specs

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
- no requirement for embedded executable Python code
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

- arbitrary Python callables embedded in `Spec`
- unserializable functions hidden inside packaged specs
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

```python
@dataclass(frozen=True)
class RegistryRef:
    kind: str
    version: str
    config: dict[str, object]
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

## Package Responsibilities

### `k3c.ir`

Owns the expression language and value model.

Primary contents:

- `Expr`
- `ExprType`
- runtime `Value`
- `Some`
- `Nothing`
- evaluator
- serde

Suggested public modules:

```python
k3c.ir.expr
k3c.ir.types
k3c.ir.value
k3c.ir.eval
k3c.ir.serde
```

### `k3c.spec`

Owns declarative specs and compilation.

Primary contents:

- `Spec`
- `FieldDef`
- `Permit`
- `Require`
- `Maintain`
- `Projection`
- `Output`
- `Korrelator`
- `DecodePlan`
- `CompiledSpec`

### `k3c.engine`

Owns deterministic step execution.

Primary contents:

- `SpecCtx`
- `Why`
- `WhyKind`
- `StepResult`
- `apply_step`
- explain trace structures

### `k3c.runtime`

Owns application-facing APIs.

Primary contents:

- `Universe`
- composition
- bridge
- replay helpers
- streaming ingestion and result emission

### `k3c.testing`

Owns randomized and strategy-based verification support.

Primary contents:

- fuzz runner
- shrinker
- strategy adapters
- maybe Hypothesis integration

### `k3c.emit`

Optional but useful.

Primary contents:

- TypeScript emitters
- SQL emitters
- perhaps JSON Schema later

### `k3c.cli`

Optional but valuable for real adoption.

Primary contents:

- validate specs
- explain outcomes
- replay event logs
- emit IR/spec JSON

## Core Data Model

### Expressions

The expression language should remain explicit and data-oriented.

Use frozen dataclasses and tagged unions via class hierarchy.

Example shape:

```python
@dataclass(frozen=True)
class LBool:
    val: bool

@dataclass(frozen=True)
class LInt:
    val: int

@dataclass(frozen=True)
class Var:
    name: str

@dataclass(frozen=True)
class Compare:
    op: CmpOp
    left: Expr
    right: Expr

type Expr = (
    LBool | LInt | LStr | LList
    | Var | Field | EventField
    | And | Or | Not | If | Implies
    | Compare | Arith | Record | With
    | Before | After
    | Always | Eventually | Within | Until
    | Named | Described
)
```

This remains a good fit for Python 3.12+ pattern matching and frozen dataclasses.

### Runtime Values

Do not use raw Python objects as the semantic value model everywhere.

Recommended approach:

- define a clear conceptual runtime value domain
- allow Python scalars and mappings at API boundaries
- normalize internally as needed

For Python, this can be lighter than Rust. A full `Value` enum may not be necessary if normalized `bool | int | float | str | list | dict | None` is sufficient.

Recommendation:

- keep Python-native values internally for v1
- define normalization and comparison rules explicitly
- reserve a custom `Value` wrapper only if ambiguity becomes painful

### Expression-Level Outcome

The `Some | Nothing` split is still useful in Python and should remain explicit.

Example:

```python
@dataclass(frozen=True)
class Some[T]:
    val: T

@dataclass(frozen=True)
class Nothing:
    field: str
    step_hash: str
```

This should remain separate from ordinary `None`.

## Spec Model

The new Python `Spec` should be a plain frozen dataclass or a lightly validated model.

Example:

```python
@dataclass(frozen=True)
class Spec:
    name: str
    state0: dict[str, object]
    fields: tuple[FieldDef, ...] = ()
    decode: DecodePlan | None = None
    permits: tuple[Permit, ...] = ()
    requires: tuple[Require, ...] = ()
    maintains: tuple[Maintain, ...] = ()
    projections: tuple[Projection, ...] = ()
    outputs: tuple[Output, ...] = ()
    korrelator: Korrelator | None = None
    protocol_start: str = "__start__"
```

Important:

- the primary `Spec` should not embed arbitrary Python callables
- the default mode should be serializable and portable

### Decode Plan

Redesign `decode` as data.

Example:

```python
@dataclass(frozen=True)
class DecodeIdentity:
    pass

@dataclass(frozen=True)
class DecodeFields:
    fields: tuple[FieldDef, ...]

@dataclass(frozen=True)
class DecodeDispatch:
    discriminant: Extractor
    cases: tuple[tuple[object, "DecodePlan"], ...]

type DecodePlan = DecodeIdentity | DecodeFields | DecodeDispatch
```

This makes fixed-width formats, tagged records, and protocol decoding first-class.

### Projections and Outputs

The default model should be declarative.

Example:

```python
@dataclass(frozen=True)
class Projection:
    name: str
    expr: Expr
    kind: ProjectionKind = "derived"

@dataclass(frozen=True)
class Output:
    name: str
    expr: Expr
    on: str | None = None
```

If a user needs custom Python behavior, that should be provided by an embedded runtime adapter, not mixed into `Spec` itself.

### Korrelator

Recommended declarative-first model:

```python
@dataclass(frozen=True)
class Korrelator:
    actual: Expr
    intended: Expr
    mode: CompareMode = CompareMode.EXACT
```

The default comparison should be deterministic and serializable.

## Extractor Model

The extractor model should be operational, not aspirational.

Recommended public shape:

```python
@dataclass(frozen=True)
class ByteSlice:
    start: int
    length: int
    encoding: TextEncoding = TextEncoding.ASCII
    trim: bool = True

@dataclass(frozen=True)
class BitField:
    byte_offset: int
    bit_offset: int
    width: int

@dataclass(frozen=True)
class MapKey:
    key: str

@dataclass(frozen=True)
class JsonPath:
    path: str

@dataclass(frozen=True)
class Computed:
    expr: Expr

@dataclass(frozen=True)
class Switch:
    discriminant: Extractor
    cases: tuple[tuple[object, Extractor], ...]

@dataclass(frozen=True)
class Identity:
    pass
```

And the runtime should actually execute these.

Recommended raw input model:

```python
type RawInput = bytes | dict[str, object] | object
```

But the engine should normalize this explicitly before evaluation rather than relying on ad hoc input shapes.

## Engine API

The engine should expose a pure step function.

Example:

```python
def apply_step(
    *,
    state: dict[str, object],
    ctx: SpecCtx,
    raw_event: object,
    compiled: CompiledSpec,
    transition: TransitionFn,
) -> StepResult[dict[str, object]]:
    ...
```

Where:

```python
type TransitionFn = Callable[[dict[str, object], dict[str, object]], dict[str, object]]
```

The step pipeline should remain explicit:

1. compute step hash
2. decode raw event into domain event
3. evaluate permits
4. run implementation transition
5. advance intended spec state
6. check safety invariants
7. run korrelation
8. update liveness state
9. compute projections and outputs
10. advance `SpecCtx`

The engine should not mutate inputs.

## Runtime API

The runtime layer should provide the ergonomic Python surface.

Recommended `Universe`:

```python
class Universe:
    def __init__(
        self,
        *,
        spec: Spec | CompiledSpec,
        transition: TransitionFn,
        state: dict[str, object] | None = None,
        ctx: SpecCtx | None = None,
        id: str | None = None,
    ) -> None: ...

    def apply(self, event: object) -> StepResult[dict[str, object]]: ...
    def reduce(self, events: Iterable[object]) -> StepResult[dict[str, object]]: ...
    def reduce_all(self, events: Iterable[object]) -> ReduceAllResult: ...
    def stream(self, events: Iterable[object]) -> Iterator[StepResult[dict[str, object]]]: ...
    def reset(self) -> None: ...
```

This is simpler and cleaner than a builder-driven public API.

## Streaming Model

The runtime must support streaming as a primary operating mode.

This includes both:

- finite replay from iterables, files, and decoder-backed sources
- unbounded live ingestion from generators, queues, sockets, or adapters

The streaming API should preserve the same semantics as repeated `apply()` calls while allowing incremental processing without collecting a full event sequence in memory.

### Runtime Vocabulary

The runtime API should use these terms consistently:

- `apply`
  Execute one causal step for one event.

- `replay`
  Process a finite historical event sequence or file-backed event source.

- `stream`
  Process events incrementally and yield per-step results as they occur.

- `ingest`
  Accept events from an external producer such as a decoder, generator, queue, or socket adapter.

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
- incremental output handling
- clean termination on `Violated`
- visibility into `Impossible` events during stream processing
- the same causal semantics for replay and live ingestion
- explicit integration with external decoders and sinks

### Runtime Position

Streaming belongs in `k3c.runtime`, not in `k3c.engine`.

The engine stays a pure single-step function.
The runtime owns orchestration over many steps, including replay and live stream consumption.

### V1 Recommendation

For v1:

- support iterator-based streaming directly on `Universe`
- support replay helpers over iterables, files, and decoder-backed sources
- defer async adapters unless a concrete use case requires them

That keeps the core implementation simple while still treating streaming as a first-class runtime concern.

### Embedded Runtime Hooks

If needed, allow runtime-only hooks:

- `transition`
- custom projection functions
- custom output functions
- custom explain enrichers

But these should not live in the portable spec model.

## Result Types

Keep the value-oriented result model.

Recommended shape:

```python
@dataclass(frozen=True)
class Ok[T]:
    state: T
    ctx: SpecCtx
    step_hash: str
    projections: dict[str, object] = field(default_factory=dict)
    outputs: tuple[dict[str, object], ...] = ()

@dataclass(frozen=True)
class Impossible:
    why: Why

@dataclass(frozen=True)
class Violated:
    why: Why

type StepResult[T] = Ok[T] | Impossible | Violated
```

This should remain central to the API design.

## Why and Explainability

`Why` should remain a rich causal record.

Recommended shape:

```python
@dataclass(frozen=True)
class Why:
    rule: str
    kind: WhyKind
    messages: tuple[str, ...]
    before: dict[str, object]
    after: dict[str, object] | None
    event: dict[str, object]
    expected: dict[str, object] | None
    trace: tuple[dict[str, object], ...]
    step_hash: str
```

And Python should lean into explanation tooling:

- pretty printers
- tree or clause traces
- notebook-friendly display
- structured JSON output

Python is better than Rust at interactive explanation workflows. The API should exploit that.

## State Representation

Python should keep the engine centered on mapping-based state in v1.

Recommendation:

- implementation state: `dict[str, object]`
- domain event: `dict[str, object]`
- spec state: `dict[str, object]`

This matches the semantics and keeps the runtime practical.

Typed models can be added later at the boundary if useful:

- dataclass adapters
- Pydantic adapters
- conversion helpers

But they should not define the core engine shape.

## Builder Strategy

The redesigned Python implementation should not revolve around a chainable builder.

Recommended primary interface:

- plain dataclasses
- small expression constructors
- optional convenience DSL helpers

Example:

```python
spec = Spec(
    name="bank",
    state0={"balance": 100},
    permits=(
        Permit(
            name="has_funds",
            on="Withdraw",
            when=Compare(
                CmpOp.GE,
                Field(Var("state"), "balance"),
                EventField("amount"),
            ),
        ),
    ),
    maintains=(
        Maintain(
            name="non_negative",
            expr=Always(
                Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))
            ),
        ),
    ),
)
```

Optional ergonomics can exist later:

- `spec(...)` helper
- `permit(...)`, `maintain(...)`, `field(...)` constructors
- maybe a thin builder for users who prefer chaining

But those should be convenience layers, not the design center.

## Serialization Strategy

Serialization should be a first-class concern.

Requirements:

- expression round-trip
- spec round-trip
- extractor round-trip
- stable schema versions
- straightforward JSON storage

Recommendations:

- define explicit version tags
- avoid serializing Python code objects
- add golden tests for serialized forms

Suggested top-level keys:

- `k3c_ir_version`
- `k3c_spec_version`

## Python-Specific Ergonomics

This is where Python can exceed a direct Rust-style design.

Useful Python-native features:

- pattern matching over result values
- concise dataclass literals
- friendly REPL and notebook support
- rich explain formatting
- integration with Hypothesis
- easy CLI and scriptability

Potential convenience helpers:

- `explain(event).summary()`
- `replay(events).report()`
- `spec.to_json()`
- `Spec.from_json(...)`
- pretty rendering of `Why`

These should be added at the outer API, not baked into the engine.

## Compose and Bridge

These are useful, but should be runtime-level features.

Recommendation:

- do not let them distort the core engine API
- implement them on top of `Universe`
- make routing and delivery explicit

Suggested runtime abstractions:

```python
class Applyable(Protocol):
    def apply(self, event: object) -> StepResult[dict[str, object]]: ...
    @property
    def state(self) -> dict[str, object]: ...
```

Then:

- `ComposedUniverse`
- `BridgedUniverse`

These remain valuable, but they should not drive the core design.

## Testing Strategy

The redesigned Python implementation should be test-heavy and explanation-friendly.

### Unit tests

- every evaluator branch
- every extractor variant
- maintain classification
- hash chain determinism
- result serialization

### Golden tests

- expression JSON
- spec JSON
- explain output

### Scenario tests

- bank account
- protocol sequencing
- korrelation mismatch
- bounded liveness expiry

### Property tests

- Hypothesis-driven random event sequences
- replay determinism
- serde round-trip

### Differential tests

If a Rust implementation exists later, compare shared scenarios across implementations.

## SSIM as the Design Benchmark

The SSIM example should be used to validate the redesign.

The new Python implementation should support:

1. fixed-width extraction through declarative decode plans
2. record-type dispatch in the decode layer
3. validations expressed declaratively where practical
4. minimal handwritten transition code
5. outputs expressed as data where practical

If SSIM still requires large piles of handwritten extraction glue, the API is still wrong.

## V1 Scope

What should exist in v1:

- expression IR
- total evaluator
- declarative `Spec`
- decode plans and extractor execution
- compiled maintain classification
- `SpecCtx`
- `Why`, `Ok`, `Impossible`, `Violated`
- pure step engine
- `Universe`
- explain support
- Hypothesis-friendly testing hooks
- one simple example and one realistic example

What can wait until v2:

- advanced builder or macro-like conveniences
- large emitter surface
- elaborate plugin systems
- nonessential bridge/compose refinements
- broader schema export targets

## Implementation Order

Recommended sequence:

1. `k3c.ir`
   Define expressions, operators, evaluator, serde.

2. `k3c.spec`
   Define portable spec structures and maintain classification.

3. `k3c.spec.extract`
   Implement extractors and decode plans.

4. `k3c.engine`
   Implement `SpecCtx`, results, and `apply_step`.

5. `k3c.runtime`
   Add `Universe`, replay, and stream APIs.

6. explain and testing support
   Make outcomes easy to inspect and test.

7. realistic example
   Rebuild SSIM against the new API.

8. operational features
   Add bridge, compose, emitters, and CLI only after the engine is stable.

## Open Design Questions

These should be decided early:

1. Should projections and outputs be declarative-only in v1?

Recommendation:
Yes, with explicit runtime escape hatches later if needed.

2. Should Python-native values be the runtime value model?

Recommendation:
Yes for v1, as long as normalization rules are explicit and tested.

3. Should Pydantic or a similar modeling library be used?

Recommendation:
No for the semantic core. Optional adapters later are fine.

4. Should the builder be removed entirely?

Recommendation:
Do not make it central. It can exist later as a convenience wrapper around plain data structures.

5. Should decode support raw bytes in v1?

Recommendation:
Yes. This is required for SSIM and for any serious protocol use case.

## Final Recommendation

The redesigned Python implementation should be data-first, engine-first, and explanation-friendly.

That means:

- declarative specs by default
- explicit decode plans and extractor execution
- total and deterministic engine
- runtime hooks only at the edge
- no obligation to preserve the current callback-centric API

If this is done correctly, the new Python implementation will be better than the current one for both authoring and correctness work. It will remain Pythonic, but in the right place: ergonomic outer layers over a clean declarative semantic core.
