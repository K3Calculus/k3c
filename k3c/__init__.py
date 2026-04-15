# k3c — Kulkarni Calculus Python SDK
"""
k3c: Design causality, and the system emerges.

Usage:
    from k3c import Spec, universe, Ok, Impossible, Violated

    spec = (
        Spec("bank")
        .state0({"balance": 100})
        .permit("has_funds", when=Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")), on="Withdraw")
        .maintain("non_negative", expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))))
        .build()
    )

    u = universe(MyBankSystem(), spec)
    match u.apply({"type": "Withdraw", "amount": 50}):
        case Ok(state=s):       print(s["balance"])
        case Impossible(why):   print(why.message)
        case Violated(why):     why.raise_()
"""

# ── Core types ──────────────────────────────────────────────────────────────
from k3c.spec.builder import (
    FieldDef,
    K3Spec,
    KorrelatorDef,
    MaintainClause,
    OutputDef,
    PermitClause,
    ProjectionDef,
    RequireClause,
    Spec,
)
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import Impossible, K3Result, Ok, Violated, Why, WhyKind

# ── K3l IR ──────────────────────────────────────────────────────────────────
from k3c.lang.ir import (
    Always,
    And,
    Arith,
    ArithOp,
    Before,
    After,
    CmpOp,
    Compare,
    EventField,
    Eventually,
    Field,
    ForAll,
    Implies,
    LBool,
    LFloat,
    LInt,
    LStr,
    Not,
    Nothing,
    Or,
    Some,
    Var,
    With,
    Within,
)

# ── Universe ────────────────────────────────────────────────────────────────
from k3c.universe.universe import (
    ChunkSource,
    ParallelReduceResult,
    ReduceAllResult,
    System,
    Universe,
    parallel_reduce,
    universe,
)

# ── Compose, Bridge & Isolate ──────────────────────────────────────────────
from k3c.universe.compose import ComposedUniverse
from k3c.universe.bridge import BridgedUniverse
from k3c.universe.isolate import IsolatedUniverse
from k3c.universe.retry import BridgeMode, FallbackStrategy, RetryPolicy

# ── Testing ─────────────────────────────────────────────────────────────────
from k3c.universe.fuzz import FuzzReport, FuzzViolation
from k3c.universe.explain import ExplainResult

# ── Errors ──────────────────────────────────────────────────────────────────
from k3c.errors import (
    K3Error,
    K3NothingException,
    K3ViolatedException,
    K3WellFormednessError,
    K3BridgeError,
)

from importlib.metadata import version as _version

__version__ = _version("k3c")

__all__ = [
    # Builder
    "Spec",
    "K3Spec",
    "FieldDef",
    "PermitClause",
    "RequireClause",
    "MaintainClause",
    "ProjectionDef",
    "OutputDef",
    "KorrelatorDef",
    # Context & Result
    "SpecCtx",
    "Ok",
    "Impossible",
    "Violated",
    "Why",
    "WhyKind",
    "K3Result",
    # K3l (most common nodes)
    "LBool",
    "LInt",
    "LFloat",
    "LStr",
    "Var",
    "Field",
    "EventField",
    "Compare",
    "CmpOp",
    "Arith",
    "ArithOp",
    "And",
    "Or",
    "Not",
    "Implies",
    "ForAll",
    "Always",
    "Eventually",
    "Within",
    "Before",
    "After",
    "With",
    "Some",
    "Nothing",
    # Universe
    "universe",
    "Universe",
    "System",
    "parallel_reduce",
    "ParallelReduceResult",
    "ReduceAllResult",
    "ChunkSource",
    # Algebra
    "ComposedUniverse",
    "BridgedUniverse",
    "IsolatedUniverse",
    "BridgeMode",
    "RetryPolicy",
    "FallbackStrategy",
    # Testing
    "FuzzReport",
    "FuzzViolation",
    "ExplainResult",
    # Errors
    "K3Error",
    "K3NothingException",
    "K3ViolatedException",
    "K3WellFormednessError",
    "K3BridgeError",
    # Version
    "__version__",
]
