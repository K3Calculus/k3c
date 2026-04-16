# k3c/runtime/bridge.py
"""
Bridge -- cross-universe event propagation.

A Bridge connects two Universes. When the source produces Ok, the mapper
transforms the event into a target event. BridgeMode controls delivery.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, cast

from k3c.engine.ctx import SpecCtx
from k3c.engine.result import Impossible, Ok, StepResult, Violated
from k3c.errors import K3BridgeError
from k3c.runtime.compose import Applyable


class BridgeMode(StrEnum):
    SYNCHRONOUS = "synchronous"
    ASYNC = "async"
    BEST_EFFORT = "best_effort"


class FallbackStrategy(StrEnum):
    FAIL = "fail"
    IGNORE = "ignore"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    base_delay_ms: int = 0
    strategy: str = "none"

    @staticmethod
    def no_retry() -> RetryPolicy:
        return RetryPolicy(max_attempts=1, base_delay_ms=0, strategy="none")

    @staticmethod
    def fixed_delay(n: int, delay_ms: int) -> RetryPolicy:
        return RetryPolicy(max_attempts=n, base_delay_ms=delay_ms, strategy="fixed")

    @staticmethod
    def exponential_backoff(n: int, base_ms: int) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=n, base_delay_ms=base_ms, strategy="exponential"
        )


@dataclass(frozen=True)
class DeadLetterEntry:
    source_event: dict[str, object]
    target_event: dict[str, object]
    source_state: dict[str, object]
    attempts: int
    last_error: str


type BridgeMapper = Callable[
    [dict[str, object], dict[str, object], dict[str, object]],
    dict[str, object] | None,
]

_State = "dict[str, object]"


def _deliver_to_target(
    target: Applyable,
    target_event: dict[str, object],
    retry: RetryPolicy,
) -> StepResult[dict[str, object]]:
    last_error = ""
    for attempt in range(retry.max_attempts):
        try:
            result = target.apply(target_event)
            if isinstance(result, (Ok, Violated)):
                return result
            if isinstance(result, Impossible):
                return result
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

        if attempt < retry.max_attempts - 1 and retry.base_delay_ms > 0:
            if retry.strategy == "fixed":
                time.sleep(retry.base_delay_ms / 1000)
            elif retry.strategy == "exponential":
                time.sleep((retry.base_delay_ms * (2**attempt)) / 1000)

    raise K3BridgeError(
        source_id="source",
        target_id="target",
        bridge_event=target_event,
        attempts=retry.max_attempts,
        last_reason=last_error
        or f"delivery failed after {retry.max_attempts} attempts",
    )


class BridgedUniverse:
    """Two Universes connected with <->."""

    def __init__(
        self,
        source: Applyable,
        target: Applyable,
        mapper: BridgeMapper,
        mode: BridgeMode = BridgeMode.SYNCHRONOUS,
        retry: RetryPolicy | None = None,
        fallback: FallbackStrategy = FallbackStrategy.FAIL,
    ) -> None:
        self._source = source
        self._target = target
        self._mapper = mapper
        self._mode = mode
        self._retry = retry or RetryPolicy.no_retry()
        self._fallback = fallback
        self._dead_letters: list[DeadLetterEntry] = []

    @property
    def source(self) -> Applyable:
        return self._source

    @property
    def target(self) -> Applyable:
        return self._target

    @property
    def dead_letters(self) -> list[DeadLetterEntry]:
        return list(self._dead_letters)

    @property
    def mode(self) -> BridgeMode:
        return self._mode

    def apply(self, event: dict[str, object]) -> StepResult[dict[str, object]]:
        source_result = self._source.apply(event)
        if not isinstance(source_result, Ok):
            return source_result

        target_event = self._mapper(
            cast(_State, source_result.state),
            event,
            cast(_State, source_result.state),
        )
        if target_event is None:
            return source_result

        return self._deliver(source_result, target_event, event)

    def _deliver(
        self,
        source_result: Ok[dict[str, object]],
        target_event: dict[str, object],
        original_event: dict[str, object],
    ) -> StepResult[dict[str, object]]:
        if self._mode == BridgeMode.SYNCHRONOUS:
            return self._deliver_sync(source_result, target_event, original_event)
        if self._mode == BridgeMode.ASYNC:
            return self._deliver_async(source_result, target_event, original_event)
        return self._deliver_best_effort(source_result, target_event, original_event)

    def _deliver_sync(self, source_result, target_event, original_event):
        try:
            target_result = _deliver_to_target(self._target, target_event, self._retry)
        except K3BridgeError:
            return self._handle_failure(
                source_result, target_event, original_event, "delivery raised"
            )
        if isinstance(target_result, Violated):
            return target_result
        if isinstance(target_result, Impossible):
            return self._handle_failure(
                source_result, target_event, original_event, "target rejected"
            )
        # Merge: combined state, source outputs + target outputs
        return Ok(
            state=self.state,
            ctx=source_result.ctx,
            step_hash=source_result.step_hash,
            projections={
                **source_result.projections,
                **{f"target.{k}": v for k, v in target_result.projections.items()},
            },
            outputs=source_result.outputs + target_result.outputs,
        )

    def _handle_failure(self, source_result, target_event, original_event, reason):
        if self._fallback == FallbackStrategy.FAIL:
            raise K3BridgeError(
                source_id="source",
                target_id="target",
                bridge_event=target_event,
                attempts=self._retry.max_attempts,
                last_reason=reason,
            )
        if self._fallback == FallbackStrategy.DEAD_LETTER:
            self._dead_letters.append(
                DeadLetterEntry(
                    source_event=original_event,
                    target_event=target_event,
                    source_state=cast(_State, source_result.state),
                    attempts=self._retry.max_attempts,
                    last_error=reason,
                )
            )
        return source_result

    def _deliver_async(self, source_result, target_event, original_event):
        try:
            target_result = _deliver_to_target(self._target, target_event, self._retry)
            if (
                isinstance(target_result, Impossible)
                and self._fallback == FallbackStrategy.DEAD_LETTER
            ):
                self._dead_letters.append(
                    DeadLetterEntry(
                        source_event=original_event,
                        target_event=target_event,
                        source_state=cast(_State, source_result.state),
                        attempts=1,
                        last_error="target rejected",
                    )
                )
        except K3BridgeError:
            if self._fallback == FallbackStrategy.DEAD_LETTER:
                self._dead_letters.append(
                    DeadLetterEntry(
                        source_event=original_event,
                        target_event=target_event,
                        source_state=cast(_State, source_result.state),
                        attempts=self._retry.max_attempts,
                        last_error="async delivery failed",
                    )
                )
        return source_result

    def _deliver_best_effort(self, source_result, target_event, original_event):
        try:
            self._target.apply(target_event)
        except Exception:  # noqa: BLE001
            pass
        return source_result

    def reduce(self, events: list[dict[str, object]]) -> StepResult[dict[str, object]]:
        result: StepResult[dict[str, object]] = Ok(
            state=self.state, ctx=SpecCtx.initial({}), step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    @property
    def state(self) -> dict[str, object]:
        return {"source": self._source.state, "target": self._target.state}

    def __repr__(self) -> str:
        return f"BridgedUniverse(mode={self._mode}, dead_letters={len(self._dead_letters)})"
