# k3c/engine/explain.py
"""
Explain -- dry-run an event with full eval trace.

explain() runs the apply_step() pipeline without mutating state, recording
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

from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Ok, StepResult
from k3c.engine.step import TransitionFn, _build_eval_ctx, _hash_step, apply_step
from k3c.ir.eval import k3_eval
from k3c.ir.value import Nothing, Some
from k3c.spec.compile import CompiledSpec
from k3c.spec.extract import run_decode
from k3c.spec.model import CompareMode


# -- Trace types ---------------------------------------------------------------


class TracePhase(StrEnum):
    """Which phase of the apply() pipeline produced this trace entry."""

    DECODE = "decode"
    GUARD = "guard"
    TRANSITION = "transition"
    REQUIRE = "require"
    SAFETY = "safety"
    KORRELATION = "korrelation"
    LIVENESS = "liveness"
    PROJECTION = "projection"
    OUTPUT = "output"


class TraceVerdict(StrEnum):
    """The outcome of evaluating one clause."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    NOTHING = "nothing"
    ERROR = "error"


@dataclass(frozen=True)
class TraceEntry:
    """One step in the explain trace."""

    phase: TracePhase
    clause: str
    verdict: TraceVerdict
    detail: str
    value: object = None


# -- ExplainResult -------------------------------------------------------------


@dataclass(frozen=True)
class ExplainResult:
    """Result of explain() -- full pipeline trace without state mutation."""

    result: StepResult[dict[str, object]]
    trace: tuple[TraceEntry, ...]
    step_hash: str
    decoded_event: dict[str, object]

    @property
    def passed(self) -> bool:
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
                f"  {marker} [{entry.phase}] {entry.clause}: {entry.verdict} \u2014 {entry.detail}"
            )
        return "\n".join(lines)


# -- explain() -----------------------------------------------------------------


def explain(
    state: dict[str, object],
    ctx: SpecCtx,
    event: object,
    compiled: CompiledSpec,
    transition: TransitionFn,
) -> ExplainResult:
    """Dry-run one causal step with full eval trace. State is NOT mutated."""
    trace: list[TraceEntry] = []

    # Ensure dict for hashing
    if isinstance(event, dict):
        event_for_hash = event
    else:
        event_for_hash = {"__raw__": event}

    # 0. Hash
    step_hash = _hash_step(state, event_for_hash, ctx.prev_step_hash, compiled.hash_fn)

    # 1. Decode
    decoded = run_decode(compiled.decode, event)
    if compiled.decode is not None:
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
        trace.append(
            TraceEntry(
                phase=TracePhase.DECODE,
                clause="I.decode",
                verdict=TraceVerdict.SKIP,
                detail="no decode plan \u2014 event passed through",
            )
        )

    # 2. Guards
    eval_ctx = _build_eval_ctx(state, decoded, ctx)
    _trace_guards(compiled, eval_ctx, decoded, step_hash, trace)

    # 3. Transition + Safety
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
        _trace_korrelation(compiled, new_state, decoded, ctx, step_hash, trace)
        _trace_projections(compiled, new_state, decoded, ctx, step_hash, trace)
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

    # 5. Run actual apply on a COPY (catch errors for dry-run safety)
    state_copy = deepcopy(state)
    try:
        result: StepResult[dict[str, object]] = apply_step(
            state=state_copy,
            ctx=ctx,
            raw_event=event,
            compiled=compiled,
            transition=transition,
        )
    except Exception:  # noqa: BLE001
        # Transition error — produce an Impossible result for the trace
        from k3c.engine.result import Impossible, Why, WhyKind

        result = Impossible(
            why=Why(
                rule="T_impl",
                kind=WhyKind.MAINTAIN,
                messages=("transition raised an exception during explain dry-run",),
                before=state,
                after=None,
                event=event if isinstance(event, dict) else {"__raw__": event},
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            )
        )

    return ExplainResult(
        result=result,
        trace=tuple(trace),
        step_hash=step_hash,
        decoded_event=decoded,
    )


# -- Trace helpers -------------------------------------------------------------


def _trace_guards(
    compiled: CompiledSpec,
    eval_ctx: dict[str, object],
    event: dict[str, object],
    step_hash: str,
    trace: list[TraceEntry],
) -> None:
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
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
    trace: list[TraceEntry],
) -> None:
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

    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    eval_ctx["__actual__"] = new_state
    eval_ctx["__intended__"] = ctx.spec_state

    actual_result = k3_eval(compiled.korrelator.actual, eval_ctx, step_hash)
    intended_result = k3_eval(compiled.korrelator.intended, eval_ctx, step_hash)

    if isinstance(actual_result, Nothing) or isinstance(intended_result, Nothing):
        trace.append(
            TraceEntry(
                phase=TracePhase.KORRELATION,
                clause="korrelator",
                verdict=TraceVerdict.NOTHING,
                detail="could not evaluate actual or intended expression",
            )
        )
        return

    actual_val = actual_result.val
    intended_val = intended_result.val

    match compiled.korrelator.mode:
        case CompareMode.EXACT:
            passed = actual_val == intended_val
        case CompareMode.SUBSET:
            if isinstance(actual_val, dict) and isinstance(intended_val, dict):
                passed = all(actual_val.get(k) == intended_val[k] for k in intended_val)
            else:
                passed = actual_val == intended_val

    trace.append(
        TraceEntry(
            phase=TracePhase.KORRELATION,
            clause="korrelator",
            verdict=TraceVerdict.PASS if passed else TraceVerdict.FAIL,
            detail=f"actual={actual_val!r} vs intended={intended_val!r}",
            value=passed,
        )
    )


def _trace_projections(
    compiled: CompiledSpec,
    new_state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
    trace: list[TraceEntry],
) -> None:
    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    for proj in compiled.projections:
        result = k3_eval(proj.expr, eval_ctx, step_hash)
        if isinstance(result, Nothing):
            trace.append(
                TraceEntry(
                    phase=TracePhase.PROJECTION,
                    clause=proj.name,
                    verdict=TraceVerdict.NOTHING,
                    detail=f"field {result.field!r} absent",
                )
            )
        else:
            trace.append(
                TraceEntry(
                    phase=TracePhase.PROJECTION,
                    clause=proj.name,
                    verdict=TraceVerdict.PASS,
                    detail=f"value={result.val!r}",
                    value=result.val,
                )
            )


def _trace_liveness(
    compiled: CompiledSpec,
    ctx: SpecCtx,
    step_hash: str,  # noqa: ARG001
    trace: list[TraceEntry],
) -> None:
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
                detail=f"unbounded, {'active \u2014 waiting for discharge' if active else 'not yet triggered'}",
            )
        )


def _safe_transition(
    state: dict[str, object],
    event: dict[str, object],
    transition: TransitionFn,
) -> dict[str, object] | None:
    """Run transition on a copy, catching exceptions."""
    try:
        state_copy = deepcopy(state)
        return transition(state_copy, event)
    except Exception:  # noqa: BLE001
        return None
