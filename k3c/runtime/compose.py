# k3c/runtime/compose.py
"""
Compose -- parallel composition of two Universes.

Two Universes composed with <||> form a ComposedUniverse. A router function
directs each incoming event to the left Universe, the right Universe, or both.
"""

from __future__ import annotations

from typing import Callable, Protocol

from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Impossible, Ok, StepResult, Violated

type RouterFn = Callable[[dict[str, object]], str]


class Applyable(Protocol):
    """Any object that supports apply() and has a state property."""

    def apply(self, event: object) -> StepResult[dict[str, object]]: ...

    @property
    def state(self) -> dict[str, object]: ...


def _merge_results(
    left: StepResult[dict[str, object]],
    right: StepResult[dict[str, object]],
) -> StepResult[dict[str, object]]:
    """Merge two StepResults. Priority: Violated > Impossible > Ok."""
    if isinstance(left, Violated):
        return left
    if isinstance(right, Violated):
        return right
    if isinstance(left, Impossible):
        return left
    if isinstance(right, Impossible):
        return right
    return Ok(
        state={"left": left.state, "right": right.state},
        ctx=left.ctx,
        step_hash=left.step_hash,
    )


class ComposedUniverse:
    """Two Universes composed with <||>."""

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
    ) -> StepResult[dict[str, object]]:
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

        return self._left.apply(event)

    def _apply_parallel(
        self, event: dict[str, object]
    ) -> StepResult[dict[str, object]]:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            left_future = pool.submit(self._left.apply, event)
            right_future = pool.submit(self._right.apply, event)
            return _merge_results(left_future.result(), right_future.result())

    def reduce(self, events: list[dict[str, object]]) -> StepResult[dict[str, object]]:
        result: StepResult[dict[str, object]] = Ok(
            state=self.state, ctx=SpecCtx.initial({}), step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    def compose(self, other: Applyable, router: RouterFn) -> ComposedUniverse:
        return ComposedUniverse(left=self, right=other, router=router)

    @property
    def state(self) -> dict[str, object]:
        return {"left": self._left.state, "right": self._right.state}

    def __repr__(self) -> str:
        return f"ComposedUniverse(left={self._left!r}, right={self._right!r})"
