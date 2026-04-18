# k3c/protocol.py
"""
Protocol DSL — declarative linear state machines.

Linear FSMs are the most common spec shape. Without sugar, they require
manually writing one Permit per transition with verbose state-checking
guards. The Protocol DSL captures the pattern in one place.

Usage:
    from k3c import Protocol, Spec, Universe

    proto = Protocol(
        name="order",
        state_field="status",
        states=("received", "classifying", "extracting", "committed"),
        transitions=(
            ("received", "CLASSIFY", "classifying"),
            ("classifying", "EXTRACT", "extracting"),
            ("extracting", "COMMIT", "committed"),
        ),
    )

    spec = Spec(
        name="order_processor",
        state0={"status": "received"},
        events=proto.event_defs(),         # auto-derived EventDefs
        permits=proto.permits(),           # auto-derived Permits
        maintains=proto.maintains(),       # auto-derived state validity invariant
    )
"""

from __future__ import annotations

from dataclasses import dataclass

from k3c.ir.expr import (
    Always,
    AnyOf,
    CmpOp,
    Compare,
    Field,
    LStr,
    Var,
)
from k3c.spec.model import EventDef, FieldDef, Maintain, Permit


@dataclass(frozen=True)
class Protocol:
    """Declarative linear state machine.

    name: protocol identifier (used as prefix for generated permits/maintain)
    state_field: which state field holds the current state (e.g. "status", "phase")
    states: ordered tuple of valid state values
    transitions: tuple of (from_state, event_type, to_state) triples
    """

    name: str
    state_field: str
    states: tuple[str, ...]
    transitions: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        state_set = set(self.states)
        for from_s, _evt, to_s in self.transitions:
            if from_s not in state_set:
                msg = f"Protocol {self.name!r}: transition from unknown state {from_s!r}"
                raise ValueError(msg)
            if to_s not in state_set:
                msg = f"Protocol {self.name!r}: transition to unknown state {to_s!r}"
                raise ValueError(msg)

    def event_types(self) -> tuple[str, ...]:
        """Return all distinct event types declared in transitions."""
        seen: list[str] = []
        for _from, evt, _to in self.transitions:
            if evt not in seen:
                seen.append(evt)
        return tuple(seen)

    def event_defs(self) -> tuple[EventDef, ...]:
        """Generate EventDef for each unique event type in the protocol."""
        return tuple(
            EventDef(name=evt, fields=(), description=f"Event for protocol {self.name!r}")
            for evt in self.event_types()
        )

    def permits(self) -> tuple[Permit, ...]:
        """Generate Permits enforcing state-ordered transitions.

        Each transition (from, EVT, to) becomes a Permit:
            Permit(name="{name}__{from}_to_{to}", on=EVT,
                   when=state.{state_field} == "{from}")

        If multiple transitions share the same event type from different states,
        they are merged into one Permit with an AnyOf guard.
        """
        # Group transitions by event type
        by_event: dict[str, list[str]] = {}
        for from_s, evt, _to in self.transitions:
            by_event.setdefault(evt, []).append(from_s)

        result: list[Permit] = []
        for evt, from_states in by_event.items():
            if len(from_states) == 1:
                guard = Compare(
                    CmpOp.EQ,
                    Field(Var("state"), self.state_field),
                    LStr(from_states[0]),
                )
                permit_name = f"{self.name}__{from_states[0]}_to_{_target_for(self.transitions, from_states[0], evt)}"
            else:
                guard = AnyOf(
                    exprs=tuple(
                        Compare(
                            CmpOp.EQ,
                            Field(Var("state"), self.state_field),
                            LStr(s),
                        )
                        for s in from_states
                    )
                )
                permit_name = f"{self.name}__{evt}_from_any"
            result.append(Permit(name=permit_name, on=evt, when=guard))
        return tuple(result)

    def maintains(self) -> tuple[Maintain, ...]:
        """Generate a state-validity invariant: state must be one of declared states."""
        guard = AnyOf(
            exprs=tuple(
                Compare(
                    CmpOp.EQ,
                    Field(Var("state"), self.state_field),
                    LStr(s),
                )
                for s in self.states
            )
        )
        return (
            Maintain(
                name=f"{self.name}__valid_{self.state_field}",
                expr=Always(guard),
            ),
        )

    def transition_table(self) -> dict[tuple[str, str], str]:
        """Return a (from, event) -> to lookup table for use in user transition fns."""
        return {(from_s, evt): to_s for from_s, evt, to_s in self.transitions}


def _target_for(
    transitions: tuple[tuple[str, str, str], ...], from_state: str, event: str
) -> str:
    """Find the target state for a (from_state, event) pair."""
    for f, e, t in transitions:
        if f == from_state and e == event:
            return t
    return "unknown"
