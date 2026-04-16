# k3c/ir/types.py
"""
Tier 1 - ExprType: what things ARE

The type system for K3 expressions. Used by the compiler, schema
validation, and well-formedness checks. Not used by eval() at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DateFormat(StrEnum):
    """Date format hints for TDate."""

    ISO8601 = "ISO8601"
    YYYYMMDD = "YYYYMMDD"
    SSIM = "SSIM"


class TimeFormat(StrEnum):
    """Time format hints for TTime."""

    ISO8601 = "ISO8601"
    HHMM = "HHMM"
    HHMMSS = "HHMMSS"


@dataclass(frozen=True)
class TBool:
    """Boolean type."""


@dataclass(frozen=True)
class TInt:
    """Integer type."""


@dataclass(frozen=True)
class TString:
    """String type."""


@dataclass(frozen=True)
class TFloat:
    """Floating-point type."""


@dataclass(frozen=True)
class TRecord:
    """Record type - named fields with typed values."""

    fields: dict[str, ExprType]


@dataclass(frozen=True)
class TVariant:
    """Tagged union type - one of several named alternatives."""

    variants: dict[str, ExprType]


@dataclass(frozen=True)
class TList:
    """Homogeneous list type."""

    element: ExprType


@dataclass(frozen=True)
class TOption:
    """Optional type - Some(T) or Nothing."""

    inner: ExprType


@dataclass(frozen=True)
class TRef:
    """Reference to a named type - for recursive or cross-referenced types."""

    name: str


@dataclass(frozen=True)
class TUnit:
    """Unit type - no value, used for side-effect-only events."""


@dataclass(frozen=True)
class TBytes:
    """Binary bytes type. length=None means variable-length."""

    length: int | None = None


@dataclass(frozen=True)
class TDate:
    """Date type with format hint."""

    format: DateFormat = DateFormat.ISO8601


@dataclass(frozen=True)
class TTime:
    """Time type with format hint."""

    format: TimeFormat = TimeFormat.ISO8601


@dataclass(frozen=True)
class TEnum:
    """Closed enumeration - one of a fixed set of string values."""

    values: tuple[str, ...]


type ExprType = (
    TBool
    | TInt
    | TString
    | TFloat
    | TUnit
    | TBytes
    | TDate
    | TTime
    | TEnum
    | TRecord
    | TVariant
    | TList
    | TOption
    | TRef
)
