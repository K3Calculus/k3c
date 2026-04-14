"""Tests for new K3l nodes — eval + serde round-trip for all ported nodes."""

from __future__ import annotations

import pytest

from k3c.lang.eval import k3_eval
from k3c.lang.ir import (
    Abs,
    Actual,
    Arith,
    ArithOp,
    CmpOp,
    Compare,
    Concat,
    Contains,
    Described,
    EventField,
    Exists,
    Field,
    Filter,
    Fold,
    ForAll,
    Implies,
    Index,
    Intended,
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
    Nothing,
    Record,
    Slice,
    Some,
    TBytes,
    TDate,
    TEnum,
    TTime,
    TUnit,
    Trim,
    Until,
    Var,
    With,
)
from k3c.lang.serde import from_dict, to_dict, type_from_dict, type_to_dict

HASH = "testhash12345678"


def _eval(expr, ctx=None):
    return k3_eval(expr, ctx or {}, HASH)


def _val(expr, ctx=None):
    result = _eval(expr, ctx)
    assert isinstance(result, Some), f"Expected Some, got {result!r}"
    return result.val


def _nothing(expr, ctx=None):
    result = _eval(expr, ctx)
    assert isinstance(result, Nothing), f"Expected Nothing, got {result!r}"
    return result


def _roundtrip(node):
    d = to_dict(node)
    restored = from_dict(d)
    assert restored == node, f"Round-trip failed: {node!r}"
    return d


def _type_roundtrip(node):
    d = type_to_dict(node)
    restored = type_from_dict(d)
    assert restored == node
    return d


class TestIndex:
    def test_list_access(self):
        assert _val(Index(Var("xs"), 1), {"xs": [10, 20, 30]}) == 20

    def test_first_element(self):
        assert _val(Index(Var("xs"), 0), {"xs": [99]}) == 99

    def test_out_of_bounds(self):
        n = _nothing(Index(Var("xs"), 5), {"xs": [1, 2]})
        assert n.field == "[5]"

    def test_negative_index_returns_nothing(self):
        n = _nothing(Index(Var("xs"), -1), {"xs": [1, 2]})
        assert "[" in n.field

    def test_nothing_propagates(self):
        n = _nothing(Index(Var("missing"), 0))
        assert n.field == "missing"

    def test_serde_roundtrip(self):
        _roundtrip(Index(Var("xs"), 2))


class TestEventField:
    def test_reads_from_event(self):
        ctx = {"event": {"amount": 100}}
        assert _val(EventField("amount"), ctx) == 100

    def test_missing_event_field(self):
        ctx = {"event": {"other": 1}}
        n = _nothing(EventField("amount"), ctx)
        assert n.field == "amount"

    def test_no_event_in_ctx(self):
        n = _nothing(EventField("x"))
        assert n.field == "event"

    def test_serde_roundtrip(self):
        _roundtrip(EventField("amount"))


class TestActualIntended:
    def test_actual(self):
        ctx = {"__actual__": {"balance": 100}}
        assert _val(Actual("balance"), ctx) == 100

    def test_intended(self):
        ctx = {"__intended__": {"balance": 200}}
        assert _val(Intended("balance"), ctx) == 200

    def test_actual_missing(self):
        n = _nothing(Actual("x"))
        assert "__actual__" in n.field or "x" in n.field

    def test_serde_roundtrip(self):
        _roundtrip(Actual("balance"))
        _roundtrip(Intended("status"))


class TestImplies:
    def test_true_implies_true(self):
        assert _val(Implies(LBool(True), LBool(True))) is True

    def test_true_implies_false(self):
        assert _val(Implies(LBool(True), LBool(False))) is False

    def test_false_implies_anything(self):
        assert _val(Implies(LBool(False), LBool(False))) is True
        assert _val(Implies(LBool(False), LBool(True))) is True

    def test_false_short_circuits(self):
        assert _val(Implies(LBool(False), Var("missing"))) is True

    def test_nothing_propagates(self):
        n = _nothing(Implies(Var("missing"), LBool(True)))
        assert n.field == "missing"

    def test_non_bool_returns_nothing(self):
        n = _nothing(Implies(LInt(1), LBool(True)))
        assert n.field == "expected-bool"

    def test_serde_roundtrip(self):
        _roundtrip(Implies(LBool(True), LBool(False)))


class TestMod:
    def test_basic(self):
        assert _val(Mod(LInt(10), LInt(3))) == 1

    def test_mod_by_zero(self):
        n = _nothing(Mod(LInt(10), LInt(0)))
        assert n.field == "mod-by-zero"

    def test_nothing_propagates(self):
        n = _nothing(Mod(Var("missing"), LInt(3)))
        assert n.field == "missing"

    def test_serde_roundtrip(self):
        _roundtrip(Mod(LInt(10), LInt(3)))


class TestNegate:
    def test_int(self):
        assert _val(Negate(LInt(5))) == -5

    def test_float(self):
        assert _val(Negate(LFloat(3.14))) == pytest.approx(-3.14)

    def test_non_numeric_returns_nothing(self):
        n = _nothing(Negate(LStr("x")))
        assert n.field == "expected-numeric"

    def test_serde_roundtrip(self):
        _roundtrip(Negate(LInt(5)))


class TestAbs:
    def test_positive(self):
        assert _val(Abs(LInt(5))) == 5

    def test_negative(self):
        assert _val(Abs(LInt(-5))) == 5

    def test_float(self):
        assert _val(Abs(LFloat(-2.5))) == pytest.approx(2.5)

    def test_non_numeric_returns_nothing(self):
        n = _nothing(Abs(LStr("x")))
        assert n.field == "expected-numeric"

    def test_serde_roundtrip(self):
        _roundtrip(Abs(LInt(-5)))


class TestMinMax:
    def test_min(self):
        assert _val(Min(LInt(3), LInt(7))) == 3

    def test_max(self):
        assert _val(Max(LInt(3), LInt(7))) == 7

    def test_nothing_propagates(self):
        n = _nothing(Min(Var("missing"), LInt(1)))
        assert n.field == "missing"

    def test_serde_roundtrip(self):
        _roundtrip(Min(LInt(1), LInt(2)))
        _roundtrip(Max(LInt(1), LInt(2)))


class TestForAll:
    def test_all_true(self):
        ctx = {"xs": [2, 4, 6]}
        expr = ForAll("x", Var("xs"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert _val(expr, ctx) is True

    def test_one_false(self):
        ctx = {"xs": [2, -1, 6]}
        expr = ForAll("x", Var("xs"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert _val(expr, ctx) is False

    def test_empty_list(self):
        ctx = {"xs": []}
        expr = ForAll("x", Var("xs"), LBool(False))
        assert _val(expr, ctx) is True  # vacuous truth

    def test_non_list_returns_nothing(self):
        ctx = {"xs": "not_a_list"}
        expr = ForAll("x", Var("xs"), LBool(True))
        n = _nothing(expr, ctx)
        assert n.field == "expected-list"

    def test_serde_roundtrip(self):
        _roundtrip(ForAll("x", Var("xs"), Compare(CmpOp.GT, Var("x"), LInt(0))))


class TestExists:
    def test_one_true(self):
        ctx = {"xs": [1, -1, 3]}
        expr = Exists("x", Var("xs"), Compare(CmpOp.LT, Var("x"), LInt(0)))
        assert _val(expr, ctx) is True

    def test_none_true(self):
        ctx = {"xs": [1, 2, 3]}
        expr = Exists("x", Var("xs"), Compare(CmpOp.LT, Var("x"), LInt(0)))
        assert _val(expr, ctx) is False

    def test_empty_list(self):
        ctx = {"xs": []}
        expr = Exists("x", Var("xs"), LBool(True))
        assert _val(expr, ctx) is False

    def test_serde_roundtrip(self):
        _roundtrip(Exists("x", Var("xs"), LBool(True)))


class TestLength:
    def test_list(self):
        assert _val(Length(Var("xs")), {"xs": [1, 2, 3]}) == 3

    def test_string(self):
        assert _val(Length(LStr("hello"))) == 5

    def test_empty(self):
        assert _val(Length(Var("xs")), {"xs": []}) == 0

    def test_non_sized_returns_nothing(self):
        n = _nothing(Length(LInt(42)))
        assert n.field == "expected-sized"

    def test_serde_roundtrip(self):
        _roundtrip(Length(Var("xs")))


class TestContains:
    def test_list_contains(self):
        ctx = {"xs": [1, 2, 3]}
        assert _val(Contains(Var("xs"), LInt(2)), ctx) is True

    def test_list_not_contains(self):
        ctx = {"xs": [1, 2, 3]}
        assert _val(Contains(Var("xs"), LInt(5)), ctx) is False

    def test_string_contains(self):
        assert _val(Contains(LStr("hello world"), LStr("world"))) is True

    def test_string_not_contains(self):
        assert _val(Contains(LStr("hello"), LStr("xyz"))) is False

    def test_serde_roundtrip(self):
        _roundtrip(Contains(Var("xs"), LInt(1)))


class TestMap:
    def test_basic(self):
        ctx = {"xs": [1, 2, 3]}
        expr = Map("x", Var("xs"), Arith(ArithOp.MUL, Var("x"), LInt(2)))
        assert _val(expr, ctx) == [2, 4, 6]

    def test_empty(self):
        ctx = {"xs": []}
        expr = Map("x", Var("xs"), Var("x"))
        assert _val(expr, ctx) == []

    def test_nothing_in_body_propagates(self):
        ctx = {"xs": [1, 2]}
        expr = Map("x", Var("xs"), Var("missing"))
        n = _nothing(expr, ctx)
        assert n.field == "missing"

    def test_serde_roundtrip(self):
        _roundtrip(Map("x", Var("xs"), Arith(ArithOp.ADD, Var("x"), LInt(1))))


class TestFilter:
    def test_basic(self):
        ctx = {"xs": [1, 2, 3, 4, 5]}
        expr = Filter("x", Var("xs"), Compare(CmpOp.GT, Var("x"), LInt(3)))
        assert _val(expr, ctx) == [4, 5]

    def test_none_pass(self):
        ctx = {"xs": [1, 2]}
        expr = Filter("x", Var("xs"), Compare(CmpOp.GT, Var("x"), LInt(10)))
        assert _val(expr, ctx) == []

    def test_serde_roundtrip(self):
        _roundtrip(Filter("x", Var("xs"), Compare(CmpOp.GT, Var("x"), LInt(0))))


class TestFold:
    def test_sum(self):
        ctx = {"xs": [1, 2, 3, 4]}
        expr = Fold(
            init=LInt(0),
            collection=Var("xs"),
            acc_var="acc",
            elem_var="x",
            body=Arith(ArithOp.ADD, Var("acc"), Var("x")),
        )
        assert _val(expr, ctx) == 10

    def test_empty_returns_init(self):
        ctx = {"xs": []}
        expr = Fold(LInt(99), Var("xs"), "acc", "x", Var("acc"))
        assert _val(expr, ctx) == 99

    def test_serde_roundtrip(self):
        _roundtrip(
            Fold(
                LInt(0), Var("xs"), "acc", "x", Arith(ArithOp.ADD, Var("acc"), Var("x"))
            )
        )


class TestConcat:
    def test_basic(self):
        assert _val(Concat(LStr("hello "), LStr("world"))) == "hello world"

    def test_non_string_returns_nothing(self):
        n = _nothing(Concat(LInt(1), LStr("x")))
        assert n.field == "expected-string"

    def test_serde_roundtrip(self):
        _roundtrip(Concat(LStr("a"), LStr("b")))


class TestTrim:
    def test_basic(self):
        assert _val(Trim(LStr("  hello  "))) == "hello"

    def test_no_whitespace(self):
        assert _val(Trim(LStr("hello"))) == "hello"

    def test_non_string_returns_nothing(self):
        n = _nothing(Trim(LInt(1)))
        assert n.field == "expected-string"

    def test_serde_roundtrip(self):
        _roundtrip(Trim(LStr("x")))


class TestSlice:
    def test_string(self):
        assert _val(Slice(LStr("hello"), LInt(1), LInt(4))) == "ell"

    def test_list(self):
        ctx = {"xs": [10, 20, 30, 40, 50]}
        assert _val(Slice(Var("xs"), LInt(1), LInt(3)), ctx) == [20, 30]

    def test_non_sliceable_returns_nothing(self):
        n = _nothing(Slice(LInt(1), LInt(0), LInt(1)))
        assert n.field == "expected-sliceable"

    def test_serde_roundtrip(self):
        _roundtrip(Slice(LStr("hello"), LInt(0), LInt(3)))


class TestMatches:
    def test_match(self):
        assert _val(Matches(LStr("hello123"), r"\d+")) is True

    def test_no_match(self):
        assert _val(Matches(LStr("hello"), r"\d+")) is False

    def test_full_pattern(self):
        assert _val(Matches(LStr("AB3"), r"^[A-Z0-9]{2,3}$")) is True

    def test_non_string_returns_nothing(self):
        n = _nothing(Matches(LInt(1), r"\d"))
        assert n.field == "expected-string"

    def test_serde_roundtrip(self):
        _roundtrip(Matches(LStr("x"), r"\d+"))


class TestRecord:
    def test_basic(self):
        expr = Record((("name", LStr("Alice")), ("age", LInt(30))))
        result = _val(expr)
        assert result == {"name": "Alice", "age": 30}

    def test_empty(self):
        assert _val(Record(())) == {}

    def test_nothing_in_field_propagates(self):
        expr = Record((("x", Var("missing")),))
        n = _nothing(expr)
        assert n.field == "missing"

    def test_serde_roundtrip(self):
        _roundtrip(Record((("a", LInt(1)), ("b", LStr("x")))))


class TestWith:
    def test_update_field(self):
        ctx = {"rec": {"a": 1, "b": 2}}
        expr = With(Var("rec"), (("b", LInt(99)),))
        result = _val(expr, ctx)
        assert result == {"a": 1, "b": 99}

    def test_add_field(self):
        ctx = {"rec": {"a": 1}}
        expr = With(Var("rec"), (("c", LInt(3)),))
        result = _val(expr, ctx)
        assert result == {"a": 1, "c": 3}

    def test_non_record_returns_nothing(self):
        n = _nothing(With(LInt(1), (("x", LInt(2)),)))
        assert n.field == "expected-record"

    def test_original_unchanged(self):
        original = {"a": 1, "b": 2}
        ctx = {"rec": original}
        _val(With(Var("rec"), (("b", LInt(99)),)), ctx)
        assert original == {"a": 1, "b": 2}

    def test_serde_roundtrip(self):
        _roundtrip(With(Var("rec"), (("a", LInt(1)),)))


class TestLList:
    def test_basic(self):
        expr = LList((LInt(1), LInt(2), LInt(3)))
        assert _val(expr) == [1, 2, 3]

    def test_empty(self):
        assert _val(LList(())) == []

    def test_mixed_types(self):
        expr = LList((LInt(1), LStr("x"), LBool(True)))
        assert _val(expr) == [1, "x", True]

    def test_nothing_in_element_propagates(self):
        expr = LList((LInt(1), Var("missing")))
        n = _nothing(expr)
        assert n.field == "missing"

    def test_serde_roundtrip(self):
        _roundtrip(LList((LInt(1), LStr("x"))))


class TestUntil:
    def test_evaluates_right(self):
        assert _val(Until(LBool(True), LBool(False))) is False

    def test_serde_roundtrip(self):
        _roundtrip(Until(LBool(True), LBool(False)))


class TestNamed:
    def test_transparent(self):
        assert _val(Named("my_rule", LInt(42))) == 42

    def test_serde_roundtrip(self):
        d = _roundtrip(Named("rule_1", LBool(True)))
        assert d["name"] == "rule_1"


class TestDescribed:
    def test_transparent(self):
        assert _val(Described("a docstring", LStr("val"))) == "val"

    def test_serde_roundtrip(self):
        d = _roundtrip(Described("docs here", LInt(1)))
        assert d["description"] == "docs here"


class TestNewTypeNodes:
    def test_tunit(self):
        _type_roundtrip(TUnit())

    def test_tbytes_fixed(self):
        d = _type_roundtrip(TBytes(length=200))
        assert d["length"] == 200

    def test_tbytes_variable(self):
        d = _type_roundtrip(TBytes())
        assert d["length"] is None

    def test_tdate(self):
        d = _type_roundtrip(TDate(format="YYYYMMDD"))
        assert d["format"] == "YYYYMMDD"

    def test_tdate_default(self):
        _type_roundtrip(TDate())

    def test_ttime(self):
        from k3c.lang.ir import TimeFormat

        _type_roundtrip(TTime(format=TimeFormat.HHMM))

    def test_tenum(self):
        d = _type_roundtrip(TEnum(values=("red", "green", "blue")))
        assert d["values"] == ["red", "green", "blue"]


class TestCompoundIntegration:
    def test_forall_with_field_access(self):
        """All items have quantity > 0."""
        ctx = {"items": [{"qty": 5}, {"qty": 3}, {"qty": 1}]}
        expr = ForAll(
            "item",
            Var("items"),
            Compare(CmpOp.GT, Field(Var("item"), "qty"), LInt(0)),
        )
        assert _val(expr, ctx) is True

    def test_map_then_fold_sum(self):
        """Sum of doubled values: sum([x*2 for x in xs])."""
        ctx = {"xs": [1, 2, 3]}
        doubled = Map("x", Var("xs"), Arith(ArithOp.MUL, Var("x"), LInt(2)))
        expr = Fold(
            LInt(0), doubled, "acc", "x", Arith(ArithOp.ADD, Var("acc"), Var("x"))
        )
        assert _val(expr, ctx) == 12

    def test_filter_then_length(self):
        """Count items above threshold."""
        ctx = {"xs": [1, 5, 3, 7, 2]}
        expr = Length(Filter("x", Var("xs"), Compare(CmpOp.GT, Var("x"), LInt(3))))
        assert _val(expr, ctx) == 2

    def test_record_with_computed_fields(self):
        ctx = {"x": 10, "y": 20}
        expr = Record(
            (
                ("sum", Arith(ArithOp.ADD, Var("x"), Var("y"))),
                ("product", Arith(ArithOp.MUL, Var("x"), Var("y"))),
            )
        )
        assert _val(expr, ctx) == {"sum": 30, "product": 200}

    def test_implies_with_forall(self):
        """∀ item: item.active ⇒ item.balance > 0"""
        ctx = {
            "items": [
                {"active": True, "balance": 100},
                {"active": False, "balance": -5},
                {"active": True, "balance": 50},
            ]
        }
        expr = ForAll(
            "item",
            Var("items"),
            Implies(
                Field(Var("item"), "active"),
                Compare(CmpOp.GT, Field(Var("item"), "balance"), LInt(0)),
            ),
        )
        assert _val(expr, ctx) is True

    def test_korrelation_pattern(self):
        """K.correlate: actual.balance == intended.balance"""
        ctx = {
            "__actual__": {"balance": 100},
            "__intended__": {"balance": 100},
        }
        expr = Compare(CmpOp.EQ, Actual("balance"), Intended("balance"))
        assert _val(expr, ctx) is True

    def test_korrelation_drift(self):
        ctx = {
            "__actual__": {"balance": 95},
            "__intended__": {"balance": 100},
        }
        expr = Compare(CmpOp.EQ, Actual("balance"), Intended("balance"))
        assert _val(expr, ctx) is False
