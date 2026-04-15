# k3c/universe/explain.py
"""
Explain — dry-run an event with full eval trace.

explain() runs the apply() pipeline without mutating state, recording
the result of every eval() call along the way. Use it to debug why an
event is Impossible or to understand what each guard/invariant evaluated to.

Usage:
    result = u.explain({"type": "Withdraw", "amount": 500})
    for step in result.trace:
        print(f"{step.clause}: {step.result}")
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from k3c.lang.compile import CompiledSpec
from k3c.lang.eval import k3_eval
from k3c.lang.ir import Nothing, Some
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import K3Result
from k3c.universe.engine import _build_eval_ctx, _hash_step, apply as engine_apply


# ── Trace types ──────────────────────────────────────────────────────────────


class TracePhase(StrEnum):
    """Which phase of the apply() pipeline produced this trace entry."""

    DECODE = "decode"
    GUARD = "guard"
    TRANSITION = "transition"
    REQUIRE = "require"
    SAFETY = "safety"
    KORRELATION = "korrelation"
    LIVENESS = "liveness"


class TraceVerdict(StrEnum):
    """The outcome of evaluating one clause."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    NOTHING = "nothing"
    ERROR = "error"


@dataclass(frozen=True)
class TraceEntry:
    """One step in the explain trace.

    phase: which pipeline stage (guard, safety, etc.)
    clause: the clause name or description
    verdict: pass/fail/skip/nothing
    detail: human-readable detail about the result
    value: the raw eval result (Some value, Nothing field, or None)
    """

    phase: TracePhase
    clause: str
    verdict: TraceVerdict
    detail: str
    value: object = None


# ── ExplainResult ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExplainResult:
    """Result of explain() — full pipeline trace without state mutation.

    result: the K3Result that apply() would have produced
    trace: ordered list of TraceEntry for every clause evaluated
    step_hash: the step_hash that would have been computed
    decoded_event: the event after I.decode (or the raw event if no decode)
    """

    result: K3Result[dict[str, object]]
    trace: tuple[TraceEntry, ...]
    step_hash: str
    decoded_event: dict[str, object]

    @property
    def passed(self) -> bool:
        from k3c.spec.result import Ok

        return isinstance(self.result, Ok)

    def summary(self) -> str:
        """Human-readable summary of the explain trace."""
        lines = [f"ExplainResult: {type(self.result).__name__}"]
        lines.append(f"  step_hash: {self.step_hash[:16]}...")
        for entry in self.trace:
            if entry.verdict == TraceVerdict.PASS:
                marker = "+"
            elif entry.verdict == TraceVerdict.FAIL:
                marker = "-"
            else:
                marker = "~"
            lines.append(
                f"  {marker} [{entry.phase}] {entry.clause}: {entry.verdict} — {entry.detail}"
            )
        return "\n".join(lines)


# ── explain() ────────────────────────────────────────────────────────────────


type _TransitionFn = Callable[[dict[str, object], dict[str, object]], dict[str, object]]


def explain(
    state: dict[str, object],
    ctx: SpecCtx,
    event: dict[str, object],
    compiled: CompiledSpec,
    transition: _TransitionFn,
) -> ExplainResult:
    """Dry-run one causal step with full eval trace. State is NOT mutated.

    Runs the entire apply() pipeline, recording every eval() result.
    Returns ExplainResult with the K3Result and the trace.
    """
    trace: list[TraceEntry] = []

    # 0. Hash
    step_hash = _hash_step(state, event, ctx.prev_step_hash, compiled.hash_fn)

    # 1. Decode
    if compiled.decode is not None:
        decoded = compiled.decode(event)
        trace.append(
            TraceEntry(
                phase=TracePhase.DECODE,
                clause="I.decode",
                verdict=TraceVerdict.PASS,
                detail=f"decoded {len(decoded)} fields",
                value=decoded,
            )
        )
    else:
        decoded = event
        trace.append(
            TraceEntry(
                phase=TracePhase.DECODE,
                clause="I.decode",
                verdict=TraceVerdict.SKIP,
                detail="no decode function — event passed through",
            )
        )

    # 2. Guards
    eval_ctx = _build_eval_ctx(state, decoded, ctx)
    _trace_guards(compiled, eval_ctx, decoded, step_hash, trace)

    # 3. Safety (evaluated against hypothetical new state)
    new_state = _safe_transition(state, decoded, transition)
    if new_state is not None:
        trace.append(
            TraceEntry(
                phase=TracePhase.TRANSITION,
                clause="T_impl",
                verdict=TraceVerdict.PASS,
                detail=f"transition produced {len(new_state)} fields",
            )
        )
        _trace_safety(compiled, state, new_state, decoded, ctx, step_hash, trace)
        _trace_korrelation(compiled, new_state, ctx, step_hash, trace)
    else:
        trace.append(
            TraceEntry(
                phase=TracePhase.TRANSITION,
                clause="T_impl",
                verdict=TraceVerdict.ERROR,
                detail="transition raised an exception",
            )
        )

    # 4. Liveness
    _trace_liveness(compiled, ctx, step_hash, trace)

    # 5. Run actual apply on a COPY to get the real result
    state_copy = deepcopy(state)
    result = engine_apply(state_copy, ctx, event, compiled, transition)

    return ExplainResult(
        result=result,
        trace=tuple(trace),
        step_hash=step_hash,
        decoded_event=decoded,
    )


# ── Trace helpers ────────────────────────────────────────────────────────────


def _trace_guards(
    compiled: CompiledSpec,
    eval_ctx: dict[str, object],
    event: dict[str, object],
    step_hash: str,
    trace: list[TraceEntry],
) -> None:
    """Trace all guard evaluations."""
    for permit in compiled.permits:
        if permit.on is not None:
            event_type = event.get("type")
            if event_type != permit.on:
                trace.append(
                    TraceEntry(
                        phase=TracePhase.GUARD,
                        clause=permit.name,
                        verdict=TraceVerdict.SKIP,
                        detail=f"event type {event_type!r} != {permit.on!r}",
                    )
                )
                continue

        result = k3_eval(permit.when, eval_ctx, step_hash)

        if isinstance(result, Nothing):
            trace.append(
                TraceEntry(
                    phase=TracePhase.GUARD,
                    clause=permit.name,
                    verdict=TraceVerdict.NOTHING,
                    detail=f"field {result.field!r} absent",
                    value=result.field,
                )
            )
        elif isinstance(result, Some) and result.val is True:
            trace.append(
                TraceEntry(
                    phase=TracePhase.GUARD,
                    clause=permit.name,
                    verdict=TraceVerdict.PASS,
                    detail="permitted",
                    value=True,
                )
            )
        elif isinstance(result, Some) and result.val is False:
            trace.append(
                TraceEntry(
                    phase=TracePhase.GUARD,
                    clause=permit.name,
                    verdict=TraceVerdict.FAIL,
                    detail="denied",
                    value=False,
                )
            )
        else:
            trace.append(
                TraceEntry(
                    phase=TracePhase.GUARD,
                    clause=permit.name,
                    verdict=TraceVerdict.PASS,
                    detail=f"evaluated to {result.val!r}",
                    value=result.val,
                )
            )


def _trace_safety(
    compiled: CompiledSpec,
    state: dict[str, object],
    new_state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
    trace: list[TraceEntry],
) -> None:
    """Trace all safety invariant evaluations."""
    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    eval_ctx["__prev_state__"] = state
    eval_ctx["__new_state__"] = new_state

    for clause in compiled.safety:
        result = k3_eval(clause.expr, eval_ctx, step_hash)

        if isinstance(result, Nothing):
            trace.append(
                TraceEntry(
                    phase=TracePhase.SAFETY,
                    clause=clause.name,
                    verdict=TraceVerdict.NOTHING,
                    detail=f"field {result.field!r} absent",
                    value=result.field,
                )
            )
        elif isinstance(result, Some) and result.val is True:
            trace.append(
                TraceEntry(
                    phase=TracePhase.SAFETY,
                    clause=clause.name,
                    verdict=TraceVerdict.PASS,
                    detail="invariant holds",
                    value=True,
                )
            )
        elif isinstance(result, Some) and result.val is False:
            trace.append(
                TraceEntry(
                    phase=TracePhase.SAFETY,
                    clause=clause.name,
                    verdict=TraceVerdict.FAIL,
                    detail="invariant violated",
                    value=False,
                )
            )
        else:
            trace.append(
                TraceEntry(
                    phase=TracePhase.SAFETY,
                    clause=clause.name,
                    verdict=TraceVerdict.PASS,
                    detail=f"evaluated to {result.val!r}",
                    value=result.val,
                )
            )


def _trace_korrelation(
    compiled: CompiledSpec,
    new_state: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,  # noqa: ARG001
    trace: list[TraceEntry],
) -> None:
    """Trace korrelator evaluation."""
    if compiled.korrelator is None:
        trace.append(
            TraceEntry(
                phase=TracePhase.KORRELATION,
                clause="korrelator",
                verdict=TraceVerdict.SKIP,
                detail="no korrelator configured",
            )
        )
        return

    actual = compiled.korrelator.lift(new_state)
    intended = ctx.spec_state

    if compiled.korrelator.correlate is not None:
        correlation = compiled.korrelator.correlate(actual, intended)
    else:
        correlation = all(actual.get(k) == intended.get(k) for k in actual)

    if compiled.korrelator.threshold is not None:
        passed = compiled.korrelator.threshold(correlation)
    else:
        passed = bool(correlation)

    trace.append(
        TraceEntry(
            phase=TracePhase.KORRELATION,
            clause="korrelator",
            verdict=TraceVerdict.PASS if passed else TraceVerdict.FAIL,
            detail=f"actual={actual!r} vs intended={intended!r}",
            value=correlation,
        )
    )


def _trace_liveness(
    compiled: CompiledSpec,
    ctx: SpecCtx,
    step_hash: str,  # noqa: ARG001
    trace: list[TraceEntry],
) -> None:
    """Trace liveness obligation status."""
    for clause in compiled.bounded:
        in_timer = clause.name in ctx.ob_timers
        remaining = ctx.ob_timers.get(clause.name, 0) if in_timer else None
        trace.append(
            TraceEntry(
                phase=TracePhase.LIVENESS,
                clause=clause.name,
                verdict=TraceVerdict.PASS
                if not in_timer or (remaining and remaining > 0)
                else TraceVerdict.FAIL,
                detail=f"bounded(n={clause.n}), timer={'active: ' + str(remaining) + ' remaining' if in_timer else 'inactive'}",
            )
        )

    for clause in compiled.liveness:
        active = clause.name in ctx.active_obligations
        trace.append(
            TraceEntry(
                phase=TracePhase.LIVENESS,
                clause=clause.name,
                verdict=TraceVerdict.PASS if not active else TraceVerdict.SKIP,
                detail=f"unbounded, {'active — waiting for discharge' if active else 'not yet triggered'}",
            )
        )


def _safe_transition(
    state: dict[str, object],
    event: dict[str, object],
    transition: _TransitionFn,
) -> dict[str, object] | None:
    """Run transition on a copy, catching exceptions."""
    try:
        state_copy = deepcopy(state)
        return transition(state_copy, event)
    except Exception:  # noqa: BLE001
        return None
