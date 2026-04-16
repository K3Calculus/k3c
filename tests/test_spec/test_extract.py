"""Tests for k3c.spec.extract -- extractors and DecodePlan execution."""

from __future__ import annotations

from k3c.spec.extract import (
    AvroField,
    ByteSlice,
    ColumnIdx,
    ColumnName,
    DecodeDispatch,
    DecodeFields,
    DecodeIdentity,
    Identity,
    MapKey,
    Switch,
    run_decode,
    run_extractor,
)


class TestByteSlice:
    def test_bytes_ascii(self):
        raw = b"ABCDEFGH"
        assert run_extractor(ByteSlice(start=2, length=3), raw) == "CDE"

    def test_bytes_with_trim(self):
        raw = b"AB  CD  "
        assert run_extractor(ByteSlice(start=2, length=4, trim=True), raw) == "CD"

    def test_bytes_without_trim(self):
        raw = b"AB  CD  "
        assert run_extractor(ByteSlice(start=2, length=4, trim=False), raw) == "  CD"

    def test_string_input(self):
        raw = "ABCDEFGH"
        assert run_extractor(ByteSlice(start=0, length=3), raw) == "ABC"

    def test_non_bytes_returns_none(self):
        assert run_extractor(ByteSlice(start=0, length=3), 42) is None


class TestMapKey:
    def test_present_key(self):
        assert run_extractor(MapKey("x"), {"x": 42, "y": 99}) == 42

    def test_missing_key(self):
        assert run_extractor(MapKey("z"), {"x": 42}) is None

    def test_non_dict(self):
        assert run_extractor(MapKey("x"), "not a dict") is None


class TestIdentity:
    def test_passthrough_dict(self):
        d = {"a": 1}
        assert run_extractor(Identity(), d) is d

    def test_passthrough_bytes(self):
        b = b"raw"
        assert run_extractor(Identity(), b) is b


class TestColumnIdx:
    def test_valid_index(self):
        assert run_extractor(ColumnIdx(index=1), [10, 20, 30]) == 20

    def test_out_of_bounds(self):
        assert run_extractor(ColumnIdx(index=5), [10]) is None


class TestColumnName:
    def test_present(self):
        assert run_extractor(ColumnName(name="x"), {"x": 42}) == 42

    def test_missing(self):
        assert run_extractor(ColumnName(name="z"), {"x": 42}) is None


class TestAvroField:
    def test_present(self):
        assert run_extractor(AvroField(name="code"), {"code": "AA"}) == "AA"


class TestSwitch:
    def test_dispatch(self):
        ext = Switch(
            discriminant=MapKey("type"),
            cases=(
                ("A", MapKey("a_val")),
                ("B", MapKey("b_val")),
            ),
        )
        assert run_extractor(ext, {"type": "A", "a_val": 10, "b_val": 20}) == 10
        assert run_extractor(ext, {"type": "B", "a_val": 10, "b_val": 20}) == 20

    def test_no_match(self):
        ext = Switch(discriminant=MapKey("type"), cases=(("A", MapKey("val")),))
        assert run_extractor(ext, {"type": "X", "val": 99}) is None


# -- DecodePlan ----------------------------------------------------------------


class TestDecodeIdentity:
    def test_dict_passthrough(self):
        result = run_decode(DecodeIdentity(), {"x": 1})
        assert result == {"x": 1}

    def test_non_dict_wraps(self):
        result = run_decode(DecodeIdentity(), "raw_string")
        assert result == {"__raw__": "raw_string"}


class TestDecodeFields:
    def test_byte_fields(self):
        plan = DecodeFields(
            fields=(
                ("type", ByteSlice(start=0, length=1)),
                ("code", ByteSlice(start=2, length=3)),
            )
        )
        result = run_decode(plan, b"A BCDEFG")
        assert result == {"type": "A", "code": "BCD"}

    def test_map_fields(self):
        plan = DecodeFields(
            fields=(
                ("name", MapKey("name")),
                ("age", MapKey("age")),
            )
        )
        result = run_decode(plan, {"name": "Alice", "age": 30, "extra": True})
        assert result == {"name": "Alice", "age": 30}


class TestDecodeDispatch:
    def test_dispatch_by_type(self):
        plan = DecodeDispatch(
            discriminant=ByteSlice(start=0, length=1),
            cases=(
                ("A", DecodeFields(fields=(("val", ByteSlice(start=2, length=3)),))),
                ("B", DecodeFields(fields=(("val", ByteSlice(start=2, length=5)),))),
            ),
        )
        result_a = run_decode(plan, b"A ABCDEFGH")
        assert result_a == {"val": "ABC"}

        result_b = run_decode(plan, b"B ABCDEFGH")
        assert result_b == {"val": "ABCDE"}

    def test_no_match_returns_raw(self):
        plan = DecodeDispatch(
            discriminant=MapKey("type"),
            cases=(("A", DecodeIdentity()),),
        )
        result = run_decode(plan, {"type": "X", "data": 1})
        assert result["__discriminant__"] == "X"
        assert result["data"] == 1


class TestDecodeNone:
    def test_none_plan_dict(self):
        result = run_decode(None, {"x": 1})
        assert result == {"x": 1}

    def test_none_plan_non_dict(self):
        result = run_decode(None, "raw")
        assert result == {"__raw__": "raw"}
