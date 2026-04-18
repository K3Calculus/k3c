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


# -- N-way composition --------------------------------------------------------


type NRouterFn = Callable[[dict[str, object]], str]


class ManyUniverse:
    """N-way composition of universes by name.

    Routes each event to one universe (or a list) by name. State is a dict
    keyed by universe name.

    Usage:
        u = compose_many(
            {"orders": order_u, "payments": payment_u, "audit": audit_u},
            router=lambda e: "audit" if e["type"].startswith("Audit") else "orders",
        )
    """

    def __init__(
        self,
        universes: dict[str, Applyable],
        router: NRouterFn,
    ) -> None:
        if not universes:
            msg = "compose_many requires at least one universe"
            raise ValueError(msg)
        self._universes = universes
        self._router = router

    @property
    def names(self) -> list[str]:
        return list(self._universes.keys())

    @property
    def state(self) -> dict[str, object]:
        return {name: u.state for name, u in self._universes.items()}

    def apply(self, event: dict[str, object]) -> StepResult[dict[str, object]]:
        target = self._router(event)
        if target not in self._universes:
            msg = f"Router returned unknown universe name: {target!r}. Known: {list(self._universes.keys())}"
            raise KeyError(msg)
        return self._universes[target].apply(event)

    def reduce(self, events: list[dict[str, object]]) -> StepResult[dict[str, object]]:
        result: StepResult[dict[str, object]] = Ok(
            state=self.state, ctx=SpecCtx.initial({}), step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    def __repr__(self) -> str:
        return f"ManyUniverse(names={self.names})"


def compose_many(
    universes: dict[str, Applyable],
    router: NRouterFn,
) -> ManyUniverse:
    """Compose N universes keyed by name. Router returns the target name per event."""
    return ManyUniverse(universes=universes, router=router)


class Pipeline:
    """Sequential pipeline — each stage processes the event then forwards.

    Unlike compose_many (event goes to ONE universe), Pipeline applies the
    event to every stage in order. If any stage returns non-Ok, the pipeline
    short-circuits.

    Usage:
        pipe = Pipeline([analyzer, memory, service_graph, correlator])
        result = pipe.apply(event)
    """

    def __init__(self, stages: list[Applyable]) -> None:
        if not stages:
            msg = "Pipeline requires at least one stage"
            raise ValueError(msg)
        self._stages = stages

    @property
    def stages(self) -> list[Applyable]:
        return list(self._stages)

    @property
    def state(self) -> dict[str, object]:
        return {f"stage_{i}": s.state for i, s in enumerate(self._stages)}

    def apply(self, event: dict[str, object]) -> StepResult[dict[str, object]]:
        last_result: StepResult[dict[str, object]] = Ok(
            state=self.state, ctx=SpecCtx.initial({}), step_hash=""
        )
        for stage in self._stages:
            result = stage.apply(event)
            if not isinstance(result, Ok):
                return result
            last_result = result
        return Ok(
            state=self.state,
            ctx=last_result.ctx,
            step_hash=last_result.step_hash,
        )

    def reduce(self, events: list[dict[str, object]]) -> StepResult[dict[str, object]]:
        result: StepResult[dict[str, object]] = Ok(
            state=self.state, ctx=SpecCtx.initial({}), step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    def __repr__(self) -> str:
        return f"Pipeline(stages={len(self._stages)})"
