# k3c/spec/builder.py
"""
Spec builder — fluent API for constructing K3.Specs (I, U, K).

Usage:
    spec = (
        Spec("bank_account")
        .state0({"balance": 0})
        .permit("has_funds",
            when=Compare(CmpOp.GE, Field(Var("state"), "balance"),
                         EventField("amount")))
        .require("debit", on="Withdraw",
            transition=With(Var("spec_state"),
                (("balance", Arith(ArithOp.SUB,
                    Field(Var("spec_state"), "balance"),
                    EventField("amount"))),)))
        .maintain("non_negative",
            expr=Always(Compare(CmpOp.GE,
                Field(Var("state"), "balance"), LInt(0))))
        .korrelate(lift=lambda s: {"balance": s["balance"]})
        .build()
    )

The output K3Spec is a frozen dataclass holding the (I, U, K) triplet.
All expressions are K3l nodes from k3c.lang.ir.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from typing import Callable

from k3c.lang.ir import K3l, K3lType
from k3c.spec.extractor import Extractor

# ═══════════════════════════════════════════════════════════════════════════════
#  Clause types — the data that (I, U, K) holds
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FieldDef:
    """A domain field definition — part of I.domain."""

    name: str
    type: K3lType
    description: str = ""
    required: bool = True
    extract: Extractor | None = None


@dataclass(frozen=True)
class PermitClause:
    """A U.permit guard clause — evaluated by G.

    name: human-readable identifier for this guard
    when: K3l expression that must evaluate to Some(True) for the event to be permitted
    on: optional event type filter — if set, this permit only applies to events of this type
    """

    name: str
    when: K3l
    on: str | None = None


@dataclass(frozen=True)
class RequireClause:
    """A U.require transition clause — advances Ctx.spec_state.

    name: human-readable identifier
    on: event type that triggers this requirement
    transition: K3l expression producing the new spec_state (typically a Record or With node)
    """

    name: str
    on: str
    transition: K3l


@dataclass(frozen=True)
class MaintainClause:
    """A U.maintain invariant/liveness clause — routed to N or L by structure.

    name: human-readable identifier
    expr: K3l expression — Always(φ) → N, Always(Within(φ,n)) → Ctx+N,
          Always(Eventually(φ)) → L

    The routing is done by compile.py, not here. The builder just stores the expression.
    """

    name: str
    expr: K3l


@dataclass(frozen=True)
class ProjectionDef:
    """A P projection — derived view from state.

    name: projection identifier
    fn: pure function S → value
    kind: 'derived' | 'observable' | 'metric'
    """

    name: str
    fn: Callable[[dict[str, object]], object]
    kind: str = "derived"


@dataclass(frozen=True)
class OutputDef:
    """An output event emitted after a successful apply().

    name: output identifier
    fn: (state, event, new_state) → output_event or None
        Returns None to skip emission for this event.
    on: optional event type filter — only emit on this event type
    """

    name: str
    fn: Callable[
        [dict[str, object], dict[str, object], dict[str, object]],
        dict[str, object] | None,
    ]
    on: str | None = None


@dataclass(frozen=True)
class KorrelatorDef:
    """K — the correctness measurement function.

    lift: project impl state → domain state (Python callable)
    correlate: compare actual vs intended (Python callable, or None for exact match)
    threshold: pass/fail decision (Python callable, or None for boolean identity)
    """

    lift: Callable[[dict[str, object]], dict[str, object]]
    correlate: Callable[[dict[str, object], dict[str, object]], object] | None = None
    threshold: Callable[[object], bool] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
#  K3Spec — the frozen output of .build()
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class K3Spec:
    """The complete (I, U, K) specification — output of Spec.build().

    This is the artifact that compile.py consumes to produce CompiledSpec.
    It is frozen and portable (modulo callable fields in K).
    """

    # ── Identity ────────────────────────────────────────────────────────────
    name: str

    # ── I — Initial ─────────────────────────────────────────────────────────
    state0: dict[str, object]
    fields: tuple[FieldDef, ...] = ()
    decode: Callable[[dict[str, object]], dict[str, object]] | None = None

    # ── U — Unfolding ───────────────────────────────────────────────────────
    permits: tuple[PermitClause, ...] = ()
    requires: tuple[RequireClause, ...] = ()
    maintains: tuple[MaintainClause, ...] = ()

    # ── P — Projections ─────────────────────────────────────────────────────
    projections: tuple[ProjectionDef, ...] = ()

    # ── Outputs ─────────────────────────────────────────────────────────────
    outputs: tuple[OutputDef, ...] = ()

    # ── K — Korrelator ──────────────────────────────────────────────────────
    korrelator: KorrelatorDef | None = None

    # ── Protocol ────────────────────────────────────────────────────────────
    protocol_start: str = "__start__"

    # ── Derived specs ───────────────────────────────────────────────────────

    def slice(
        self,
        from_state: dict[str, object],
        events: list[str] | None = None,
    ) -> K3Spec:
        """Derive a sub-spec starting from a known DFA checkpoint.

        from_state becomes state₀ for the derived spec.
        events filters permits to only those matching the given event names.
        Maintain clauses and korrelator are unchanged — same causal laws.

        The derived spec IS this spec, resumed from a checkpoint.
        Use for: parallel_reduce() chunks, checkpoint-based replay.

        Example:
            leg_spec = ssim_spec.slice(
                from_state={"phase": "IN_CARRIER", "serial": 100, "rt2": ctx},
                events=["rt3_in_carrier"],
            )
        """
        if events is not None:
            event_set = set(events)
            active_permits = tuple(
                p for p in self.permits if p.on in event_set or p.name in event_set
            )
        else:
            active_permits = self.permits

        return K3Spec(
            name=self.name,
            state0=from_state,
            fields=self.fields,
            decode=self.decode,
            permits=active_permits,
            requires=self.requires,
            maintains=self.maintains,
            korrelator=self.korrelator,
            protocol_start=str(from_state["phase"])
            if isinstance(from_state.get("phase"), str)
            else self.protocol_start,
        )

    # ── k3l_ir JSON export ──────────────────────────────────────────────────

    def to_ir(self) -> dict[str, object]:
        """Export the spec to k3l_ir JSON format.

        The k3l_ir is the portable, version-controlled representation.
        It serializes all K3l expressions but NOT Python callables
        (decode, korrelator, projections, outputs — marked as non-portable).

        Used by: spec registry, subinterpreter isolation, TLA+ export, diffing.
        """
        from k3c.lang.serde import to_dict

        ir: dict[str, object] = {
            "k3l_ir_version": "1.0",
            "name": self.name,
            "state0": self.state0,
            "protocol_start": self.protocol_start,
            "fields": [
                {
                    "name": f.name,
                    "type": f.type.__class__.__name__,
                    "description": f.description,
                    "required": f.required,
                }
                for f in self.fields
            ],
            "permits": [
                {
                    "name": p.name,
                    "when": to_dict(p.when),
                    "on": p.on,
                }
                for p in self.permits
            ],
            "requires": [
                {
                    "name": r.name,
                    "on": r.on,
                    "transition": to_dict(r.transition),
                }
                for r in self.requires
            ],
            "maintains": [
                {
                    "name": m.name,
                    "expr": to_dict(m.expr),
                }
                for m in self.maintains
            ],
            "projections": [
                {
                    "name": p.name,
                    "kind": p.kind,
                    "portable": False,
                    "signature": _callable_sig(p.fn),
                }
                for p in self.projections
            ],
            "outputs": [
                {
                    "name": o.name,
                    "on": o.on,
                    "portable": False,
                    "signature": _callable_sig(o.fn),
                }
                for o in self.outputs
            ],
            "korrelator": _korrelator_ir(self.korrelator),
            "decode": _callable_sig(self.decode) if self.decode else None,
        }

        # Content-addressed hash of the portable IR (excludes non-portable callables)
        _non_portable = {"projections", "outputs", "korrelator", "decode"}
        portable = json.dumps(
            {k: v for k, v in ir.items() if k not in _non_portable},
            sort_keys=True,
            default=str,
        )
        ir["ir_hash"] = hashlib.sha256(portable.encode()).hexdigest()

        return ir

    def to_ir_json(self, indent: int = 2) -> str:
        """Export to k3l_ir as a formatted JSON string."""
        return json.dumps(self.to_ir(), indent=indent, sort_keys=False, default=str)

    @staticmethod
    def from_ir(ir: dict[str, object]) -> K3Spec:
        """Import a K3Spec from k3l_ir JSON format.

        Reconstructs the spec from the serialized K3l expressions.
        Callable fields (decode, korrelator, projections, outputs) are NOT
        restored — they must be re-attached by the consumer.
        """
        from k3c.lang.serde import from_dict

        permits = tuple(
            PermitClause(
                name=p["name"],
                when=from_dict(p["when"]),
                on=p.get("on"),
            )
            for p in ir.get("permits", [])
        )

        requires = tuple(
            RequireClause(
                name=r["name"],
                on=r["on"],
                transition=from_dict(r["transition"]),
            )
            for r in ir.get("requires", [])
        )

        maintains = tuple(
            MaintainClause(
                name=m["name"],
                expr=from_dict(m["expr"]),
            )
            for m in ir.get("maintains", [])
        )

        return K3Spec(
            name=ir.get("name", ""),
            state0=ir.get("state0", {}),
            permits=permits,
            requires=requires,
            maintains=maintains,
            protocol_start=ir.get("protocol_start", "__start__"),
        )


# ── IR helpers ───────────────────────────────────────────────────────────────

# Portable type mapping: Python annotations → language-neutral types
_PORTABLE_TYPES: dict[str, str] = {
    "dict": "Record",
    "dict[str, object]": "Record",
    "dict[str, Any]": "Record",
    "int": "Int",
    "float": "Float",
    "str": "String",
    "bool": "Bool",
    "list": "List",
    "tuple": "Tuple",
    "None": "Void",
    "object": "Any",
}


def _to_portable_type(annotation: object) -> str:
    """Convert a Python type annotation to a portable type string."""
    if annotation is inspect.Parameter.empty:
        return "Any"
    s = str(annotation)
    # Strip <class '...'> wrapper
    if s.startswith("<class '") and s.endswith("'>"):
        s = s[8:-2]
    return _PORTABLE_TYPES.get(s, s)


def _callable_sig(fn: object) -> dict[str, object]:
    """Extract language-neutral signature info from a callable for the k3l_ir.

    Produces a portable schema:
      parameters: [{name, type, description}]
      returns: {type, description}
      description: docstring if available
    """
    if fn is None:
        return {}

    params: list[dict[str, str]] = []
    return_type = "Any"
    description = ""

    try:
        sig = inspect.signature(fn)  # type: ignore[arg-type]
        for name, param in sig.parameters.items():
            p: dict[str, str] = {
                "name": name,
                "type": _to_portable_type(param.annotation),
            }
            if param.default is not inspect.Parameter.empty:
                p["default"] = repr(param.default)
            params.append(p)
        if sig.return_annotation is not inspect.Parameter.empty:
            return_type = _to_portable_type(sig.return_annotation)
    except (ValueError, TypeError):
        pass

    # Extract docstring
    doc = getattr(fn, "__doc__", None)
    if doc:
        description = doc.strip().split("\n")[0]

    result: dict[str, object] = {
        "parameters": params,
        "returns": return_type,
    }
    if description:
        result["description"] = description
    return result


def _korrelator_ir(k: KorrelatorDef | None) -> dict[str, object] | None:
    """Serialize korrelator info for IR export."""
    if k is None:
        return None
    return {
        "lift": _callable_sig(k.lift),
        "correlate": _callable_sig(k.correlate) if k.correlate else None,
        "threshold": _callable_sig(k.threshold) if k.threshold else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Spec — fluent builder
# ═══════════════════════════════════════════════════════════════════════════════


class Spec:
    """Fluent builder for constructing a K3Spec.

    Every method returns self for chaining. Call .build() to produce the
    frozen K3Spec.

    Example:
        spec = (
            Spec("order")
            .state0({"status": "pending", "total": 0})
            .permit("can_place", when=Compare(CmpOp.EQ, ...))
            .maintain("positive_total", expr=Always(Compare(CmpOp.GE, ...)))
            .build()
        )
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._state0: dict[str, object] = {}
        self._fields: list[FieldDef] = []
        self._decode: Callable[[dict[str, object]], dict[str, object]] | None = None
        self._permits: list[PermitClause] = []
        self._requires: list[RequireClause] = []
        self._maintains: list[MaintainClause] = []
        self._projections: list[ProjectionDef] = []
        self._outputs: list[OutputDef] = []
        self._korrelator: KorrelatorDef | None = None
        self._protocol_start: str = "__start__"

    # ── I — Initial ─────────────────────────────────────────────────────────

    def state0(self, initial_state: dict[str, object]) -> Spec:
        """Set the initial spec state (I.state₀ → Ctx₀.spec_state)."""
        self._state0 = initial_state
        return self

    def field(
        self,
        name: str,
        type: K3lType,
        *,
        description: str = "",
        required: bool = True,
        extract: Extractor | None = None,
    ) -> Spec:
        """Add a domain field definition (I.domain).

        extract: optional Extractor describing how to extract this field
                 from a raw event. When present, enables portable I.decode
                 (serializable to JSON, transpilable to SQL/TLA+).
        """
        self._fields.append(
            FieldDef(
                name=name,
                type=type,
                description=description,
                required=required,
                extract=extract,
            )
        )
        return self

    def decode(self, fn: Callable[[dict[str, object]], dict[str, object]]) -> Spec:
        """Set the decode function (I.decode: raw → domain)."""
        self._decode = fn
        return self

    # ── U — Unfolding ───────────────────────────────────────────────────────

    def permit(self, name: str, *, when: K3l, on: str | None = None) -> Spec:
        """Add a permit clause (U.permit → G).

        when: K3l expression that must be Some(True) for the event to pass.
        on: optional event type filter.
        """
        self._permits.append(PermitClause(name=name, when=when, on=on))
        return self

    def require(self, name: str, *, on: str, transition: K3l) -> Spec:
        """Add a require clause (U.require → advances Ctx.spec_state).

        on: event type that triggers this requirement.
        transition: K3l expression producing the new spec_state.
        """
        self._requires.append(RequireClause(name=name, on=on, transition=transition))
        return self

    def maintain(self, name: str, *, expr: K3l) -> Spec:
        """Add a maintain clause (U.maintain → N or L).

        expr should typically be wrapped in Always(), Eventually(), or Within().
        Routing to N vs L is done by compile.py based on the expression structure.
        """
        self._maintains.append(MaintainClause(name=name, expr=expr))
        return self

    # ── P — Projections ─────────────────────────────────────────────────────

    def project(
        self,
        name: str,
        fn: Callable[[dict[str, object]], object],
        *,
        kind: str = "derived",
    ) -> Spec:
        """Add a projection (P). Pure function from state to derived value.

        kind: 'derived' (default), 'observable', or 'metric'
        """
        self._projections.append(ProjectionDef(name=name, fn=fn, kind=kind))
        return self

    # ── Outputs ─────────────────────────────────────────────────────────────

    def output(
        self,
        name: str,
        fn: Callable[
            [dict[str, object], dict[str, object], dict[str, object]],
            dict[str, object] | None,
        ],
        *,
        on: str | None = None,
    ) -> Spec:
        """Add an output event emitted after successful apply().

        fn: (state_before, event, new_state) → output_event or None.
        on: optional event type filter.

        Outputs are post-causal — computed after T runs and N holds.
        They do not affect the causal step. Used by bridges.
        """
        self._outputs.append(OutputDef(name=name, fn=fn, on=on))
        return self

    # ── K — Korrelator ──────────────────────────────────────────────────────

    def korrelate(
        self,
        *,
        lift: Callable[[dict[str, object]], dict[str, object]],
        correlate: Callable[[dict[str, object], dict[str, object]], object]
        | None = None,
        threshold: Callable[[object], bool] | None = None,
    ) -> Spec:
        """Set the korrelator (K).

        lift: project impl state → domain state for comparison.
        correlate: compare actual (K.lift(S)) vs intended (Ctx.spec_state).
                   Defaults to exact equality if None.
        threshold: pass/fail on the correlation result.
                   Defaults to boolean identity if None.
        """
        self._korrelator = KorrelatorDef(
            lift=lift, correlate=correlate, threshold=threshold
        )
        return self

    # ── Protocol ────────────────────────────────────────────────────────────

    def protocol_start(self, pos: str) -> Spec:
        """Set the initial protocol DFA position (default: '__start__')."""
        self._protocol_start = pos
        return self

    # ── Build ───────────────────────────────────────────────────────────────

    def build(self) -> K3Spec:
        """Produce the frozen K3Spec."""
        return K3Spec(
            name=self._name,
            state0=self._state0,
            fields=tuple(self._fields),
            decode=self._decode,
            permits=tuple(self._permits),
            requires=tuple(self._requires),
            maintains=tuple(self._maintains),
            projections=tuple(self._projections),
            outputs=tuple(self._outputs),
            korrelator=self._korrelator,
            protocol_start=self._protocol_start,
        )
