# k3c/spec/extract.py
"""
Extractors and DecodePlan -- portable field extraction from raw events.

An Extractor describes HOW to extract a domain field from a raw event.
It is data, not code -- serializable to JSON, transpilable to SQL/TLA+.

DecodePlan describes how to decode a raw event into a domain event.
It replaces the old callable-based I.decode.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from k3c.ir.expr import Expr

if TYPE_CHECKING:
    pass


class TextEncoding(StrEnum):
    """Text encoding for byte extraction."""

    ASCII = "ASCII"
    UTF8 = "UTF-8"
    LATIN1 = "LATIN-1"
    EBCDIC = "EBCDIC"


# -- Byte-level extraction -----------------------------------------------------


@dataclass(frozen=True)
class ByteSlice:
    """Extract a substring from fixed-width bytes.

    cast: optional type coercion for the extracted string.
          "int" -> int(), "float" -> float(), "bool" -> bool().
          None (default) -> return as string.
    """

    start: int
    length: int
    encoding: TextEncoding = TextEncoding.ASCII
    trim: bool = True
    cast: str | None = None


@dataclass(frozen=True)
class BitField:
    """Extract a bit field from binary data."""

    byte_offset: int
    bit_offset: int
    width: int


# -- Structured data extraction ------------------------------------------------


@dataclass(frozen=True)
class JsonPath:
    """Extract a value using a JSON path expression."""

    path: str


@dataclass(frozen=True)
class XmlPath:
    """Extract a value using an XPath expression."""

    path: str


@dataclass(frozen=True)
class MapKey:
    """Extract a value by dict/map key lookup."""

    key: str


# -- Schema-aware extraction ---------------------------------------------------


@dataclass(frozen=True)
class FieldNum:
    """Extract by protobuf field number."""

    number: int


@dataclass(frozen=True)
class AvroField:
    """Extract by Avro field name."""

    name: str


@dataclass(frozen=True)
class ColumnName:
    """Extract by SQL column name."""

    name: str


@dataclass(frozen=True)
class ColumnIdx:
    """Extract by SQL column index (zero-based)."""

    index: int


# -- Derived extraction --------------------------------------------------------


@dataclass(frozen=True)
class Computed:
    """Derive a field from an Expr over other extracted fields."""

    expr: Expr


@dataclass(frozen=True)
class Switch:
    """Discriminated extraction -- choose extractor based on a condition."""

    discriminant: Expr
    cases: tuple[tuple[object, Extractor], ...]


@dataclass(frozen=True)
class Identity:
    """No extraction needed -- raw value IS the domain value."""


# -- Extractor discriminated union ---------------------------------------------

type Extractor = (
    ByteSlice
    | BitField
    | JsonPath
    | XmlPath
    | MapKey
    | FieldNum
    | AvroField
    | ColumnName
    | ColumnIdx
    | Computed
    | Switch
    | Identity
)


# -- DecodePlan ----------------------------------------------------------------


@dataclass(frozen=True)
class DecodeIdentity:
    """No decoding needed -- raw event is already in domain form."""


@dataclass(frozen=True)
class DecodeFields:
    """Decode by extracting named fields from the raw event."""

    fields: tuple[tuple[str, Extractor], ...]


@dataclass(frozen=True)
class DecodeDispatch:
    """Decode by dispatching on a discriminant value.

    default: if set to "skip", unmatched events produce {"__skip__": True}
             which the engine can use to produce Impossible.
             If set to a DecodePlan, that plan is used for unmatched events.
             If None (default), unmatched events pass through with __discriminant__.
    """

    discriminant: Extractor
    cases: tuple[tuple[object, DecodePlan], ...]
    default: DecodePlan | str | None = None


type DecodePlan = DecodeIdentity | DecodeFields | DecodeDispatch


# -- Cast helper ---------------------------------------------------------------

_CAST_FNS: dict[str, type] = {"int": int, "float": float, "bool": bool}


def _apply_cast(val: str, cast_type: str | None) -> object:
    """Apply optional type coercion to an extracted string value."""
    if cast_type is None:
        return val
    fn = _CAST_FNS.get(cast_type)
    if fn is None:
        return val
    try:
        return fn(val)
    except (ValueError, TypeError):
        return None


# -- Extractor execution -------------------------------------------------------


def run_extractor(
    extractor: Extractor, raw: bytes | dict[str, object] | object
) -> object:
    """Execute an extractor against a raw input.

    Returns the extracted value.
    """
    match extractor:
        case ByteSlice(start=s, length=l, encoding=enc, trim=do_trim, cast=cast_type):
            if isinstance(raw, (bytes, bytearray)):
                chunk = raw[s : s + l]
                decoded = chunk.decode(enc.value)
                val = decoded.strip() if do_trim else decoded
            elif isinstance(raw, str):
                chunk = raw[s : s + l]
                val = chunk.strip() if do_trim else chunk
            else:
                return None
            return _apply_cast(val, cast_type)

        case BitField(byte_offset=bo, bit_offset=bi, width=w):
            if isinstance(raw, (bytes, bytearray)):
                # Extract bits from the byte array
                value = 0
                for i in range(w):
                    total_bit = (bo * 8) + bi + i
                    byte_idx = total_bit // 8
                    bit_idx = 7 - (total_bit % 8)
                    if byte_idx < len(raw):
                        value = (value << 1) | ((raw[byte_idx] >> bit_idx) & 1)
                return value
            return None

        case MapKey(key=k):
            if isinstance(raw, dict):
                return cast("dict[str, object]", raw).get(k)
            return None

        case JsonPath(path=p):
            if isinstance(raw, dict):
                # Simple dotted path: $.a.b.c
                parts = p.lstrip("$.").split(".")
                current: object = raw
                for part in parts:
                    if isinstance(current, dict):
                        current = current.get(part)
                    else:
                        return None
                return current
            return None

        case Identity():
            return raw

        case ColumnIdx(index=idx):
            if isinstance(raw, (list, tuple)) and 0 <= idx < len(raw):
                return raw[idx]
            return None

        case ColumnName(name=n):
            if isinstance(raw, dict):
                return cast("dict[str, object]", raw).get(n)
            return None

        case AvroField(name=n):
            if isinstance(raw, dict):
                return cast("dict[str, object]", raw).get(n)
            return None

        case FieldNum(number=_):
            # Protobuf field extraction requires protobuf runtime
            return None

        case XmlPath(path=_):
            # XML extraction requires lxml or similar
            return None

        case Computed(expr=_):
            # Computed requires k3_eval with a context -- handled at decode level
            return None

        case Switch(discriminant=disc, cases=cases):
            disc_val = run_extractor(disc, raw)
            for case_val, case_ext in cases:
                if disc_val == case_val:
                    return run_extractor(case_ext, raw)
            return None

    return None  # pragma: no cover


def run_decode(plan: DecodePlan | None, raw: object) -> dict[str, object]:
    """Execute a DecodePlan against a raw event.

    Returns the decoded domain event as a dict.
    If plan is None, assumes raw is already a dict.
    """
    if plan is None:
        if isinstance(raw, dict):
            return cast("dict[str, object]", raw)
        return {"__raw__": raw}

    match plan:
        case DecodeIdentity():
            if isinstance(raw, dict):
                return cast("dict[str, object]", raw)
            return {"__raw__": raw}

        case DecodeFields(fields=fields):
            result: dict[str, object] = {}
            # Two-pass: extract non-Computed first, then evaluate Computed
            computed: list[tuple[str, Computed]] = []
            for name, extractor in fields:
                if isinstance(extractor, Computed):
                    computed.append((name, extractor))
                else:
                    result[name] = run_extractor(extractor, raw)
            if computed:
                from k3c.ir.eval import k3_eval
                from k3c.ir.value import Some

                eval_ctx: dict[str, object] = {"event": result, "raw": raw}
                for name, comp in computed:
                    val = k3_eval(comp.expr, eval_ctx, "")
                    result[name] = val.val if isinstance(val, Some) else None
            return result

        case DecodeDispatch(discriminant=disc, cases=cases, default=default):
            disc_val = run_extractor(disc, raw)
            for case_val, sub_plan in cases:
                if disc_val == case_val:
                    return run_decode(sub_plan, raw)
            # No matching case -- apply default strategy
            if default == "skip":
                return {"__skip__": True, "__discriminant__": disc_val}
            if default is not None and not isinstance(default, str):
                return run_decode(default, raw)
            # Legacy: pass through with discriminant
            result = {"__discriminant__": disc_val}
            if isinstance(raw, dict):
                result.update(cast("dict[str, object]", raw))
            return result
