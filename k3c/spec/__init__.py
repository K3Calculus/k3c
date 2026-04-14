# k3c.spec — The Intent Layer
"""
K3.Specs: (I, U, K) specification framework.

Key exports:
    - Spec builder + K3Spec
    - Clause types (PermitClause, RequireClause, MaintainClause, ...)
    - SpecCtx — the ambient witness
    - K3Result (Ok, Impossible, Violated) + Why
    - Extractors for I.decode
"""

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
from k3c.spec.extractor import (
    AvroField,
    BitField,
    ByteSlice,
    ColumnIdx,
    ColumnName,
    Computed,
    Extractor,
    Identity,
    JsonPath,
    MapKey,
    Switch,
    TextEncoding,
    XmlPath,
)
from k3c.spec.result import Impossible, K3Result, Ok, Violated, Why, WhyKind

__all__ = [
    "Spec",
    "K3Spec",
    "SpecCtx",
    "FieldDef",
    "PermitClause",
    "RequireClause",
    "MaintainClause",
    "ProjectionDef",
    "OutputDef",
    "KorrelatorDef",
    "Ok",
    "Impossible",
    "Violated",
    "Why",
    "WhyKind",
    "K3Result",
    "ByteSlice",
    "BitField",
    "JsonPath",
    "XmlPath",
    "MapKey",
    "ColumnName",
    "ColumnIdx",
    "AvroField",
    "Computed",
    "Switch",
    "Identity",
    "TextEncoding",
    "Extractor",
]
