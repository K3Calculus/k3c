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
class EventDef:
    """An event type schema -- declares what an event of a given type carries.

    name: the event type identifier (matches event["type"] at runtime)
    fields: typed fields the event carries (excluding "type" itself)
    description: human-readable purpose of the event

    Use to give events a declared structure. Permit/Validate `on=` parameters
    refer to EventDef.name. Enables future schema validation, IDE autocomplete,
    and code emission.

    Example:
        EventDef(
            name="Withdraw",
            fields=(
                FieldDef(name="amount", type=TInt()),
                FieldDef(name="currency", type=TString()),
            ),
            description="Withdraw funds from account",
        )
    """

    name: str
    fields: tuple[FieldDef, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class Permit:
    """A guard clause -- evaluated by G.

    name: human-readable identifier
    when: Expr that must evaluate to Some(True) for the event to be permitted
    on: optional event type filter
    denied: optional Expr (evaluated when guard fails) producing a rich message.
            Should evaluate to a string. If None, generic "Permit X denied" is used.
            Has access to state, event, and spec_state.
    """

    name: str
    when: Expr
    on: str | None = None
    denied: Expr | None = None


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
    denied: optional Expr (evaluated when invariant fails) producing a rich message.
            Should evaluate to a string. If None, generic "Maintain X violated" is used.

    Routing is done by compile.py, not here.
    """

    name: str
    expr: Expr
    severity: Severity = Severity.ERROR
    denied: Expr | None = None


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
    denied: optional Expr (evaluated when check fails) producing a rich message.
    """

    name: str
    on: str
    check: Expr
    severity: Severity = Severity.ERROR
    field: str | None = None
    constraint: str | None = None
    denied: Expr | None = None


class CompareMode(StrEnum):
    """Korrelation comparison mode."""

    EXACT = "exact"
    SUBSET = "subset"


@dataclass(frozen=True)
class Migration:
    """Schema migration — transforms state from one schema version to another.

    from_version: source schema version (must match state's __schema_version__ or be applied in chain)
    to_version: target schema version
    transform: IR Expr that produces the new state from the old.
               Has access to state (the old state).
               Should produce a Record/With expression.

    Example:
        Migration(
            from_version=1,
            to_version=2,
            transform=With(Var("state"), (("currency", LStr("USD")),)),
        )
    """

    from_version: int
    to_version: int
    transform: Expr


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
    events: tuple[EventDef, ...] = ()
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

    # Schema versioning + migrations
    version: int = 1
    migrations: tuple[Migration, ...] = ()

    # Protocol
    protocol_start: str = "__start__"

    def decode_event(self, raw: object) -> dict[str, object]:
        """Decode a raw event using this spec's decode plan without the full apply pipeline.

        Returns the decoded domain event as a dict. Useful for inspecting
        decoded fields without running guards, transitions, or invariants.
        """
        from k3c.spec.extract import run_decode

        return run_decode(self.decode, raw)

    def slice(
        self,
        from_state: dict[str, object],
        events: list[str] | None = None,
        relax: list[str] | None = None,
    ) -> Spec:
        """Derive a sub-spec starting from a known DFA checkpoint.

        from_state: becomes state0 for the derived spec. Hash chain resets.
        events: filters permits to only those matching the given event names.
        relax: list of Maintain clause names to drop from the derived spec.
               Use this when splitting chunks that would break specific
               invariants (e.g., serial continuity across sub-chunks).

        SpecCtx starts fresh. Before() on the first step returns Nothing
        (no previous state). Maintain and korrelator are carried forward
        unless explicitly relaxed.
        """
        if events is not None:
            event_set = set(events)
            active_permits = tuple(
                p for p in self.permits if p.on in event_set or p.name in event_set
            )
        else:
            active_permits = self.permits

        if relax is not None:
            relax_set = set(relax)
            active_maintains = tuple(
                m for m in self.maintains if m.name not in relax_set
            )
            active_validates = tuple(
                v for v in self.validates if v.name not in relax_set
            )
        else:
            active_maintains = self.maintains
            active_validates = self.validates

        return Spec(
            name=self.name,
            state0=from_state,
            fields=self.fields,
            events=self.events,
            decode=self.decode,
            permits=active_permits,
            requires=self.requires,
            maintains=active_maintains,
            validates=active_validates,
            projections=self.projections,
            outputs=self.outputs,
            korrelator=self.korrelator,
            version=self.version,
            migrations=self.migrations,
            protocol_start=str(from_state["phase"])
            if isinstance(from_state.get("phase"), str)
            else self.protocol_start,
        )
