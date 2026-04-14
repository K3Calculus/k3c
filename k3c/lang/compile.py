# k3c/lang/compile.py
"""
Compile K3Spec → CompiledSpec.

Takes the (I, U, K) specification from the builder and produces the
CompiledSpec that the engine consumes. The key transformation is
routing U.maintain clauses to the correct 9-tuple element:

    Always(φ)              → safety (N)    — checked every step
    Always(Within(φ, n))   → bounded (N)   — timer in Ctx.ob_timers
    Always(Eventually(φ))  → liveness (L)  — unbounded temporal obligation
    Always(φ Until ψ)      → liveness (L)  — until obligation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable

from k3c.cache import K3Cache
from k3c.lang.ir import Always, Eventually, K3l, Until, Within
from k3c.spec.builder import (
    K3Spec,
    KorrelatorDef,
    MaintainClause,
    OutputDef,
    PermitClause,
    ProjectionDef,
    RequireClause,
)


# ── Maintain clause routing ─────────────────────────────────────────────────


class MaintainKind(StrEnum):
    """How a maintain clause maps to the 9-tuple."""

    SAFETY = "safety"
    BOUNDED = "bounded"
    LIVENESS = "liveness"


@dataclass(frozen=True)
class ClassifiedMaintain:
    """A maintain clause with its routing classification.

    kind: where it goes in the 9-tuple
    name: human-readable identifier (from MaintainClause)
    expr: the inner K3l expression (unwrapped from Always/Within/Eventually)
    original: the full original expression (for serialization/export)
    n: timer bound for bounded liveness (Within), None otherwise
    """

    kind: MaintainKind
    name: str
    expr: K3l
    original: K3l
    n: int | None = None


def _find_temporal(expr: K3l) -> Within | Eventually | Until | None:
    """Search an expression tree for the first temporal wrapper.

    Looks through Always, Implies, And, Or, Not, If — the connectives
    that commonly wrap temporal obligations in spec patterns like
    □(trigger ⇒ ◇φ) or □(cond ∧ Within(φ, n)).
    """
    if isinstance(expr, (Within, Eventually, Until)):
        return expr
    if isinstance(expr, Always):
        return _find_temporal(expr.expr)

    # Look through logical connectives — the temporal node is typically
    # on the right side of an Implies or And
    from k3c.lang.ir import (
        And as AndNode,
        Implies as ImpliesNode,
        Not as NotNode,
        Or as OrNode,
    )

    if isinstance(expr, ImpliesNode):
        return _find_temporal(expr.right) or _find_temporal(expr.left)
    if isinstance(expr, (AndNode, OrNode)):
        return _find_temporal(expr.left) or _find_temporal(expr.right)
    if isinstance(expr, NotNode):
        return _find_temporal(expr.expr)
    return None


def classify_maintain(clause: MaintainClause) -> ClassifiedMaintain:
    """Route a maintain clause to its 9-tuple element.

    Scans the expression tree for temporal wrappers:
      Within(φ, n)   found → BOUNDED  — timer set in Ctx, expired = Violated
      Eventually(φ)  found → LIVENESS — unbounded obligation in L
      Until(φ, ψ)    found → LIVENESS — until obligation in L
      none found           → SAFETY   — checked every step in N

    Handles common patterns like:
      Always(φ)                        → SAFETY
      Always(Implies(trigger, Within(φ, n)))  → BOUNDED
      Always(Implies(trigger, Eventually(φ))) → LIVENESS
      bare φ                           → SAFETY
    """
    temporal = _find_temporal(clause.expr)

    if temporal is None:
        # Pure safety — unwrap Always if present
        inner = clause.expr
        if isinstance(inner, Always):
            inner = inner.expr
        return ClassifiedMaintain(
            kind=MaintainKind.SAFETY,
            name=clause.name,
            expr=inner,
            original=clause.expr,
        )

    if isinstance(temporal, Within):
        return ClassifiedMaintain(
            kind=MaintainKind.BOUNDED,
            name=clause.name,
            expr=temporal.expr,
            original=clause.expr,
            n=temporal.n,
        )

    if isinstance(temporal, Eventually):
        return ClassifiedMaintain(
            kind=MaintainKind.LIVENESS,
            name=clause.name,
            expr=temporal.expr,
            original=clause.expr,
        )

    # Until
    return ClassifiedMaintain(
        kind=MaintainKind.LIVENESS,
        name=clause.name,
        expr=temporal.right,
        original=clause.expr,
    )


# ── CompiledSpec ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompiledSpec:
    """The compiled form of a K3Spec — ready for the engine.

    This is the artifact consumed by apply(). It separates concerns that
    the builder keeps unified:
      - permits are ready for G evaluation
      - requires are indexed by event type for O(1) lookup
      - maintains are classified into safety/bounded/liveness
      - the korrelator is ready for N
    """

    # ── Identity ────────────────────────────────────────────────────────────
    name: str

    # ── I — Initial ─────────────────────────────────────────────────────────
    state0: dict[str, object]
    decode: Callable[[dict[str, object]], dict[str, object]] | None

    # ── G — Guards (from U.permit) ──────────────────────────────────────────
    permits: tuple[PermitClause, ...]

    # ── T — Transitions (from U.require, indexed by event type) ─────────────
    requires: dict[str, RequireClause]

    # ── N — Safety invariants (from U.maintain Always(φ)) ───────────────────
    safety: tuple[ClassifiedMaintain, ...]

    # ── N+Ctx — Bounded liveness (from U.maintain Always(Within(φ, n))) ─────
    bounded: tuple[ClassifiedMaintain, ...]

    # ── L — Unbounded liveness (from U.maintain Always(Eventually(φ))) ──────
    liveness: tuple[ClassifiedMaintain, ...]

    # ── P — Projections ─────────────────────────────────────────────────────
    projections: tuple[ProjectionDef, ...]

    # ── Outputs ─────────────────────────────────────────────────────────────
    outputs: tuple[OutputDef, ...]

    # ── K — Korrelator ──────────────────────────────────────────────────────
    korrelator: KorrelatorDef | None

    # ── Protocol ────────────────────────────────────────────────────────────
    protocol_start: str

    # ── Hash ────────────────────────────────────────────────────────────────
    hash_fn: str = "sha256"

    # ── Cache ───────────────────────────────────────────────────────────────
    cache: K3Cache = field(default_factory=K3Cache, compare=False, hash=False)


# ── compile() ────────────────────────────────────────────────────────────────


def compile_spec(spec: K3Spec, *, hash_fn: str = "sha256") -> CompiledSpec:
    """Compile a K3Spec into a CompiledSpec for the engine.

    This is the central transformation:
      1. Permits pass through unchanged (engine evaluates them)
      2. Requires are indexed by event type for O(1) lookup
      3. Maintains are classified and routed to safety/bounded/liveness
      4. Korrelator passes through

    hash_fn is stored on CompiledSpec and flows into every hash operation.
    """
    # Classify all maintain clauses
    classified = [classify_maintain(m) for m in spec.maintains]

    safety = tuple(c for c in classified if c.kind == MaintainKind.SAFETY)
    bounded = tuple(c for c in classified if c.kind == MaintainKind.BOUNDED)
    liveness = tuple(c for c in classified if c.kind == MaintainKind.LIVENESS)

    # Index requires by event type for O(1) lookup in apply()
    requires_index: dict[str, RequireClause] = {}
    for req in spec.requires:
        requires_index[req.on] = req

    return CompiledSpec(
        name=spec.name,
        state0=spec.state0,
        decode=spec.decode,
        permits=spec.permits,
        requires=requires_index,
        safety=safety,
        bounded=bounded,
        liveness=liveness,
        projections=spec.projections,
        outputs=spec.outputs,
        korrelator=spec.korrelator,
        protocol_start=spec.protocol_start,
        hash_fn=hash_fn,
    )
