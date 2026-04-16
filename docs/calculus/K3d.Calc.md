# The Kulkarni Calculus — Deterministic Case (K3d)

## For Systems with Complete Causal Knowledge

**Version 0.1**

**Derives from:** K3.Calculus.md (The General Calculus)

---

## Abstract

**K3d** is the deterministic specialization of the Kulkarni Calculus (K3). It applies to systems where **all relevant causes are modeled** — where the transition function maps each state-event pair to exactly one next state, with no unmodeled causal variables.

K3d inherits K3's 7-tuple structure and three meta-operators, with simplified types: `T : S × E → S` and `N : S → Bool × String`. K3d is the appropriate choice for the vast majority of practical systems — bank accounts, state machines, workflow engines, game logic, protocol specifications — where the modeler has complete causal knowledge.

K3d is not a separate calculus. It is K3 where every distribution is a point: `∀s, e: T(s, e) = δ(s')`. This document presents the simplified types and semantics directly, so that programmers building deterministic systems need never encounter distributions.

> **Core Doctrine:** *Design causality, and the system emerges.*

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [The Calculus](#2-the-calculus)
3. [Operational Semantics](#3-operational-semantics)
4. [Meta-Operators](#4-meta-operators)
5. [Output](#5-output)
6. [Tracing](#6-tracing)
7. [Determinism & Replay](#7-determinism--replay)
8. [Verification](#8-verification)
9. [Extensions](#9-extensions)
10. [Compliance Levels](#10-compliance-levels)
11. [Algebraic Properties](#11-algebraic-properties)
12. [Expressiveness & Limitations](#12-expressiveness--limitations)
13. [Comparison with Related Work](#13-comparison-with-related-work)
14. [Implementation Notes](#14-implementation-notes)
15. [Appendices](#appendices)

---

# 1. Introduction

## 1.1 Motivation

Traditional approaches to system design — state machines, event sourcing, actor models — lack a unifying formal foundation. Each provides useful abstractions but none offers a minimal, complete calculus from which system behaviors can be derived with formal guarantees.

K3d addresses this gap by treating **causality** as the primitive concept. Every system behavior is expressed as: *given this state and this event, what happens next, and what must remain true?*

## 1.2 When to Use K3d

K3d is the right choice when your causal model is **complete** — when the transition function captures every relevant cause, and the outcome is fully determined by the current state and the incoming event.

| Domain                      | K3d? | Reason                                           |
| --------------------------- | ---- | ------------------------------------------------ |
| Bank accounts               | Yes  | Balance changes are fully determined             |
| State machines              | Yes  | Transitions are deterministic by definition      |
| Workflow/saga orchestration | Yes  | Each step is determined by current state + event |
| CRUD applications           | Yes  | Data operations are deterministic                |
| Game logic (resolved)       | Yes  | Once dice/randomness is resolved into events     |
| Protocol specifications     | Yes  | Protocol steps are deterministic                 |
| Geometric constructions     | Yes  | Constructions are deterministic                  |
| Physical simulation         | Yes  | Discretized physics with known forces            |
| Trading systems with risk   | No   | Unmodeled market causes → use general K3         |
| Population dynamics         | No   | Unmodeled individual causes → use general K3     |

When your system has significant **unmodeled causes** — where you want to reason about a *field of potential* rather than a single outcome — use the general K3 calculus (K3.Calculus.md).

## 1.3 Relationship to K3

K3d is K3 where every distribution is a point:

```text
K3d ≡ K3 where ∀s, e: T(s, e) = δ(T_det(s, e))
```

The simplified types are obtained by composing with δ and extraction:

```text
K3:    T : S × E → Dist(S)           K3d:   T : S × E → S
K3:    N : Dist(S) → Bool × String    K3d:   N : S → Bool × String
K3:    Apply → Dist(S) ∪ {⊥}         K3d:   Apply → S ∪ {⊥}
```

Everything in this document is derivable from K3. If you need to compose a K3d system with a general K3 system, lift via `δ`: `T_general(s, e) = δ(T_det(s, e))`.

## 1.4 The Physics Analogy

K3d is a **physics engine for systems**. Just as physics engines model the physical world, K3d models any deterministic system as chains of cause and effect:

| Physics Engine    | K3d                 |
| ----------------- | ------------------- |
| Particles         | Entities (in state) |
| Forces            | Events              |
| Laws of motion    | Transitions         |
| Conservation laws | Invariants          |
| Time evolution    | Simulation          |
| Measurement       | Projection          |

## 1.5 Design Principles

1. **Minimality**: No primitive can be derived from others
2. **Expressiveness**: Any discrete causal system with decidable predicates can be expressed
3. **Compositionality**: Systems combine algebraically
4. **Decidability**: Guards and invariants are computable predicates
5. **Determinism**: Same inputs always produce same outputs

## 1.6 Etymology

**Kulkarni Calculus** denoted as **K3** is derived from "Karma Kognitive Kit". The name **Karma** (कर्म) from Sanskrit means "action" or "deed" — the universal law of cause and effect.

## 1.7 Philosophical Foundation

### Satkaryavada — The Effect Pre-Exists in the Cause

The Samkhya school of Indian philosophy provides a theory of causation called **Satkaryavada** (सत्कार्यवाद): the effect pre-exists in the cause. The pot exists latently in the clay before the potter shapes it. In K3d, this principle is fully realized: given state and event, the next state is already determined.

### Why These Seven Primitives?

Each K3d primitive corresponds to an irreducible aspect of causality:

| Primitive          | Sanskrit        | Philosophical Role                                                          |
| ------------------ | --------------- | --------------------------------------------------------------------------- |
| **S** (State)      | Avasthā (अवस्था)  | *The condition of being* — what exists now                                  |
| **S₀** (Initial)   | Aarambha (आरम्भ) | *The beginning* — every causal chain has an origin                          |
| **E** (Event)      | Ghatna (घटना)    | *That which happens* — the impulse that disturbs equilibrium                |
| **G** (Guard)      | Rakshak (रक्षक)  | *The protector* — not all actions are permitted in all states               |
| **T** (Transition) | Chalan (चलन)    | *Movement* — the law by which cause produces effect                         |
| **N** (Invariant)  | Niyama (नियम)    | *The rule, the law* — that which must always hold                           |
| **P** (Projection) | Prakriti (प्रकृति) | *Nature, derived form* — the observable manifestation of underlying reality |

### The Karmic Correspondence

- **Kriyamana karma** — actions being performed now → Events
- **Sanchita karma** — accumulated effects from past actions → State
- **Prarabdha karma** — effects currently manifesting → Transitions
- **Niyama** — the cosmic law ensuring like causes produce like effects → Invariants

## 1.8 Scope

K3d is designed for **discrete causal systems** — systems where:

- State is discrete (or discretized)
- Time advances in logical steps (event indices)
- Transitions are deterministic functions
- All predicates (guards, invariants) are decidable

K3d does **not** natively model:

- Continuous-time dynamics (use discretized time steps — see K3.Patterns)
- Systems with significant unmodeled causes (see general K3)
- Liveness properties (see K3ᵗ extension)
- Higher-order systems that modify their own transitions (model as rules-in-state)
- Concurrent event processing (use composition)

### Sequential Semantics

**K3d systems process events sequentially.** The `Apply` function defines an atomic state transition; there is no concurrent `Apply` in K3d semantics.

```text
Apply(s, e) → s' ∪ {⊥}       // Atomic: one event, one state transition
Reduce(s, E*)                  // Sequential: events processed one at a time
```

For systems requiring concurrent event processing, model concurrent components as separate K3d systems and compose them:

```text
System = Component₁ <||> Component₂ <||> Component₃
```

Each component processes its events sequentially. Concurrency exists *between* components, mediated by bridges.

---

# 2. The Calculus

## 2.1 Definition

A K3d model is a **7-tuple**:

```text
K3d = (S, S₀, E, G, T, N, P)
```

## 2.2 The Seven Primitives

| Symbol | Name       | Sanskrit | Devanagari | Type                    | Description                |
| ------ | ---------- | -------- | ---------- | ----------------------- | -------------------------- |
| **S**  | State      | Avasthā  | अवस्था       | `Set`                   | The state space            |
| **S₀** | Initial    | Aarambha | आरम्भ       | `S₀ ∈ S`                | The initial state          |
| **E**  | Event      | Ghatna   | घटना        | `Set`                   | The event space            |
| **G**  | Guard      | Rakshak  | रक्षक       | `S × E → Bool × String` | Admissibility predicate    |
| **T**  | Transition | Chalan   | चलन        | `S × E → S`             | State transformation       |
| **N**  | Invariant  | Niyama   | नियम        | `S → Bool × String`     | Safety predicate           |
| **P**  | Projection | Prakriti | प्रकृति       | `{name: S → R}`         | Named derived computations |

### Note on Projections

Projections unify derived computations and observable views. Both are pure functions from state to some output type:

```text
P = {
    name: String,
    fn: S → R,
    kind: Derived | Observable | Metric,  // Optional classification
    cache: Bool                            // Implementation hint
}
```

The distinction between "computation for business logic" vs "projection for display" is an implementation concern, not a semantic one.

## 2.3 The Three Meta-Operators

| Symbol     | Name    | Sanskrit | Type                                 | Description                    |
| ---------- | ------- | -------- | ------------------------------------ | ------------------------------ |
| **<\|\|>** | Compose | —        | `K3d × K3d → K3d`                    | Parallel composition           |
| **<->**    | Bridge  | —        | `K3d × K3d × Mapper × Mode → Bridge` | Cross-system event propagation |
| **<?>**    | Samsara | संसार      | `K3d × E* → RunResult`               | Simulation & testing           |

## 2.4 Complete Reference

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                    K3d: THE KULKARNI CALCULUS (DETERMINISTIC)               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  7-TUPLE:  K3d = (S, S₀, E, G, T, N, P)                                     │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  PRIMITIVES                                                          │   │
│  ├──────────┬──────────────┬─────────────────────────┬──────────────────┤   │
│  │  Symbol  │  Sanskrit    │  Type                   │  Role            │   │
│  ├──────────┼──────────────┼─────────────────────────┼──────────────────┤   │
│  │  S       │  Avasthā     │  Set                    │  State space     │   │
│  │  S₀      │  Aarambha    │  ∈ S                    │  Initial state   │   │
│  │  E       │  Ghatna      │  Set                    │  Event space     │   │
│  │  G       │  Rakshak     │  S × E → Bool × String  │  Guard           │   │
│  │  T       │  Chalan      │  S × E → S              │  Transition      │   │
│  │  N       │  Niyama      │  S → Bool × String      │  Invariant       │   │
│  │  P       │  Prakriti    │  {name: S → R}          │  Projection      │   │
│  └──────────┴──────────────┴─────────────────────────┴──────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  META-OPERATORS                                                      │   │
│  ├──────────┬──────────────┬─────────────────────────┬──────────────────┤   │
│  │  <||>    │  Compose     │  K3d × K3d → K3d        │ Parallel         │   │
│  │  <->     │  Bridge      │  K3d × K3d × M × B → Br │ Event propagation│   │
│  │  <?>     │  Samsara     │  K3d × E* → RunResult   │ Simulation       │   │
│  └──────────┴──────────────┴─────────────────────────┴──────────────────┘   │
│                                                                             │
│  CAUSAL STEP:  Apply(s, e) = G(s,e) → s' = T(s,e) → N(s') → s'              │
│  REDUCTION:    Reduce(s, []) = s; Reduce(s, e::es) = Reduce(Apply(s,e), es) │
│                                                                             │
│  AXIOMS:                                                                    │
│    1. Determinism:    T, G, N, P are deterministic                          │
│    2. Totality:       G(s,e), T(s,e), N(s) defined ∀s,e                     │
│    3. Closure:        T(s,e) ∈ S                                            │
│    4. Initial:        N(S₀) = true                                          │
│  WELL-FORMEDNESS:     N(s) ∧ G(s,e) ⇒ N(T(s,e))                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2.5 Primitive Definitions

### State (S) — Avasthā

The **state space** is a set of all possible states the system can be in. Each state is a snapshot of the system at a point in logical time.

```text
S : Set

// Practical form: a record type
S = {
    field₁: Type₁,
    field₂: Type₂,
    ...
}
```

### Initial State (S₀) — Aarambha

A distinguished element of S representing the starting configuration:

```text
S₀ ∈ S
```

The initial state MUST satisfy the invariant: `N(S₀) = (true, _)`.

### Events (E) — Ghatna

The **event space** defines all possible inputs to the system:

```text
E : Set

// Practical form: a discriminated union
E = EventType₁(payload₁)
    | EventType₂(payload₂)
    | ...
```

Events represent external stimuli — things that happen *to* the system. They carry data as payloads.

### Guard (G) — Rakshak

The **guard** determines whether an event is admissible given the current state:

```text
G : S × E → Bool × String
```

The guard returns `(true, "")` if the event is allowed, or `(false, reason)` if it is rejected. `reason` is a human-readable string explaining why.

**No side effects.** Guards are pure functions. They cannot modify state, emit events, or depend on external input.

**Determinism rule:** No `now()`, `random()`, `uuid()` in guards. External inputs (timestamps, random values) must arrive in event payloads.

### Transition (T) — Chalan

The **transition function** computes the next state:

```text
T : S × E → S
```

Given the current state and an admissible event, T produces exactly one next state.

**No side effects.** Transitions are pure functions. External actions (sending emails, calling APIs) are handled by Output (§5), which is computed post-transition.

**Determinism rule:** Same as guards — no `now()`, `random()`, `uuid()` in transitions.

### Invariant (N) — Niyama

The **invariant** checks that a state satisfies the system's safety properties:

```text
N : S → Bool × String
```

Returns `(true, "")` if the state is valid, or `(false, reason)` if it violates an invariant.

**The `why` pattern:** The string explains *what* is violated and *why*:

```text
N(s) = (
    s.balance ≥ 0 ∧ s.status ∈ {Active, Closed},
    if s.balance < 0 then "Balance cannot be negative: " + s.balance
    else "Invalid status: " + s.status
)
```

### Projection (P) — Prakriti

**Projections** are named, pure functions from state to derived values:

```text
P = {
    name₁: S → R₁,
    name₂: S → R₂,
    ...
}
```

Projections observe but never cause. They reveal what is latent in the state.

## 2.6 Foundational Axioms

**Axiom 1 — Determinism.** `T`, `G`, `N`, and `P` are deterministic functions. Given the same inputs, they always produce the same outputs.

```text
∀s ∈ S, e ∈ E: T(s, e) = T(s, e)    // Referentially transparent
```

**Axiom 2 — Totality.** `G`, `T`, and `N` are total functions:

```text
∀s ∈ S, e ∈ E: G(s, e) is defined
∀s ∈ S, e ∈ E: T(s, e) is defined
∀s ∈ S: N(s) is defined
```

**Axiom 3 — Closure.** Every transition produces a state within S:

```text
∀s ∈ S, e ∈ E: T(s, e) ∈ S
```

**Axiom 4 — Initial Validity.** The initial state satisfies the invariant:

```text
N(S₀) = (true, _)
```

**Well-Formedness.** Valid transitions of valid states produce valid states:

```text
∀s ∈ S, e ∈ E:
    N(s) = (true, _) ∧ G(s, e) = (true, _) ⇒ N(T(s, e)) = (true, _)
```

This is the fundamental **proof obligation** for every K3d system.

---

# 3. Operational Semantics

## 3.1 The Causal Step (Apply)

The fundamental operation in K3d:

```text
Apply : S × E → S ∪ {⊥}

Apply(s, e) =
    let (g_ok, g_reason) = G(s, e) in
    if ¬g_ok then ⊥[impossible(g_reason)]
    else
        let s' = T(s, e) in
        let (n_ok, n_reason) = N(s') in
        if ¬n_ok then ⊥[violated(n_reason)]
        else s'
```

## 3.2 Execution Order

```text
1. Pre-invariant check (optional, defense in depth)
2. Guard evaluation
3. Transition computation
4. Post-invariant check
5. Result: new state or rejection
```

## 3.3 Pre-Invariant Check (Defense in Depth)

Implementations MAY check the invariant on the current state before processing:

```text
Apply_defended(s, e) =
    let (pre_ok, pre_reason) = N(s) in
    if ¬pre_ok then ⊥[corrupted(pre_reason)]
    else Apply(s, e)
```

Pre-invariant failure indicates a bug — the system reached an invalid state.

## 3.4 Invariant Phases

| Phase | Checks           | Use Case                            |
| ----- | ---------------- | ----------------------------------- |
| Post  | After T only     | Normal operation (default)          |
| Both  | Before and after | Debug mode, defense in depth        |
| Pre   | Before T only    | Detect prior corruption             |
| None  | Never            | Performance mode (use with caution) |

## 3.5 Reduction

```text
Reduce : S × E* → S ∪ {⊥}

Reduce(s, []) = s
Reduce(s, e :: es) =
    let s' = Apply(s, e) in
    if s' = ⊥ then ⊥
    else Reduce(s', es)
```

**Theorem (Replay Equivalence):** `Reduce` is a pure function. Identical inputs always yield identical outputs.

*Proof:* By induction on the event sequence length, using Axiom 1 (determinism). Base case: `Reduce(s, []) = s`. Inductive step: `Apply(s, e)` is deterministic by Axiom 1, so `Reduce` of the tail is deterministic by induction hypothesis. ∎

## 3.6 Simulation

```text
Simulate : S × E* → RunResult

RunResult = {
    final_state: S,
    trajectory: S*,
    traces: Trace*
}

Simulate(s, []) = { final_state: s, trajectory: [s], traces: [] }
Simulate(s, e :: es) =
    let s' = Apply(s, e) in
    if s' = ⊥ then error
    else
        let rest = Simulate(s', es) in
        { ...rest, trajectory: [s] ++ rest.trajectory }
```

## 3.7 Time Semantics

K3d uses **logical time**, not wall-clock time:

```text
time(s) = number of events processed to reach s
```

Logical time defines *ordering*, not duration. Real-time constraints can be modeled by encoding timestamps in event payloads and checking them in guards.

## 3.8 Error Types

| Error                | Condition                                        |
| -------------------- | ------------------------------------------------ |
| `PreInvariantError`  | `N(s) = (false, reason)` — current state invalid |
| `GuardError`         | `G(s, e) = (false, reason)` — event not allowed  |
| `PostInvariantError` | `N(s') = (false, reason)` — new state invalid    |
| `UnknownEventError`  | Event has no registered transition (strict mode) |

---

# 4. Meta-Operators

## 4.1 Composition (<||>)

The **parallel composition** operator combines two K3d systems:

```text
(<||>) : K3d × K3d → K3d

K3d₁ <||> K3d₂ = (S, S₀, E, G, T, N, P)
```

Where:

```text
S  = S₁ × S₂                           // Product state
S₀ = (S₀₁, S₀₂)                        // Product initial
E  = Left(E₁) | Right(E₂)              // Sum of events

G((s₁, s₂), Left(e₁))  = G₁(s₁, e₁)
G((s₁, s₂), Right(e₂)) = G₂(s₂, e₂)

T((s₁, s₂), Left(e₁))  = (T₁(s₁, e₁), s₂)
T((s₁, s₂), Right(e₂)) = (s₁, T₂(s₂, e₂))

N((s₁, s₂)) = N₁(s₁) ∧ N₂(s₂)          // Conjunction

P = {left.p: P₁.p ∘ π₁, right.p: P₂.p ∘ π₂}
```

Events in one system do not affect the other (unless connected by a bridge).

## 4.2 Bridge (<->)

The **bridge** operator connects two systems with event propagation:

```text
(<->) : K3d × K3d × Mapper × BridgeMode → Bridge

Bridge = {
    source: K3d₁,
    target: K3d₂,
    mapper: (s_before: S₁, e: E₁, s_after: S₁) → Option<E₂>,
    mode: BridgeMode
}

BridgeMode = Synchronous | Async | BestEffort
```

The mapper observes source transitions and optionally emits target events:

```text
mapper(s_before, e, s_after) =
    Some(e₂)    // Emit event e₂ to target
    | None      // No propagation
```

### Bridge Modes

| Mode          | Semantics                                        | Use Case                   |
| ------------- | ------------------------------------------------ | -------------------------- |
| `Synchronous` | Target failure fails entire operation            | Transactional systems      |
| `Async`       | Target event queued, source succeeds immediately | Event-driven architectures |
| `BestEffort`  | Target failure logged but ignored                | Notifications, metrics     |

**Bridge Determinism Rule:** For Async and BestEffort modes, delivery outcomes must be encoded into state to preserve replay determinism.

**Synchronous Bridge Apply:**

```text
BridgeApply_sync(s₁, s₂, e₁) =
    let s₁' = Apply₁(s₁, e₁) in
    if s₁' = ⊥ then ⊥
    else
        match mapper(s₁, e₁, s₁') with
        | None → (s₁', s₂)
        | Some(e₂) →
            let s₂' = Apply₂(s₂, e₂) in
            if s₂' = ⊥ then ⊥
            else (s₁', s₂')
```

**Async Bridge Apply:**

```text
BridgeApply_async(s₁, s₂, e₁, queue) =
    let s₁' = Apply₁(s₁, e₁) in
    if s₁' = ⊥ then ⊥
    else
        match mapper(s₁, e₁, s₁') with
        | None → (s₁', s₂, queue)
        | Some(e₂) → (s₁', s₂, queue ++ [e₂])
```

**BestEffort Bridge Apply:**

```text
BridgeApply_besteffort(s₁, s₂, e₁, traces) =
    let s₁' = Apply₁(s₁, e₁) in
    if s₁' = ⊥ then ⊥
    else
        match mapper(s₁, e₁, s₁') with
        | None → (s₁', s₂, traces)
        | Some(e₂) →
            let s₂' = Apply₂(s₂, e₂) in
            if s₂' = ⊥ then
                (s₁', s₂, traces ++ [BridgeFailure(e₂)])
            else (s₁', s₂', traces)
```

### Async Bridge Formalization

An Async bridge is formally a composition of three K3d systems with Synchronous bridges:

```text
AsyncBridge(A, B, mapper) =
    let Queue = K3d(
        S = {
            pending: List<E_B>,
            in_flight: Option<E_B>,
            delivered: List<E_B>,
            failed: List<(E_B, Error)>,
            retry_count: Map<E_B, ℕ>,
            max_retries: ℕ
        },
        S₀ = { pending: [], in_flight: None, delivered: [], failed: [], retry_count: {}, max_retries: 3 },
        E = Enqueue(e: E_B) | Deliver | Ack | Nack(error: Error) | Retry | DeadLetter,
        G = {
            Enqueue(_): true,
            Deliver: pending ≠ [] ∧ in_flight = None,
            Ack: in_flight ≠ None,
            Nack(_): in_flight ≠ None,
            Retry(e): failed.contains(e) ∧ retry_count[e] < max_retries,
            DeadLetter(e): failed.contains(e) ∧ retry_count[e] ≥ max_retries
        },
        T = { ... },    // Standard queue operations
        N = { |pending| + |in_flight| + |delivered| + |failed| = total_enqueued }
    )
    in
        (A <->[mapper, Sync] Queue) <||> (Queue <->[deliver_mapper, Sync] B)
```

**Key insight:** Async is just Sync composition with an explicit queue system. The queue is a full K3d system with its own state, events, guards, and invariants.

## 4.3 Samsara (<?>)

The **samsara** operator provides simulation and testing:

```text
(<?>) : K3d × E* → RunResult

RunResult = {
    final_state: S,
    trajectory: S*,
    traces: Trace*
}
```

**Samsara operations:**

| Operation      | Signature         | Description            |
| -------------- | ----------------- | ---------------------- |
| simulate       | E* → RunResult    | Run with trajectory    |
| reduce         | E* → S            | Run without trajectory |
| fuzz           | Config → Report   | Random testing         |
| random_stream  | Int → E*          | Generate random events |
| property_check | Property → Result | Property-based testing |

---

# 5. Output

Output (O) is a **derived concept**, not a primitive:

```text
O : (S × E × S) → O*
```

Outputs are commands emitted *after* a transition for external execution. They are:

- **Post-causal:** Computed after Apply, not part of the causal step
- **Deterministic:** Same `(s, e, s')` → same output list
- **Replay-safe:** Skipped during replay (external effects not re-executed)
- **Distinct from projections:** P reads state; O emits commands

```text
Apply(s, e) → s'
O(s, e, s') → [SendEmail(...), EnqueueJob(...), ...]
```

Outputs execute outside K3d semantics. The K3d system is causally complete without them.

---

# 6. Tracing

## 6.1 Design Principle

Traces are **non-interfering projections** over execution:

```text
Trace ⊥ Apply     // Tracing is orthogonal to causality
```

This means:

1. Removing all traces produces identical state evolution
2. Traces are replay-derivable
3. Traces may be discarded without loss of correctness

## 6.2 Formal Definition

```text
TraceRecord = {
    t: ℕ,                       // Logical time
    event: E,
    state_before: S,
    state_after: S,
    guard_result: (Bool, String),
    invariant_result: (Bool, String),
    outputs: O*,
    metadata: Map<String, Any>
}
```

## 6.3 Tracing and Apply

```text
ApplyTraced(s, e) =
    let (g_ok, g_reason) = G(s, e) in
    if ¬g_ok then
        emit_trace(s, e, ⊥, (g_ok, g_reason), ⊥)
        ⊥
    else
        let s' = T(s, e) in
        let (n_ok, n_reason) = N(s') in
        emit_trace(s, e, s', (true, ""), (n_ok, n_reason))
        if ¬n_ok then ⊥
        else s'
```

`emit_trace` is a projection — it observes but cannot affect the return value.

## 6.4 Design Invariants for Tracing

```text
1. Idempotent:     trace(trace(Apply)) ≡ trace(Apply)
2. Non-interfering: Apply_with_tracing(s,e) ≡ Apply_without_tracing(s,e)
3. Reproducible:   replay(events) produces identical traces
4. Discardable:    system correctness does not depend on traces
```

---

# 7. Determinism & Replay

## 7.1 The Determinism Guarantee

K3d provides the strongest possible replay guarantee:

```text
∀S₀, ∀E*: Reduce(S₀, E*) is deterministic
```

Same initial state + same event sequence = same final state. Always. No entropy recording needed, no seeds, no special replay mode. This is the defining property of K3d.

## 7.2 Replay

```text
Replay(S₀, event_log) =
    Reduce(S₀, event_log.events)

// Verification
assert Replay(S₀, event_log).final_state = recorded_final_state
```

## 7.3 Determinism Rules

To preserve the determinism guarantee, K3d forbids nondeterministic inputs in G, T, N, and P:

| Forbidden in G/T/N/P | Why                          | Alternative                   |
| -------------------- | ---------------------------- | ----------------------------- |
| `now()`              | Wall clock varies            | Timestamp in event payload    |
| `random()`           | Different each call          | Random value in event payload |
| `uuid()`             | Different each call          | UUID in event payload         |
| File/network I/O     | External state varies        | Result as event payload       |
| Mutable global state | Shared state race conditions | Include in S or event payload |

All nondeterminism enters through **event payloads**, never through G, T, N, or P directly.

---

# 8. Verification

## 8.1 The Proof Obligation

Every K3d system must satisfy well-formedness:

```text
∀s ∈ S, e ∈ E:
    N(s) = (true, _) ∧ G(s, e) = (true, _) ⇒ N(T(s, e)) = (true, _)
```

## 8.2 Verification Strategies

### Property-Based Testing (Fuzz)

```text
fuzz_test(K3d, iterations=10000):
    for _ in iterations:
        events = random_event_sequence(max_length=100)
        result = simulate(S₀, events)
        assert result ≠ PostInvariantError
```

### Golden Stream Testing

```text
golden_test(K3d, event_sequence, expected_final_state):
    actual = reduce(S₀, event_sequence)
    assert actual = expected_final_state
```

### Inductive Proof

```text
1. Base case:    Prove N(S₀) = (true, _)
2. Inductive:    For each event type e:
                     Assume N(s) ∧ G(s, e) = (true, _)
                     Prove N(T(s, e)) = (true, _)
```

### Model Checking

For finite or bounded state spaces:

```text
model_check(K3d, bound):
    reachable = explore_states(S₀, bound)
    for s in reachable:
        assert N(s) = (true, _)
        for e in E:
            if G(s, e) = (true, _):
                s' = T(s, e)
                assert N(s') = (true, _)
```

Tools: TLA+ (TLC), Alloy, SPIN.

## 8.3 Verification Templates

### Monotonicity

```text
Invariant: x ≤ max_value
Proof: Guard encodes the bound check.
  G(s, Increment(delta)) = (s.x + delta ≤ max_value, "Would exceed max")
  T(s, Increment(delta)) = { ...s, x: s.x + delta }
  ⟹ Guard ensures post-condition.
```

### Conservation

```text
Invariant: sum(field) = constant
Proof: Every increment has a matching decrement.
  T(s, Transfer(from, to, amt)) = {
      ...s,
      balances: s.balances.update(from, b → b - amt).update(to, b → b + amt)
  }
  ⟹ Net change is zero.
```

### Ordering

```text
Invariant: list is sorted
Proof: Guard validates insertion point.
  G(s, Insert(x, pos)) = (
      (pos = 0 ∨ s.list[pos-1] ≤ x) ∧ (pos = |s.list| ∨ x ≤ s.list[pos]),
      "Would break ordering"
  )
```

### State Machine

```text
Invariant: status ∈ reachable_from(initial_status)
Proof: Guard checks current status.
  G(s, Ship) = (s.status = Paid, "Can only ship paid orders")
  T(s, Ship) = { ...s, status: Shipped }
```

### Referential Integrity

```text
Invariant: ∀ref ∈ references: ref ∈ valid_targets
Proof: Guard checks target exists before adding reference.
  G(s, AddItem(order_id, product_id)) = (
      order_id ∈ s.orders ∧ product_id ∈ s.products, "Invalid reference"
  )
```

## 8.4 Decidable Fragments

| Fragment             | N type                       | Decision Procedure     |
| -------------------- | ---------------------------- | ---------------------- |
| Finite state × event | Any computable N             | Exhaustive enumeration |
| Linear arithmetic    | Linear inequalities over ℤ/ℝ | SMT (Z3, CVC5)         |
| Monotonic systems    | f(s') ≥ f(s)                 | Induction              |

---

# 9. Extensions

K3d systems can be lifted to general K3 and composed with K3 extensions:

## 9.1 Lifting to K3 (General)

```text
lift : K3d → K3
lift(S, S₀, E, G, T_det, N_det, P) = (S, S₀, E, G, T, N, P)
    where
        T(s, e) = δ(T_det(s, e))
        N(d) = N_det(the_single_state(d))
```

This is required when composing K3d systems with non-deterministic K3 systems via `<||>` or `<->`.

## 9.2 K3⁺ — Context Extension

Adds an 8th element `Ctx` for multi-tenancy, audit trails, and ambient information:

```text
K3d⁺ = (S, S₀, E, G, T, N, P, Ctx)
```

## 9.3 K3ᵗ — Temporal Extension

Adds temporal/liveness properties:

```text
K3dᵗ = (S, S₀, E, G, T, N, P, L)
L : Set<TemporalFormula>    // ◇φ, □φ, φ U ψ
```

---

# 10. Compliance Levels

KC (Kulkarni Calculus) Compliance Levels for K3d implementations:

| Level    | Name                    | Core Capability                   |
| -------- | ----------------------- | --------------------------------- |
| **KC-1** | Core Semantics          | Deterministic state transitions   |
| **KC-2** | Observable Semantics    | Projections and observability     |
| **KC-3** | Traceable Semantics     | Simulation with replay guarantees |
| **KC-4** | Compositional Semantics | Multi-system modeling             |
| **KC-5** | Verified Semantics      | Formal correctness proofs         |
| **KC-6** | Certified Runtime       | Regulatory-grade audit            |

### KC-1: Core Semantics

**Required:** S, S₀, E, G, T (→ S), N (S → Bool × String)

**Guarantees:** Deterministic state evolution, guard-based admission, invariant-based safety.

### KC-2: Observable Semantics

KC-1 + P (projections).

### KC-3: Traceable Semantics

KC-2 + <?> (Samsara) with deterministic replay.

### KC-4: Compositional Semantics

KC-3 + <||> (composition) + <-> (bridges, all modes).

### KC-5: Verified Semantics

KC-4 + fuzz testing, golden stream testing, invariant preservation verification.

### KC-6: Certified Runtime

KC-5 + tamper-evident event log, attestation chain, formal well-formedness proof.

**Note:** KC-6 is OPTIONAL and intended for regulated industries.

### Compliance Matrix

| Capability           | KC-1 | KC-2 | KC-3 | KC-4 | KC-5 | KC-6 |
| -------------------- | ---- | ---- | ---- | ---- | ---- | ---- |
| Apply                | ✓    | ✓    | ✓    | ✓    | ✓    | ✓    |
| Guard + Invariant    | ✓    | ✓    | ✓    | ✓    | ✓    | ✓    |
| Projections          |      | ✓    | ✓    | ✓    | ✓    | ✓    |
| Samsara              |      |      | ✓    | ✓    | ✓    | ✓    |
| Deterministic Replay |      |      | ✓    | ✓    | ✓    | ✓    |
| Composition (<\|\|>) |      |      |      | ✓    | ✓    | ✓    |
| Bridge (<->)         |      |      |      | ✓    | ✓    | ✓    |
| Fuzz / Golden tests  |      |      |      |      | ✓    | ✓    |
| Formal verification  |      |      |      |      | ✓    | ✓    |
| Certified audit      |      |      |      |      |      | ✓    |

---

# 11. Algebraic Properties

## 11.1 Composition Laws

```text
(A <||> B) <||> C  ≅  A <||> (B <||> C)     // Associativity
A <||> B  ≅  B <||> A                         // Commutativity (up to iso)
A <||> Unit  ≅  A                              // Identity
    where Unit = ({()}, (), {}, λ_.true, λ_.(), λ_.true, {})
```

## 11.2 Reduction Laws

```text
Reduce(s, []) = s
Reduce(s, E₁ ++ E₂) = Reduce(Reduce(s, E₁), E₂)    // Associativity
```

## 11.3 Safety Laws

```text
N(s) ∧ G(s,e) ⇒ N(T(s,e))                            // Invariant preservation
N(S₀) ∧ (∀s,e: N(s) ∧ G(s,e) ⇒ N(T(s,e))) ⇒ ∀ reachable s: N(s)  // Induction
¬G(s,e) ⇒ Apply(s,e) = ⊥                              // Guard safety
N₁(s₁) ∧ N₂(s₂) ⇒ N_composed(s₁, s₂)                 // Composition
```

## 11.4 Trace Laws

```text
Apply_traced(s, e).state = Apply(s, e).state            // Non-interference
trace(Replay(E*)) = trace(Replay(E*))                    // Reproducibility
```

## 11.5 Category-Theoretic Structure

K3d systems form a **symmetric monoidal category**:

- **Objects:** K3d systems
- **Morphisms:** Bridges
- **Tensor product:** <||>
- **Unit:** The trivial K3d system

---

# 12. Expressiveness & Limitations

## 12.1 What K3d Can Express

Any discrete, deterministic causal system with decidable predicates:

- State machines (finite or infinite state)
- Event-sourced systems
- Workflow/saga orchestration
- Protocol specifications
- Game mechanics (with resolved randomness)
- Physical simulations (discretized, with known forces)
- Chemical reactions
- Geometric constructions
- Lambda Calculus (Turing-complete)

## 12.2 Turing Completeness

K3d is Turing-complete. Lambda Calculus encodes as a K3d system:

```text
S = { term: LambdaTerm, reduced: Bool }
E = BetaReduce
G(s, BetaReduce) = (has_redex(s.term) ∧ ¬s.reduced, "No redex")
T(s, BetaReduce) = { term: reduce_leftmost(s.term), reduced: ¬has_redex(...) }
N(s) = (true, "")
```

## 12.3 What K3d Cannot Express Natively

| Concept                     | Why Not Native         | Modeling Strategy         |
| --------------------------- | ---------------------- | ------------------------- |
| Unmodeled causes            | K3d is deterministic   | Use general K3            |
| Continuous time             | K3d uses logical time  | Tick events + integration |
| Liveness properties         | K3d is safety-oriented | K3ᵗ extension             |
| Higher-order transitions    | T is fixed             | Rules as state            |
| Concurrent event processing | Apply is sequential    | Composition (<\|\|>)      |

## 12.4 Expressiveness Relationship

```text
FSM ⊂ LTS ⊂ K3d ⊂ K3

Petri Nets ≅ K3d (with appropriate encoding)
Event Sourcing ⊂ K3d (K3d adds guards + invariants + composition)
Actor Model ~ K3d <||> + <-> (composition + bridges)
```

---

# 13. Comparison with Related Work

| System         | K3d Comparison                                                                   |
| -------------- | -------------------------------------------------------------------------------- |
| TLA+           | K3d is more operational; TLA+ is more declarative. K3d adds composition natively |
| Event Sourcing | K3d formalizes + adds guards, invariants, composition                            |
| State Machines | K3d generalizes with arbitrary S, invariants, algebra                            |
| Petri Nets     | K3d adds guards, invariants, richer state                                        |
| CSP/CCS        | K3d uses sequential semantics + composition rather than concurrency primitives   |

---

# 14. Implementation Notes

## 14.1 Well-Formedness Rules

A K3d system is **well-formed** if:

```text
1. S ≠ ∅                           // Non-empty state space
2. S₀ ∈ S                          // Initial state exists
3. N(S₀) = (true, _)               // Initial state is valid
4. E ≠ ∅                           // Non-empty event space
5. ∀s ∈ S, e ∈ E: G(s,e) defined   // Guard is total
6. ∀s ∈ S, e ∈ E: T(s,e) ∈ S       // Transition is closed
7. ∀s ∈ S: N(s) defined            // Invariant is total
8. Invariant preservation holds    // Well-formedness condition
```

## 14.2 State Cloning

```text
CloneMode = None | Shallow | Deep

None:    No cloning (immutable state required)
Shallow: Shallow copy
Deep:    Deep copy (safe but slow)
```

**Recommendation**: Use immutable state with `CloneMode = None`.

## 14.3 Performance Characteristics

| Operation | Complexity           | Notes              |
| --------- | -------------------- | ------------------ |
| Apply     | O(G + T + N)         | Single event       |
| Reduce    | O(n × Apply)         | n events           |
| Simulate  | O(n × Apply + n × S) | Trajectory storage |
| Compose   | O(1)                 | Lazy delegation    |

## 14.4 Thread Safety

K3d models are thread-safe when state is immutable or `CloneMode ≠ None`.

## 14.5 Distributed Composition

When composing K3d systems across network boundaries:

| Composition             | Consistency | Guarantee                 |
| ----------------------- | ----------- | ------------------------- |
| `<\|\|>` (same process) | Strong      | Linearizable              |
| `<->` Synchronous       | Strong      | Atomic across systems     |
| `<->` Async             | Eventual    | Causal ordering preserved |
| `<->` BestEffort        | Weak        | No ordering guarantee     |

```text
DistributedBridgeConfig = {
    retry_policy: RetryPolicy,
    timeout: Duration,
    fallback: FallbackStrategy,
    dead_letter_queue: Queue?
}

RetryPolicy = NoRetry | FixedDelay(n, delay) | ExponentialBackoff(n, base)
FallbackStrategy = Fail | Ignore | DeadLetter | Compensate(action)
```

---

# Appendices

## Appendix A: Sanskrit Terminology

| Symbol | English    | Sanskrit | Devanagari | Meaning                 |
| ------ | ---------- | -------- | ---------- | ----------------------- |
| S      | State      | Avasthā  | अवस्था       | Condition, state        |
| S₀     | Initial    | Aarambha | आरम्भ       | Beginning, commencement |
| E      | Event      | Ghatna   | घटना        | Happening, event        |
| G      | Guard      | Rakshak  | रक्षक       | Protector, guard        |
| T      | Transition | Chalan   | चलन        | Movement, motion        |
| N      | Invariant  | Niyama   | नियम        | Rule, law               |
| P      | Projection | Prakriti | प्रकृति       | Nature, derived form    |
| O      | Output     | Pariṇāma | परिणाम       | Result, consequence     |
| <?>    | Simulate   | Samsara  | संसार        | Cycle, world            |

## Appendix B: Quick Reference

```text
K3d = (S, S₀, E, G, T, N, P)

Causal Step ≡ Apply(s, e) = G(s,e) → s' = T(s,e) → N(s') → s'

Reduce(s, []) = s
Reduce(s, e::es) = Reduce(Apply(s,e), es)

K3d₁ <||> K3d₂ = parallel composition
K3d₁ <->[m, mode] K3d₂ = bridge with mapper m and mode
<?>(K3d, E*) = simulation

Axioms:
  1. Determinism:   T, G, N, P are deterministic
  2. Totality:      G(s,e), T(s,e), and N(s) defined ∀s,e
  3. Closure:       T(s,e) ∈ S
  4. Initial:       N(S₀) = true

Well-formedness:
  N(s) ∧ G(s,e) ⇒ N(T(s,e))   [Proof obligation]

Theorem (Replay):
  Reduce is a pure function: identical inputs yield identical outputs

Output (O) — Derived Concept:
  O : (s, e, s') → O*
  - Post-causal, deterministic, replay-safe

Tracing:
  - Non-interfering projection over execution
  - Deterministic and reproducible
  - Discardable without loss of correctness

Lift to general K3:
  T_general(s, e) = δ(T_det(s, e))
  N_general(d) = N_det(the_single_state(d))
```

## Appendix C: Example — Bank Account

```text
K3d_BankAccount = (S, S₀, E, G, T, N, P)

S = { balance: ℕ, status: Active | Closed }

S₀ = { balance: 0, status: Active }

E = Deposit(amount: ℕ)
    | Withdraw(amount: ℕ)
    | Close

G(s, Deposit(_))  = (s.status = Active, "Account must be active")
G(s, Withdraw(a)) = (s.balance ≥ a ∧ s.status = Active, "Insufficient funds or closed")
G(s, Close)       = (s.balance = 0, "Must have zero balance")

T(s, Deposit(a))  = { ...s, balance: s.balance + a }
T(s, Withdraw(a)) = { ...s, balance: s.balance - a }
T(s, Close)       = { ...s, status: Closed }

N(s) = (s.balance ≥ 0, "Balance cannot be negative")

P = {
    interest: s → s.balance * 0.04,
    summary: s → "Balance: ₹" + s.balance + ", Status: " + s.status
}

Verification:
    N(S₀): 0 ≥ 0 ✓
    Deposit preserves N: balance + a ≥ 0 when balance ≥ 0 and a ≥ 0 ✓
    Withdraw preserves N: guard ensures balance ≥ a, so balance - a ≥ 0 ✓
    Close preserves N: balance unchanged ✓
```

## Appendix D: Example — Distributed Lock Service

```text
K3d_LockManager = (S, S₀, E, G, T, N, P)

S = {
    locks: Map<ResourceId, LockState>,
    waiters: Map<ResourceId, Queue<ClientId>>
}

LockState = Free | Held(client: ClientId, expires: Timestamp)

S₀ = { locks: {}, waiters: {} }

E = Acquire(client: ClientId, resource: ResourceId, ttl: Duration, at: Timestamp)
    | Release(client: ClientId, resource: ResourceId, at: Timestamp)
    | Expire(resource: ResourceId, at: Timestamp)
    | Heartbeat(client: ClientId, resource: ResourceId, ttl: Duration, at: Timestamp)

G(s, Acquire(c, r, _, _)) =
    let lock = s.locks.get(r, Free) in
    (lock = Free ∨ lock.client = c, "Resource locked by another client")

G(s, Release(c, r, _)) =
    let lock = s.locks.get(r, Free) in
    (lock ≠ Free ∧ lock.client = c, "Not held by this client")

G(s, Expire(r, at)) =
    let lock = s.locks.get(r, Free) in
    (lock ≠ Free ∧ lock.expires < at, "Lock not expired")

G(s, Heartbeat(c, r, _, _)) =
    let lock = s.locks.get(r, Free) in
    (lock ≠ Free ∧ lock.client = c, "Not held by this client")

T(s, Acquire(c, r, ttl, at)) = { ...s, locks: s.locks.set(r, Held(c, at + ttl)) }
T(s, Release(c, r, _))       = { ...s, locks: s.locks.remove(r) }
T(s, Expire(r, _))           = { ...s, locks: s.locks.remove(r) }
T(s, Heartbeat(c, r, ttl, at)) = { ...s, locks: s.locks.set(r, Held(c, at + ttl)) }

N(s) = (∀r: at_most_one_holder(s.locks, r), "Resource held by multiple clients")

P = {
    held_count: s → s.locks.values.count(l → l ≠ Free),
    client_locks: client → (s → s.locks.filter((r, l) → l.client = client))
}

// Bridge to audit log (BestEffort):
LockManager <->[audit_mapper, BestEffort] AuditLog

audit_mapper(before, event, after) = match event with
    | Acquire(c, r, _, at) → Some(Log("ACQUIRE", {client: c, resource: r}, at))
    | Release(c, r, at)    → Some(Log("RELEASE", {client: c, resource: r}, at))
    | Expire(r, at)        → Some(Log("EXPIRE", {resource: r}, at))
    | Heartbeat(_, _, _, _) → None
```

## Appendix E: Example — Saga with Compensation

```text
K3d_OrderSaga = (S, S₀, E, G, T, N, P)

S = {
    order_id: OrderId,
    status: Pending | PaymentProcessing | InventoryReserving |
            Shipping | Completed |
            PaymentFailed | InventoryFailed | ShippingFailed |
            Compensating | Compensated,
    payment_ref: Option<PaymentRef>,
    inventory_ref: Option<InventoryRef>,
    shipping_ref: Option<ShippingRef>
}

S₀ = { order_id: new_id, status: Pending, payment_ref: None, inventory_ref: None, shipping_ref: None }

E = StartPayment | PaymentSucceeded(ref) | PaymentFailed(reason)
    | StartInventoryReserve | InventoryReserved(ref) | InventoryFailed(reason)
    | StartShipping | ShippingStarted(ref) | ShippingFailed(reason)
    | Complete
    | StartCompensation | CompensateShipping | CompensateInventory | CompensatePayment | CompensationComplete

G(s, StartPayment) = (s.status = Pending, "Must be pending")
G(s, PaymentSucceeded(_)) = (s.status = PaymentProcessing, "Must be processing payment")
// ... (guards enforce state machine edges)
G(s, StartCompensation) = (s.status ∈ {PaymentFailed, InventoryFailed, ShippingFailed}, "Must be failed")

T(s, StartPayment) = { ...s, status: PaymentProcessing }
T(s, PaymentSucceeded(ref)) = { ...s, payment_ref: Some(ref) }
// ... (transitions follow state machine)
T(s, CompensateShipping) = { ...s, shipping_ref: None }
T(s, CompensateInventory) = { ...s, inventory_ref: None }
T(s, CompensatePayment) = { ...s, payment_ref: None }
T(s, CompensationComplete) = { ...s, status: Compensated }

N(s) = (
    valid_state_machine(s.status) ∧
    (s.status = Completed ⇒ all_refs_present(s)) ∧
    (s.status = Compensated ⇒ all_refs_reversed(s)),
    "Invalid saga state"
)
```

## Appendix F: Example — Point Particle Mechanics

```text
K3d_Particle = (S, S₀, E, G, T, N, P)

S = { position: Vector3, velocity: Vector3, mass: ℝ⁺ }

S₀ = { position: (0, 0, 0), velocity: (0, 0, 0), mass: 1.0 }

E = ApplyForce(force: Vector3, dt: ℝ⁺)
    | Tick(dt: ℝ⁺)

G(s, ApplyForce(f, dt)) = (dt > 0, "Time step must be positive")
G(s, Tick(dt)) = (dt > 0, "Time step must be positive")

T(s, ApplyForce(f, dt)) =
    let a = f / s.mass in
    { ...s, position: s.position + s.velocity * dt, velocity: s.velocity + a * dt }

T(s, Tick(dt)) = { ...s, position: s.position + s.velocity * dt }

N(s) = (s.mass > 0, "Mass must be positive")

P = {
    kinetic_energy: s → 0.5 * s.mass * |s.velocity|²,
    momentum: s → s.mass * s.velocity
}
```

## Appendix G: Universality Observation

| Domain      | State                  | Event                | Guard                  | Transition           | Invariant             |
| ----------- | ---------------------- | -------------------- | ---------------------- | -------------------- | --------------------- |
| Finance     | Balances               | Deposits/withdrawals | Sufficient funds       | Arithmetic           | Non-negativity        |
| Mechanics   | Position, velocity     | Force application    | Physical validity      | Newton's laws        | Conservation laws     |
| Chemistry   | Concentrations         | Reactions            | Sufficient reactants   | Stoichiometry        | Mass conservation     |
| Geometry    | Points, lines, circles | Constructions        | Constructibility rules | Geometric operations | Referential integrity |
| Computation | Lambda terms           | β-reduction          | Valid redex            | Substitution         | Well-formedness       |
| Workflows   | Status + refs          | Step events          | State machine edges    | State + ref updates  | Valid state machine   |

The pattern is universal: **State** holds what exists, **Events** perturb it, **Guards** constrain what's possible, **Transitions** define how perturbation produces change, **Invariants** ensure consistency, and **Projections** reveal derived properties.

---

## Conclusion

K3d provides the **deterministic specialization** of the Kulkarni Calculus. It is the right choice for the vast majority of practical systems — those where the causal model is complete and every outcome is fully determined by state and event.

The calculus is:

- **Minimal**: No primitive is redundant
- **Expressive**: Any discrete deterministic causal system is expressible
- **Compositional**: Systems combine algebraically
- **Deterministic**: Same inputs always produce same outputs — automatic replay
- **Observable**: Tracing provides complete visibility without affecting causality
- **Liftable**: Any K3d system lifts to general K3 via `δ`

### The Foundational Claim

K3d is not merely one formalism among many — it captures the irreducible structure of discrete, deterministic cause and effect. FSMs, LTS, Petri nets, event sourcing, and actor systems are all fragments or special cases. K3d reveals the structure they share.

When your system has significant unmodeled causes — when you need to reason about fields of potential rather than single outcomes — lift to the general K3 calculus (K3.Calculus.md). K3d and K3 are the same calculus; they differ only in how much of the world you have chosen to model.

> *Design causality, and the system emerges.*

---

© 2026 Anil Kulkarni. [k3c.dev](https://k3c.dev)
