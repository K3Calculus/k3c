"""Tests for k3c.spec.extractor — Extractor types and integration with builder."""

from __future__ import annotations

import pytest

from k3c.lang.ir import Arith, ArithOp, LInt, TInt, TString, Var
from k3c.spec.builder import Spec
from k3c.spec.extractor import (
    AvroField,
    BitField,
    ByteSlice,
    ColumnIdx,
    ColumnName,
    Computed,
    Identity,
    JsonPath,
    MapKey,
    Switch,
    TextEncoding,
    XmlPath,
)


class TestTextEncoding:
    def test_all_variants(self):
        assert TextEncoding.ASCII == "ASCII"
        assert TextEncoding.UTF8 == "UTF-8"
        assert TextEncoding.LATIN1 == "LATIN-1"
        assert TextEncoding.EBCDIC == "EBCDIC"

    def test_is_str(self):
        assert isinstance(TextEncoding.ASCII, str)


class TestByteSlice:
    def test_construction(self):
        b = ByteSlice(start=2, length=3)
        assert b.start == 2
        assert b.length == 3
        assert b.encoding == TextEncoding.ASCII

    def test_custom_encoding(self):
        b = ByteSlice(start=0, length=10, encoding=TextEncoding.EBCDIC)
        assert b.encoding == TextEncoding.EBCDIC

    def test_frozen(self):
        b = ByteSlice(start=0, length=1)
        with pytest.raises(AttributeError):
            b.start = 5  # type: ignore[misc]


class TestBitField:
    def test_construction(self):
        b = BitField(byte_offset=0, bit_offset=5, width=11)
        assert b.byte_offset == 0
        assert b.bit_offset == 5
        assert b.width == 11

    def test_frozen(self):
        b = BitField(byte_offset=0, bit_offset=0, width=1)
        with pytest.raises(AttributeError):
            b.width = 8  # type: ignore[misc]


class TestJsonPath:
    def test_construction(self):
        j = JsonPath("$.carrier.iata_code")
        assert j.path == "$.carrier.iata_code"


class TestXmlPath:
    def test_construction(self):
        x = XmlPath("//carrier/@code")
        assert x.path == "//carrier/@code"


class TestMapKey:
    def test_construction(self):
        m = MapKey("airline_code")
        assert m.key == "airline_code"


class TestFieldNum:
    def test_construction(self):
        from k3c.spec.extractor import FieldNum

        f = FieldNum(3)
        assert f.number == 3


class TestAvroField:
    def test_construction(self):
        a = AvroField("airline_code")
        assert a.name == "airline_code"


class TestColumnName:
    def test_construction(self):
        c = ColumnName("airline_code")
        assert c.name == "airline_code"


class TestColumnIdx:
    def test_construction(self):
        c = ColumnIdx(2)
        assert c.index == 2


class TestComputed:
    def test_construction(self):
        expr = Arith(ArithOp.SUB, Var("departure"), Var("utc_offset"))
        c = Computed(expr=expr)
        assert c.expr == expr


class TestSwitch:
    def test_construction(self):
        s = Switch(
            discriminant=Var("packet_type"),
            cases=(
                (1, ByteSlice(start=0, length=4)),
                (2, ByteSlice(start=0, length=8)),
            ),
        )
        assert len(s.cases) == 2
        assert s.cases[0][0] == 1
        assert isinstance(s.cases[0][1], ByteSlice)


class TestIdentity:
    def test_construction(self):
        i = Identity()
        assert isinstance(i, Identity)


class TestBuilderIntegration:
    def test_field_with_byteslice(self):
        spec = (
            Spec("ssim")
            .state0({})
            .field("airline", TString(), extract=ByteSlice(start=2, length=3))
            .build()
        )
        assert spec.fields[0].extract == ByteSlice(start=2, length=3)

    def test_field_with_jsonpath(self):
        spec = (
            Spec("api")
            .state0({})
            .field("carrier_code", TString(), extract=JsonPath("$.carrier.iata_code"))
            .build()
        )
        assert isinstance(spec.fields[0].extract, JsonPath)

    def test_field_with_identity(self):
        spec = (
            Spec("typed")
            .state0({})
            .field("status", TString(), extract=Identity())
            .build()
        )
        assert isinstance(spec.fields[0].extract, Identity)

    def test_field_without_extractor(self):
        spec = Spec("plain").state0({}).field("x", TInt()).build()
        assert spec.fields[0].extract is None

    def test_field_with_computed(self):
        spec = (
            Spec("derived")
            .state0({})
            .field(
                "total",
                TInt(),
                extract=Computed(Arith(ArithOp.ADD, Var("price"), Var("tax"))),
            )
            .build()
        )
        assert isinstance(spec.fields[0].extract, Computed)

    def test_ssim_multiple_extractors(self):
        spec = (
            Spec("ssim")
            .state0({"phase": "START"})
            .field(
                "airline",
                TString(),
                description="IATA code",
                extract=ByteSlice(start=2, length=3),
            )
            .field("serial", TInt(), extract=ByteSlice(start=0, length=2))
            .field(
                "flags", TInt(), extract=BitField(byte_offset=10, bit_offset=0, width=8)
            )
            .build()
        )
        assert len(spec.fields) == 3
        assert isinstance(spec.fields[0].extract, ByteSlice)
        assert isinstance(spec.fields[1].extract, ByteSlice)
        assert isinstance(spec.fields[2].extract, BitField)

    def test_mixed_extractors_and_plain(self):
        spec = (
            Spec("mixed")
            .state0({})
            .field("extracted", TString(), extract=MapKey("code"))
            .field("plain", TInt())
            .field("computed", TInt(), extract=Computed(LInt(42)))
            .build()
        )
        assert spec.fields[0].extract is not None
        assert spec.fields[1].extract is None
        assert spec.fields[2].extract is not None
