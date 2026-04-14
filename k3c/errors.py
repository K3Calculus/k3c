# K3C Errors
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from k3c.spec.result import Why


class K3Error(Exception):
    """Base for all k3c exceptions. catch K3Error to handle any k3c failure."""


# ── Eval layer ────────────────────────────────────────────────────────────────
class K3NothingException(K3Error):
    """Nothing.raise_() — required field absent from state or event.
    Carries: field (which field), step_hash (which apply() call)."""

    def __init__(self, field: str, step_hash: str) -> None:
        self.field = field
        self.step_hash = step_hash
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Required field {self.field!r} absent step:{self.step_hash[:8]}"


# ── Result layer ──────────────────────────────────────────────────────────────
class K3ViolatedException(K3Error):
    """Violated.raise_() — implementation diverged from spec. This is a bug.
    Carries: why (full Why context — messages, before, after, event, step_hash)."""

    def __init__(self, why: Why) -> None:
        self.why = why
        super().__init__(str(self))

    def __str__(self) -> str:
        return self.why.to_prompt()

    def fingerprint(self) -> str:
        return self.why.fingerprint  # stable dedup key


# ── Construction layer ────────────────────────────────────────────────────────
class K3WellFormednessError(K3Error):
    """Universe construction failed a well-formedness rule.
    The Universe cannot run until this is fixed — not a runtime error."""

    def __init__(self, rule: int, message: str) -> None:
        self.rule = rule
        self.message = message
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Well-formedness rule {self.rule} violated: {self.message}"


# ── Composition layer ─────────────────────────────────────────────────────────
class K3BridgeError(K3Error):
    """Bridge delivery failed after all retries.
    FallbackStrategy=Fail triggered this. Carries full delivery context."""

    def __init__(
        self,
        source_id: str,
        target_id: str,
        bridge_event: dict[str, object],
        attempts: int,
        last_reason: str,
    ) -> None:
        self.source_id = source_id
        self.target_id = target_id
        self.bridge_event = bridge_event
        self.attempts = attempts
        self.last_reason = last_reason
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"Bridge {self.source_id!r} → {self.target_id!r} "
            f"failed after {self.attempts} attempts: {self.last_reason}"
        )


class K3ComposeError(K3Error):
    """Composition failed — incompatible specs, routing error,
    or composite state inconsistency."""

    def __init__(self, left_id: str, right_id: str, message: str) -> None:
        self.left_id = left_id
        self.right_id = right_id
        self.message = message
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Compose {self.left_id!r} <||> {self.right_id!r}: {self.message}"


# ── Schema / spec layer ───────────────────────────────────────────────────────
class K3SchemaError(K3Error):
    """k3l_ir JSON failed schema validation.
    Raised by load() when the spec file is malformed."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Schema error at {self.path!r}: {self.message}"


class K3SerdeError(K3Error):
    """Serialization / deserialization error.
    Raised by serde.py when a k3l node cannot be round-tripped."""

    def __init__(self, node: str, message: str) -> None:
        self.node = node
        self.message = message
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"Serde error on {self.node!r}: {self.message}"
