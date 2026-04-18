"""12 — Keyed Attestation (KC-6)

Sign every step with HMAC, build a portable bundle, and verify it later.

Demonstrates:
- HmacSigner (stdlib, no extra deps) — Ed25519Signer also available
- AttestationBundle.from_run(run, signer=...)
- Two-layer verify_bundle:
    1. Content integrity — recompute step_hash from inputs
    2. Authenticity — verify signature over canonical payload
- JSON wire format round-trip
- Tamper detection
"""

from __future__ import annotations

import dataclasses
import json

from k3c import (
    AttestationBundle,
    HmacSigner,
    Permit,
    S,
    Spec,
    Universe,
    k3,
    verify_bundle,
)


def main() -> None:
    spec = Spec(
        name="counter",
        state0={"count": 0},
        permits=(Permit(name="ok", when=k3(S.count >= 0)),),
    )
    u = Universe(spec=spec, transition=lambda s, e: {**s, "count": s["count"] + 1})

    # 1. Run a simulation that we want to attest
    run = u.simulate([{"type": "Inc"}, {"type": "Inc"}, {"type": "Inc"}])
    print(f"Simulated {run.processed} steps, final={run.final_state}")

    # 2. Build a signed bundle
    signer = HmacSigner(key=b"production-secret-2026", key_id="prod-2026")
    bundle = AttestationBundle.from_run(run, signer=signer)
    print(f"Bundle: {len(bundle.steps)} signed steps, algorithm={bundle.algorithm}")

    # 3. Serialize for the wire
    json_str = bundle.to_json()
    print(f"JSON wire format: {len(json_str)} bytes")

    # 4. Deserialize and verify (typically on a different host with shared key)
    received = AttestationBundle.from_dict(json.loads(json_str))
    result = verify_bundle(received, verifier=signer)
    print(f"\nClean bundle verify: valid={result.valid}, steps_verified={result.steps_verified}")

    # 5. Tamper detection — every mode is caught
    print("\n== Tamper detection ==")

    def tamper(field: str, value: object) -> AttestationBundle:
        steps = list(received.steps)
        steps[1] = dataclasses.replace(steps[1], **{field: value})
        return dataclasses.replace(received, steps=tuple(steps))

    for field, value in [
        ("event",        {"type": "EvilEvent"}),
        ("state_after",  {"count": 999}),
        ("state_before", {"count": 999}),
        ("signature",    "AAAA"),
        ("step_hash",    "deadbeef" * 8),
    ]:
        r = verify_bundle(tamper(field, value), verifier=signer)
        print(f"  {field:14s}  valid={r.valid}  kind={r.failure_kind}  step={r.first_invalid_step}")


if __name__ == "__main__":
    main()
