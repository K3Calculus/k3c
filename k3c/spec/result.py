# K3 Result

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Generic, Never, TypeVar

from k3c.errors import K3ViolatedException
from k3c.spec.ctx import SpecCtx

T = TypeVar("T")
U = TypeVar("U")


class WhyKind(StrEnum):
    """Which layer produced the non-Ok outcome."""

    PERMIT = "permit"
    MISSING = "missing"
    MAINTAIN = "maintain"
    KORRELATE = "korrelate"
    TIMER = "timer"
    LIVENESS = "liveness"


@dataclass(frozen=True)
class Why:
    """
    The complete causal record of a non-Ok outcome.

    Carried by both Impossible and Violated. Always a value — never an
    exception. Constructed by the engine at the exact moment of the outcome.
    Nothing is reconstructed after the fact.

    The kind field tells you which layer produced it:
      'permit'    — U.permit guard evaluated to Some(False)
      'missing'   — eval() returned Nothing(field) — required field absent
      'maintain'  — U.maintain Always(φ) clause failed
      'korrelate' — K.correlate actual ≠ intended
      'timer'     — Within(φ, n) timer expired
      'liveness'  — Eventually(φ) obligation not discharged at termination

    Impossible carries kind='permit' or kind='missing'.
    Violated  carries kind='maintain', 'korrelate', 'timer', or 'liveness'.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    rule: str
    # Which spec rule produced this outcome.
    # For permits: the permit clause name.
    # For maintain: the maintain clause name.
    # For korrelate: the korrelator name.
    # For missing: the permit name whose eval() returned Nothing.

    kind: WhyKind
    # Which layer produced this outcome — see WhyKind enum.

    # ── Reason chain ──────────────────────────────────────────────────────────
    messages: tuple[str, ...]
    # Full chain — primary message first, all contributing reasons after.
    # Never empty. Immutable — matches frozen dataclass contract.
    # Example: ("Permit 'withdraw_has_funds' denied: insufficient balance",
    #            "balance=50, amount=200, shortfall=150")

    # ── State snapshot ────────────────────────────────────────────────────────
    before: dict[str, object]
    # Full causal state S before the event.
    # Always present — even for Impossible (guard runs before T, state unchanged).

    after: dict[str, object] | None
    # Full causal state S after T ran.
    # None for Impossible — T never ran, state is unchanged.
    # Always present for Violated — T ran, then invariant failed.

    event: dict[str, object]
    # The triggering event exactly as received by apply().
    # Raw form — before I.decode. Reproducible: same event + same state = same step_hash.

    # ── Context snapshot ──────────────────────────────────────────────────────
    ctx: SpecCtx
    # The complete SpecCtx at the moment of the outcome.
    # Contains: spec_state, protocol_pos, ob_timers, active_obligations,
    #           prev_step_hash, trace_ring — everything the witness knew.

    expected: dict[str, object] | None
    # What the spec required — present for 'korrelate' and 'require' kinds.
    # For korrelate: the intended spec_state that K.lift(S) failed to match.
    # None for 'permit', 'missing', 'timer', 'liveness'.

    trace: tuple[dict[str, object], ...]
    # Immutable snapshot of ctx.trace_ring at the moment of the outcome.
    # The last ≤16 domain events before this one. Bounded — never grows.
    # Populated via ctx.snapshot_trace() at construction time.

    # ── Audit identity ────────────────────────────────────────────────────────
    step_hash: str
    # SHA-256(state, event, prev_step_hash) — computed by apply() before
    # anything else runs. Chained: incorporates the previous step's hash.
    # Same for Ok, Impossible, and Violated on the same (state, event) input.
    # The immutable identity of the causal step that produced this Why.

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def message(self) -> str:
        """Primary message — shorthand for messages[0]."""
        return self.messages[0] if self.messages else ""

    @property
    def fingerprint(self) -> str:
        """
        SHA-256[:16] of (rule, kind, primary message).

        Stable across different states, environments, and runs.
        Same violation type firing in production and staging gets the same
        fingerprint. Use for: deduplication, alerting, error grouping,
        dashboard aggregation, suppression rules.

        Excludes: before, after, event, step_hash — because those vary
        per-occurrence. Fingerprint answers "what kind of thing?" not
        "which exact occurrence?"
        """
        payload = json.dumps(
            {"rule": self.rule, "kind": self.kind, "message": self.message},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, object]:
        """
        Serialise all fields to a plain dict.

        Ready for any log store: Datadog, OpenTelemetry, S3, Postgres jsonb,
        Elasticsearch, CloudWatch. No post-processing required.
        Includes step_hash and fingerprint — both present in every record.
        ctx is serialised as ctx.spec_state (the observable part).
        """
        return {
            "rule": self.rule,
            "kind": self.kind,
            "messages": self.messages,
            "before": self.before,
            "after": self.after,
            "event": self.event,
            "expected": self.expected,
            "trace": list(self.trace),
            "ctx": self.ctx.spec_state,
            "step_hash": self.step_hash,
            "fingerprint": self.fingerprint,
        }

    def to_prompt(self) -> str:
        """
        Format as AI agent feedback string.

        Prefixed with step_hash[:8] so that when an agent reads a violation
        and regenerates code, the regeneration cycle is traceable back to
        the exact causal step that triggered it.

        Used by K3ViolatedException.__str__() and by agent.regenerate().
        """
        lines = [f"[{self.kind.upper()}] {self.rule}  step:{self.step_hash[:8]}"]
        lines.extend(self.messages)
        lines.append(f"Before: {self.before}")
        lines.append(f"Event:  {self.event}")
        if self.after is not None:
            lines.append(f"After:  {self.after}")
        if self.expected is not None:
            lines.append(f"Expected: {self.expected}")
        lines.append(f"fingerprint: {self.fingerprint}")
        return "\n".join(lines)

    def to_log_record(self) -> dict[str, object]:
        """
        Structured log record with standard observability field names.

        Compatible with OpenTelemetry semantic conventions.
        Suitable for direct emission as a structured log event.
        """
        return {
            # OTel standard fields
            "severity": "WARN"
            if self.kind in (WhyKind.PERMIT, WhyKind.MISSING)
            else "ERROR",
            "severityText": "IMPOSSIBLE"
            if self.kind in (WhyKind.PERMIT, WhyKind.MISSING)
            else "VIOLATED",
            # k3c fields
            "k3c.rule": self.rule,
            "k3c.kind": self.kind,
            "k3c.message": self.message,
            "k3c.step_hash": self.step_hash,
            "k3c.fingerprint": self.fingerprint,
            "k3c.before": json.dumps(self.before, default=str),
            "k3c.after": json.dumps(self.after, default=str),
            "k3c.event": json.dumps(self.event, default=str),
            "k3c.expected": json.dumps(self.expected, default=str),
            "k3c.protocol_pos": self.ctx.protocol_pos,
            "k3c.spec_state": json.dumps(self.ctx.spec_state, default=str),
        }


# ── The two result variants that carry Why ────────────────────────────────────


@dataclass(frozen=True)
class Impossible:
    """
    Guard rejected the event. Precondition not met.

    NOT a bug. The system is still in a valid state — S is unchanged.
    T never ran. Handle gracefully: retry, skip, log informally, inform caller.

    kind is always 'permit' or 'missing'.
    after is always None — T never ran.
    """

    why: Why

    def map(self, _f: Callable[..., object]) -> Impossible:
        return self  # short-circuit — Impossible propagates unchanged

    def and_then(self, _f: Callable[..., object]) -> Impossible:
        return self  # short-circuit


@dataclass(frozen=True)
class Violated:
    """
    Invariant broken. Implementation diverged from spec.

    THIS IS A BUG. T ran, the new state was produced, but N, the Korrelator,
    or L found a divergence from the spec. The engine returns it as a value.
    The caller decides severity: raise, log and halt, or send to AI agent.

    kind is always 'maintain', 'korrelate', 'timer', or 'liveness'.
    after is always present — T ran before the violation was detected.
    """

    why: Why

    def map(self, _f: Callable[..., object]) -> Violated:
        return self  # short-circuit

    def and_then(self, _f: Callable[..., object]) -> Violated:
        return self  # short-circuit

    def raise_(self) -> Never:
        """
        Escalate to K3ViolatedException.

        Never called by the engine. Always called by the client.
        The engine returns Violated as a value. Only the caller
        decides to make it fatal.
        """
        raise K3ViolatedException(self.why)


@dataclass(frozen=True)
class Ok(Generic[T]):
    """
    The success variant of K3Result.

    Returned by apply() when:
      - The event was permitted  (G returned Some(True) for all permit clauses)
      - T ran and produced new_state
      - N held  (check_invariants returned None)
      - L advanced  (step_liveness updated obligations without violation)

    Carries three named fields — not a tuple. Named fields allow exhaustive
    pattern matching without positional ambiguity.

    ctx is the NEW SpecCtx after the step — ready for the next apply() call.
    The caller does not need to track ctx externally; Ok carries it forward.

    step_hash is the chained SHA-256 of (state, event, prev_step_hash).
    It is the identity of the causal step. Same as Why.step_hash would be
    for Impossible or Violated on the same input — the hash is computed
    before anything runs and flows into every variant.
    """

    state: T
    # The new causal state S' after T ran.
    # Named 'state' not 'value' — makes match/case reads like English:
    #   case Ok(state=s, ctx=c): ...

    ctx: SpecCtx
    # The new SpecCtx after the step.
    # Contains updated: spec_state, protocol_pos, ob_timers,
    #                   active_obligations, prev_step_hash, trace_ring.
    # Pass directly into the next apply() call — no unwrapping needed.

    step_hash: str
    # SHA-256(state_before, event, prev_step_hash).
    # Computed at the top of apply() before anything else runs.

    projections: dict[str, object] = field(default_factory=dict)
    # P — derived views computed post-causal after N holds.
    # Empty if no projections defined. Keyed by projection name.

    outputs: tuple[dict[str, object], ...] = ()
    # Output events emitted post-causal after N holds.
    # Empty if no outputs defined or none matched the event type.

    # ── Combinators ───────────────────────────────────────────────────────────

    def map(self, f: Callable[[T], U]) -> Ok[U]:
        """
        Transform the state without changing ctx or step_hash.

        Use when you want to post-process the state before returning
        to the caller — e.g. stripping internal fields, computing a view.

        Impossible and Violated implement the same interface but return self.
        So .map() on a K3Result is always safe — it short-circuits on non-Ok.

        Example:
            result = apply(state, ctx, event, compiled)
            public_state = result.map(lambda s: {k: v for k, v in s.items()
                                                  if not k.startswith('_')})
        """
        return Ok(
            state=f(self.state),
            ctx=self.ctx,
            step_hash=self.step_hash,
        )

    def and_then(self, f: Callable[[T, SpecCtx], K3Result[U]]) -> K3Result[U]:
        """
        Chain the next causal step.

        f receives the new state and ctx, returns another K3Result.
        If f returns Impossible or Violated, the chain stops there.

        Impossible and Violated implement the same interface but return self,
        so a chain of .and_then() calls propagates the first failure unchanged.

        Example:
            result = (
                apply(state, ctx, event1, compiled)
                .and_then(lambda s, c: apply(s, c, event2, compiled))
                .and_then(lambda s, c: apply(s, c, event3, compiled))
            )
            match result:
                case Ok(state=s): ...         # all three succeeded
                case Impossible(why): ...     # one was rejected
                case Violated(why): ...       # one broke an invariant
        """
        return f(self.state, self.ctx)

    # ── Convenience ───────────────────────────────────────────────────────────

    def unwrap(self) -> tuple[T, SpecCtx]:
        """
        Unpack into (state, ctx) for callers that have already
        matched Ok and want the fields positionally.

        Use only inside a match arm — never on a bare K3Result.
        """
        return self.state, self.ctx

    def __repr__(self) -> str:
        return f"Ok(state={self.state!r}, step={self.step_hash[:8]})"


# ── The complete K3Result union ─────────────────────────-----------------------

type K3Result[T] = Ok[T] | Impossible | Violated
