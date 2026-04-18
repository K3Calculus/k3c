# k3c/attest.py
"""
Keyed attestation for KC-6 — sign each step_hash with HMAC or Ed25519.

A plain hash chain proves internal consistency. A signed chain proves *who*
signed it. KC-6 (regulatory-grade audit) requires keyed attestation.

Usage:
    from k3c import Universe, HmacSigner, AttestationBundle, verify_bundle

    signer = HmacSigner(key=b"secret-key-bytes", key_id="prod-2026")

    u = Universe(spec=spec, transition=fn, signer=signer)
    run = u.simulate(events)

    # Build a verifiable bundle
    bundle = AttestationBundle.from_run(run, signer=signer)

    # Later, verify it
    result = verify_bundle(bundle, verifier=signer)
    assert result.valid
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from k3c.runtime.samsara import RunResult


# -- Signer protocol -----------------------------------------------------------


class Signer(Protocol):
    """Protocol for step_hash signers.

    Implementations: HmacSigner, Ed25519Signer.
    """

    @property
    def algorithm(self) -> str: ...

    @property
    def key_id(self) -> str: ...

    def sign(self, payload: bytes) -> bytes: ...

    def verify(self, payload: bytes, signature: bytes) -> bool: ...


# -- HMAC signer (stdlib) ------------------------------------------------------


@dataclass(frozen=True)
class HmacSigner:
    """HMAC-SHA256 signer using a shared secret.

    key: secret key bytes
    key_id: identifier for the key (for rotation, audit)
    digest: hash digest name (default sha256)
    """

    key: bytes
    key_id: str = "default"
    digest: str = "sha256"

    @property
    def algorithm(self) -> str:
        return f"hmac-{self.digest}"

    def sign(self, payload: bytes) -> bytes:
        return hmac.new(self.key, payload, self.digest).digest()

    def verify(self, payload: bytes, signature: bytes) -> bool:
        expected = self.sign(payload)
        return hmac.compare_digest(expected, signature)


# -- Ed25519 signer (optional, requires cryptography) -------------------------


@dataclass(frozen=True)
class Ed25519Signer:
    """Ed25519 signer using a private key.

    Requires `pip install cryptography`.

    key: 32-byte private key seed
    key_id: identifier for the key
    """

    key: bytes
    key_id: str = "default"

    @property
    def algorithm(self) -> str:
        return "ed25519"

    def _private(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
        except ImportError as exc:
            msg = "Ed25519Signer requires: pip install cryptography"
            raise ImportError(msg) from exc
        return Ed25519PrivateKey.from_private_bytes(self.key)

    def _public(self):
        return self._private().public_key()

    def sign(self, payload: bytes) -> bytes:
        return self._private().sign(payload)

    def verify(self, payload: bytes, signature: bytes) -> bool:
        try:
            self._public().verify(signature, payload)
        except Exception:  # noqa: BLE001
            return False
        return True


# -- AttestationBundle ---------------------------------------------------------


@dataclass(frozen=True)
class SignedStep:
    """A single signed step record."""

    t: int
    event: dict[str, object]
    state_after: dict[str, object]
    step_hash: str
    signature: str  # base64-encoded


@dataclass(frozen=True)
class AttestationBundle:
    """A signed trace — verifiable by anyone with the verifier.

    spec_name: the spec the run was executed against
    universe_id: optional universe identifier
    algorithm: signing algorithm (hmac-sha256, ed25519, ...)
    key_id: which key was used
    initial_state: state before any events were applied
    steps: ordered tuple of signed steps
    metadata: arbitrary key-value annotations (e.g. {"region": "us-east-1"})
    """

    spec_name: str
    universe_id: str
    algorithm: str
    key_id: str
    initial_state: dict[str, object]
    steps: tuple[SignedStep, ...]
    metadata: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def from_run(run: RunResult, *, signer: Signer, universe_id: str = "") -> AttestationBundle:
        """Build a signed bundle from a Samsara RunResult."""
        signed_steps: list[SignedStep] = []
        for t, rec in enumerate(run.traces):
            payload = _payload_for(rec.step_hash)
            sig = signer.sign(payload)
            signed_steps.append(
                SignedStep(
                    t=t,
                    event=rec.event,
                    state_after=rec.state_after or {},
                    step_hash=rec.step_hash,
                    signature=base64.b64encode(sig).decode("ascii"),
                )
            )
        return AttestationBundle(
            spec_name="",
            universe_id=universe_id,
            algorithm=signer.algorithm,
            key_id=signer.key_id,
            initial_state=run.trajectory[0] if run.trajectory else {},
            steps=tuple(signed_steps),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "spec_name": self.spec_name,
            "universe_id": self.universe_id,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "initial_state": self.initial_state,
            "steps": [
                {
                    "t": s.t,
                    "event": s.event,
                    "state_after": s.state_after,
                    "step_hash": s.step_hash,
                    "signature": s.signature,
                }
                for s in self.steps
            ],
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> AttestationBundle:
        steps_raw = data.get("steps", [])
        steps = tuple(
            SignedStep(
                t=int(s["t"]),  # type: ignore[arg-type]
                event=s["event"],  # type: ignore[arg-type]
                state_after=s["state_after"],  # type: ignore[arg-type]
                step_hash=str(s["step_hash"]),
                signature=str(s["signature"]),
            )
            for s in steps_raw  # type: ignore[union-attr]
        )
        return AttestationBundle(
            spec_name=str(data.get("spec_name", "")),
            universe_id=str(data.get("universe_id", "")),
            algorithm=str(data["algorithm"]),
            key_id=str(data["key_id"]),
            initial_state=data.get("initial_state", {}),  # type: ignore[arg-type]
            steps=steps,
            metadata=data.get("metadata", {}),  # type: ignore[arg-type]
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


# -- Verification --------------------------------------------------------------


@dataclass(frozen=True)
class VerifyResult:
    """Result of verifying an AttestationBundle."""

    valid: bool
    steps_verified: int
    first_invalid_step: int | None = None
    reason: str = ""


def verify_bundle(
    bundle: AttestationBundle, *, verifier: Signer
) -> VerifyResult:
    """Verify every signed step in a bundle.

    Checks:
      - Each signature matches its step_hash under the verifier
      - The algorithm/key_id in the bundle matches the verifier
    """
    if bundle.algorithm != verifier.algorithm:
        return VerifyResult(
            valid=False,
            steps_verified=0,
            reason=f"algorithm mismatch: bundle={bundle.algorithm}, verifier={verifier.algorithm}",
        )
    if bundle.key_id != verifier.key_id:
        return VerifyResult(
            valid=False,
            steps_verified=0,
            reason=f"key_id mismatch: bundle={bundle.key_id}, verifier={verifier.key_id}",
        )

    for step in bundle.steps:
        try:
            sig = base64.b64decode(step.signature)
        except Exception:  # noqa: BLE001
            return VerifyResult(
                valid=False,
                steps_verified=step.t,
                first_invalid_step=step.t,
                reason="signature is not valid base64",
            )

        payload = _payload_for(step.step_hash)
        if not verifier.verify(payload, sig):
            return VerifyResult(
                valid=False,
                steps_verified=step.t,
                first_invalid_step=step.t,
                reason=f"signature verification failed at step {step.t}",
            )

    return VerifyResult(valid=True, steps_verified=len(bundle.steps))


def _payload_for(step_hash: str) -> bytes:
    """Canonical bytes-to-sign for a step_hash."""
    return step_hash.encode("ascii")
