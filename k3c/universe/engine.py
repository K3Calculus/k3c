# k3c/universe/engine.py
"""
The causal step — apply().

apply() is a total pure function. It never throws. step_hash is computed
first and flows into every result. eval() returns Some|Nothing — Nothing
at the guard boundary becomes Impossible. A failed invariant becomes Violated.

Pipeline:
  1. step_hash = hash(state, event, prev_step_hash)
  2. e' = I.decode(e)
  3. G check: eval permits
  4. s' = T_impl(s, e)
  5. ctx' = U.require(ctx, e')
  6. N check: safety invariants + korrelation
  7. L track: liveness obligations
  8. Return Ok(state=s', ctx=ctx', step_hash=h)
"""

from __future__ import annotations

import hashlib
from typing import Callable, cast

from k3c.json import dumps as _json_dumps

from k3c.cache import invariant_cache_key
from k3c.lang.compile import CompiledSpec
from k3c.lang.eval import k3_eval
from k3c.lang.ir import Nothing, Some
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import Impossible, K3Result, Ok, Violated, Why, WhyKind


# ── Hash step ────────────────────────────────────────────────────────────────


def _hash_step(
    state: dict[str, object],
    event: dict[str, object],
    prev_step_hash: str,
    hash_fn: str = "sha256",
) -> str:
    """Compute the chained step hash. Deterministic — same inputs always produce same hash."""
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


# ── Build eval context ───────────────────────────────────────────────────────


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


# ── G check — guards ─────────────────────────────────────────────────────────


def _check_guards(
    compiled: CompiledSpec,
    eval_ctx: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> Why | None:
    """Evaluate all permit clauses. Returns Why on first failure, None if all pass."""
    for permit in compiled.permits:
        # Skip permits filtered by event type
        if permit.on is not None:
            event_type = event.get("type")
            if event_type != permit.on:
                continue

        result = k3_eval(permit.when, eval_ctx, step_hash)

        if isinstance(result, Nothing):
            return Why(
                rule=permit.name,
                kind=WhyKind.MISSING,
                messages=(
                    f"Field {result.field!r} absent — required by {permit.name!r}",
                ),
                before=cast("dict[str, object]", eval_ctx.get("state", {})),
                after=None,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            )

        if isinstance(result, Some) and result.val is False:
            return Why(
                rule=permit.name,
                kind=WhyKind.PERMIT,
                messages=(f"Permit {permit.name!r} denied",),
                before=cast("dict[str, object]", eval_ctx.get("state", {})),
                after=None,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            )

    return None


# ── N check — safety invariants ──────────────────────────────────────────────


def _check_safety(
    compiled: CompiledSpec,
    state: dict[str, object],
    new_state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> Why | None:
    """Check all safety invariants against the NEW state. Returns Why on first failure."""
    # Cache check: step_hash uniquely identifies (state, event, prev_hash)
    cache_key = invariant_cache_key(step_hash)
    cached = compiled.cache.spec_invariant.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    eval_ctx = _build_eval_ctx(new_state, event, ctx, new_state)
    eval_ctx["__prev_state__"] = state
    eval_ctx["__new_state__"] = new_state

    failure: Why | None = None
    for clause in compiled.safety:
        result = k3_eval(clause.expr, eval_ctx, step_hash)

        if isinstance(result, Nothing):
            failure = Why(
                rule=clause.name,
                kind=WhyKind.MAINTAIN,
                messages=(f"Maintain {clause.name!r}: field {result.field!r} absent",),
                before=state,
                after=new_state,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            )
            break

        if isinstance(result, Some) and result.val is False:
            failure = Why(
                rule=clause.name,
                kind=WhyKind.MAINTAIN,
                messages=(f"Maintain {clause.name!r} violated",),
                before=state,
                after=new_state,
                event=event,
                ctx=ctx,
                expected=None,
                trace=ctx.snapshot_trace(),
                step_hash=step_hash,
            )
            break

    # Cache result (None = all passed, Why = first failure)
    compiled.cache.spec_invariant.put(cache_key, failure)
    return failure


# ── K check — korrelation ───────────────────────────────────────────────────


def _check_korrelation(
    compiled: CompiledSpec,
    new_state: dict[str, object],
    state: dict[str, object],
    event: dict[str, object],
    ctx: SpecCtx,
    step_hash: str,
) -> Why | None:
    """Check korrelator: actual (K.lift(S)) vs intended (Ctx.spec_state)."""
    if compiled.korrelator is None:
        return None

    actual = compiled.korrelator.lift(new_state)
    intended = ctx.spec_state

    if compiled.korrelator.correlate is not None:
        correlation = compiled.korrelator.correlate(actual, intended)
    else:
        # Default: exact equality on lifted fields
        correlation = all(actual.get(k) == intended.get(k) for k in actual)

    if compiled.korrelator.threshold is not None:
        passed = compiled.korrelator.threshold(correlation)
    else:
        passed = bool(correlation)

    if not passed:
        return Why(
            rule="korrelator",
            kind=WhyKind.KORRELATE,
            messages=(
                f"Korrelation failed: actual={actual!r} != intended={intended!r}",
            ),
            before=state,
            after=new_state,
            event=event,
            ctx=ctx,
            expected=intended,
            trace=ctx.snapshot_trace(),
            step_hash=step_hash,
        )

    return None


# ── U.require — advance spec_state ───────────────────────────────────────────


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


# ── L track — liveness obligations ──────────────────────────────────────────


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
    # Tick existing timers
    tick_result = ctx.tick_timers()
    new_ctx = tick_result.ctx

    if tick_result.expired:
        first_expired = tick_result.expired[0]
        return new_ctx, Why(
            rule=first_expired,
            kind=WhyKind.TIMER,
            messages=(f"Timer {first_expired!r} expired — bounded liveness violated",),
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


# ── P — projections ─────────────────────────────────────────────────────────


def _compute_projections(
    compiled: CompiledSpec,
    new_state: dict[str, object],
) -> dict[str, object]:
    """Compute all projections against the new state. Post-causal — after N holds."""
    result: dict[str, object] = {}
    for proj in compiled.projections:
        result[proj.name] = proj.fn(new_state)
    return result


# ── Outputs ──────────────────────────────────────────────────────────────────


def _compute_outputs(
    compiled: CompiledSpec,
    state: dict[str, object],
    event: dict[str, object],
    new_state: dict[str, object],
) -> tuple[dict[str, object], ...]:
    """Compute output events. Post-causal — after N holds."""
    outputs: list[dict[str, object]] = []
    for output_def in compiled.outputs:
        if output_def.on is not None and event.get("type") != output_def.on:
            continue
        output_event = output_def.fn(state, event, new_state)
        if output_event is not None:
            outputs.append(output_event)
    return tuple(outputs)


# ── apply() — the causal step ───────────────────────────────────────────────


def apply(
    state: dict[str, object],
    ctx: SpecCtx,
    event: dict[str, object],
    compiled: CompiledSpec,
    transition: Callable[[dict[str, object], dict[str, object]], dict[str, object]],
) -> K3Result[dict[str, object]]:
    """Execute one causal step. Total — never throws, always returns K3Result.

    state: current implementation state S
    ctx: current SpecCtx (the ambient witness)
    event: incoming event (raw form)
    compiled: the CompiledSpec from compile_spec()
    transition: T_impl — user-supplied transition function T(s, e) → s'

    Returns:
        Ok(state=s', ctx=ctx', step_hash=h) — success
        Impossible(why) — guard rejected, state unchanged
        Violated(why) — invariant broken after T ran
    """
    # 0. Chained hash — must be first
    step_hash = _hash_step(state, event, ctx.prev_step_hash, compiled.hash_fn)

    # 1. I.decode — raw event → domain fields
    domain_event = compiled.decode(event) if compiled.decode else event

    # 2. G check — eval() returns Some(True) | Some(False) | Nothing
    eval_ctx = _build_eval_ctx(state, domain_event, ctx)
    guard_failure = _check_guards(compiled, eval_ctx, domain_event, ctx, step_hash)
    if guard_failure is not None:
        return Impossible(why=guard_failure)

    # 3. T — user transition
    new_state = transition(state, domain_event)

    # 4. Ctx update — U.require advances spec_state
    new_ctx = _apply_require(ctx, domain_event, compiled, step_hash)

    # 5. N — safety invariants
    safety_failure = _check_safety(
        compiled, state, new_state, domain_event, new_ctx, step_hash
    )
    if safety_failure is not None:
        return Violated(why=safety_failure)

    # 5b. K — korrelation check
    korr_failure = _check_korrelation(
        compiled, new_state, state, domain_event, new_ctx, step_hash
    )
    if korr_failure is not None:
        return Violated(why=korr_failure)

    # 6. L — liveness obligations
    new_ctx, liveness_failure = _step_liveness(
        new_ctx, new_state, domain_event, compiled, step_hash
    )
    if liveness_failure is not None:
        return Violated(why=liveness_failure)

    # 7. P — compute projections (post-causal, after N holds)
    projections = _compute_projections(compiled, new_state)

    # 8. Outputs — compute output events (post-causal)
    outputs = _compute_outputs(compiled, state, domain_event, new_state)

    # 9. Advance Ctx for next step
    new_ctx = new_ctx.advance(
        new_spec_state=new_ctx.spec_state,
        event=domain_event,
        new_timers=new_ctx.ob_timers,
        new_pos=new_ctx.protocol_pos,
        step_hash=step_hash,
    )

    return Ok(
        state=new_state,
        ctx=new_ctx,
        step_hash=step_hash,
        projections=projections,
        outputs=outputs,
    )
