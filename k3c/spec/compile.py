# k3c/spec/compile.py
"""
Compile Spec -> CompiledSpec.

Routes U.maintain clauses to the correct 9-tuple element:
    Always(phi)              -> safety (N)
    Always(Within(phi, n))   -> bounded (N)
    Always(Eventually(phi))  -> liveness (L)
    Always(phi Until psi)    -> liveness (L)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from k3c.cache import K3Cache
from k3c.ir.expr import Always, And, Eventually, Expr, Implies, Not, Or, Until, Within
from k3c.spec.extract import DecodePlan
from k3c.spec.model import (
    Korrelator,
    Maintain,
    Output,
    Permit,
    Projection,
    Require,
    Severity,
    Spec,
    Validate,
)


# -- Maintain clause routing ---------------------------------------------------


class MaintainKind(StrEnum):
    """How a maintain clause maps to the 9-tuple."""

    SAFETY = "safety"
    BOUNDED = "bounded"
    LIVENESS = "liveness"


@dataclass(frozen=True)
class ClassifiedMaintain:
    """A maintain clause with its routing classification."""

    kind: MaintainKind
    name: str
    expr: Expr
    original: Expr
    n: int | None = None
    severity: Severity = Severity.ERROR


def _find_temporal(expr: Expr) -> Within | Eventually | Until | None:
    """Search an expression tree for the first temporal wrapper."""
    if isinstance(expr, (Within, Eventually, Until)):
        return expr
    if isinstance(expr, Always):
        return _find_temporal(expr.expr)
    if isinstance(expr, Implies):
        return _find_temporal(expr.right) or _find_temporal(expr.left)
    if isinstance(expr, (And, Or)):
        return _find_temporal(expr.left) or _find_temporal(expr.right)
    if isinstance(expr, Not):
        return _find_temporal(expr.expr)
    return None


def classify_maintain(clause: Maintain) -> ClassifiedMaintain:
    """Route a maintain clause to its 9-tuple element."""
    temporal = _find_temporal(clause.expr)

    if temporal is None:
        inner = clause.expr
        if isinstance(inner, Always):
            inner = inner.expr
        return ClassifiedMaintain(
            kind=MaintainKind.SAFETY,
            name=clause.name,
            expr=inner,
            original=clause.expr,
            severity=clause.severity,
        )

    if isinstance(temporal, Within):
        return ClassifiedMaintain(
            kind=MaintainKind.BOUNDED,
            name=clause.name,
            expr=temporal.expr,
            original=clause.expr,
            n=temporal.n,
            severity=clause.severity,
        )

    if isinstance(temporal, Eventually):
        return ClassifiedMaintain(
            kind=MaintainKind.LIVENESS,
            name=clause.name,
            expr=temporal.expr,
            original=clause.expr,
            severity=clause.severity,
        )

    # Until
    return ClassifiedMaintain(
        kind=MaintainKind.LIVENESS,
        name=clause.name,
        expr=temporal.right,
        original=clause.expr,
        severity=clause.severity,
    )


# -- CompiledSpec --------------------------------------------------------------


@dataclass(frozen=True)
class CompiledSpec:
    """The compiled form of a Spec -- ready for the engine."""

    # Identity
    name: str

    # I -- Initial
    state0: dict[str, object]
    decode: DecodePlan | None

    # G -- Guards
    permits: tuple[Permit, ...]

    # T -- Transitions (indexed by event type)
    requires: dict[str, Require]

    # N -- Safety invariants
    safety: tuple[ClassifiedMaintain, ...]

    # N+Ctx -- Bounded liveness
    bounded: tuple[ClassifiedMaintain, ...]

    # L -- Unbounded liveness
    liveness: tuple[ClassifiedMaintain, ...]

    # P -- Projections (declarative)
    projections: tuple[Projection, ...]

    # Outputs (declarative)
    outputs: tuple[Output, ...]

    # V -- Validates (event-scoped)
    validates: dict[str, tuple[Validate, ...]]

    # K -- Korrelator (declarative)
    korrelator: Korrelator | None

    # Protocol
    protocol_start: str

    # Hash
    hash_fn: str = "sha256"

    # Cache
    cache: K3Cache = field(default_factory=K3Cache, compare=False, hash=False)


# -- compile() -----------------------------------------------------------------


def compile_spec(spec: Spec, *, hash_fn: str = "sha256") -> CompiledSpec:
    """Compile a Spec into a CompiledSpec for the engine."""
    classified = [classify_maintain(m) for m in spec.maintains]

    safety = tuple(c for c in classified if c.kind == MaintainKind.SAFETY)
    bounded = tuple(c for c in classified if c.kind == MaintainKind.BOUNDED)
    liveness = tuple(c for c in classified if c.kind == MaintainKind.LIVENESS)

    requires_index: dict[str, Require] = {}
    for req in spec.requires:
        requires_index[req.on] = req

    # Index validates by event type for O(1) lookup
    validates_index: dict[str, list[Validate]] = {}
    for v in spec.validates:
        validates_index.setdefault(v.on, []).append(v)
    validates_frozen = {k: tuple(v) for k, v in validates_index.items()}

    return CompiledSpec(
        name=spec.name,
        state0=spec.state0,
        decode=spec.decode,
        permits=spec.permits,
        requires=requires_index,
        safety=safety,
        bounded=bounded,
        liveness=liveness,
        validates=validates_frozen,
        projections=spec.projections,
        outputs=spec.outputs,
        korrelator=spec.korrelator,
        protocol_start=spec.protocol_start,
        hash_fn=hash_fn,
    )
