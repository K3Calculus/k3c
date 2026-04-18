"""Tests for EventDef runtime schema enforcement."""

from __future__ import annotations

from k3c import (
    EventDef,
    FieldDef,
    Impossible,
    LBool,
    Ok,
    Permit,
    S,
    Spec,
    Universe,
    k3,
)
from k3c.ir.types import TBool, TEnum, TInt, TString


def _spec(events: tuple[EventDef, ...]) -> Spec:
    return Spec(
        name="t",
        state0={"x": 0},
        events=events,
        permits=(Permit(name="ok", when=LBool(True)),),
    )


def _u(events: tuple[EventDef, ...]) -> Universe:
    return Universe(spec=_spec(events), transition=lambda s, e: s, validate=False)


class TestNoEnforcementWithoutEventDefs:
    def test_no_events_means_no_enforcement(self):
        spec = Spec(name="open", state0={"x": 0},
                    permits=(Permit(name="ok", when=LBool(True)),))
        u = Universe(spec=spec, transition=lambda s, e: s, validate=False)
        # Any event type is allowed
        assert isinstance(u.apply({"type": "Anything"}), Ok)
        assert isinstance(u.apply({"type": "Whatever", "any": "field"}), Ok)


class TestUnknownEventType:
    def test_unknown_type_rejected(self):
        u = _u((EventDef(name="Inc"),))
        r = u.apply({"type": "Bogus"})
        assert isinstance(r, Impossible)
        assert r.why.rule == "event_schema"
        assert "unknown event type" in r.why.message

    def test_known_type_accepted(self):
        u = _u((EventDef(name="Inc"),))
        r = u.apply({"type": "Inc"})
        assert isinstance(r, Ok)

    def test_missing_type_rejected(self):
        u = _u((EventDef(name="Inc"),))
        r = u.apply({"not_type": "x"})
        assert isinstance(r, Impossible)
        assert "missing 'type'" in r.why.message


class TestRequiredFields:
    def test_missing_required_field_rejected(self):
        u = _u((EventDef(name="Inc", fields=(FieldDef(name="n", type=TInt()),)),))
        r = u.apply({"type": "Inc"})
        assert isinstance(r, Impossible)
        assert "missing required field 'n'" in r.why.message

    def test_optional_field_not_required(self):
        u = _u((EventDef(name="Inc", fields=(
            FieldDef(name="n", type=TInt(), required=False),
        )),))
        r = u.apply({"type": "Inc"})
        assert isinstance(r, Ok)

    def test_required_field_present_accepted(self):
        u = _u((EventDef(name="Inc", fields=(FieldDef(name="n", type=TInt()),)),))
        r = u.apply({"type": "Inc", "n": 5})
        assert isinstance(r, Ok)


class TestTypeChecks:
    def test_int_field_rejects_string(self):
        u = _u((EventDef(name="Inc", fields=(FieldDef(name="n", type=TInt()),)),))
        r = u.apply({"type": "Inc", "n": "five"})
        assert isinstance(r, Impossible)
        assert "type mismatch" in r.why.message
        assert "expected TInt" in r.why.message

    def test_int_field_rejects_bool(self):
        # bool is technically int in Python — k3c distinguishes
        u = _u((EventDef(name="Inc", fields=(FieldDef(name="n", type=TInt()),)),))
        r = u.apply({"type": "Inc", "n": True})
        assert isinstance(r, Impossible)

    def test_string_field_rejects_int(self):
        u = _u((EventDef(name="Set", fields=(FieldDef(name="key", type=TString()),)),))
        r = u.apply({"type": "Set", "key": 123})
        assert isinstance(r, Impossible)

    def test_bool_field_accepts_bool(self):
        u = _u((EventDef(name="X", fields=(FieldDef(name="flag", type=TBool()),)),))
        assert isinstance(u.apply({"type": "X", "flag": True}), Ok)
        assert isinstance(u.apply({"type": "X", "flag": False}), Ok)

    def test_bool_field_rejects_int(self):
        u = _u((EventDef(name="X", fields=(FieldDef(name="flag", type=TBool()),)),))
        r = u.apply({"type": "X", "flag": 1})
        assert isinstance(r, Impossible)

    def test_enum_field_membership(self):
        u = _u((EventDef(name="X", fields=(
            FieldDef(name="phase", type=TEnum(values=("a", "b", "c"))),
        )),))
        assert isinstance(u.apply({"type": "X", "phase": "a"}), Ok)
        assert isinstance(u.apply({"type": "X", "phase": "b"}), Ok)
        r = u.apply({"type": "X", "phase": "z"})
        assert isinstance(r, Impossible)
        assert "type mismatch" in r.why.message
