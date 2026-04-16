# k3c.spec — The Declarative Spec Layer
"""
K3.Specs: (I, U, K) specification framework.

Key exports:
    - Spec (frozen dataclass)
    - Clause types (Permit, Require, Maintain, Projection, Output, Korrelator)
    - Extractors and DecodePlan
    - compile_spec() -> CompiledSpec
"""

from k3c.spec.compile import (
    ClassifiedMaintain,
    CompiledSpec,
    MaintainKind,
    classify_maintain,
    compile_spec,
)
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
    Extractor,
    FieldNum,
    Identity,
    JsonPath,
    MapKey,
    Switch,
    TextEncoding,
    XmlPath,
    run_decode,
    run_extractor,
)
from k3c.spec.model import (
    CompareMode,
    FieldDef,
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
from k3c.spec.serde import (
    spec_from_dict,
    spec_to_dict,
)

__all__ = [
    "Spec",
    "FieldDef",
    "Permit",
    "Require",
    "Maintain",
    "Projection",
    "Output",
    "Korrelator",
    "CompareMode",
    "compile_spec",
    "CompiledSpec",
    "ClassifiedMaintain",
    "MaintainKind",
    "classify_maintain",
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
    "Extractor",
    "DecodeIdentity",
    "DecodeFields",
    "DecodeDispatch",
    "run_extractor",
    "run_decode",
    "Severity",
    "Validate",
    "spec_to_dict",
    "spec_from_dict",
]
