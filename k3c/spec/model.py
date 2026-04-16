# k3c/spec/model.py
"""
Declarative spec model — the data-first K3 specification.

All structures are frozen dataclasses. No Python callables in the spec.
The spec is 100% serializable, portable, and replayable.

Usage:
    spec = Spec(
        name="bank",
        state0={"balance": 100},
        permits=(
            Permit(name="has_funds", on="Withdraw",
                   when=Compare(CmpOp.GE, Field(Var("state"), "balance"),
                                EventField("amount"))),
        ),
        maintains=(
            Maintain(name="non_negative",
                     expr=Always(Compare(CmpOp.GE,
                         Field(Var("state"), "balance"), LInt(0)))),
        ),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from k3c.ir.expr import Expr
from k3c.ir.types import ExprType
from k3c.spec.extract import DecodePlan, Extractor


# -- Clause types --------------------------------------------------------------


@dataclass(frozen=True)
class FieldDef:
    """A domain field definition -- part of I.domain."""

    name: str
    type: ExprType
    description: str = ""
    required: bool = True
    extract: Extractor | None = None


@dataclass(frozen=True)
class Permit:
    """A guard clause -- evaluated by G.

    name: human-readable identifier
    when: Expr that must evaluate to Some(True) for the event to be permitted
    on: optional event type filter
    """

    name: str
    when: Expr
    on: str | None = None


@dataclass(frozen=True)
class Require:
    """A transition clause -- advances Ctx.spec_state.

    name: human-readable identifier
    on: event type that triggers this requirement
    transition: Expr producing the new spec_state (typically Record or With)
    """

    name: str
    on: str
    transition: Expr


class Severity(StrEnum):
    """Maintain clause severity level."""

    ERROR = "error"  # Violated — stops processing
    WARNING = "warning"  # Warning — continues with causal record


@dataclass(frozen=True)
class Maintain:
    """An invariant/liveness clause -- routed to N or L by structure.

    name: human-readable identifier
    expr: Always(phi) -> N, Always(Within(phi,n)) -> Ctx+N,
          Always(Eventually(phi)) -> L
    severity: "error" (default, produces Violated) or "warning" (produces Warning)

    Routing is done by compile.py, not here.
    """

    name: str
    expr: Expr
    severity: Severity = Severity.ERROR


@dataclass(frozen=True)
class Projection:
    """A derived view from state -- declarative expression.

    name: projection identifier
    expr: Expr evaluated against the current state
    kind: 'derived' | 'observable' | 'metric'
    """

    name: str
    expr: Expr
    kind: str = "derived"


@dataclass(frozen=True)
class Output:
    """An output event emitted after a successful apply().

    name: output identifier
    expr: Expr evaluated against state+event context. Nothing -> skip.
    on: optional event type filter
    """

    name: str
    expr: Expr
    on: str | None = None


@dataclass(frozen=True)
class Validate:
    """Event-scoped validation — checked after transition, before invariants.

    Unlike Maintain (which checks state invariants), Validate checks the event
    itself against the current state. Has access to both EventField and state.

    name: human-readable identifier
    on: event type filter (required — scopes to specific event types)
    check: Expr that must evaluate to Some(True). Has access to state + event.
    severity: "error" (produces Violated) or "warning" (produces Warning)
    field: optional field name for structured error detail
    constraint: optional constraint description for structured error detail
    """

    name: str
    on: str
    check: Expr
    severity: Severity = Severity.ERROR
    field: str | None = None
    constraint: str | None = None


class CompareMode(StrEnum):
    """Korrelation comparison mode."""

    EXACT = "exact"
    SUBSET = "subset"


@dataclass(frozen=True)
class Korrelator:
    """K -- the correctness measurement.

    actual: Expr to project impl state -> domain state
    intended: Expr to project spec_state -> intended domain state
    mode: comparison mode (exact or subset match)
    """

    actual: Expr
    intended: Expr
    mode: CompareMode = CompareMode.EXACT


# -- Spec ----------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    """The complete (I, U, K) specification -- portable, serializable data.

    This replaces the old fluent builder. Construct directly:

        spec = Spec(
            name="bank",
            state0={"balance": 100},
            permits=(...),
            maintains=(...),
        )
    """

    # Identity
    name: str

    # I -- Initial
    state0: dict[str, object]
    fields: tuple[FieldDef, ...] = ()
    decode: DecodePlan | None = None

    # U -- Unfolding
    permits: tuple[Permit, ...] = ()
    requires: tuple[Require, ...] = ()
    maintains: tuple[Maintain, ...] = ()
    validates: tuple[Validate, ...] = ()

    # P -- Projections (declarative)
    projections: tuple[Projection, ...] = ()

    # Outputs (declarative)
    outputs: tuple[Output, ...] = ()

    # K -- Korrelator (declarative)
    korrelator: Korrelator | None = None

    # Protocol
    protocol_start: str = "__start__"

    def slice(
        self,
        from_state: dict[str, object],
        events: list[str] | None = None,
    ) -> Spec:
        """Derive a sub-spec starting from a known DFA checkpoint.

        from_state becomes state0 for the derived spec.
        events filters permits to only those matching the given event names.
        Maintain clauses and korrelator are unchanged -- same causal laws.
        """
        if events is not None:
            event_set = set(events)
            active_permits = tuple(
                p for p in self.permits if p.on in event_set or p.name in event_set
            )
        else:
            active_permits = self.permits

        return Spec(
            name=self.name,
            state0=from_state,
            fields=self.fields,
            decode=self.decode,
            permits=active_permits,
            requires=self.requires,
            maintains=self.maintains,
            validates=self.validates,
            projections=self.projections,
            outputs=self.outputs,
            korrelator=self.korrelator,
            protocol_start=str(from_state["phase"])
            if isinstance(from_state.get("phase"), str)
            else self.protocol_start,
        )
