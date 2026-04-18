# k3c/attest.py
"""
Keyed attestation for KC-6 — sign each step with HMAC or Ed25519.

A plain hash chain proves internal consistency. A signed chain proves *who*
signed it. KC-6 (regulatory-grade audit) requires keyed attestation.

Two-layer verification:

1. **Content integrity** — recompute every step_hash from the custody inputs
   (prev_step_hash, state_before, event) and verify it matches the recorded hash.
   Catches tampering with `event` or `state_before` even if the signature is
   replaced. Catches tampering with `state_after` because it becomes
   `state_before` for the next step.

2. **Authenticity** — verify the signature over the canonical step payload
   (event, state_after, step_hash). Catches signature forgery.

Usage:
    from k3c import Universe, HmacSigner, AttestationBundle, verify_bundle

    signer = HmacSigner(key=b"secret-key-bytes", key_id="prod-2026")

    u = Universe(spec=spec, transition=fn)
    run = u.simulate(events)

    bundle = AttestationBundle.from_run(run, signer=signer)

    # Verify (typically with a separate verifier instance using same key/key_id)
    result = verify_bundle(bundle, verifier=signer)
    assert result.valid
"""

from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from k3c.engine.step import compute_step_hash
from k3c.json import dumps as _json_dumps

if TYPE_CHECKING:
    from k3c.runtime.samsara import RunResult


# -- Signer protocol -----------------------------------------------------------


class Signer(Protocol):
    """Protocol for step signers.

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


# -- JSON-primitive discipline -------------------------------------------------


_JSON_PRIMITIVES = (str, int, float, bool, type(None))


def _ensure_json_safe(value: object, path: str = "") -> object:
    """Recursively check that a value is composed of JSON primitives.

    Raises ValueError on first non-JSON-safe value, naming the offending path.
    Returns the value unchanged if safe.
    """
    if isinstance(value, _JSON_PRIMITIVES):
        return value
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                msg = f"Non-string dict key at {path or '<root>'}: {type(k).__name__}"
                raise ValueError(msg)
            _ensure_json_safe(v, f"{path}.{k}" if path else k)
        return value
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _ensure_json_safe(v, f"{path}[{i}]")
        return value
    msg = (
        f"Non-JSON-primitive value at {path or '<root>'}: {type(value).__name__}. "
        "Attestation requires state and event values to be JSON primitives "
        "(str, int, float, bool, None, list/dict thereof). Convert dataclasses "
        "or domain objects to dicts before applying events."
    )
    raise ValueError(msg)


# -- AttestationBundle ---------------------------------------------------------


# Bundle wire format version. Bump when the canonical encoding changes.
BUNDLE_VERSION = 2


@dataclass(frozen=True)
class SignedStep:
    """A single signed step record.

    All fields except signature must be JSON-safe (str/int/float/bool/None or
    list/dict thereof). The signature is base64-encoded raw signature bytes.

    state_before is recorded explicitly so verification can re-derive step_hash
    independently of the chain. (For step 0, state_before == bundle.initial_state.)

    result_kind drives chain advancement: "ok"/"violated" advance prev_step_hash,
    "impossible" leaves it unchanged (matching engine semantics).
    """

    t: int
    event: dict[str, object]
    state_before: dict[str, object]
    state_after: dict[str, object]
    prev_step_hash: str
    step_hash: str
    result_kind: str  # "ok" | "impossible" | "violated"
    signature: str  # base64-encoded


@dataclass(frozen=True)
class AttestationBundle:
    """A signed trace — verifiable by anyone with the verifier.

    spec_name: the spec the run was executed against
    universe_id: optional universe identifier
    bundle_version: wire format version
    algorithm: signing algorithm (hmac-sha256, ed25519, ...)
    hash_fn: step_hash algorithm (sha256, blake2b, blake3) — required to recompute hashes
    key_id: which key was used
    initial_state: state before any events were applied (== steps[0].state_before)
    initial_step_hash: starting hash for the chain (typically "")
    steps: ordered tuple of signed steps
    metadata: arbitrary key-value annotations (must be JSON-safe)
    """

    spec_name: str
    universe_id: str
    algorithm: str
    hash_fn: str
    key_id: str
    initial_state: dict[str, object]
    initial_step_hash: str
    steps: tuple[SignedStep, ...]
    bundle_version: int = BUNDLE_VERSION
    metadata: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def from_run(
        run: RunResult,
        *,
        signer: Signer,
        spec_name: str = "",
        universe_id: str = "",
        hash_fn: str = "sha256",
        metadata: dict[str, object] | None = None,
    ) -> AttestationBundle:
        """Build a signed bundle from a Samsara RunResult.

        State and event values must be JSON primitives. Raises ValueError
        with the offending path if any value is opaque (dataclass, custom class).

        hash_fn must match the hash_fn used to produce the run.
        """
        meta = metadata or {}
        _ensure_json_safe(meta, "metadata")

        # Initial state = state_before of the very first step (NOT trajectory[0]
        # which is the state AFTER step 0).
        if run.traces:
            initial_state = run.traces[0].state_before
        else:
            initial_state = {}
        _ensure_json_safe(initial_state, "initial_state")

        signed_steps: list[SignedStep] = []
        prev_hash = ""

        for t, rec in enumerate(run.traces):
            state_before = rec.state_before
            # state_after is None for Impossible — state didn't change
            state_after = rec.state_after if rec.state_after is not None else state_before

            _ensure_json_safe(rec.event, f"steps[{t}].event")
            _ensure_json_safe(state_before, f"steps[{t}].state_before")
            _ensure_json_safe(state_after, f"steps[{t}].state_after")

            payload = _signature_payload(
                event=rec.event,
                state_after=state_after,
                step_hash=rec.step_hash,
                result_kind=rec.result_kind,
            )
            sig = signer.sign(payload)
            signed_steps.append(
                SignedStep(
                    t=t,
                    event=rec.event,
                    state_before=state_before,
                    state_after=state_after,
                    prev_step_hash=prev_hash,
                    step_hash=rec.step_hash,
                    result_kind=rec.result_kind,
                    signature=base64.b64encode(sig).decode("ascii"),
                )
            )
            # Engine advances ctx.prev_step_hash only on Ok. Impossible/Violated
            # leave the chain unchanged. Mirror that here.
            if rec.result_kind == "ok":
                prev_hash = rec.step_hash

        return AttestationBundle(
            spec_name=spec_name,
            universe_id=universe_id,
            algorithm=signer.algorithm,
            hash_fn=hash_fn,
            key_id=signer.key_id,
            initial_state=initial_state,
            initial_step_hash="",
            steps=tuple(signed_steps),
            metadata=meta,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_version": self.bundle_version,
            "spec_name": self.spec_name,
            "universe_id": self.universe_id,
            "algorithm": self.algorithm,
            "hash_fn": self.hash_fn,
            "key_id": self.key_id,
            "initial_state": self.initial_state,
            "initial_step_hash": self.initial_step_hash,
            "steps": [
                {
                    "t": s.t,
                    "event": s.event,
                    "state_before": s.state_before,
                    "state_after": s.state_after,
                    "prev_step_hash": s.prev_step_hash,
                    "step_hash": s.step_hash,
                    "result_kind": s.result_kind,
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
                state_before=s.get("state_before", {}),  # type: ignore[arg-type,union-attr]
                state_after=s["state_after"],  # type: ignore[arg-type]
                prev_step_hash=str(s.get("prev_step_hash", "")),
                step_hash=str(s["step_hash"]),
                result_kind=str(s.get("result_kind", "ok")),
                signature=str(s["signature"]),
            )
            for s in steps_raw  # type: ignore[union-attr]
        )
        return AttestationBundle(
            bundle_version=int(data.get("bundle_version", 1)),  # type: ignore[arg-type]
            spec_name=str(data.get("spec_name", "")),
            universe_id=str(data.get("universe_id", "")),
            algorithm=str(data["algorithm"]),
            hash_fn=str(data.get("hash_fn", "sha256")),
            key_id=str(data["key_id"]),
            initial_state=data.get("initial_state", {}),  # type: ignore[arg-type]
            initial_step_hash=str(data.get("initial_step_hash", "")),
            steps=steps,
            metadata=data.get("metadata", {}),  # type: ignore[arg-type]
        )

    def to_json(self) -> str:
        # _ensure_json_safe was called at construction time; safe to dump.
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


# -- Verification --------------------------------------------------------------


@dataclass(frozen=True)
class VerifyResult:
    """Result of verifying an AttestationBundle.

    valid: True iff every step passed both content integrity and signature checks
    steps_verified: number of steps fully verified before failure (or total if valid)
    first_invalid_step: index of the first step that failed (None if valid)
    failure_kind: one of "algorithm", "key_id", "content", "signature", "" (if valid)
    reason: human-readable failure description
    """

    valid: bool
    steps_verified: int
    first_invalid_step: int | None = None
    failure_kind: str = ""
    reason: str = ""


def verify_bundle(
    bundle: AttestationBundle, *, verifier: Signer
) -> VerifyResult:
    """Verify every step in a bundle — content integrity AND authenticity.

    Two-layer check per step:
      1. Recompute step_hash from (prev_step_hash, state_before, event) using
         the bundle's hash_fn. Compare against recorded step_hash.
      2. Verify the signature over canonical (event, state_after, step_hash).

    Also enforces chain continuity: each step's prev_step_hash must equal the
    previous step's step_hash, starting from initial_step_hash.
    """
    if bundle.algorithm != verifier.algorithm:
        return VerifyResult(
            valid=False,
            steps_verified=0,
            failure_kind="algorithm",
            reason=f"algorithm mismatch: bundle={bundle.algorithm}, verifier={verifier.algorithm}",
        )
    if bundle.key_id != verifier.key_id:
        return VerifyResult(
            valid=False,
            steps_verified=0,
            failure_kind="key_id",
            reason=f"key_id mismatch: bundle={bundle.key_id}, verifier={verifier.key_id}",
        )

    expected_prev_hash = bundle.initial_step_hash
    expected_state_before = bundle.initial_state

    for step in bundle.steps:
        # 0. Chain continuity
        if step.prev_step_hash != expected_prev_hash:
            return VerifyResult(
                valid=False,
                steps_verified=step.t,
                first_invalid_step=step.t,
                failure_kind="content",
                reason=(
                    f"chain break at step {step.t}: prev_step_hash="
                    f"{step.prev_step_hash!r}, expected={expected_prev_hash!r}"
                ),
            )

        # 0b. Implicit chain continuity for state_before
        if step.state_before != expected_state_before:
            return VerifyResult(
                valid=False,
                steps_verified=step.t,
                first_invalid_step=step.t,
                failure_kind="content",
                reason=(
                    f"state chain break at step {step.t}: state_before does not "
                    "match previous step's state_after (or initial_state)"
                ),
            )

        # 1. Recompute step_hash from custody inputs
        recomputed = compute_step_hash(
            step.state_before,
            step.event,
            step.prev_step_hash,
            bundle.hash_fn,
        )
        if recomputed != step.step_hash:
            return VerifyResult(
                valid=False,
                steps_verified=step.t,
                first_invalid_step=step.t,
                failure_kind="content",
                reason=(
                    f"step_hash mismatch at step {step.t}: "
                    f"recomputed={recomputed[:16]}..., recorded={step.step_hash[:16]}... "
                    "(event or state_before tampered)"
                ),
            )

        # 2. Verify signature over canonical (event, state_after, step_hash)
        try:
            sig = base64.b64decode(step.signature)
        except Exception:  # noqa: BLE001
            return VerifyResult(
                valid=False,
                steps_verified=step.t,
                first_invalid_step=step.t,
                failure_kind="signature",
                reason=f"signature is not valid base64 at step {step.t}",
            )

        payload = _signature_payload(
            event=step.event,
            state_after=step.state_after,
            step_hash=step.step_hash,
            result_kind=step.result_kind,
        )
        if not verifier.verify(payload, sig):
            return VerifyResult(
                valid=False,
                steps_verified=step.t,
                first_invalid_step=step.t,
                failure_kind="signature",
                reason=(
                    f"signature verification failed at step {step.t} "
                    "(signature, state_after, event, step_hash, or result_kind tampered)"
                ),
            )

        # Engine semantics: only Ok advances ctx.prev_step_hash.
        if step.result_kind == "ok":
            expected_prev_hash = step.step_hash
            expected_state_before = step.state_after
        # Impossible/Violated: chain unchanged, state unchanged (state_after == state_before)

    return VerifyResult(valid=True, steps_verified=len(bundle.steps))


def _signature_payload(
    *,
    event: dict[str, object],
    state_after: dict[str, object],
    step_hash: str,
    result_kind: str,
) -> bytes:
    """Canonical bytes-to-sign for a step.

    Includes (event, state_after, step_hash, result_kind) so tampering with
    any of them invalidates the signature even if the recomputed step_hash
    chain still passes (e.g., when only state_after is changed at the final
    step, or when result_kind is flipped to fake a successful outcome).
    """
    return _json_dumps({
        "event": event,
        "state_after": state_after,
        "step_hash": step_hash,
        "result_kind": result_kind,
    })
