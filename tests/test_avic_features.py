"""Tests for avic-feedback features: sugar, Protocol, denied, attestation,
compose_many, Pipeline, Migration, sub-expression diagnostics."""

from __future__ import annotations

import dataclasses
import json

import pytest

from k3c import (
    AttestationBundle,
    Concat,
    E,
    EventDef,
    Field,
    FieldDef,
    HmacSigner,
    LStr,
    Maintain,
    Migration,
    Permit,
    Pipeline,
    Protocol,
    S,
    Spec,
    Universe,
    Validate,
    Var,
    Violated,
    With,
    all_of,
    any_of,
    compose_many,
    expr_from_dict,
    expr_to_dict,
    k3,
    spec_from_dict,
    spec_to_dict,
    verify_bundle,
)
from k3c.engine.result import Impossible, Ok
from k3c.ir.expr import LInt
from k3c.ir.types import TInt


# -- #3 IR Sugar --------------------------------------------------------------


class TestSugar:
    def test_basic_comparison(self):
        spec = Spec(
            name="bank",
            state0={"balance": 100},
            permits=(
                Permit(name="has_funds", on="W", when=k3(S.balance >= E.amount)),
            ),
        )
        u = Universe(
            spec=spec, transition=lambda s, e: {**s, "balance": s["balance"] - e["amount"]}
        )
        assert isinstance(u.apply({"type": "W", "amount": 50}), Ok)
        assert isinstance(u.apply({"type": "W", "amount": 200}), Impossible)

    def test_logical_combinators(self):
        spec = Spec(
            name="bank",
            state0={"balance": 100, "status": "active"},
            permits=(
                Permit(
                    name="ok",
                    on="W",
                    when=k3((S.balance >= E.amount) & (S.status == "active")),
                ),
            ),
        )
        u = Universe(spec=spec, transition=lambda s, e: s)
        assert isinstance(u.apply({"type": "W", "amount": 50}), Ok)

    def test_in_membership(self):
        spec = Spec(
            name="status",
            state0={"phase": "idle"},
            permits=(
                Permit(name="ok", when=k3(S.phase.in_("idle", "active", "done"))),
            ),
        )
        u = Universe(spec=spec, transition=lambda s, e: s)
        assert isinstance(u.apply({"type": "X"}), Ok)

    def test_arithmetic(self):
        spec = Spec(
            name="calc",
            state0={"x": 10, "y": 5},
            permits=(Permit(name="ok", when=k3((S.x + S.y) > 0)),),
        )
        u = Universe(spec=spec, transition=lambda s, e: s)
        assert isinstance(u.apply({"type": "X"}), Ok)

    def test_all_of_any_of(self):
        spec = Spec(
            name="multi",
            state0={"a": 1, "b": 2, "c": 3},
            permits=(Permit(name="ok", when=k3(all_of(S.a > 0, S.b > 0, S.c > 0))),),
        )
        u = Universe(spec=spec, transition=lambda s, e: s)
        assert isinstance(u.apply({"type": "X"}), Ok)

    def test_q_bool_misuse_raises(self):
        with pytest.raises(TypeError, match="cannot be used as Python bools"):
            bool(S.balance >= 0)


# -- EventDef -----------------------------------------------------------------


class TestEventDef:
    def test_event_def_in_spec(self):
        spec = Spec(
            name="events",
            state0={"x": 0},
            events=(
                EventDef(
                    name="Withdraw",
                    fields=(FieldDef(name="amount", type=TInt()),),
                    description="Withdraw funds",
                ),
            ),
            permits=(Permit(name="ok", when=k3(S.x >= 0)),),
        )
        assert spec.events[0].name == "Withdraw"
        assert spec.events[0].fields[0].name == "amount"

    def test_event_def_round_trip(self):
        spec = Spec(
            name="events",
            state0={"x": 0},
            events=(EventDef(name="A", fields=(FieldDef(name="n", type=TInt()),)),),
        )
        d = spec_to_dict(spec)
        restored = spec_from_dict(d)
        assert restored.events[0].name == "A"
        assert restored.events[0].fields[0].name == "n"


# -- #7 Protocol DSL ----------------------------------------------------------


class TestProtocol:
    def _proto(self):
        return Protocol(
            name="order",
            state_field="status",
            states=("received", "classifying", "extracting", "committed"),
            transitions=(
                ("received", "CLASSIFY", "classifying"),
                ("classifying", "EXTRACT", "extracting"),
                ("extracting", "COMMIT", "committed"),
            ),
        )

    def test_event_types(self):
        proto = self._proto()
        assert proto.event_types() == ("CLASSIFY", "EXTRACT", "COMMIT")

    def test_event_defs_generated(self):
        proto = self._proto()
        defs = proto.event_defs()
        assert len(defs) == 3
        assert {d.name for d in defs} == {"CLASSIFY", "EXTRACT", "COMMIT"}

    def test_permits_generated(self):
        proto = self._proto()
        permits = proto.permits()
        assert len(permits) == 3
        names = {p.name for p in permits}
        assert "order__received_to_classifying" in names

    def test_full_protocol_run(self):
        proto = self._proto()
        table = proto.transition_table()

        def t(state, event):
            new = table.get((state["status"], event["type"]))
            if new:
                return {**state, "status": new}
            return state

        spec = Spec(
            name="order_proc",
            state0={"status": "received"},
            events=proto.event_defs(),
            permits=proto.permits(),
            maintains=proto.maintains(),
        )
        u = Universe(spec=spec, transition=t)

        assert isinstance(u.apply({"type": "CLASSIFY"}), Ok)
        assert u.get("status") == "classifying"
        # Wrong order
        assert isinstance(u.apply({"type": "COMMIT"}), Impossible)
        # Continue
        assert isinstance(u.apply({"type": "EXTRACT"}), Ok)
        assert isinstance(u.apply({"type": "COMMIT"}), Ok)
        assert u.get("status") == "committed"

    def test_unknown_state_raises(self):
        with pytest.raises(ValueError, match="unknown state"):
            Protocol(
                name="bad",
                state_field="x",
                states=("a", "b"),
                transitions=(("a", "EVT", "c"),),  # c not declared
            )


# -- #4 denied= ----------------------------------------------------------------


class TestDenied:
    def test_permit_denied_message(self):
        spec = Spec(
            name="order",
            state0={"stage": "RECEIVED"},
            permits=(
                Permit(
                    name="can_classify",
                    on="CLASSIFY",
                    when=k3(S.stage == "COMMITTED"),  # always false for fresh state
                    denied=Concat(
                        Concat(LStr("stage is "), Field(Var("state"), "stage")),
                        LStr(", expected COMMITTED"),
                    ),
                ),
            ),
        )
        u = Universe(spec=spec, transition=lambda s, e: s)
        r = u.apply({"type": "CLASSIFY"})
        assert isinstance(r, Impossible)
        assert "stage is RECEIVED" in r.why.message

    def test_validate_denied_message(self):
        spec = Spec(
            name="v",
            state0={"x": 0},
            permits=(Permit(name="ok", when=k3(S.x >= 0)),),
            validates=(
                Validate(
                    name="amount_check",
                    on="W",
                    check=k3(E.amount > 100),
                    denied=Concat(LStr("amount too small: "), LStr("got value")),
                ),
            ),
        )
        u = Universe(spec=spec, transition=lambda s, e: s)
        r = u.apply({"type": "W", "amount": 5})
        assert isinstance(r, Violated)
        assert "amount too small" in r.why.message


# -- #1 Keyed Attestation ----------------------------------------------------


class TestAttestation:
    def test_hmac_sign_verify(self):
        signer = HmacSigner(key=b"secret", key_id="k1")
        payload = b"step_hash_abc"
        sig = signer.sign(payload)
        assert signer.verify(payload, sig)
        assert not signer.verify(b"tampered", sig)

    def test_bundle_round_trip(self):
        spec = Spec(
            name="counter",
            state0={"count": 0},
            permits=(Permit(name="ok", when=k3(S.count >= 0)),),
        )
        u = Universe(spec=spec, transition=lambda s, e: {**s, "count": s["count"] + 1})
        run = u.simulate([{"type": "Inc"}, {"type": "Inc"}])
        signer = HmacSigner(key=b"secret-key", key_id="prod")

        bundle = AttestationBundle.from_run(run, signer=signer)
        assert len(bundle.steps) == 2
        assert bundle.algorithm == "hmac-sha256"

        result = verify_bundle(bundle, verifier=signer)
        assert result.valid
        assert result.steps_verified == 2

    def test_tampered_bundle_fails(self):
        spec = Spec(
            name="counter",
            state0={"count": 0},
            permits=(Permit(name="ok", when=k3(S.count >= 0)),),
        )
        u = Universe(spec=spec, transition=lambda s, e: {**s, "count": s["count"] + 1})
        run = u.simulate([{"type": "Inc"}, {"type": "Inc"}, {"type": "Inc"}])
        signer = HmacSigner(key=b"k", key_id="x")

        bundle = AttestationBundle.from_run(run, signer=signer)
        steps = list(bundle.steps)
        steps[1] = dataclasses.replace(steps[1], step_hash="tampered")
        tampered = dataclasses.replace(bundle, steps=tuple(steps))

        result = verify_bundle(tampered, verifier=signer)
        assert not result.valid
        assert result.first_invalid_step == 1

    def test_wrong_key_fails(self):
        spec = Spec(name="x", state0={"a": 0}, permits=(Permit(name="ok", when=k3(S.a >= 0)),))
        u = Universe(spec=spec, transition=lambda s, e: s)
        run = u.simulate([{"type": "X"}])

        signer1 = HmacSigner(key=b"key1", key_id="k")
        signer2 = HmacSigner(key=b"key2", key_id="k")

        bundle = AttestationBundle.from_run(run, signer=signer1)
        result = verify_bundle(bundle, verifier=signer2)
        assert not result.valid

    def test_bundle_to_json_round_trip(self):
        spec = Spec(name="x", state0={"a": 0}, permits=(Permit(name="ok", when=k3(S.a >= 0)),))
        u = Universe(spec=spec, transition=lambda s, e: s)
        run = u.simulate([{"type": "X"}])
        signer = HmacSigner(key=b"k", key_id="kid")
        bundle = AttestationBundle.from_run(run, signer=signer)

        json_str = bundle.to_json()
        restored = AttestationBundle.from_dict(json.loads(json_str))
        assert restored.algorithm == bundle.algorithm
        assert len(restored.steps) == len(bundle.steps)
        assert verify_bundle(restored, verifier=signer).valid


# -- #2 N-way composition ----------------------------------------------------


class TestComposeMany:
    def test_routes_by_name(self):
        def make(name, start):
            return Universe(
                spec=Spec(
                    name=name,
                    state0={"count": start},
                    permits=(Permit(name="ok", when=k3(S.count >= 0)),),
                ),
                transition=lambda s, e: {**s, "count": s["count"] + 1},
            )

        u_a, u_b = make("A", 0), make("B", 100)
        composed = compose_many(
            {"a": u_a, "b": u_b},
            router=lambda e: e["target"],
        )
        composed.apply({"type": "X", "target": "a"})
        composed.apply({"type": "X", "target": "b"})
        composed.apply({"type": "X", "target": "a"})

        state = composed.state
        assert state["a"]["count"] == 2
        assert state["b"]["count"] == 101

    def test_unknown_target_raises(self):
        u = Universe(
            spec=Spec(name="x", state0={"a": 0}, permits=(Permit(name="ok", when=k3(S.a >= 0)),)),
            transition=lambda s, e: s,
        )
        composed = compose_many({"x": u}, router=lambda e: "nope")
        with pytest.raises(KeyError, match="unknown universe"):
            composed.apply({"type": "X"})


class TestPipeline:
    def test_all_stages_apply(self):
        def make(name):
            counter = {"c": 0}

            def t(s, e):
                counter["c"] += 1
                return {**s, "n": counter["c"]}

            return Universe(
                spec=Spec(name=name, state0={"n": 0}, permits=(Permit(name="ok", when=k3(S.n >= 0)),)),
                transition=t,
            )

        a, b, c = make("a"), make("b"), make("c")
        pipe = Pipeline([a, b, c])
        pipe.apply({"type": "X"})
        # All three counters should be 1
        assert a.get("n") == 1
        assert b.get("n") == 1
        assert c.get("n") == 1

    def test_pipeline_short_circuits(self):
        u_ok = Universe(
            spec=Spec(name="ok", state0={"x": 0}, permits=(Permit(name="o", when=k3(S.x >= 0)),)),
            transition=lambda s, e: s,
        )
        # Universe that always rejects
        u_no = Universe(
            spec=Spec(
                name="no",
                state0={"x": 0},
                permits=(Permit(name="never", when=k3(S.x < 0)),),
            ),
            transition=lambda s, e: s,
        )
        pipe = Pipeline([u_ok, u_no, u_ok])
        result = pipe.apply({"type": "X"})
        assert isinstance(result, Impossible)


# -- #9 Schema Migration -----------------------------------------------------


class TestMigration:
    def test_migrate_state(self):
        # Spec at version 2; old state at version 1 (missing "currency")
        spec = Spec(
            name="bank",
            state0={"balance": 100, "currency": "USD", "__schema_version__": 2},
            permits=(Permit(name="ok", when=k3(S.balance >= 0)),),
            version=2,
            migrations=(
                Migration(
                    from_version=1,
                    to_version=2,
                    transform=With(Var("state"), (("currency", LStr("USD")),)),
                ),
            ),
        )
        # Provide v1 state
        v1_state = {"balance": 200, "__schema_version__": 1}
        u = Universe(spec=spec, transition=lambda s, e: s, state=v1_state, validate=False)
        assert u.get("currency") == "USD"
        assert u.get("balance") == 200
        assert u.get("__schema_version__") == 2

    def test_chained_migrations(self):
        spec = Spec(
            name="m",
            state0={"a": 1, "b": 2, "c": 3, "__schema_version__": 3},
            permits=(Permit(name="ok", when=k3(S.a >= 0)),),
            version=3,
            migrations=(
                Migration(from_version=1, to_version=2,
                          transform=With(Var("state"), (("b", LInt(2)),))),
                Migration(from_version=2, to_version=3,
                          transform=With(Var("state"), (("c", LInt(3)),))),
            ),
        )
        u = Universe(spec=spec, transition=lambda s, e: s,
                     state={"a": 1, "__schema_version__": 1}, validate=False)
        assert u.get("b") == 2
        assert u.get("c") == 3
        assert u.get("__schema_version__") == 3


# -- #10 Sub-expression diagnostics ------------------------------------------


class TestDiagnostics:
    def test_diagnosis_in_violated(self):
        from k3c import Always, Implies

        spec = Spec(
            name="complex",
            state0={"a": 5, "b": 10, "c": 300},
            permits=(Permit(name="ok", when=k3(S.a >= 0)),),
            maintains=(
                Maintain(
                    name="req",
                    expr=Always(Implies(
                        k3((S.a > 0) & (S.b > 0)),
                        k3(S.c > 200),
                    )),
                ),
            ),
        )

        def t(s, e):
            if e.get("type") == "DropC":
                return {**s, "c": 50}
            return s

        u = Universe(spec=spec, transition=t, validate=False)
        r = u.apply({"type": "DropC"})
        assert isinstance(r, Violated)
        # Should have diagnosis in the messages
        full = "\n".join(r.why.messages)
        assert "diagnosis" in full
        assert "state.c" in full
        assert "False" in full
