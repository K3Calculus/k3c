# k3c/universe/compose.py
"""
Compose — parallel composition of two Universes.

Two Universes composed with <||> form a ComposedUniverse. A router function
directs each incoming event to the left Universe, the right Universe, or both.
The composite state is the product of both states.

The algebra is closed: ComposedUniverse supports compose() and bridge().

Usage:
    commerce = order_u.compose(payment_u, router)
    match commerce.apply({"type": "PlaceOrder", "amount": 100}):
        case Ok(state=s): ...
"""

from __future__ import annotations

from typing import Callable, Protocol

from k3c.spec.ctx import SpecCtx
from k3c.spec.result import Impossible, K3Result, Ok, Violated
from k3c.universe.retry import BridgeMode, FallbackStrategy, RetryPolicy

# ── Protocols ───────────────────────────────────────────────────────────────

# Router returns "left", "right", or "both"
type RouterFn = Callable[[dict[str, object]], str]


class Applyable(Protocol):
    """Any object that supports apply() and has a state property."""

    def apply(self, event: dict[str, object]) -> K3Result[dict[str, object]]: ...

    @property
    def state(self) -> dict[str, object]: ...


# ── Result merging ──────────────────────────────────────────────────────────


def _merge_results(
    left: K3Result[dict[str, object]],
    right: K3Result[dict[str, object]],
) -> K3Result[dict[str, object]]:
    """Merge two K3Results deterministically.

    Priority: Violated > Impossible > Ok.
    If both Ok, produce product state {"left": sl, "right": sr}.
    """
    if isinstance(left, Violated):
        return left
    if isinstance(right, Violated):
        return right
    if isinstance(left, Impossible):
        return left
    if isinstance(right, Impossible):
        return right
    # Both Ok
    return Ok(
        state={"left": left.state, "right": right.state},
        ctx=left.ctx,
        step_hash=left.step_hash,
    )


# ── ComposedUniverse ────────────────────────────────────────────────────────


class ComposedUniverse:
    """Two Universes composed with <||>.

    Events are routed to left, right, or both via the router function.
    Each Universe is sequential. The composite expresses concurrency.

    Supports the same apply()/reduce()/compose()/bridge() interface.
    """

    def __init__(
        self,
        left: Applyable,
        right: Applyable,
        router: RouterFn,
    ) -> None:
        self._left = left
        self._right = right
        self._router = router

    @property
    def left(self) -> Applyable:
        return self._left

    @property
    def right(self) -> Applyable:
        return self._right

    def apply(
        self, event: dict[str, object], *, mode: str = "sequential"
    ) -> K3Result[dict[str, object]]:
        """Route event and apply to the appropriate Universe(s).

        Router returns:
            "left"  → apply to left only, right state unchanged
            "right" → apply to right only, left state unchanged
            "both"  → apply to both, merge results

        mode:
            "sequential" (default) — left then right, deterministic
            "parallel"  — both run simultaneously on separate threads/processes
        """
        direction = self._router(event)

        if direction == "left":
            return self._left.apply(event)
        if direction == "right":
            return self._right.apply(event)
        if direction == "both":
            if mode == "parallel":
                return self._apply_parallel(event)
            left_result = self._left.apply(event)
            right_result = self._right.apply(event)
            return _merge_results(left_result, right_result)

        # Unknown direction — treat as left
        return self._left.apply(event)

    def _apply_parallel(self, event: dict[str, object]) -> K3Result[dict[str, object]]:
        """Apply event to both sides simultaneously using threads.

        Safe because Universes share no state (by construction).
        Results merge deterministically: Violated > Impossible > Ok.

        Uses ThreadPoolExecutor (GIL-bound but concurrent I/O) as baseline.
        Python 3.14+ can use InterpreterPoolExecutor for true parallelism.
        """
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            left_future = pool.submit(self._left.apply, event)
            right_future = pool.submit(self._right.apply, event)
            left_result = left_future.result()
            right_result = right_future.result()

        return _merge_results(left_result, right_result)

    def reduce(self, events: list[dict[str, object]]) -> K3Result[dict[str, object]]:
        """Fold events through apply(). Stops on first non-Ok."""
        if not events:
            return Ok(
                state=self.state,
                ctx=SpecCtx.initial({}),
                step_hash="",
            )
        result: K3Result[dict[str, object]] = Ok(
            state=self.state,
            ctx=SpecCtx.initial({}),
            step_hash="",
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    def compose(self, other: Applyable, router: RouterFn) -> ComposedUniverse:
        """Compose this composite with another Universe. Algebra is closed."""
        return ComposedUniverse(left=self, right=other, router=router)

    def bridge(
        self,
        target: Applyable,
        mapper: Callable[
            [dict[str, object], dict[str, object], dict[str, object]],
            dict[str, object] | None,
        ],
        mode: BridgeMode = BridgeMode.SYNCHRONOUS,
        retry: RetryPolicy | None = None,
        fallback: FallbackStrategy = FallbackStrategy.FAIL,
    ) -> object:
        """Bridge this composite to another Universe."""
        from k3c.universe.bridge import BridgedUniverse

        return BridgedUniverse(
            source=self,
            target=target,
            mapper=mapper,
            mode=mode,
            retry=retry,
            fallback=fallback,
        )

    @property
    def state(self) -> dict[str, object]:
        return {
            "left": self._left.state,
            "right": self._right.state,
        }

    def __repr__(self) -> str:
        return f"ComposedUniverse(left={self._left!r}, right={self._right!r})"
