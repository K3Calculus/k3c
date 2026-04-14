# k3c/universe/bridge.py
"""
Bridge — cross-universe event propagation.

A Bridge connects two Universes. When the source Universe produces an
output event (via apply → Ok), the mapper function transforms it into
an input event for the target. The BridgeMode controls delivery guarantees.

Usage:
    audited = order_u.bridge(audit_u, order_to_audit, BridgeMode.ASYNC)

The algebra is closed: BridgedUniverse supports compose() and bridge().
"""

from __future__ import annotations

import time
from typing import Callable, cast

from k3c.errors import K3BridgeError
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import Impossible, K3Result, Ok, Violated
from k3c.universe.compose import Applyable
from k3c.universe.retry import (
    BridgeMode,
    DeadLetterEntry,
    FallbackStrategy,
    RetryPolicy,
)

_State = "dict[str, object]"

# ── Mapper type ──────────────────────────────────────────────────────────────

# Mapper: (source_state, event, new_state) → target_event or None
type BridgeMapper = Callable[
    [dict[str, object], dict[str, object], dict[str, object]],
    dict[str, object] | None,
]


# ── Delivery with retry ────────────────────────────────────────────────────


def _deliver_to_target(
    target: Applyable,
    target_event: dict[str, object],
    retry: RetryPolicy,
) -> K3Result[dict[str, object]]:
    """Attempt delivery to target with retry policy."""
    last_error = ""
    for attempt in range(retry.max_attempts):
        try:
            result = target.apply(target_event)
            if isinstance(result, (Ok, Violated)):
                return result
            if isinstance(result, Impossible):
                # Impossible on target — not retryable
                return result
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

        if attempt < retry.max_attempts - 1 and retry.base_delay_ms > 0:
            if retry.strategy == "fixed":
                time.sleep(retry.base_delay_ms / 1000)
            elif retry.strategy == "exponential":
                time.sleep((retry.base_delay_ms * (2**attempt)) / 1000)

    msg = f"Bridge delivery failed after {retry.max_attempts} attempts: {last_error}"
    raise K3BridgeError(
        source_id="source",
        target_id="target",
        bridge_event=target_event,
        attempts=retry.max_attempts,
        last_reason=last_error or msg,
    )


# ── BridgedUniverse ─────────────────────────────────────────────────────────


class BridgedUniverse:
    """Two Universes connected with <->.

    When source.apply() produces Ok, the mapper transforms the event into
    a target event. Delivery behavior depends on BridgeMode:

        Synchronous: both must succeed or neither does
        Async: source commits first, target receives later
        BestEffort: target delivery is best-effort, failures ignored

    Supports the same apply()/reduce()/compose()/bridge() interface.
    """

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

    def apply(self, event: dict[str, object]) -> K3Result[dict[str, object]]:
        """Apply event to source. On Ok, bridge to target per mode."""
        source_result = self._source.apply(event)

        if not isinstance(source_result, Ok):
            return source_result

        # Map source output to target input
        target_event = self._mapper(
            cast(_State, source_result.state),
            event,
            cast(_State, source_result.state),
        )

        if target_event is None:
            # Mapper chose not to bridge this event
            return source_result

        return self._deliver(source_result, target_event, event)

    def _deliver(
        self,
        source_result: Ok[dict[str, object]],
        target_event: dict[str, object],
        original_event: dict[str, object],
    ) -> K3Result[dict[str, object]]:
        """Deliver to target based on bridge mode."""
        if self._mode == BridgeMode.SYNCHRONOUS:
            return self._deliver_sync(source_result, target_event, original_event)
        if self._mode == BridgeMode.ASYNC:
            return self._deliver_async(source_result, target_event, original_event)
        # BestEffort
        return self._deliver_best_effort(source_result, target_event, original_event)

    def _deliver_sync(
        self,
        source_result: Ok[dict[str, object]],
        target_event: dict[str, object],
        original_event: dict[str, object],
    ) -> K3Result[dict[str, object]]:
        """Synchronous: both succeed or neither does."""
        try:
            target_result = _deliver_to_target(self._target, target_event, self._retry)
        except K3BridgeError:
            return self._handle_delivery_failure(
                source_result, target_event, original_event, "delivery raised"
            )

        if isinstance(target_result, Violated):
            return target_result

        if isinstance(target_result, Impossible):
            return self._handle_delivery_failure(
                source_result, target_event, original_event, "target rejected event"
            )

        return source_result

    def _handle_delivery_failure(
        self,
        source_result: Ok[dict[str, object]],
        target_event: dict[str, object],
        original_event: dict[str, object],
        reason: str,
    ) -> K3Result[dict[str, object]]:
        """Handle a bridge delivery failure based on fallback strategy."""
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
        # IGNORE or DEAD_LETTER — source result stands
        return source_result

    def _deliver_async(
        self,
        source_result: Ok[dict[str, object]],
        target_event: dict[str, object],
        original_event: dict[str, object],
    ) -> K3Result[dict[str, object]]:
        """Async: source commits first. Target receives later.

        Source result is returned immediately. Target delivery happens
        but failures don't affect the source outcome.
        """
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
                        last_error="target rejected event",
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

    def _deliver_best_effort(
        self,
        source_result: Ok[dict[str, object]],
        target_event: dict[str, object],
        original_event: dict[str, object],  # noqa: ARG002
    ) -> K3Result[dict[str, object]]:
        """BestEffort: try once, ignore failures."""
        try:
            self._target.apply(target_event)
        except Exception:  # noqa: BLE001
            pass  # best effort — silently ignore
        return source_result

    def reduce(self, events: list[dict[str, object]]) -> K3Result[dict[str, object]]:
        """Fold events through apply(). Stops on first non-Ok."""
        if not events:
            return Ok(state=self.state, ctx=SpecCtx.initial({}), step_hash="")
        result: K3Result[dict[str, object]] = Ok(
            state=self.state, ctx=SpecCtx.initial({}), step_hash=""
        )
        for event in events:
            result = self.apply(event)
            if not isinstance(result, Ok):
                return result
        return result

    def compose(
        self, other: Applyable, router: Callable[[dict[str, object]], str]
    ) -> object:
        """Compose this bridged universe with another. Algebra is closed."""
        from k3c.universe.compose import ComposedUniverse

        return ComposedUniverse(left=self, right=other, router=router)

    def bridge(
        self,
        target: Applyable,
        mapper: BridgeMapper,
        mode: BridgeMode = BridgeMode.SYNCHRONOUS,
        retry: RetryPolicy | None = None,
        fallback: FallbackStrategy = FallbackStrategy.FAIL,
    ) -> BridgedUniverse:
        """Bridge this to another target. Algebra is closed."""
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
            "source": self._source.state,
            "target": self._target.state,
        }

    def __repr__(self) -> str:
        return f"BridgedUniverse(mode={self._mode}, dead_letters={len(self._dead_letters)})"
