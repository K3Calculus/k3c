# k3c.ir - The Expression Layer
"""
K3 IR: portable expression language for K3 specifications.

Key exports:
    - Expr nodes (LBool, LInt, Var, Field, Compare, Arith, Always, ...)
    - Option types (Some, Nothing)
    - ExprType nodes (TBool, TInt, TString, TRecord, ...)
    - Typed enums (CmpOp, ArithOp, DateFormat, TimeFormat)
    - k3_eval() total interpreter
    - to_dict() / from_dict() JSON serde
"""

from k3c.ir.eval import k3_eval
from k3c.ir.expr import (
    Abs,
    Actual,
    After,
    Always,
    And,
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
    Index,
    Intended,
    IsSome,
    LBool,
    LFloat,
    LInt,
    LList,
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
    Trim,
    Until,
    UnwrapOr,
    Var,
    With,
    Within,
)
from k3c.ir.serde import from_dict, to_dict, type_from_dict, type_to_dict
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
from k3c.ir.value import K3Option, Nothing, Some

__all__ = [
    # Evaluator
    "k3_eval",
    # Serde
    "to_dict",
    "from_dict",
    "type_to_dict",
    "type_from_dict",
    # Option types
    "Some",
    "Nothing",
    "K3Option",
    # Expression union
    "Expr",
    # Type union
    "ExprType",
    # Operator enums
    "CmpOp",
    "ArithOp",
    "DateFormat",
    "TimeFormat",
    # Literals
    "LBool",
    "LInt",
    "LFloat",
    "LStr",
    "LList",
    # Variables and access
    "Var",
    "Field",
    "Index",
    "EventField",
    "Actual",
    "Intended",
    # Logic
    "And",
    "Or",
    "Not",
    "If",
    "Implies",
    # Comparison and arithmetic
    "Compare",
    "Arith",
    "Mod",
    "Negate",
    "Abs",
    "Min",
    "Max",
    # Option operations
    "IsSome",
    "UnwrapOr",
    # Collections
    "ForAll",
    "Exists",
    "Length",
    "Contains",
    "Map",
    "Filter",
    "Fold",
    # String operations
    "Concat",
    "Trim",
    "Slice",
    "Matches",
    # Record construction
    "Record",
    "With",
    # Temporal
    "Before",
    "After",
    # Spec nodes
    "Always",
    "Eventually",
    "Within",
    "Until",
    # Annotation
    "Named",
    "Described",
    # Type nodes
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
]
