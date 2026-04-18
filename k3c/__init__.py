# k3c — Kulkarni Calculus Python SDK
"""
k3c: Design causality, and the system emerges.

Usage:
    from k3c import Spec, Permit, Maintain, Universe, Ok, Impossible, Violated

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

    u = Universe(spec=spec, transition=bank_transition)
    match u.apply({"type": "Withdraw", "amount": 50}):
        case Ok(state=s):       print(s["balance"])
        case Impossible(why):   print(why.message)
        case Violated(why):     why.raise_()
"""

# -- Spec model (declarative, no builder) --------------------------------------
from k3c.spec.model import (
    CompareMode,
    EventDef,
    FieldDef,
    Korrelator,
    Maintain,
    Migration,
    Output,
    Permit,
    Projection,
    Require,
    Severity,
    Spec,
    Validate,
)

# -- Extractors and decode plans -----------------------------------------------
from k3c.spec.extract import (
    AvroField,
    BitField,
    ByteSlice,
    ColumnIdx,
    ColumnName,
    Computed,
    DecodeDispatch,
    DecodeFields,
    DecodeIdentity,
    FieldNum,
    Identity,
    JsonPath,
    MapKey,
    Switch,
    TextEncoding,
    XmlPath,
)

# -- Engine context and results ------------------------------------------------
from k3c.engine.ctx import SpecCtx
from k3c.engine.result import (
    ErrorAction,
    ErrorHandler,
    Impossible,
    Ok,
    StepError,
    StepResult,
    Violated,
    Warning,
    Why,
    WhyKind,
)
from k3c.engine.step import TransitionFn, apply_step

# -- IR: expressions -----------------------------------------------------------
from k3c.ir.expr import (
    Abs,
    Actual,
    After,
    AllOf,
    Always,
    And,
    AnyOf,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    Concat,
    Contains,
    Described,
    EventField,
    Eventually,
    Exists,
    Expr,
    Field,
    Filter,
    Fold,
    ForAll,
    If,
    Implies,
    In,
    Index,
    Intended,
    IsSome,
    LBool,
    LFloat,
    LInt,
    LList,
    LNull,
    LStr,
    Length,
    Map,
    Matches,
    Max,
    Min,
    Mod,
    Named,
    Negate,
    Not,
    Or,
    Record,
    Slice,
    Str,
    Trim,
    Until,
    UnwrapOr,
    Var,
    With,
    Within,
)

# -- IR: option types ----------------------------------------------------------
from k3c.ir.value import K3Option, Nothing, Some

# -- IR: type system -----------------------------------------------------------
from k3c.ir.types import (
    DateFormat,
    ExprType,
    TBool,
    TBytes,
    TDate,
    TEnum,
    TFloat,
    TInt,
    TList,
    TOption,
    TRecord,
    TRef,
    TString,
    TTime,
    TUnit,
    TVariant,
    TimeFormat,
)

# -- Runtime -------------------------------------------------------------------
from k3c.runtime.universe import ReduceAllResult, Universe
from k3c.runtime.compose import (
    Applyable,
    ComposedUniverse,
    ManyUniverse,
    Pipeline,
    compose_many,
)
from k3c.runtime.embedded import EmbeddedRuntime, EmbeddedUniverse
from k3c.runtime.isolate import IsolatedUniverse
from k3c.runtime.parallel import ChunkResult, ChunkSource, ParallelReduceResult, parallel_reduce
from k3c.runtime.bridge import (
    BridgedUniverse,
    BridgeMode,
    FallbackStrategy,
    RetryPolicy,
)
from k3c.runtime.samsara import ReplayMismatch, ReplayResult, RunResult, TraceRecord

# -- Explain -------------------------------------------------------------------
from k3c.engine.explain import ExplainResult

# -- Testing -------------------------------------------------------------------
from k3c.testing.fuzz import FuzzReport, FuzzViolation

# -- Serde ---------------------------------------------------------------------
from k3c.ir.serde import from_dict as expr_from_dict
from k3c.ir.serde import to_dict as expr_to_dict
from k3c.ir.serde import type_from_dict, type_to_dict
from k3c.spec.serde import spec_from_dict, spec_to_dict

# -- Sugar ---------------------------------------------------------------------
from k3c.sugar import E, Q, S, SS, after, all_of, any_of, before, k3, lit

# -- Protocol DSL --------------------------------------------------------------
from k3c.protocol import Protocol

# -- Attestation (KC-6) --------------------------------------------------------
from k3c.attest import (
    AttestationBundle,
    Ed25519Signer,
    HmacSigner,
    SignedStep,
    Signer,
    VerifyResult,
    verify_bundle,
)

# -- Emit ----------------------------------------------------------------------
from k3c.emit import to_python, to_sql, to_typescript

# -- Errors --------------------------------------------------------------------
from k3c.errors import (
    K3BridgeError,
    K3Error,
    K3NothingException,
    K3ViolatedException,
    K3WellFormednessError,
)

from importlib.metadata import version as _version

__version__ = _version("k3c")

__all__ = [
    # Spec model
    "Spec",
    "FieldDef",
    "EventDef",
    "Permit",
    "Require",
    "Maintain",
    "Migration",
    "Validate",
    "Severity",
    "Projection",
    "Output",
    "Korrelator",
    "CompareMode",
    # Extractors
    "ByteSlice",
    "BitField",
    "JsonPath",
    "XmlPath",
    "MapKey",
    "FieldNum",
    "AvroField",
    "ColumnName",
    "ColumnIdx",
    "Computed",
    "Switch",
    "Identity",
    "TextEncoding",
    "DecodeIdentity",
    "DecodeFields",
    "DecodeDispatch",
    # Engine
    "SpecCtx",
    "Ok",
    "Impossible",
    "Violated",
    "Warning",
    "Why",
    "WhyKind",
    "StepResult",
    "StepError",
    "ErrorAction",
    "ErrorHandler",
    "TransitionFn",
    "apply_step",
    # Expressions
    "Expr",
    "LBool",
    "LInt",
    "LFloat",
    "LStr",
    "LNull",
    "LList",
    "Var",
    "Field",
    "Index",
    "EventField",
    "Actual",
    "Intended",
    "And",
    "Or",
    "Not",
    "If",
    "Implies",
    "AllOf",
    "AnyOf",
    "In",
    "Compare",
    "CmpOp",
    "Arith",
    "ArithOp",
    "Mod",
    "Negate",
    "Abs",
    "Min",
    "Max",
    "IsSome",
    "UnwrapOr",
    "ForAll",
    "Exists",
    "Length",
    "Contains",
    "Map",
    "Filter",
    "Fold",
    "Concat",
    "Trim",
    "Slice",
    "Str",
    "Matches",
    "Record",
    "With",
    "Before",
    "After",
    "Always",
    "Eventually",
    "Within",
    "Until",
    "Named",
    "Described",
    # Option types
    "Some",
    "Nothing",
    "K3Option",
    # Type system
    "ExprType",
    "DateFormat",
    "TimeFormat",
    "TBool",
    "TInt",
    "TString",
    "TFloat",
    "TUnit",
    "TBytes",
    "TDate",
    "TTime",
    "TEnum",
    "TRecord",
    "TVariant",
    "TList",
    "TOption",
    "TRef",
    # Runtime
    "Universe",
    "ReduceAllResult",
    "Applyable",
    "ComposedUniverse",
    "ManyUniverse",
    "Pipeline",
    "compose_many",
    "BridgedUniverse",
    "BridgeMode",
    "FallbackStrategy",
    "RetryPolicy",
    # Embedded runtime
    "EmbeddedRuntime",
    "EmbeddedUniverse",
    # Isolation
    "IsolatedUniverse",
    # Parallel
    "parallel_reduce",
    "ParallelReduceResult",
    "ChunkResult",
    "ChunkSource",
    # Samsara (KC-3)
    "TraceRecord",
    "RunResult",
    "ReplayResult",
    "ReplayMismatch",
    # Explain
    "ExplainResult",
    # Testing
    "FuzzReport",
    "FuzzViolation",
    # Serde
    "expr_to_dict",
    "expr_from_dict",
    "type_to_dict",
    "type_from_dict",
    "spec_to_dict",
    "spec_from_dict",
    # Sugar
    "S",
    "E",
    "SS",
    "Q",
    "k3",
    "lit",
    "all_of",
    "any_of",
    "before",
    "after",
    # Protocol
    "Protocol",
    # Attestation
    "Signer",
    "HmacSigner",
    "Ed25519Signer",
    "AttestationBundle",
    "SignedStep",
    "VerifyResult",
    "verify_bundle",
    # Emit
    "to_typescript",
    "to_sql",
    "to_python",
    # Errors
    "K3Error",
    "K3NothingException",
    "K3ViolatedException",
    "K3WellFormednessError",
    "K3BridgeError",
    # Version
    "__version__",
]
