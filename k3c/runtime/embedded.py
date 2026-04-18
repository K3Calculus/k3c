# k3c/runtime/embedded.py
"""
EmbeddedRuntime -- attach Python callables at the runtime boundary.

The portable Spec is 100% serializable data. When you need Python callables
for projections, outputs, decode, or korrelation, wrap the spec in an
EmbeddedRuntime. The callables exist only at the runtime boundary -- they
are never serialized, never part of the spec registry, never replayed.

Usage:
    spec = Spec(name="bank", state0={"balance": 100}, ...)

    runtime = EmbeddedRuntime(
        spec=spec,
        transition=bank_transition,
        projection_hooks={
            "summary": lambda state, event, ctx: {"balance": state["balance"], "healthy": state["balance"] > 0},
        },
        output_hooks={
            "low_balance_alert": lambda state, event, new_state: (
                {"alert": "low", "balance": new_state["balance"]}
                if new_state["balance"] < 20 else None
            ),
        },
    )

    u = runtime.universe()
    result = u.apply({"type": "Withdraw", "amount": 90})
    # result.projections includes both declarative + hook projections
    # result.outputs includes both declarative + hook outputs
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable, cast

from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Ok, StepResult, Violated
from k3c.engine.step import TransitionFn, apply_step
from k3c.spec.compile import CompiledSpec, compile_spec
from k3c.spec.extract import run_decode
from k3c.spec.model import Spec


# Type aliases for hook functions
type ProjectionHook = Callable[[dict[str, object], dict[str, object], SpecCtx], object]
type OutputHook = Callable[
    [dict[str, object], dict[str, object], dict[str, object]], dict[str, object] | None
]
type DecodeHook = Callable[[object], dict[str, object]]
type KorrelateHook = Callable[[dict[str, object], dict[str, object]], bool]


@dataclass
class EmbeddedRuntime:
    """Wraps a portable Spec with Python callables at the runtime boundary.

    The spec remains pure data. The hooks are runtime-only integration points.
    """

    spec: Spec
    transition: TransitionFn

    # Runtime-only hooks (not part of the portable spec)
    projection_hooks: dict[str, ProjectionHook] = field(default_factory=dict)
    output_hooks: dict[str, OutputHook] = field(default_factory=dict)
    decode_hook: DecodeHook | None = None
    korrelate_hook: KorrelateHook | None = None

    # Configuration
    hash_fn: str = "sha256"
    id: str | None = None
    validate: bool = True

    def universe(
        self,
        *,
        state: dict[str, object] | None = None,
        ctx: SpecCtx | None = None,
    ) -> EmbeddedUniverse:
        """Create an EmbeddedUniverse from this runtime configuration."""
        compiled = compile_spec(self.spec, hash_fn=self.hash_fn)
        if self.validate:
            from k3c.runtime.universe import _validate_well_formed

            _validate_well_formed(compiled)

        return EmbeddedUniverse(
            compiled=compiled,
            spec=self.spec,
            transition=self.transition,
            projection_hooks=self.projection_hooks,
            output_hooks=self.output_hooks,
            decode_hook=self.decode_hook,
            korrelate_hook=self.korrelate_hook,
            state=deepcopy(state or compiled.state0),
            ctx=ctx or SpecCtx.initial(compiled.state0),
            id=self.id or compiled.name,
        )


class EmbeddedUniverse:
    """A Universe with embedded Python hooks for projections, outputs, decode.

    Wraps the pure apply_step() with post-processing that runs hook functions.
    The hooks produce additional projections and outputs beyond what the
    declarative spec provides.
    """

    def __init__(
        self,
        *,
        compiled: CompiledSpec,
        spec: Spec,
        transition: TransitionFn,
        projection_hooks: dict[str, ProjectionHook],
        output_hooks: dict[str, OutputHook],
        decode_hook: DecodeHook | None,
        korrelate_hook: KorrelateHook | None,
        state: dict[str, object],
        ctx: SpecCtx,
        id: str,
    ) -> None:
        self._compiled = compiled
        self._spec = spec
        self._transition = transition
        self._projection_hooks = projection_hooks
        self._output_hooks = output_hooks
        self._decode_hook = decode_hook
        self._korrelate_hook = korrelate_hook
        self._state = state
        self._ctx = ctx
        self._id = id
        self._initial_state = deepcopy(state)

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self) -> dict[str, object]:
        return self._state.copy()

    @property
    def ctx(self) -> SpecCtx:
        return self._ctx

    @property
    def compiled(self) -> CompiledSpec:
        return self._compiled

    def apply(self, event: object) -> StepResult[dict[str, object]]:
        """Execute one causal step with embedded hooks."""
        # If decode hook is set, use it instead of the declarative decode plan
        if self._decode_hook is not None:
            decoded = self._decode_hook(event)
            raw_event: object = decoded
        else:
            raw_event = event

        result = apply_step(
            state=self._state,
            ctx=self._ctx,
            raw_event=raw_event,
            compiled=self._compiled,
            transition=self._transition,
        )

        if isinstance(result, Ok):
            new_state = cast("dict[str, object]", result.state)

            # Decode the event for hook context
            if self._decode_hook is not None:
                domain_event = self._decode_hook(event)
            else:
                domain_event = run_decode(self._compiled.decode, event)

            # Run projection hooks (merge with declarative projections)
            extra_projections = self._run_projection_hooks(
                new_state, domain_event, result.ctx
            )
            merged_projections = {**result.projections, **extra_projections}

            # Run output hooks (append to declarative outputs)
            extra_outputs = self._run_output_hooks(self._state, domain_event, new_state)
            merged_outputs = result.outputs + tuple(extra_outputs)

            # Run korrelate hook if present
            if self._korrelate_hook is not None:
                passed = self._korrelate_hook(new_state, result.ctx.spec_state)
                if not passed:
                    from k3c.engine.result import Why, WhyKind

                    return Violated(
                        why=Why(
                            rule="korrelator_hook",
                            kind=WhyKind.KORRELATE,
                            messages=("Embedded korrelation hook failed",),
                            before=self._state,
                            after=new_state,
                            event=domain_event,
                            ctx=result.ctx,
                            expected=result.ctx.spec_state,
                            trace=result.ctx.snapshot_trace(),
                            step_hash=result.step_hash,
                        )
                    )

            # Update state
            self._state = new_state
            self._ctx = result.ctx

            return Ok(
                state=new_state,
                ctx=result.ctx,
                step_hash=result.step_hash,
                projections=merged_projections,
                outputs=merged_outputs,
            )

        return result

    def _run_projection_hooks(
        self,
        new_state: dict[str, object],
        event: dict[str, object],
        ctx: SpecCtx,
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, hook in self._projection_hooks.items():
            val = hook(new_state, event, ctx)
            if val is not None:
                result[name] = val
        return result

    def _run_output_hooks(
        self,
        state: dict[str, object],
        event: dict[str, object],
        new_state: dict[str, object],
    ) -> list[dict[str, object]]:
        outputs: list[dict[str, object]] = []
        for name, hook in self._output_hooks.items():
            output = hook(state, event, new_state)
            if output is not None:
                outputs.append(output)
        return outputs

    def reduce(self, events: Iterable[object]) -> StepResult[dict[str, object]]:
        """Fold event stream. Stops on first non-Ok."""
        result: StepResult[dict[str, object]] = Ok(
            state=self._state, ctx=self._ctx, step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    def stream(
        self, events: Iterable[object]
    ) -> Iterator[StepResult[dict[str, object]]]:
        """Yield each apply() result. Stops after Violated."""
        for event in events:
            result = self.apply(event)
            yield result
            if isinstance(result, Violated):
                return

    def get(self, field: str, default: object = None) -> object:
        """Read a single state field without copying the entire dict."""
        return self._state.get(field, default)

    def simulate(self, events: Iterable[object]):
        """Samsara — simulate with full trajectory collection (KC-3).

        Returns a RunResult suitable for attestation, replay, and inspection.
        Same semantics as Universe.simulate().
        """
        from k3c.runtime.samsara import simulate as _simulate

        return _simulate(self, events)

    def replay(
        self,
        events,
        *,
        expected_hashes,
    ):
        """Deterministic replay verification (KC-3). See Universe.replay()."""
        from k3c.runtime.samsara import replay as _replay

        self.reset()
        return _replay(self, events, expected_hashes=expected_hashes)

    def reset(self) -> None:
        """Reset state and ctx to initial."""
        self._state = deepcopy(self._initial_state)
        self._ctx = SpecCtx.initial(self._compiled.state0)

    def __repr__(self) -> str:
        hooks = []
        if self._projection_hooks:
            hooks.append(f"projections={list(self._projection_hooks.keys())}")
        if self._output_hooks:
            hooks.append(f"outputs={list(self._output_hooks.keys())}")
        if self._decode_hook:
            hooks.append("decode=custom")
        if self._korrelate_hook:
            hooks.append("korrelate=custom")
        hook_str = ", ".join(hooks) if hooks else "none"
        return f"EmbeddedUniverse(id={self._id!r}, hooks=[{hook_str}])"
