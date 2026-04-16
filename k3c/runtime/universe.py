# k3c/runtime/universe.py
"""
Universe -- the public API for K3 causal systems.

A Universe is a self-contained causal world. Events enter. State evolves.
The causal laws hold.

Usage:
    u = Universe(spec=bank_spec, transition=bank_transition)
    match u.apply({"type": "Withdraw", "amount": 50}):
        case Ok(state=s):        print(s["balance"])
        case Impossible(why):    print(why.message)
        case Violated(why):      why.raise_()
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, cast

from k3c.engine.ctx import SpecCtx
from k3c.engine.result import (
    ErrorAction,
    ErrorHandler,
    Impossible,
    Ok,
    StepError,
    StepResult,
    Violated,
    Warning,
)
from k3c.engine.step import TransitionFn, apply_step
from k3c.errors import K3WellFormednessError
from k3c.ir.eval import k3_eval
from k3c.ir.value import Nothing, Some
from k3c.spec.compile import CompiledSpec, compile_spec
from k3c.spec.model import Spec
from k3c.testing import EventGenerator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from k3c.engine.explain import ExplainResult
    from k3c.runtime.bridge import BridgedUniverse
    from k3c.runtime.compose import Applyable, ComposedUniverse
    from k3c.runtime.isolate import IsolatedUniverse
    from k3c.runtime.samsara import ReplayResult, RunResult


# -- ReduceAllResult -----------------------------------------------------------


@dataclass(frozen=True)
class ReduceAllResult:
    """Result of reduce_all -- processes all events, skipping Impossible."""

    final: StepResult[dict[str, object]]
    processed: int
    skipped: list[tuple[int, Impossible]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return isinstance(self.final, Ok)


# -- Well-formedness validation ------------------------------------------------


def _validate_well_formed(compiled: CompiledSpec) -> None:
    """Check well-formedness rules at construction time."""
    if not compiled.state0:
        raise K3WellFormednessError(rule=1, message="state0 must be a non-empty dict")

    ctx = SpecCtx.initial(compiled.state0)
    eval_ctx: dict[str, object] = {
        "state": compiled.state0,
        "event": {},
        "__ctx__": ctx,
        "__new_state__": compiled.state0,
    }
    for clause in compiled.safety:
        result = k3_eval(clause.expr, eval_ctx, "")
        if isinstance(result, Some) and result.val is False:
            raise K3WellFormednessError(
                rule=3,
                message=f"Initial state violates safety invariant {clause.name!r}",
            )
        if isinstance(result, Nothing):
            if result.field.startswith(("before.", "after.")):
                continue
            raise K3WellFormednessError(
                rule=3,
                message=f"Safety invariant {clause.name!r}: field {result.field!r} absent in initial state",
            )


# -- Universe ------------------------------------------------------------------


class Universe:
    """A self-contained K3 causal system.

    Constructor takes spec + transition directly. No factory function needed.

    Usage:
        u = Universe(spec=bank_spec, transition=bank_transition)
        result = u.apply({"type": "Deposit", "amount": 50})
    """

    def __init__(
        self,
        *,
        spec: Spec | CompiledSpec,
        transition: TransitionFn,
        state: dict[str, object] | None = None,
        ctx: SpecCtx | None = None,
        id: str | None = None,
        hash_fn: str = "sha256",
        validate: bool = True,
    ) -> None:
        if isinstance(spec, CompiledSpec):
            self._compiled = spec
            self._spec = None
        else:
            self._compiled = compile_spec(spec, hash_fn=hash_fn)
            self._spec = spec

        if validate:
            _validate_well_formed(self._compiled)

        self._id = id or self._compiled.name
        self._state = deepcopy(state or self._compiled.state0)
        self._ctx = ctx or SpecCtx.initial(self._compiled.state0)
        self._transition = transition
        self._initial_state = deepcopy(self._state)

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

    def cache_stats(self) -> dict[str, object]:
        return self._compiled.cache.stats()

    def apply(self, event: object) -> StepResult[dict[str, object]]:
        """Execute one causal step. Total -- never throws."""
        result = apply_step(
            state=self._state,
            ctx=self._ctx,
            raw_event=event,
            compiled=self._compiled,
            transition=self._transition,
        )
        if isinstance(result, (Ok, Warning)):
            self._state = cast("dict[str, object]", result.state)
            self._ctx = result.ctx
        return result

    def reduce(self, events: Iterable[object]) -> StepResult[dict[str, object]]:
        """Fold event stream. Stops on first non-Ok/Warning."""
        result: StepResult[dict[str, object]] = Ok(
            state=self._state, ctx=self._ctx, step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, (Ok, Warning)):
                return result
        return result

    def reduce_all(self, events: Iterable[object]) -> ReduceAllResult:
        """Process all events. Skip Impossible, stop on Violated."""
        skipped: list[tuple[int, Impossible]] = []
        processed = 0
        last_ok: StepResult[dict[str, object]] = Ok(
            state=self._state, ctx=self._ctx, step_hash=""
        )

        for i, event in enumerate(events):
            result = self.apply(event)
            if isinstance(result, (Ok, Warning)):
                processed += 1
                last_ok = result
            elif isinstance(result, Impossible):
                skipped.append((i, result))
            else:
                return ReduceAllResult(
                    final=result, processed=processed, skipped=skipped
                )

        return ReduceAllResult(final=last_ok, processed=processed, skipped=skipped)

    def stream(
        self, events: Iterable[object]
    ) -> Iterator[StepResult[dict[str, object]]]:
        """Yield each apply() result. Stops after Violated."""
        for event in events:
            result = self.apply(event)
            yield result
            if isinstance(result, Violated):
                return

    def stream_errors(
        self,
        events: Iterable[object],
        *,
        on_error: ErrorHandler | None = None,
    ) -> Iterator[StepError]:
        """Yield only errors (Impossible/Violated) with full step identity.

        Processes all events, yielding a StepError for each non-Ok result.
        If on_error is provided, the client controls flow via ErrorAction.
        Without on_error, Impossible events are skipped and Violated aborts.

        Usage:
            for error in u.stream_errors(events):
                logger.warning(error.why.to_log_record())
        """
        for offset, event in enumerate(events):
            result = self.apply(event)

            if isinstance(result, Ok):
                continue

            step_error = StepError(chunk_index=0, offset=offset, result=result)
            yield step_error

            if on_error is not None:
                action = on_error(step_error)
            else:
                action = (
                    ErrorAction.ABORT_CHUNK
                    if isinstance(result, Violated)
                    else ErrorAction.SKIP
                )

            if action in (ErrorAction.ABORT_CHUNK, ErrorAction.ABORT_ALL):
                return

    def reset(self) -> None:
        """Reset state and ctx to initial."""
        self._state = deepcopy(self._initial_state)
        self._ctx = SpecCtx.initial(self._compiled.state0)

    def explain(self, event: object) -> ExplainResult:
        """Dry-run an event with full eval trace. State is NOT mutated."""
        from k3c.engine.explain import explain as _explain

        return _explain(self._state, self._ctx, event, self._compiled, self._transition)

    def fuzz(
        self,
        *,
        sequences: int = 1000,
        steps: int = 100,
        seed: int = 0,
        event_generator: EventGenerator | None = None,
        max_violations: int = 1,
        shrink: bool = True,
    ) -> object:
        """Property-based fuzz testing. Discharges well-formedness rule 8."""
        from k3c.testing.fuzz import fuzz as _fuzz

        return _fuzz(
            self,
            sequences=sequences,
            steps=steps,
            seed=seed,
            event_generator=event_generator,
            max_violations=max_violations,
            shrink=shrink,
        )

    def isolate(self) -> IsolatedUniverse:
        """Move this Universe into an isolated execution context.

        Returns an IsolatedUniverse with deep-copied state and no shared
        references. All communication is via serializable dicts.
        """
        from k3c.runtime.isolate import IsolatedUniverse as _Isolated

        return _Isolated(
            spec=self._compiled,
            state=self._state,
            transition=self._transition,
            id=f"{self._id}:isolated",
            hash_fn=self._compiled.hash_fn,
        )

    def compose(
        self,
        other: Applyable,
        router: Callable[[dict[str, object]], str],
    ) -> ComposedUniverse:
        """Compose with another Universe via <||>."""
        from k3c.runtime.compose import ComposedUniverse as _Composed

        return _Composed(left=self, right=other, router=router)

    def bridge(
        self,
        target: Applyable,
        mapper: Callable[
            [dict[str, object], dict[str, object], dict[str, object]],
            dict[str, object] | None,
        ],
        mode: str = "synchronous",
        retry: object | None = None,
        fallback: str = "fail",
    ) -> BridgedUniverse:
        """Bridge to another Universe via <->."""
        from k3c.runtime.bridge import BridgedUniverse as _Bridged
        from k3c.runtime.bridge import BridgeMode, FallbackStrategy, RetryPolicy

        return _Bridged(
            source=self,
            target=target,
            mapper=mapper,
            mode=BridgeMode(mode),
            retry=retry if isinstance(retry, RetryPolicy) else None,
            fallback=FallbackStrategy(fallback),
        )

    def simulate(self, events: Iterable[object]) -> RunResult:
        """Samsara (<?>) -- simulate with full trajectory collection (KC-3).

        Processes all events while collecting the complete state trajectory
        and per-step trace records. Skips Impossible, stops on Violated.

        This is the opt-in trajectory collection mode. For processing
        without trajectory overhead, use reduce() or stream().
        """
        from k3c.runtime.samsara import simulate as _simulate

        return _simulate(self, events)

    def replay(
        self,
        events: Sequence[object],
        *,
        expected_hashes: Sequence[str],
    ) -> ReplayResult:
        """Deterministic replay verification (KC-3).

        Replays the event sequence and verifies that every step produces
        the same step_hash as the original run. Resets the Universe first,
        then replays from initial state.
        """
        from k3c.runtime.samsara import replay as _replay

        self.reset()
        return _replay(self, events, expected_hashes=expected_hashes)

    def __repr__(self) -> str:
        return f"Universe(id={self._id!r}, state_keys={list(self._state.keys())})"
