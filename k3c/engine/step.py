# k3c/engine/step.py
"""
The causal step -- apply_step().

A total pure function. Never throws. step_hash is computed first and flows
into every result. eval() returns Some|Nothing -- Nothing at the guard
boundary becomes Impossible. A failed invariant becomes Violated.

Pipeline:
  1. step_hash = hash(state, event, prev_step_hash)
  2. e' = run_decode(decode_plan, e)
  3. G check: eval permits
  4. s' = transition(s, e)
  5. ctx' = U.require(ctx, e')
  6. N check: safety invariants + korrelation
  7. L track: liveness obligations
  8. P + outputs: compute projections and outputs (declarative)
  9. Return Ok(state=s', ctx=ctx', step_hash=h)
"""

from __future__ import annotations

import hashlib
from typing import Callable, cast

from k3c.cache import invariant_cache_key
from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Impossible, Ok, StepResult, Violated, Warning, Why, WhyKind
from k3c.ir.diagnose import diagnose, format_diagnosis
from k3c.ir.eval import k3_eval
from k3c.ir.value import Nothing, Some
from k3c.json import dumps as _json_dumps
from k3c.spec.compile import CompiledSpec
from k3c.spec.extract import run_decode
from k3c.spec.model import CompareMode, Severity

type TransitionFn = Callable[[dict[str, object], dict[str, object]], dict[str, object]]


# -- Hash step -----------------------------------------------------------------


def _hash_step(
    state: dict[str, object],
    event: dict[str, object],
    prev_step_hash: str,
    hash_fn: str = "sha256",
) -> str:
    """Compute the chained step hash."""
    if hash_fn == "none":
        return ""

    payload = _json_dumps({"state": state, "event": event, "prev": prev_step_hash})
    match hash_fn:
        case "sha256":
            return hashlib.sha256(payload).hexdigest()
        case "blake2b":
            return hashlib.blake2b(payload).hexdigest()
        case "blake3":
            try:
                import blake3 as _blake3

                return _blake3.blake3(payload).hexdigest()
            except ImportError as exc:
                msg = "hash_fn='blake3' requires: pip install blake3"
                raise ImportError(msg) from exc
        case _:
            msg = f"Unknown hash_fn: {hash_fn!r}"
            raise ValueError(msg)


# -- Build eval context --------------------------------------------------------


def _build_eval_ctx(
    state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    new_state: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the context dict that k3_eval receives."""
    eval_ctx: dict[str, object] = {
        "state": state,
        "event": event,
        "__ctx__": ctx,
        "__prev_state__": ctx.prev_state,
        "__new_state__": new_state or state,
    }
    if ctx.spec_state:
        eval_ctx["spec_state"] = ctx.spec_state
    return eval_ctx


# -- G check: guards ----------------------------------------------------------


def _eval_denied_msg(
    denied_expr: object,
    eval_ctx: dict[str, object],
    step_hash: str,
    fallback: str,
) -> str:
    """Evaluate a denied= expression to a string. Returns fallback if absent or fails."""
    if denied_expr is None:
        return fallback
    result = k3_eval(denied_expr, eval_ctx, step_hash)  # type: ignore[arg-type]
    if isinstance(result, Some):
        return str(result.val)
    return fallback


def _check_guards(
    compiled: CompiledSpec,
    eval_ctx: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> Why | None:
    """Evaluate all permit clauses. Returns Why on first failure."""
    for permit in compiled.permits:
        if permit.on is not None:
            event_type = event.get("type")
            if event_type != permit.on:
                continue

        result = k3_eval(permit.when, eval_ctx, step_hash)

        if isinstance(result, Nothing):
            msg = _eval_denied_msg(
                permit.denied,
                eval_ctx,
                step_hash,
                f"Field {result.field!r} absent \u2014 required by {permit.name!r}",
            )
            return Why(
                rule=permit.name,
                kind=WhyKind.MISSING,
                messages=(msg,),
                before=cast("dict[str, object]", eval_ctx.get("state", {})),
                after=None,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            )

        if isinstance(result, Some) and result.val is False:
            msg = _eval_denied_msg(
                permit.denied,
                eval_ctx,
                step_hash,
                f"Permit {permit.name!r} denied",
            )
            return Why(
                rule=permit.name,
                kind=WhyKind.PERMIT,
                messages=(msg,),
                before=cast("dict[str, object]", eval_ctx.get("state", {})),
                after=None,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            )

    return None


# -- N check: safety invariants ------------------------------------------------


def _check_safety(
    compiled: CompiledSpec,
    state: dict[str, object],
    new_state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> tuple[Why | None, Severity]:
    """Check all safety invariants against the NEW state.

    Returns (Why, Severity) — severity determines Violated vs Warning.
    """
    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    eval_ctx["__prev_state__"] = state
    eval_ctx["__new_state__"] = new_state

    for clause in compiled.safety:
        result = k3_eval(clause.expr, eval_ctx, step_hash)
        denied_expr = getattr(clause, "denied", None) or getattr(
            clause, "_denied", None
        )

        if isinstance(result, Nothing):
            msg = _eval_denied_msg(
                denied_expr,
                eval_ctx,
                step_hash,
                f"Maintain {clause.name!r}: field {result.field!r} absent",
            )
            return Why(
                rule=clause.name,
                kind=WhyKind.MAINTAIN,
                messages=(msg,),
                before=state,
                after=new_state,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            ), clause.severity

        if isinstance(result, Some) and result.val is False:
            msg = _eval_denied_msg(
                denied_expr,
                eval_ctx,
                step_hash,
                f"Maintain {clause.name!r} violated",
            )
            # Sub-expression diagnosis for compound clauses
            diag = diagnose(clause.expr, eval_ctx, step_hash)
            messages = (msg, "diagnosis:\n" + format_diagnosis(diag))
            return Why(
                rule=clause.name,
                kind=WhyKind.MAINTAIN,
                messages=messages,
                before=state,
                after=new_state,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            ), clause.severity

    return None, Severity.ERROR


# -- K check: korrelation -----------------------------------------------------


def _check_korrelation(
    compiled: CompiledSpec,
    new_state: dict[str, object],
    state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> Why | None:
    """Check korrelator: actual vs intended via expression evaluation."""
    if compiled.korrelator is None:
        return None

    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    eval_ctx["__actual__"] = new_state
    eval_ctx["__intended__"] = ctx.spec_state

    actual_result = k3_eval(compiled.korrelator.actual, eval_ctx, step_hash)
    intended_result = k3_eval(compiled.korrelator.intended, eval_ctx, step_hash)

    if isinstance(actual_result, Nothing) or isinstance(intended_result, Nothing):
        return Why(
            rule="korrelator",
            kind=WhyKind.KORRELATE,
            messages=("Korrelation: could not evaluate actual or intended expression",),
            before=state,
            after=new_state,
            event=event,
            ctx=ctx,
            expected=ctx.spec_state,
            trace=ctx.snapshot_trace(),
            step_hash=step_hash,
        )

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

    if not passed:
        return Why(
            rule="korrelator",
            kind=WhyKind.KORRELATE,
            messages=(
                f"Korrelation failed: actual={actual_val!r} != intended={intended_val!r}",
            ),
            before=state,
            after=new_state,
            event=event,
            ctx=ctx,
            expected=ctx.spec_state,
            trace=ctx.snapshot_trace(),
            step_hash=step_hash,
        )

    return None


# -- U.require: advance spec_state --------------------------------------------


def _apply_require(
    ctx: SpecCtx,
    event: dict[str, object],
    compiled: CompiledSpec,
    step_hash: str,
) -> SpecCtx:
    """Advance Ctx.spec_state via the matching U.require clause."""
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return ctx

    req = compiled.requires.get(event_type)
    if req is None:
        return ctx

    eval_ctx = _build_eval_ctx(ctx.spec_state, event, ctx)
    result = k3_eval(req.transition, eval_ctx, step_hash)

    if isinstance(result, Some) and isinstance(result.val, dict):
        return ctx._with(spec_state=result.val)

    return ctx


# -- L track: liveness obligations ---------------------------------------------


def _step_bounded(
    ctx: SpecCtx,
    eval_ctx: dict[str, object],
    compiled: CompiledSpec,
    step_hash: str,
) -> SpecCtx:
    """Set new timers and discharge satisfied bounded obligations."""
    new_ctx = ctx
    for clause in compiled.bounded:
        if clause.name not in new_ctx.ob_timers and clause.n is not None:
            result = k3_eval(clause.original, eval_ctx, step_hash)
            if isinstance(result, Some) and result.val is not False:
                new_ctx = new_ctx._with(
                    ob_timers={**new_ctx.ob_timers, clause.name: clause.n}
                )

    for clause in compiled.bounded:
        if clause.name in new_ctx.ob_timers:
            result = k3_eval(clause.expr, eval_ctx, step_hash)
            if isinstance(result, Some) and result.val is True:
                timers = {
                    k: v for k, v in new_ctx.ob_timers.items() if k != clause.name
                }
                new_ctx = new_ctx._with(ob_timers=timers)

    return new_ctx


def _step_unbounded(
    ctx: SpecCtx,
    eval_ctx: dict[str, object],
    compiled: CompiledSpec,
    step_hash: str,
) -> SpecCtx:
    """Activate and discharge unbounded liveness obligations."""
    new_ctx = ctx
    for clause in compiled.liveness:
        if clause.name not in new_ctx.active_obligations:
            new_ctx = new_ctx.add_activate_obligation(clause.name, 0)
        result = k3_eval(clause.expr, eval_ctx, step_hash)
        if isinstance(result, Some) and result.val is True:
            new_ctx = new_ctx.discharge_obligation(clause.name)
    return new_ctx


def _step_liveness(
    ctx: SpecCtx,
    new_state: dict[str, object],
    event: dict[str, object],
    compiled: CompiledSpec,
    step_hash: str,
) -> tuple[SpecCtx, Why | None]:
    """Track liveness obligations. Returns (new_ctx, violation_or_none)."""
    tick_result = ctx.tick_timers()
    new_ctx = tick_result.ctx

    if tick_result.expired:
        first_expired = tick_result.expired[0]
        return new_ctx, Why(
            rule=first_expired,
            kind=WhyKind.TIMER,
            messages=(
                f"Timer {first_expired!r} expired \u2014 bounded liveness violated",
            ),
            before=ctx.spec_state,
            after=new_state,
            event=event,
            ctx=new_ctx,
            expected=None,
            trace=new_ctx.snapshot_trace(),
            step_hash=step_hash,
        )

    eval_ctx = _build_eval_ctx(new_state, event, new_ctx, new_state)
    new_ctx = _step_bounded(new_ctx, eval_ctx, compiled, step_hash)
    new_ctx = _step_unbounded(new_ctx, eval_ctx, compiled, step_hash)

    return new_ctx, None


# -- P: projections (declarative) ----------------------------------------------


def _compute_projections(
    compiled: CompiledSpec,
    new_state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> dict[str, object]:
    """Compute all projections by evaluating Expr against state."""
    result: dict[str, object] = {}
    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    for proj in compiled.projections:
        val = k3_eval(proj.expr, eval_ctx, step_hash)
        if isinstance(val, Some):
            result[proj.name] = val.val
        # Nothing -> skip projection
    return result


# -- Outputs (declarative) -----------------------------------------------------


def _compute_outputs(
    compiled: CompiledSpec,
    state: dict[str, object],
    event: dict[str, object],
    new_state: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> tuple[dict[str, object], ...]:
    """Compute output events by evaluating Expr."""
    outputs: list[dict[str, object]] = []
    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    eval_ctx["__prev_state__"] = state
    for output in compiled.outputs:
        if output.on is not None and event.get("type") != output.on:
            continue
        val = k3_eval(output.expr, eval_ctx, step_hash)
        if isinstance(val, Some) and isinstance(val.val, dict):
            outputs.append(val.val)
        elif isinstance(val, Some) and val.val is True:
            outputs.append({"name": output.name, "triggered": True})
        # Nothing or False -> skip
    return tuple(outputs)


# -- apply_step() -- the causal step ------------------------------------------


# -- V check: event-scoped validates ------------------------------------------


def _check_validates(
    compiled: CompiledSpec,
    state: dict[str, object],
    new_state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> tuple[Why, Severity] | None:
    """Check event-scoped validate clauses.

    Only runs validates matching the event's type. Has full access to both
    state and event fields in the eval context.
    """
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return None

    clauses = compiled.validates.get(event_type)
    if not clauses:
        return None

    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    eval_ctx["__prev_state__"] = state

    for clause in clauses:
        result = k3_eval(clause.check, eval_ctx, step_hash)

        if isinstance(result, Nothing):
            primary = _eval_denied_msg(
                clause.denied,
                eval_ctx,
                step_hash,
                f"Validate {clause.name!r}: field {result.field!r} absent",
            )
            msgs = [primary]
            if clause.field:
                msgs.append(f"field: {clause.field}")
            if clause.constraint:
                msgs.append(f"constraint: {clause.constraint}")
            return Why(
                rule=clause.name,
                kind=WhyKind.MAINTAIN,
                messages=tuple(msgs),
                before=state,
                after=new_state,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            ), clause.severity

        if isinstance(result, Some) and result.val is False:
            primary = _eval_denied_msg(
                clause.denied,
                eval_ctx,
                step_hash,
                f"Validate {clause.name!r} failed",
            )
            msgs = [primary]
            if clause.field:
                msgs.append(f"field: {clause.field}")
            if clause.constraint:
                msgs.append(f"constraint: {clause.constraint}")
            return Why(
                rule=clause.name,
                kind=WhyKind.MAINTAIN,
                messages=tuple(msgs),
                before=state,
                after=new_state,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            ), clause.severity

    return None


# -- apply_step() -- the causal step ------------------------------------------


def apply_step(
    *,
    state: dict[str, object],
    ctx: SpecCtx,
    raw_event: object,
    compiled: CompiledSpec,
    transition: TransitionFn,
) -> StepResult[dict[str, object]]:
    """Execute one causal step. Total -- never throws, always returns StepResult.

    state: current implementation state S
    ctx: current SpecCtx (the ambient witness)
    raw_event: incoming event (raw form, before decode)
    compiled: the CompiledSpec from compile_spec()
    transition: T_impl -- user-supplied transition function T(s, e) -> s'

    Returns:
        Ok(state=s', ctx=ctx', step_hash=h) -- success
        Impossible(why) -- guard rejected, state unchanged
        Violated(why) -- invariant broken after T ran
    """
    # Ensure event is a dict for hashing
    if isinstance(raw_event, dict):
        event_for_hash = cast("dict[str, object]", raw_event)
    else:
        event_for_hash = {"__raw__": raw_event}

    # 0. Chained hash -- must be first
    step_hash = _hash_step(state, event_for_hash, ctx.prev_step_hash, compiled.hash_fn)

    # 1. I.decode -- raw event -> domain fields
    domain_event = run_decode(compiled.decode, raw_event)

    # 1b. Check for __skip__ from DecodeDispatch default="skip"
    if isinstance(domain_event, dict) and domain_event.get("__skip__"):
        return Impossible(
            why=Why(
                rule="decode",
                kind=WhyKind.MISSING,
                messages=(
                    f"Unmatched dispatch: discriminant={domain_event.get('__discriminant__')!r}",
                ),
                before=state,
                after=None,
                event=event_for_hash,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            )
        )

    # 2. G check
    eval_ctx = _build_eval_ctx(state, domain_event, ctx)
    guard_failure = _check_guards(compiled, eval_ctx, domain_event, ctx, step_hash)
    if guard_failure is not None:
        return Impossible(why=guard_failure)

    # 3. T -- user transition
    new_state = transition(state, domain_event)

    # 4. Ctx update -- U.require advances spec_state
    new_ctx = _apply_require(ctx, domain_event, compiled, step_hash)

    # 4b. V -- event-scoped validates
    warnings: list[Why] = []
    validate_failure = _check_validates(
        compiled, state, new_state, domain_event, new_ctx, step_hash
    )
    if validate_failure is not None:
        v_why, v_severity = validate_failure
        if v_severity == Severity.ERROR:
            return Violated(why=v_why)
        warnings.append(v_why)

    # 5. N -- safety invariants
    safety_why, safety_severity = _check_safety(
        compiled, state, new_state, domain_event, new_ctx, step_hash
    )
    if safety_why is not None:
        if safety_severity == Severity.ERROR:
            return Violated(why=safety_why)
        warnings.append(safety_why)

    # 5b. K -- korrelation check
    korr_failure = _check_korrelation(
        compiled, new_state, state, domain_event, new_ctx, step_hash
    )
    if korr_failure is not None:
        return Violated(why=korr_failure)

    # 6. L -- liveness obligations
    new_ctx, liveness_failure = _step_liveness(
        new_ctx, new_state, domain_event, compiled, step_hash
    )
    if liveness_failure is not None:
        return Violated(why=liveness_failure)

    # 7. P -- compute projections (declarative)
    projections = _compute_projections(
        compiled, new_state, domain_event, new_ctx, step_hash
    )

    # 8. Outputs -- compute output events (declarative)
    outputs = _compute_outputs(
        compiled, state, domain_event, new_state, new_ctx, step_hash
    )

    # 9. Advance Ctx for next step
    new_ctx = new_ctx.advance(
        new_spec_state=new_ctx.spec_state,
        event=domain_event,
        new_timers=new_ctx.ob_timers,
        new_pos=new_ctx.protocol_pos,
        step_hash=step_hash,
    )

    # If there are warnings, return Warning with the first one
    if warnings:
        return Warning(
            state=new_state,
            ctx=new_ctx,
            step_hash=step_hash,
            why=warnings[0],
            projections=projections,
            outputs=outputs,
        )

    return Ok(
        state=new_state,
        ctx=new_ctx,
        step_hash=step_hash,
        projections=projections,
        outputs=outputs,
    )
