"""Tests for tier-1 improvements: Warning, Validate, DecodeDispatch default."""

from __future__ import annotations

from k3c.engine.result import Impossible, Ok, Violated, Warning
from k3c.ir.expr import (
    Always,
    CmpOp,
    Compare,
    EventField,
    Field,
    In,
    LInt,
    LStr,
    Matches,
    Var,
)
from k3c.runtime.universe import Universe
from k3c.spec.extract import ByteSlice, DecodeDispatch, DecodeFields, DecodeIdentity
from k3c.spec.model import Maintain, Permit, Severity, Spec, Validate


def _counter_transition(state, event):
    match event.get("type"):
        case "Inc":
            return {**state, "count": state["count"] + event.get("n", 1)}
        case _:
            return state


class TestMaintainSeverityWarning:
    def test_warning_severity_produces_warning(self):
        spec = Spec(
            name="warn_test",
            state0={"count": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, EventField("n"), LInt(-100))),),
            maintains=(
                Maintain(
                    name="prefer_positive",
                    expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
                    severity=Severity.WARNING,
                ),
            ),
        )
        u = Universe(spec=spec, transition=_counter_transition)
        r = u.apply({"type": "Inc", "n": -5})
        assert isinstance(r, Warning)
        assert r.why.rule == "prefer_positive"
        assert r.state["count"] == -5  # state still advances

    def test_error_severity_produces_violated(self):
        spec = Spec(
            name="error_test",
            state0={"count": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, EventField("n"), LInt(-100))),),
            maintains=(
                Maintain(
                    name="must_be_positive",
                    expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
                    severity=Severity.ERROR,
                ),
            ),
        )
        u = Universe(spec=spec, transition=_counter_transition)
        r = u.apply({"type": "Inc", "n": -5})
        assert isinstance(r, Violated)

    def test_warning_continues_processing(self):
        spec = Spec(
            name="warn_continue",
            state0={"count": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, EventField("n"), LInt(-100))),),
            maintains=(
                Maintain(
                    name="prefer_positive",
                    expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
                    severity=Severity.WARNING,
                ),
            ),
        )
        u = Universe(spec=spec, transition=_counter_transition)
        r1 = u.apply({"type": "Inc", "n": -5})
        assert isinstance(r1, Warning)
        r2 = u.apply({"type": "Inc", "n": 10})
        assert isinstance(r2, Ok)
        assert r2.state["count"] == 5


class TestValidateClause:
    def test_validate_checks_event_field(self):
        """Validate can access EventField — the key feature."""
        spec = Spec(
            name="validate_test",
            state0={"count": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, EventField("n"), LInt(0))),),
            validates=(
                Validate(
                    name="n_not_too_large",
                    on="Inc",
                    check=Compare(CmpOp.LE, EventField("n"), LInt(100)),
                    field="n",
                    constraint="<= 100",
                ),
            ),
        )
        u = Universe(spec=spec, transition=_counter_transition)

        # Valid event
        r1 = u.apply({"type": "Inc", "n": 5})
        assert isinstance(r1, Ok)

        # Invalid — n too large
        r2 = u.apply({"type": "Inc", "n": 200})
        assert isinstance(r2, Violated)
        assert r2.why.rule == "n_not_too_large"
        assert "field: n" in r2.why.messages
        assert "constraint: <= 100" in r2.why.messages

    def test_validate_with_warning_severity(self):
        spec = Spec(
            name="validate_warn",
            state0={"count": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, EventField("n"), LInt(0))),),
            validates=(
                Validate(
                    name="prefer_small",
                    on="Inc",
                    check=Compare(CmpOp.LE, EventField("n"), LInt(10)),
                    severity=Severity.WARNING,
                ),
            ),
        )
        u = Universe(spec=spec, transition=_counter_transition)
        r = u.apply({"type": "Inc", "n": 50})
        assert isinstance(r, Warning)
        assert r.why.rule == "prefer_small"
        assert r.state["count"] == 50

    def test_validate_scoped_to_event_type(self):
        """Validate with on='Inc' only runs for Inc events."""
        spec = Spec(
            name="scoped",
            state0={"count": 0},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, EventField("n"), LInt(0))),),
            validates=(
                Validate(
                    name="inc_only",
                    on="Inc",
                    check=Compare(CmpOp.LE, EventField("n"), LInt(10)),
                ),
            ),
        )
        u = Universe(spec=spec, transition=_counter_transition)
        # Different event type — validate doesn't fire
        r = u.apply({"type": "Other", "n": 999})
        assert isinstance(r, Ok)

    def test_validate_with_regex(self):
        """Validate can use Matches for regex checking."""
        def code_transition(state, event):
            return {**state, "last_code": event.get("code", "")}

        spec = Spec(
            name="regex_validate",
            state0={"last_code": ""},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
            validates=(
                Validate(
                    name="valid_airport",
                    on="SetAirport",
                    check=Matches(EventField("code"), r"^[A-Z]{3}$"),
                    field="code",
                    constraint="^[A-Z]{3}$",
                ),
            ),
        )
        u = Universe(spec=spec, transition=code_transition)

        r1 = u.apply({"type": "SetAirport", "code": "LAX"})
        assert isinstance(r1, Ok)

        r2 = u.apply({"type": "SetAirport", "code": "X2Z"})
        assert isinstance(r2, Violated)
        assert r2.why.rule == "valid_airport"

    def test_validate_with_in_expression(self):
        """Validate works with the new In expression."""
        def phase_transition(state, event):
            return {**state, "phase": event.get("phase", state["phase"])}

        spec = Spec(
            name="in_validate",
            state0={"phase": "idle"},
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
            validates=(
                Validate(
                    name="valid_phase",
                    on="SetPhase",
                    check=In(
                        EventField("phase"),
                        (LStr("idle"), LStr("active"), LStr("done")),
                    ),
                    field="phase",
                    constraint="one of: idle, active, done",
                ),
            ),
        )
        u = Universe(spec=spec, transition=phase_transition)

        r1 = u.apply({"type": "SetPhase", "phase": "active"})
        assert isinstance(r1, Ok)

        r2 = u.apply({"type": "SetPhase", "phase": "bogus"})
        assert isinstance(r2, Violated)
        assert r2.why.rule == "valid_phase"


class TestDecodeDispatchDefault:
    def test_skip_produces_impossible(self):
        spec = Spec(
            name="dispatch_skip",
            state0={"count": 0},
            decode=DecodeDispatch(
                discriminant=ByteSlice(start=0, length=1),
                cases=(
                    ("1", DecodeIdentity()),
                ),
                default="skip",
            ),
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
        )
        u = Universe(spec=spec, transition=_counter_transition)
        r = u.apply({"type": "Unknown", "data": "x"})
        assert isinstance(r, Impossible)
        assert r.why.rule == "decode"
        assert "Unmatched dispatch" in r.why.message

    def test_fallback_plan(self):
        """Default decode plan used for unmatched discriminants."""
        spec = Spec(
            name="dispatch_fallback",
            state0={"count": 0},
            decode=DecodeDispatch(
                discriminant=ByteSlice(start=0, length=1),
                cases=(
                    ("1", DecodeIdentity()),
                ),
                default=DecodeFields(fields=(("type", ByteSlice(start=0, length=1)),)),
            ),
            permits=(Permit(name="ok", when=Compare(CmpOp.GE, LInt(1), LInt(0))),),
        )
        u = Universe(spec=spec, transition=_counter_transition)
        r = u.apply("Xhello")
        assert isinstance(r, Ok)  # decoded via fallback plan
