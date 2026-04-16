# k3c/engine/result.py
"""
StepResult = Ok[T] | Impossible | Violated

The return type of apply_step(). Always a value. Never raises.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Generic, Never, TypeVar

from k3c.engine.ctx import SpecCtx
from k3c.errors import K3ViolatedException

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
    """The complete causal record of a non-Ok outcome."""

    rule: str
    kind: WhyKind
    messages: tuple[str, ...]
    before: dict[str, object]
    after: dict[str, object] | None
    event: dict[str, object]
    ctx: SpecCtx
    expected: dict[str, object] | None
    trace: tuple[dict[str, object], ...]
    step_hash: str

    @property
    def message(self) -> str:
        """Primary message."""
        return self.messages[0] if self.messages else ""

    @property
    def fingerprint(self) -> str:
        """SHA-256[:16] of (rule, kind, primary message). Stable across runs."""
        payload = json.dumps(
            {"rule": self.rule, "kind": self.kind, "message": self.message},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, object]:
        """Serialise all fields to a plain dict."""
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
        """Format as AI agent feedback string."""
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
        """Structured log record with OTel-compatible field names."""
        return {
            "severity": "WARN"
            if self.kind in (WhyKind.PERMIT, WhyKind.MISSING)
            else "ERROR",
            "severityText": "IMPOSSIBLE"
            if self.kind in (WhyKind.PERMIT, WhyKind.MISSING)
            else "VIOLATED",
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


@dataclass(frozen=True)
class Impossible:
    """Guard rejected the event. Precondition not met. State unchanged."""

    why: Why

    def map(self, _f: Callable[..., object]) -> Impossible:
        return self

    def and_then(self, _f: Callable[..., object]) -> Impossible:
        return self


@dataclass(frozen=True)
class Violated:
    """Invariant broken. Implementation diverged from spec. THIS IS A BUG."""

    why: Why

    def map(self, _f: Callable[..., object]) -> Violated:
        return self

    def and_then(self, _f: Callable[..., object]) -> Violated:
        return self

    def raise_(self) -> Never:
        """Escalate to K3ViolatedException. Caller opt-in only."""
        raise K3ViolatedException(self.why)


@dataclass(frozen=True)
class Ok(Generic[T]):
    """Success. All guards passed, invariants held."""

    state: T
    ctx: SpecCtx
    step_hash: str
    projections: dict[str, object] = field(default_factory=dict)
    outputs: tuple[dict[str, object], ...] = ()

    def map(self, f: Callable[[T], U]) -> Ok[U]:
        """Transform the state without changing ctx or step_hash."""
        return Ok(
            state=f(self.state),
            ctx=self.ctx,
            step_hash=self.step_hash,
        )

    def and_then(self, f: Callable[[T, SpecCtx], StepResult[U]]) -> StepResult[U]:
        """Chain the next causal step."""
        return f(self.state, self.ctx)

    def unwrap(self) -> tuple[T, SpecCtx]:
        """Unpack into (state, ctx)."""
        return self.state, self.ctx

    def __repr__(self) -> str:
        return f"Ok(state={self.state!r}, step={self.step_hash[:8]})"


type StepResult[T] = Ok[T] | Impossible | Violated


# -- Error streaming -----------------------------------------------------------


class ErrorAction(StrEnum):
    """Client decision on how to handle a step error."""

    SKIP = "skip"  # skip this event, continue processing
    ABORT_CHUNK = "abort_chunk"  # stop this chunk, others continue
    ABORT_ALL = "abort_all"  # stop everything


@dataclass(frozen=True)
class StepError:
    """Full error identity for a failed step.

    Carries chunk context so errors from parallel_reduce can be traced
    back to their source.
    """

    chunk_index: int
    offset: int
    result: Impossible | Violated

    @property
    def why(self) -> Why:
        return self.result.why

    @property
    def is_violation(self) -> bool:
        return isinstance(self.result, Violated)

    def __repr__(self) -> str:
        kind = "Violated" if self.is_violation else "Impossible"
        return (
            f"StepError(chunk={self.chunk_index}, offset={self.offset}, "
            f"{kind}: {self.why.rule})"
        )


type ErrorHandler = Callable[[StepError], ErrorAction]
