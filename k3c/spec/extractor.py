# k3c/spec/extractor.py
"""
Extractors for I.decode — portable field extraction from raw events.

An Extractor describes HOW to extract a domain field from a raw event.
It is data, not code — serializable to JSON, transpilable to SQL/TLA+.

Each FieldDef in the builder can carry an optional Extractor. When present,
the engine uses it instead of a Python callable for I.decode.

The extractor discriminated union mirrors the OCaml k3l extractor type.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from k3c.lang.ir import K3l


class TextEncoding(StrEnum):
    """Text encoding for byte extraction."""

    ASCII = "ASCII"
    UTF8 = "UTF-8"
    LATIN1 = "LATIN-1"
    EBCDIC = "EBCDIC"


# ── Byte-level extraction ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ByteSlice:
    """Extract a substring from fixed-width bytes.

    Used by: SSIM, COBOL, binary protocols, CAN bus.
    Example: ByteSlice(start=2, length=3, encoding=TextEncoding.ASCII)
             extracts bytes[2:5] and decodes as ASCII.
    """

    start: int
    length: int
    encoding: TextEncoding = TextEncoding.ASCII


@dataclass(frozen=True)
class BitField:
    """Extract a bit field from binary data.

    Used by: CAN bus frames, TCP flags, binary protocols.
    Example: BitField(byte_offset=0, bit_offset=5, width=11)
             extracts 11 bits starting at byte 0, bit 5.
    """

    byte_offset: int
    bit_offset: int
    width: int


# ── Structured data extraction ──────────────────────────────────────────────


@dataclass(frozen=True)
class JsonPath:
    """Extract a value using a JSON path expression.

    Used by: REST APIs, JSON events.
    Example: JsonPath("$.carrier.iata_code")
    """

    path: str


@dataclass(frozen=True)
class XmlPath:
    """Extract a value using an XPath expression.

    Used by: SOAP, XML-based protocols.
    Example: XmlPath("//carrier/@iata_code")
    """

    path: str


@dataclass(frozen=True)
class MapKey:
    """Extract a value by dict/map key lookup.

    Used by: HL7 v2 (after segment split), generic dicts.
    Example: MapKey("airline_code")
    """

    key: str


# ── Schema-aware extraction ─────────────────────────────────────────────────


@dataclass(frozen=True)
class FieldNum:
    """Extract by protobuf field number.

    Used by: gRPC/protobuf messages.
    Example: FieldNum(3)
    """

    number: int


@dataclass(frozen=True)
class AvroField:
    """Extract by Avro field name.

    Used by: Kafka + Avro schema registry.
    Example: AvroField("airline_code")
    """

    name: str


@dataclass(frozen=True)
class ColumnName:
    """Extract by SQL column name.

    Used by: SQL result sets, database rows.
    Example: ColumnName("airline_code")
    """

    name: str


@dataclass(frozen=True)
class ColumnIdx:
    """Extract by SQL column index (zero-based).

    Used by: positional SQL result sets.
    Example: ColumnIdx(2)
    """

    index: int


# ── Derived extraction ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Computed:
    """Derive a field from a K3l expression over other extracted fields.

    Used by: calculated fields, cross-field derivations.
    Example: Computed(Arith(ArithOp.SUB, Var("departure"), Var("utc_offset")))
    """

    expr: K3l


@dataclass(frozen=True)
class Switch:
    """Discriminated extraction — choose extractor based on a condition.

    Used by: MQTT packet types, multi-format protocols.
    discriminant: K3l expression that produces the discriminating value.
    cases: mapping from discriminant value to extractor.
    """

    discriminant: K3l
    cases: tuple[tuple[object, Extractor], ...]


@dataclass(frozen=True)
class Identity:
    """No extraction needed — raw value IS the domain value.

    Used by: typed OCaml/Python records where the event is already in domain form.
    Zero cost — no parsing, no transformation.
    """


# ── Extractor discriminated union ───────────────────────────────────────────

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
