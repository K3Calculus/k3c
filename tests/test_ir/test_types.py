"""Tests for k3c.ir.types — ExprType nodes."""

from __future__ import annotations

import pytest

from k3c.ir.types import (
    DateFormat,
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


class TestPrimitiveTypes:
    def test_tbool(self):
        assert TBool() == TBool()

    def test_tint(self):
        assert TInt() == TInt()

    def test_tstring(self):
        assert TString() == TString()

    def test_tfloat(self):
        assert TFloat() == TFloat()

    def test_tunit(self):
        assert TUnit() == TUnit()


class TestTBytes:
    def test_default_variable_length(self):
        assert TBytes().length is None

    def test_fixed_length(self):
        assert TBytes(length=4).length == 4


class TestTDate:
    def test_default_iso(self):
        assert TDate().format == DateFormat.ISO8601

    def test_ssim(self):
        assert TDate(format=DateFormat.SSIM).format == DateFormat.SSIM


class TestTTime:
    def test_default_iso(self):
        assert TTime().format == TimeFormat.ISO8601

    def test_hhmm(self):
        assert TTime(format=TimeFormat.HHMM).format == TimeFormat.HHMM


class TestTEnum:
    def test_values(self):
        e = TEnum(values=("A", "B", "C"))
        assert e.values == ("A", "B", "C")


class TestCompoundTypes:
    def test_trecord(self):
        t = TRecord(fields={"name": TString(), "age": TInt()})
        assert "name" in t.fields
        assert isinstance(t.fields["age"], TInt)

    def test_tvariant(self):
        t = TVariant(variants={"ok": TInt(), "err": TString()})
        assert "ok" in t.variants

    def test_tlist(self):
        t = TList(element=TInt())
        assert isinstance(t.element, TInt)

    def test_toption(self):
        t = TOption(inner=TString())
        assert isinstance(t.inner, TString)

    def test_tref(self):
        assert TRef("OrderId").name == "OrderId"


class TestNested:
    def test_deeply_nested(self):
        t = TRecord(
            fields={
                "items": TList(
                    element=TRecord(fields={"id": TRef("ItemId"), "qty": TInt()})
                ),
                "total": TOption(inner=TFloat()),
            }
        )
        assert isinstance(t.fields["items"], TList)
        inner = t.fields["items"].element
        assert isinstance(inner, TRecord)
        assert isinstance(inner.fields["id"], TRef)


class TestFrozen:
    def test_types_are_frozen(self):
        t = TBytes(length=4)
        with pytest.raises(AttributeError):
            t.length = 8  # type: ignore[misc]

    def test_hashable(self):
        s = {TBool(), TInt(), TString()}
        assert len(s) == 3
