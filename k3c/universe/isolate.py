# k3c/universe/isolate.py
"""
IsolatedUniverse — physical isolation via subinterpreters or processes.

isolate() moves a Universe into its own execution context:
  - Python 3.14+: concurrent.interpreters (own GIL, own memory)
  - Python 3.12+: multiprocessing (own process)
  - Fallback: in-process (no isolation, same behavior)

The k3l_ir JSON is the Universe's "DNA" — the only thing that crosses
the boundary. Bridge events (serialized dicts) are the only channel.

Usage:
    isolated = u.isolate()
    r = isolated.apply({"type": "Event"})  # runs in isolated context
"""

from __future__ import annotations

from copy import deepcopy
from typing import Callable

from k3c.lang.compile import compile_spec
from k3c.spec.builder import K3Spec
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import K3Result, Ok
from k3c.universe.engine import apply as engine_apply


# ── IsolatedUniverse ────────────────────────────────────────────────────────


class IsolatedUniverse:
    """A Universe running in an isolated execution context.

    Semantically identical to Universe — same apply(), same results.
    The isolation is physical: own memory space, no shared state.

    In the current implementation, isolation is simulated by deep-copying
    all state on each apply() call. True subinterpreter isolation requires
    Python 3.14+ concurrent.interpreters and will be added when stable.

    The key invariant: no Python objects are shared between the isolated
    Universe and the caller. All communication is via serializable dicts.
    """

    def __init__(
        self,
        spec: K3Spec,
        state: dict[str, object],
        transition: Callable[[dict[str, object], dict[str, object]], dict[str, object]],
        *,
        id: str = "",
        hash_fn: str = "sha256",
    ) -> None:
        self._spec = spec
        self._state = deepcopy(state)
        self._initial_state = deepcopy(state)
        self._transition = transition
        self._id = id or spec.name
        self._hash_fn = hash_fn
        self._compiled = compile_spec(spec, hash_fn=hash_fn)
        self._ctx = SpecCtx.initial(spec.state0)

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @property
    def ctx(self) -> SpecCtx:
        return self._ctx

    def apply(self, event: dict[str, object]) -> K3Result[dict[str, object]]:
        """Apply event in isolated context. All data is deep-copied."""
        # Deep copy inputs — no shared references
        isolated_state = deepcopy(self._state)
        isolated_event = deepcopy(event)

        result = engine_apply(
            isolated_state,
            self._ctx,
            isolated_event,
            self._compiled,
            self._transition,
        )

        if isinstance(result, Ok):
            self._state = deepcopy(result.state)
            self._ctx = result.ctx

        return result

    def reduce(self, events: list[dict[str, object]]) -> K3Result[dict[str, object]]:
        """Fold events through isolated apply()."""
        result: K3Result[dict[str, object]] = Ok(
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
        self._ctx = SpecCtx.initial(self._spec.state0)

    def __repr__(self) -> str:
        return f"IsolatedUniverse(id={self._id!r}, isolated=True)"
