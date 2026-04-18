"""Tests for hardened attestation: tamper detection, JSON discipline,
EmbeddedUniverse simulate."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

import pytest

from k3c import (
    AttestationBundle,
    EmbeddedRuntime,
    HmacSigner,
    LBool,
    Permit,
    S,
    Spec,
    Universe,
    k3,
    verify_bundle,
)


def _counter_spec():
    return Spec(
        name="counter",
        state0={"count": 0},
        permits=(Permit(name="ok", when=k3(S.count >= 0)),),
    )


def _counter_t(state, event):
    return {**state, "count": state["count"] + 1}


def _bundle_for(events, signer):
    spec = _counter_spec()
    u = Universe(spec=spec, transition=_counter_t)
    run = u.simulate(events)
    return AttestationBundle.from_run(run, signer=signer)


class TestTamperDetection:
    """Every tamper mode must invalidate the bundle."""

    def test_clean_bundle_valid(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for(
            [{"type": "Inc"}, {"type": "Inc"}, {"type": "Inc"}], signer
        )
        result = verify_bundle(bundle, verifier=signer)
        assert result.valid
        assert result.steps_verified == 3

    def test_state_after_tamper_caught(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}, {"type": "Inc"}, {"type": "Inc"}], signer)

        steps = list(bundle.steps)
        steps[1] = dataclasses.replace(steps[1], state_after={"count": 999})
        tampered = dataclasses.replace(bundle, steps=tuple(steps))

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid
        assert result.first_invalid_step is not None

    def test_state_before_tamper_caught(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}, {"type": "Inc"}, {"type": "Inc"}], signer)

        steps = list(bundle.steps)
        steps[1] = dataclasses.replace(steps[1], state_before={"count": 999})
        tampered = dataclasses.replace(bundle, steps=tuple(steps))

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid
        assert result.failure_kind == "content"

    def test_event_tamper_caught(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}, {"type": "Inc"}, {"type": "Inc"}], signer)

        steps = list(bundle.steps)
        steps[1] = dataclasses.replace(steps[1], event={"type": "EvilEvent"})
        tampered = dataclasses.replace(bundle, steps=tuple(steps))

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid
        assert result.failure_kind == "content"

    def test_signature_tamper_caught(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}, {"type": "Inc"}], signer)

        steps = list(bundle.steps)
        steps[0] = dataclasses.replace(steps[0], signature="AAAA")
        tampered = dataclasses.replace(bundle, steps=tuple(steps))

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid
        assert result.failure_kind == "signature"

    def test_step_hash_tamper_caught(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}, {"type": "Inc"}], signer)

        steps = list(bundle.steps)
        steps[1] = dataclasses.replace(steps[1], step_hash="deadbeef" * 8)
        tampered = dataclasses.replace(bundle, steps=tuple(steps))

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid

    def test_result_kind_tamper_caught(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}, {"type": "Inc"}], signer)

        steps = list(bundle.steps)
        steps[0] = dataclasses.replace(steps[0], result_kind="impossible")
        tampered = dataclasses.replace(bundle, steps=tuple(steps))

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid
        assert result.failure_kind == "signature"

    def test_chain_break_caught(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}, {"type": "Inc"}], signer)

        steps = list(bundle.steps)
        steps[1] = dataclasses.replace(steps[1], prev_step_hash="bogus")
        tampered = dataclasses.replace(bundle, steps=tuple(steps))

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid
        assert result.failure_kind == "content"

    def test_initial_state_tamper_caught(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}], signer)
        tampered = dataclasses.replace(bundle, initial_state={"count": 999})

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid


class TestJsonDiscipline:
    def test_opaque_dataclass_in_state_rejected(self):
        @dataclass
        class Opaque:
            x: int

        spec = Spec(
            name="opaque",
            state0={"count": 0},
            permits=(Permit(name="ok", when=LBool(True)),),
        )
        u = Universe(
            spec=spec,
            transition=lambda s, e: {**s, "obj": Opaque(1), "count": s["count"] + 1},
            validate=False,
        )
        run = u.simulate([{"type": "X"}])
        signer = HmacSigner(key=b"k", key_id="kid")
        with pytest.raises(ValueError, match="Non-JSON-primitive"):
            AttestationBundle.from_run(run, signer=signer)

    def test_opaque_in_event_rejected(self):
        # Event with opaque value reaches state via transition
        @dataclass
        class Foo:
            v: int

        spec = Spec(
            name="x",
            state0={"a": 0},
            permits=(Permit(name="ok", when=LBool(True)),),
        )

        def t(s, e):
            return {**s, "from_event": e.get("payload"), "a": s["a"] + 1}

        u = Universe(spec=spec, transition=t, validate=False)
        run = u.simulate([{"type": "X", "payload": Foo(1)}])
        signer = HmacSigner(key=b"k", key_id="kid")
        with pytest.raises(ValueError, match="Non-JSON-primitive"):
            AttestationBundle.from_run(run, signer=signer)

    def test_clean_state_passes(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}], signer)
        # to_json must succeed
        j = bundle.to_json()
        assert json.loads(j)["bundle_version"] >= 2


class TestJsonRoundTrip:
    def test_full_round_trip(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for(
            [{"type": "Inc"}, {"type": "Inc"}, {"type": "Inc"}], signer
        )
        json_str = bundle.to_json()
        restored = AttestationBundle.from_dict(json.loads(json_str))
        assert verify_bundle(restored, verifier=signer).valid

    def test_round_trip_preserves_result_kind(self):
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = _bundle_for([{"type": "Inc"}], signer)
        restored = AttestationBundle.from_dict(json.loads(bundle.to_json()))
        assert restored.steps[0].result_kind == "ok"


class TestEmbeddedSimulate:
    def test_embedded_universe_has_simulate(self):
        spec = _counter_spec()
        runtime = EmbeddedRuntime(spec=spec, transition=_counter_t)
        u = runtime.universe()
        assert hasattr(u, "simulate")
        assert hasattr(u, "replay")
        assert hasattr(u, "get")

    def test_simulate_produces_attestable_run(self):
        spec = _counter_spec()
        runtime = EmbeddedRuntime(
            spec=spec,
            transition=_counter_t,
            projection_hooks={"is_even": lambda s, e, ctx: s["count"] % 2 == 0},
        )
        u = runtime.universe()
        run = u.simulate([{"type": "Inc"}, {"type": "Inc"}, {"type": "Inc"}])
        assert run.processed == 3

        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = AttestationBundle.from_run(run, signer=signer)
        assert verify_bundle(bundle, verifier=signer).valid

    def test_get_field(self):
        spec = _counter_spec()
        runtime = EmbeddedRuntime(spec=spec, transition=_counter_t)
        u = runtime.universe()
        u.apply({"type": "Inc"})
        u.apply({"type": "Inc"})
        assert u.get("count") == 2
        assert u.get("missing", default=42) == 42

    def test_replay(self):
        spec = _counter_spec()
        runtime = EmbeddedRuntime(spec=spec, transition=_counter_t)
        u = runtime.universe()
        events = [{"type": "Inc"}, {"type": "Inc"}]
        run = u.simulate(events)
        replay = u.replay(events, expected_hashes=run.step_hashes)
        assert replay.matched
