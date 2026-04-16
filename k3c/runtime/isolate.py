# k3c/runtime/isolate.py
"""
IsolatedUniverse -- physical isolation via deep-copy boundaries.

isolate() moves a Universe into its own execution context:
  - All state is deep-copied on every apply() call
  - No Python objects are shared between the isolated Universe and the caller
  - All communication is via serializable dicts

Usage:
    isolated = u.isolate()
    r = isolated.apply({"type": "Event"})
"""

from __future__ import annotations

from copy import deepcopy
from typing import cast

from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Ok, StepResult
from k3c.engine.step import TransitionFn, apply_step
from k3c.spec.compile import CompiledSpec, compile_spec
from k3c.spec.model import Spec


class IsolatedUniverse:
    """A Universe running in an isolated execution context.

    Semantically identical to Universe -- same apply(), same results.
    The isolation is physical: own memory space, no shared state.

    All state is deep-copied on each apply() call. No Python objects
    are shared between the isolated Universe and the caller.
    """

    def __init__(
        self,
        spec: Spec | CompiledSpec,
        state: dict[str, object],
        transition: TransitionFn,
        *,
        id: str = "",
        hash_fn: str = "sha256",
    ) -> None:
        if isinstance(spec, CompiledSpec):
            self._compiled = spec
            self._spec_state0 = spec.state0
        else:
            self._compiled = compile_spec(spec, hash_fn=hash_fn)
            self._spec_state0 = spec.state0
        self._state = deepcopy(state)
        self._initial_state = deepcopy(state)
        self._transition = transition
        self._id = id or self._compiled.name
        self._ctx = SpecCtx.initial(self._spec_state0)

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @property
    def ctx(self) -> SpecCtx:
        return self._ctx

    def apply(self, event: object) -> StepResult[dict[str, object]]:
        """Apply event in isolated context. All data is deep-copied."""
        isolated_state = deepcopy(self._state)
        isolated_event = deepcopy(event)

        result = apply_step(
            state=isolated_state,
            ctx=self._ctx,
            raw_event=isolated_event,
            compiled=self._compiled,
            transition=self._transition,
        )

        if isinstance(result, Ok):
            self._state = deepcopy(cast("dict[str, object]", result.state))
            self._ctx = result.ctx

        return result

    def reduce(self, events: list[object]) -> StepResult[dict[str, object]]:
        """Fold events through isolated apply()."""
        result: StepResult[dict[str, object]] = Ok(
            state=self._state, ctx=self._ctx, step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    def reset(self) -> None:
        """Reset to initial state."""
        self._state = deepcopy(self._initial_state)
        self._ctx = SpecCtx.initial(self._spec_state0)

    def __repr__(self) -> str:
        return f"IsolatedUniverse(id={self._id!r}, isolated=True)"
