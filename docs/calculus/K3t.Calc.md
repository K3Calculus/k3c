# K3ᵗ — Temporal Extension

## A Calculus for Liveness and Temporal Properties

**Version 0.1**

**Prerequisite:** K3.Calculus.md (the base calculus). Examples in this document use K3d (deterministic) systems.

---

## Abstract

K3ᵗ extends the Kulkarni Calculus with **temporal operators** and **liveness properties**, enabling the specification and verification of properties like "every request eventually receives a response" or "the universe eventually reaches a stable configuration."

Base K3 invariants express **safety** — "bad things never happen." K3ᵗ adds **liveness** — "good things eventually happen." Together, they provide complete temporal specification of discrete causal universes.

> **Design Principle:** Safety says what must always hold. Liveness says what must eventually hold. Both are essential for complete specification.

---

## Table of Contents

1. [Motivation](#1-motivation)
2. [The Calculus](#2-the-calculus)
3. [Temporal Operators](#3-temporal-operators)
4. [Liveness Properties](#4-liveness-properties)
5. [Fairness](#5-fairness)
6. [Operational Semantics](#6-operational-semantics)
7. [Composition](#7-composition)
8. [Verification](#8-verification)
9. [Relationship to Base K3](#9-relationship-to-base-k3)
10. [Examples](#10-examples)

---

# 1. Motivation

## 1.1 The Safety-Liveness Gap

Base K3 invariants (`N : Dist(S) → Bool × String`, or `N : S → Bool × String` in K3d) express safety properties — predicates that must hold at every reachable state or transformation. This is powerful but incomplete.

Consider a request-response universe:

```text
N(s) = (s.balance ≥ 0, "No negative balance")     // Safety ✓
```

But no base K3 primitive can express:

```text
"Every pending request eventually gets a response"   // Liveness ✗
"The queue eventually drains"                         // Liveness ✗
"Consensus is eventually reached"                     // Liveness ✗
```

These are **liveness properties** — they guarantee progress, not just safety. Without liveness, a universe that does nothing (processes no events) trivially satisfies all safety invariants.

## 1.2 Why a Separate Extension?

Temporal operators change what is **verifiable**:

- Safety properties are decidable for finite-state systems (model checking)
- Liveness properties require **fairness assumptions** — without them, any system can avoid progress by never scheduling the relevant events
- Liveness verification typically needs specialized tools (TLC, SPIN, nuSMV)
- Adding temporal operators to the base calculus would compromise K3's decidability guarantee
- For general K3 systems (with non-trivial distributions), liveness interacts with the field of potential — a property may be live with probability 1 but not certain

K3ᵗ is therefore a separate specification that introduces temporal reasoning without altering the core calculus.

## 1.3 Design Philosophy

K3ᵗ follows the temporal logic tradition established by Pnueli (1977) and Lamport (TLA+), adapted to K3's event-driven, causal-step semantics. The key adaptation: temporal formulas in K3ᵗ are evaluated over **event-indexed traces**, not abstract infinite sequences.

---

# 2. The Calculus

## 2.1 Definition

A K3ᵗ model is an **8-tuple**:

```text
K3ᵗ = (S, S₀, E, G, T, N, P, L)
```

Where L is a set of temporal (liveness) properties, and all other components are standard K3.

## 2.2 New Primitive

| Symbol | Name               | Type                       | Description                          |
| ------ | ------------------ | -------------------------- | ------------------------------------ |
| **L**  | Liveness Properties | `Set<TemporalFormula>`     | Properties that must eventually hold |

**L does not replace N.** Safety (N) and liveness (L) are complementary:

| Concern    | Primitive | Question                             | Violation                      |
| ---------- | --------- | ------------------------------------ | ------------------------------ |
| **Safety** | N         | "Is this transformation valid?"       | An invalid transformation occurs |
| **Liveness** | L       | "Will something good happen?"        | Progress fails to occur        |

---

# 3. Temporal Operators

## 3.1 Traces

Temporal formulas are evaluated over **traces** — infinite sequences of states produced by event processing:

```text
σ = s₀, s₁, s₂, ...

where sᵢ₊₁ = ApplySampled(sᵢ, eᵢ, ωᵢ) for some event eᵢ and unmodeled causes ωᵢ
```

For K3d (deterministic) systems, ω is irrelevant and `sᵢ₊₁ = Apply(sᵢ, eᵢ)` directly. Most K3ᵗ specifications are over deterministic systems.

For general K3 systems, temporal properties hold over **sampled traces** — specific manifestations of the field of potential. A liveness property may hold with probability 1 under all valid ω, or may hold only under specific fairness + distributional assumptions.

A **position** in a trace is an index `i ∈ ℕ`. The suffix of σ starting at position i is denoted `σⁱ`.

```text
σⁱ = sᵢ, sᵢ₊₁, sᵢ₊₂, ...
```

### Finite Traces

In practice, K3 executions are finite. K3ᵗ handles this by defining:

- A finite trace `σ = s₀, ..., sₙ` satisfies a liveness property if the property is satisfied within the trace, OR
- The trace is explicitly marked as **incomplete** (execution ongoing), in which case liveness obligations are deferred

A **terminated** trace (no further events possible) that has unsatisfied liveness obligations is a **liveness violation**.

## 3.2 State Formulas

State formulas are predicates over individual states:

```text
φ, ψ ::=
    | P(s)                 // Atomic predicate (any decidable predicate on state)
    | ¬φ                   // Negation
    | φ ∧ ψ                // Conjunction
    | φ ∨ ψ                // Disjunction
    | φ ⇒ ψ                // Implication
```

## 3.3 Temporal Formulas

Temporal formulas extend state formulas with operators over traces:

### Eventually (◇)

```text
◇φ  —  "φ holds at some future position"

σ, i ⊨ ◇φ   iff   ∃j ≥ i : σ, j ⊨ φ
```

Read: "eventually φ." There exists a future state in the trace where φ is true.

### Always (□)

```text
□φ  —  "φ holds at all future positions"

σ, i ⊨ □φ   iff   ∀j ≥ i : σ, j ⊨ φ
```

Read: "always φ." φ is true at every future state.

**Note:** `□φ` where φ is a state predicate is equivalent to a K3 invariant `N`. This shows that safety is a special case of temporal specification.

### Until (U)

```text
φ U ψ  —  "φ holds until ψ becomes true"

σ, i ⊨ φ U ψ   iff   ∃j ≥ i : (σ, j ⊨ ψ) ∧ (∀k, i ≤ k < j : σ, k ⊨ φ)
```

Read: "φ until ψ." ψ eventually becomes true, and φ remains true until then.

### Weak Until (W)

```text
φ W ψ  —  "φ holds until ψ, or φ holds forever"

σ, i ⊨ φ W ψ   iff   (σ, i ⊨ φ U ψ) ∨ (σ, i ⊨ □φ)
```

Read: "φ unless ψ." Like Until, but φ may hold forever without ψ ever becoming true.

### Next (○)

```text
○φ  —  "φ holds at the next position"

σ, i ⊨ ○φ   iff   σ, i+1 ⊨ φ
```

Read: "next φ." φ is true after the next event.

### Compound Operators

```text
◇□φ    — "eventually always φ"  (universe stabilizes into φ)
□◇φ    — "always eventually φ"  (φ recurs infinitely often)
□(φ ⇒ ◇ψ)  — "every φ leads to ψ" (response property)
```

## 3.4 Operator Relationships

```text
◇φ  ≡  true U φ           // Eventually is Until with trivial precondition
□φ  ≡  ¬◇¬φ               // Always is dual of Eventually
φ W ψ ≡ (φ U ψ) ∨ □φ      // Weak Until
◇□φ ⇒ □◇φ                 // Stabilization implies recurrence
□φ ⇒ ◇φ                   // Always implies eventually (for non-empty traces)
```

## 3.5 Formal Type

```text
TemporalFormula =
    | Always(φ : StateFormula)                    // □φ
    | Eventually(φ : StateFormula)                // ◇φ
    | Until(φ : StateFormula, ψ : StateFormula)   // φ U ψ
    | WeakUntil(φ : StateFormula, ψ : StateFormula)  // φ W ψ
    | Next(φ : StateFormula)                      // ○φ
    | Leads(φ : StateFormula, ψ : StateFormula)   // □(φ ⇒ ◇ψ)
    | StabilizesTo(φ : StateFormula)              // ◇□φ
    | Recurs(φ : StateFormula)                    // □◇φ
    | Not(f : TemporalFormula)
    | And(f₁ : TemporalFormula, f₂ : TemporalFormula)
    | Or(f₁ : TemporalFormula, f₂ : TemporalFormula)
```

---

# 4. Liveness Properties

## 4.1 Liveness Definition

A property is a **liveness** property if every finite prefix can be extended to satisfy it (Alpern & Schneider, 1985):

```text
Property P is liveness iff:
    ∀σ_finite : ∃σ_infinite ⊇ σ_finite : σ_infinite ⊨ P
```

Intuitively: no matter what has happened so far, it's never "too late" for the property to be satisfied. Something good can always still happen.

Contrast with **safety**: a safety property can be violated in finite time and can never be "repaired."

## 4.2 Common Liveness Patterns

### Response (Lead-to)

```text
□(request ⇒ ◇response)
```

"Every request eventually receives a response." The most common liveness pattern.

### Termination

```text
◇terminated
```

"The universe eventually stops." For universes that should complete.

### Progress

```text
□(¬idle ⇒ ◇(idle ∨ advanced))
```

"If the universe is not idle, it eventually becomes idle or makes progress."

### Stabilization

```text
◇□stable
```

"The universe eventually reaches a stable configuration and remains there." (Consensus algorithms, convergence.)

### Recurrence

```text
□◇checkpoint
```

"Checkpoints happen infinitely often." (Heartbeats, garbage collection, periodic tasks.)

### Starvation Freedom

```text
□(waiting(process_i) ⇒ ◇running(process_i))
```

"Every waiting process eventually gets to run." (Scheduler fairness.)

### Bounded Liveness

```text
□(request ⇒ ◇≤k response)

where ◇≤k φ ≡ ∃j, i ≤ j ≤ i+k : σ, j ⊨ φ
```

"Every request is responded to within k steps." (Bounded response time.)

## 4.3 L in K3ᵗ

The liveness component of a K3ᵗ universe is a set of temporal formulas:

```text
L = {
    l₁ : TemporalFormula,
    l₂ : TemporalFormula,
    ...
}
```

Each formula has:

```text
LivenessProperty = {
    name: String,                // Human-readable identifier
    formula: TemporalFormula,    // The temporal specification
    why: String,                 // Explanation of why this property matters
    fairness: FairnessAssumption // Required fairness (see §5)
}
```

Note the `why` field — consistent with K3's pattern of first-class reasons.

---

# 5. Fairness

## 5.1 The Fairness Problem

Liveness properties cannot be verified without **fairness assumptions**. Consider:

```text
L = { □(request ⇒ ◇response) }
```

A universe that simply never processes the response event trivially violates this property. But is that the universe's fault, or the scheduler's?

Fairness assumptions constrain the environment to ensure that enabled events are eventually processed.

## 5.2 Fairness Types

### Unconditional Fairness

```text
UnconditionalFair(e) :  □◇(e is processed)
```

"Event e is processed infinitely often." Strongest guarantee — the event happens regardless of state.

### Weak Fairness (Justice)

```text
WeakFair(e) :  □◇(¬enabled(e)) ∨ □◇(e is processed)
```

"If event e is continuously enabled, it is eventually processed." Equivalently: e cannot be enabled forever without being processed.

### Strong Fairness (Compassion)

```text
StrongFair(e) :  ◇□(¬enabled(e)) ∨ □◇(e is processed)
```

"If event e is enabled infinitely often, it is eventually processed." Stronger than weak fairness — even if e is only intermittently enabled, it must eventually happen.

### Where "enabled" in K3

An event is **enabled** in a state if its guard passes:

```text
enabled(e, s) ≡ G(s, e) = (true, _)
```

## 5.3 Fairness in K3ᵗ

Each liveness property declares its required fairness:

```text
FairnessAssumption =
    | None                           // No fairness needed (e.g., ◇□φ for absorbing states)
    | WeakFairness(events: Set<E>)   // Specified events are weakly fair
    | StrongFairness(events: Set<E>) // Specified events are strongly fair
    | Custom(formula: TemporalFormula)  // Arbitrary fairness constraint
```

**Convention:** When no fairness is declared, weak fairness for all events is assumed. This is the most common assumption and matches the intuition that "if an event can happen, it eventually does."

## 5.4 Fairness and the Environment

Fairness is a contract between the universe and its environment:

| Component     | Responsibility                                    |
| ------------- | ------------------------------------------------- |
| **Universe**  | Defines guards, transitions, invariants           |
| **Environment** | Provides events (subject to fairness constraints) |
| **K3ᵗ**       | Specifies the contract (L + fairness)             |

A universe is **correct under fairness F** if all traces satisfying F also satisfy all properties in L:

```text
∀σ : (σ satisfies F) ⇒ (σ ⊨ ∧L)
```

---

# 6. Operational Semantics

## 6.1 Apply (Unchanged)

The Apply function is identical to base K3:

```text
Apply(s, e) → s' | ⊥
```

K3ᵗ does not modify the causal step. Temporal properties are **specifications over traces**, not operational modifications.

## 6.2 Temporal Evaluation

Given a trace σ and a temporal formula φ:

```text
eval : Trace × ℕ × TemporalFormula → Bool

eval(σ, i, Always(φ)) =
    ∀j ≥ i : eval_state(σ[j], φ)

eval(σ, i, Eventually(φ)) =
    ∃j ≥ i : eval_state(σ[j], φ)

eval(σ, i, Until(φ, ψ)) =
    ∃j ≥ i : eval_state(σ[j], ψ) ∧ ∀k, i ≤ k < j : eval_state(σ[k], φ)

eval(σ, i, Next(φ)) =
    eval_state(σ[i+1], φ)

eval(σ, i, Leads(φ, ψ)) =
    ∀j ≥ i : eval_state(σ[j], φ) ⇒ ∃k ≥ j : eval_state(σ[k], ψ)
```

### Finite Trace Evaluation

For finite traces `σ = s₀, ..., sₙ`:

```text
eval_finite(σ, i, Eventually(φ)) =
    ∃j, i ≤ j ≤ n : eval_state(σ[j], φ)
    // If not found: INCONCLUSIVE (not violated — execution may continue)

eval_finite(σ, i, Always(φ)) =
    ∀j, i ≤ j ≤ n : eval_state(σ[j], φ)
    // If true for all seen: HOLDS_SO_FAR (may be violated later)
```

Finite evaluation returns a three-valued result:

```text
TemporalResult = Satisfied | Violated | Inconclusive
```

**Inconclusive** means the trace is too short to determine the property. For monitoring, this triggers continued observation.

## 6.3 Runtime Monitoring

K3ᵗ supports runtime monitoring of temporal properties:

```text
Monitor = {
    property: LivenessProperty,
    state: MonitorState,
    history: relevant state observations
}

MonitorState =
    | Watching          // Property not yet satisfied or violated
    | Satisfied         // Property has been satisfied
    | Violated          // Property has been violated (deadlock detected)
    | TimedOut(bound)   // Bounded liveness: exceeded step bound
```

After each Apply step, monitors update:

```text
update_monitors(monitors, s_old, e, s_new) =
    for m in monitors:
        m.state = eval_incremental(m.property, m.history, s_new)
```

**Incremental evaluation** avoids re-scanning the entire trace. For safety properties (`□φ`), check φ on the new state. For response properties (`□(φ ⇒ ◇ψ)`), track pending obligations.

## 6.4 Deadlock Detection

A **deadlock** is a state from which no event is enabled:

```text
deadlock(s) ≡ ∀e ∈ E : G(s, e) = (false, _)
```

If a deadlock state has unsatisfied liveness obligations, this is a **liveness violation**:

```text
liveness_deadlock(s, L) ≡
    deadlock(s) ∧ ∃l ∈ L : ¬satisfied(l)
```

K3ᵗ runtimes SHOULD detect deadlocks and report unfulfilled liveness obligations.

---

# 7. Composition

## 7.1 Parallel Composition

When composing K3ᵗ universes:

```text
K3ᵗ₁ <||> K3ᵗ₂ = (S₁ × S₂, (S₀₁, S₀₂), E, G, T, N, P, L)

L = L₁' ∪ L₂'
```

Where L₁' lifts temporal formulas to the product state:

```text
lift₁(φ)(s₁, s₂) = φ(s₁)      // Lift left state predicates
lift₂(ψ)(s₁, s₂) = ψ(s₂)      // Lift right state predicates
```

Each universe's liveness properties are preserved independently.

### Cross-Universe Temporal Properties

Composition may introduce **new** temporal properties that span both universes:

```text
L_cross = {
    □(left.request ⇒ ◇right.response),    // Cross-universe response
    ◇(left.done ∧ right.done)              // Joint termination
}
```

These are specified on the composed universe and cannot be decomposed.

## 7.2 Bridges and Liveness

Bridges affect liveness through delivery guarantees:

| Bridge Mode   | Liveness Implication                                |
| ------------- | --------------------------------------------------- |
| Synchronous   | Source liveness depends on target liveness           |
| Async         | Source liveness independent; target liveness depends on queue drainage |
| BestEffort    | Source liveness independent; no target liveness guarantee |

For Async bridges, add a queue drainage liveness property:

```text
L_queue = { ◇(queue.pending = []) }    // Queue eventually drains
```

## 7.3 Fairness Composition

When composing, fairness assumptions combine:

```text
Fairness(K3ᵗ₁ <||> K3ᵗ₂) =
    lift₁(Fairness₁) ∧ lift₂(Fairness₂) ∧ Fairness_cross
```

Where `Fairness_cross` captures any additional fairness needed for cross-universe properties.

---

# 8. Verification

## 8.1 Verification Landscape

| Property Type           | Verification Method           | Tool Support                    |
| ----------------------- | ----------------------------- | ------------------------------- |
| Safety (□φ)             | Model checking, invariant proof | TLC, SPIN, Alloy, manual proof |
| Bounded liveness (◇≤k φ) | Bounded model checking        | CBMC, TLC with depth bound     |
| Unbounded liveness (◇φ) | Model checking + fairness      | TLC, SPIN, nuSMV              |
| Response (□(φ ⇒ ◇ψ))   | Model checking + fairness      | TLC, SPIN                      |
| Stabilization (◇□φ)     | Ranking functions, convergence | Manual proof, Dafny            |

## 8.2 Model Checking

For finite-state K3ᵗ universes, temporal properties can be verified exhaustively.

### Translation to TLA+

K3ᵗ maps naturally to TLA+:

```text
K3ᵗ to TLA+ mapping:
    S         → VARIABLES
    S₀        → Init
    T(s, e)   → Next (disjunction over event types)
    N(s)      → TypeInvariant / SafetyInvariant
    G(s, e)   → ENABLED sub-actions
    L         → Temporal properties
    Fairness  → WF_ / SF_ annotations
```

```text
// Example TLA+ translation
SPECIFICATION Spec ==
    Init ∧ □[Next]_vars ∧ WF_vars(ProcessRequest)

PROPERTIES
    □(balance ≥ 0)                              // Safety (from N)
    □(request_pending ⇒ ◇response_sent)         // Liveness (from L)
```

### Translation to SPIN/Promela

```text
K3ᵗ to Promela mapping:
    S         → Global variables
    T(s, e)   → Guarded statements in a do loop
    G(s, e)   → Guard conditions
    L         → LTL properties (checked via never claims)
```

## 8.3 Ranking Functions

For unbounded liveness, construct a **ranking function** that decreases with each relevant step:

```text
rank : S → ℕ (or well-founded order)

Prove:
1. rank(s) ≥ 0 for all reachable s
2. For each step that makes progress toward the liveness goal:
   rank(s') < rank(s)
3. The liveness property holds when rank reaches 0
```

**Example:** For "queue eventually drains":

```text
rank(s) = |s.queue.pending|
```

Each `Deliver` event decreases rank. Under weak fairness (Deliver is eventually processed when enabled), rank reaches 0.

## 8.4 Bounded Liveness Testing

For practical testing without full model checking:

```text
bounded_liveness_test(K3ᵗ, bound, n_runs):
    for i in 1..n_runs:
        events = random_event_sequence(length = bound)
        trace = simulate(S₀, events)
        for l in L:
            result = eval_finite(trace, 0, l)
            if result = Violated:
                return Failure(l, trace)
            if result = Inconclusive:
                log("Property " + l.name + " inconclusive after " + bound + " steps")
    return Pass
```

**Limitations:** Cannot verify unbounded liveness. Inconclusive results are expected.

## 8.5 Decidability

| Property Class       | Finite S | Infinite S   |
| -------------------- | -------- | ------------ |
| □φ (safety)          | Decidable | Undecidable  |
| ◇φ (reachability)    | Decidable | Undecidable  |
| □(φ ⇒ ◇ψ) (response) | Decidable (with fairness) | Undecidable |
| ◇□φ (stabilization)  | Decidable (with fairness) | Undecidable |
| Nested temporal       | Decidable | Undecidable  |

---

# 9. Relationship to Base K3

## 9.1 Conservative Extension

Every K3 system is a K3ᵗ system with `L = {}`:

```text
embed : K3 → K3ᵗ
embed(S, S₀, E, G, T, N, P) = (S, S₀, E, G, T, N, P, {})
```

This applies to both general K3 (distributional T) and K3d (deterministic T).

## 9.2 Safety as Temporal

Base K3 invariants are temporal formulas:

```text
N(d) = (φ(d), why)   ≡   □φ_d with why annotation       // General K3
N(s) = (φ(s), why)   ≡   □φ with why annotation           // K3d
```

This means K3's invariant checking is a special case of K3ᵗ's temporal verification. But K3 maintains this as a separate primitive (N) because safety is fundamental and checkable at each step without trace analysis.

For general K3 systems, the distributional invariant `N : Dist(S) → Bool × String` validates the transformation at each step, while temporal formulas in L reason about sequences of sampled states over time. The two are complementary: N ensures each transition is valid; L ensures the system makes progress.

## 9.3 Outputs and Liveness

K3 outputs (O) interact with liveness: if an output triggers an external action that eventually produces an event, this creates an implicit liveness dependency:

```text
// Output sends email → user eventually responds → Response event
O(s, PlaceOrder, s') = [SendConfirmationEmail(s.user)]

// Liveness assumes the external world cooperates:
L = { □(order_placed ⇒ ◇(confirmed ∨ cancelled ∨ timed_out)) }
    with fairness: StrongFairness({ConfirmOrder, CancelOrder, TimeoutOrder})
```

This makes explicit the assumptions about external world behavior.

---

# 10. Examples

**Note:** The following examples use K3d (deterministic) transitions, which is typical for systems where liveness is the primary concern. K3ᵗ applies equally to general K3 systems with distributional transitions — temporal formulas evaluate over sampled traces.

## 10.1 Request-Response Server

```text
K3ᵗ_Server = (S, S₀, E, G, T, N, P, L)

S = {
    pending: Map<RequestId, Request>,
    completed: Set<RequestId>,
    next_id: ℕ
}

S₀ = { pending: {}, completed: {}, next_id: 0 }

E = Submit(payload: Data)
    | Process(id: RequestId)
    | Complete(id: RequestId, result: Result)

G(s, Submit(_)) = (true, "")
G(s, Process(id)) = (id ∈ s.pending ∧ s.pending[id].status = Queued, "Not a queued request")
G(s, Complete(id, _)) = (id ∈ s.pending ∧ s.pending[id].status = Processing, "Not processing")

T(s, Submit(data)) = { ...s,
    pending: s.pending.set(s.next_id, {payload: data, status: Queued}),
    next_id: s.next_id + 1
}
T(s, Process(id)) = { ...s, pending: s.pending.update(id, r → { ...r, status: Processing }) }
T(s, Complete(id, result)) = { ...s,
    pending: s.pending.remove(id),
    completed: s.completed ∪ {id}
}

N(s) = (true, "")   // No safety invariant beyond type correctness

P = {
    queue_depth: s → |s.pending|,
    throughput: s → |s.completed|
}

L = {
    {
        name: "every-request-completed",
        formula: □(∀id ∈ pending.keys : ◇(id ∈ completed)),
        why: "Every submitted request must eventually complete",
        fairness: WeakFairness({Process, Complete})
    },
    {
        name: "queue-bounded",
        formula: □(|pending| ≤ max_queue_size ⇒ ◇(|pending| < max_queue_size)),
        why: "Queue doesn't permanently fill up",
        fairness: WeakFairness({Process})
    }
}
```

**Verification sketch:** Under weak fairness for Process and Complete, every Queued request eventually gets processed (Process is enabled when pending is non-empty), and every Processing request eventually completes. The ranking function is `|pending|`, which decreases with each Complete event.

## 10.2 Consensus Protocol

```text
K3ᵗ_Consensus = (S, S₀, E, G, T, N, P, L)

S = {
    proposals: Map<NodeId, Value>,
    votes: Map<NodeId, Map<NodeId, Value>>,
    decided: Option<Value>,
    round: ℕ,
    n_nodes: ℕ
}

S₀ = { proposals: {}, votes: {}, decided: None, round: 0, n_nodes: 5 }

E = Propose(node: NodeId, value: Value)
    | Vote(voter: NodeId, for_node: NodeId)
    | Decide(value: Value)
    | NextRound

// ... Guards and Transitions omitted for brevity ...

N(s) = (
    // Agreement: if decided, all future decisions match
    (s.decided ≠ None ⇒ ∀v: decided_value(v) ⇒ v = s.decided.get),
    "Consensus agreement violated"
)

L = {
    {
        name: "termination",
        formula: ◇(decided ≠ None),
        why: "Consensus must eventually be reached",
        fairness: StrongFairness({Vote, Decide})
    },
    {
        name: "validity",
        formula: □(decided = Some(v) ⇒ v ∈ proposed_values),
        why: "Decided value must have been proposed",
        fairness: None    // This is actually a safety property
    }
}
```

**Note:** The "validity" property is technically safety (□φ), demonstrating that L can contain both safety and liveness properties. Placing it in L keeps all specification properties in one place.

## 10.3 Producer-Consumer with Bounded Buffer

```text
K3ᵗ_ProducerConsumer = (S, S₀, E, G, T, N, P, L)

S = {
    buffer: List<Item>,
    capacity: ℕ,
    produced: ℕ,
    consumed: ℕ
}

S₀ = { buffer: [], capacity: 10, produced: 0, consumed: 0 }

E = Produce(item: Item) | Consume

G(s, Produce(_)) = (|s.buffer| < s.capacity, "Buffer full")
G(s, Consume) = (|s.buffer| > 0, "Buffer empty")

T(s, Produce(item)) = { ...s, buffer: s.buffer ++ [item], produced: s.produced + 1 }
T(s, Consume) = { ...s, buffer: tail(s.buffer), consumed: s.consumed + 1 }

N(s) = (|s.buffer| ≤ s.capacity, "Buffer overflow")

P = {
    utilization: s → |s.buffer| / s.capacity,
    throughput: s → s.consumed
}

L = {
    {
        name: "producer-not-starved",
        formula: □◇(|buffer| < capacity),
        why: "Producer can always eventually produce",
        fairness: WeakFairness({Consume})
    },
    {
        name: "consumer-not-starved",
        formula: □◇(|buffer| > 0),
        why: "Consumer can always eventually consume",
        fairness: WeakFairness({Produce})
    },
    {
        name: "items-eventually-consumed",
        formula: □(|buffer| > 0 ⇒ ◇(consumed > consumed_now)),
        why: "Items in buffer are eventually consumed",
        fairness: WeakFairness({Consume})
    }
}
```

---

## Axiom Summary

K3ᵗ inherits all K3 axioms unchanged (including distributional transitions and the Parinama Principle) and adds:

| Property             | Specification                                          |
| -------------------- | ------------------------------------------------------ |
| **Safety**           | N(d) or N(s) must hold at every reachable transformation/state (from base K3) |
| **Liveness**         | L properties must hold over all fair traces             |
| **Fairness contract** | Each liveness property declares required fairness      |
| **Non-interference** | L does not modify Apply semantics                      |

**Key insight:** K3ᵗ is purely **declarative** — it specifies *what must hold* over traces but does not change *how* the system evolves. The causal core (Apply, Reduce, Compose, Bridge) is identical to base K3 (whether general or K3d). Temporal properties are verified against traces, not enforced during execution.

---

> **K3ᵗ — Temporal Kulkarni Calculus**
>
> *Safety says what must always hold. Liveness says what must eventually hold. Together, they tell the full story.*

---

© 2026 Anil Kulkarni. [k3c.dev](https://k3c.dev)
