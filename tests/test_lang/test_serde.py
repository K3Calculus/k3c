"""Tests for k3c.lang.serde — K3l and K3lType round-trip serialization."""

from __future__ import annotations

import json

import pytest

from k3c.errors import K3SerdeError
from k3c.lang.ir import (
    After,
    Always,
    And,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    Eventually,
    Field,
    If,
    IsSome,
    LBool,
    LFloat,
    LInt,
    LStr,
    Not,
    Or,
    TBool,
    TFloat,
    TInt,
    TList,
    TOption,
    TRecord,
    TRef,
    TString,
    TVariant,
    UnwrapOr,
    Var,
    Within,
)
from k3c.lang.serde import from_dict, to_dict, type_from_dict, type_to_dict


# ── Helpers ──────────────────────────────────────────────────────────────────


def _roundtrip(node):
    """Serialize and deserialize — assert equality."""
    d = to_dict(node)
    restored = from_dict(d)
    assert restored == node, f"Round-trip failed: {node!r} != {restored!r}"
    return d


def _type_roundtrip(node):
    d = type_to_dict(node)
    restored = type_from_dict(d)
    assert restored == node
    return d


class TestLiterals:
    def test_bool_true(self):
        d = _roundtrip(LBool(True))
        assert d == {"type": "LBool", "val": True}

    def test_bool_false(self):
        _roundtrip(LBool(False))

    def test_int(self):
        d = _roundtrip(LInt(42))
        assert d == {"type": "LInt", "val": 42}

    def test_int_zero(self):
        _roundtrip(LInt(0))

    def test_int_negative(self):
        _roundtrip(LInt(-7))

    def test_float(self):
        d = _roundtrip(LFloat(3.14))
        assert d["val"] == pytest.approx(3.14)

    def test_string(self):
        d = _roundtrip(LStr("hello"))
        assert d == {"type": "LStr", "val": "hello"}

    def test_string_empty(self):
        _roundtrip(LStr(""))


class TestVariables:
    def test_var(self):
        d = _roundtrip(Var("balance"))
        assert d == {"type": "Var", "name": "balance"}

    def test_field(self):
        node = Field(Var("order"), "amount")
        d = _roundtrip(node)
        assert d["type"] == "Field"
        assert d["name"] == "amount"
        assert d["expr"] == {"type": "Var", "name": "order"}

    def test_nested_field(self):
        node = Field(Field(Var("a"), "b"), "c")
        _roundtrip(node)


class TestLogic:
    def test_and(self):
        _roundtrip(And(LBool(True), LBool(False)))

    def test_or(self):
        _roundtrip(Or(LBool(False), LBool(True)))

    def test_not(self):
        _roundtrip(Not(LBool(True)))

    def test_if(self):
        node = If(cond=LBool(True), then=LInt(1), else_=LInt(2))
        d = _roundtrip(node)
        assert d["type"] == "If"
        assert "cond" in d
        assert "then" in d
        assert "else_" in d


class TestCompareArith:
    def test_compare_eq(self):
        node = Compare(CmpOp.EQ, LInt(1), LInt(1))
        d = _roundtrip(node)
        assert d["op"] == "Eq"

    def test_compare_all_ops(self):
        for op in ("Eq", "Ne", "Lt", "Le", "Gt", "Ge"):
            _roundtrip(Compare(op, LInt(1), LInt(2)))

    def test_arith_add(self):
        _roundtrip(Arith(ArithOp.ADD, LInt(3), LInt(4)))

    def test_arith_all_ops(self):
        for op in ("Add", "Sub", "Mul", "Div"):
            _roundtrip(Arith(op, LFloat(1.0), LFloat(2.0)))


class TestOptionOps:
    def test_is_some(self):
        _roundtrip(IsSome(Var("x")))

    def test_unwrap_or(self):
        node = UnwrapOr(Var("x"), LInt(0))
        d = _roundtrip(node)
        assert d["type"] == "UnwrapOr"
        assert "default" in d


class TestTemporal:
    def test_before(self):
        d = _roundtrip(Before("status"))
        assert d == {"type": "Before", "field": "status"}

    def test_after(self):
        d = _roundtrip(After("balance"))
        assert d == {"type": "After", "field": "balance"}


class TestSpecNodes:
    def test_always(self):
        _roundtrip(Always(LBool(True)))

    def test_eventually(self):
        _roundtrip(Eventually(Compare(CmpOp.EQ, Var("status"), LStr("shipped"))))

    def test_within(self):
        node = Within(LBool(True), n=5)
        d = _roundtrip(node)
        assert d["n"] == 5


class TestCompoundRoundTrip:
    def test_guard_expression(self):
        """balance >= amount AND status == 'active'"""
        node = And(
            Compare(
                CmpOp.GE, Field(Var("state"), "balance"), Field(Var("event"), "amount")
            ),
            Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("active")),
        )
        _roundtrip(node)

    def test_maintain_clause(self):
        """Always(After(balance) == Before(balance) - event.amount)"""
        node = Always(
            Compare(
                CmpOp.EQ,
                After("balance"),
                Arith(ArithOp.SUB, Before("balance"), Field(Var("event"), "amount")),
            )
        )
        _roundtrip(node)

    def test_nested_if(self):
        node = If(
            Compare(CmpOp.GT, Var("x"), LInt(0)),
            Arith(ArithOp.MUL, Var("x"), LInt(2)),
            UnwrapOr(Var("default"), LInt(0)),
        )
        _roundtrip(node)


class TestJsonCompatibility:
    def test_json_serializable(self):
        node = And(Compare(CmpOp.GE, Var("x"), LInt(0)), LBool(True))
        d = to_dict(node)
        json_str = json.dumps(d, sort_keys=True)
        restored_dict = json.loads(json_str)
        restored = from_dict(restored_dict)
        assert restored == node

    def test_deterministic_output(self):
        node = Compare(CmpOp.EQ, Var("a"), Var("b"))
        d1 = to_dict(node)
        d2 = to_dict(node)
        assert d1 == d2
        assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)


class TestFromDictErrors:
    def test_missing_type_field(self):
        with pytest.raises(K3SerdeError, match="type"):
            from_dict({"val": 42})

    def test_non_string_type(self):
        with pytest.raises(K3SerdeError, match="type"):
            from_dict({"type": 123})

    def test_unknown_type(self):
        with pytest.raises(K3SerdeError, match="unknown node type"):
            from_dict({"type": "Bogus"})

    def test_lbool_wrong_val_type(self):
        with pytest.raises(K3SerdeError, match="expected bool"):
            from_dict({"type": "LBool", "val": 1})

    def test_lint_wrong_val_type(self):
        with pytest.raises(K3SerdeError, match="expected int"):
            from_dict({"type": "LInt", "val": "not_int"})

    def test_lint_rejects_bool(self):
        with pytest.raises(K3SerdeError, match="expected int"):
            from_dict({"type": "LInt", "val": True})

    def test_lfloat_wrong_val_type(self):
        with pytest.raises(K3SerdeError, match="expected float"):
            from_dict({"type": "LFloat", "val": "x"})

    def test_lfloat_rejects_bool(self):
        with pytest.raises(K3SerdeError, match="expected float"):
            from_dict({"type": "LFloat", "val": True})

    def test_lfloat_accepts_int(self):
        node = from_dict({"type": "LFloat", "val": 3})
        assert isinstance(node, LFloat)
        assert node.val == pytest.approx(3.0)

    def test_lstr_wrong_val_type(self):
        with pytest.raises(K3SerdeError, match="expected str"):
            from_dict({"type": "LStr", "val": 42})

    def test_var_missing_name(self):
        with pytest.raises(K3SerdeError, match="name"):
            from_dict({"type": "Var"})

    def test_field_missing_expr(self):
        with pytest.raises(K3SerdeError, match="expr"):
            from_dict({"type": "Field", "name": "x"})

    def test_and_missing_left(self):
        with pytest.raises(K3SerdeError, match="left"):
            from_dict({"type": "And", "right": {"type": "LBool", "val": True}})

    def test_compare_missing_op(self):
        with pytest.raises(K3SerdeError, match="op"):
            from_dict(
                {
                    "type": "Compare",
                    "left": {"type": "LInt", "val": 1},
                    "right": {"type": "LInt", "val": 2},
                }
            )

    def test_within_non_int_n(self):
        with pytest.raises(K3SerdeError, match="expected int"):
            from_dict(
                {
                    "type": "Within",
                    "expr": {"type": "LBool", "val": True},
                    "n": 3.5,
                }
            )

    def test_within_bool_n(self):
        with pytest.raises(K3SerdeError, match="expected int"):
            from_dict(
                {
                    "type": "Within",
                    "expr": {"type": "LBool", "val": True},
                    "n": True,
                }
            )

    def test_if_missing_else(self):
        with pytest.raises(K3SerdeError, match="else_"):
            from_dict(
                {
                    "type": "If",
                    "cond": {"type": "LBool", "val": True},
                    "then": {"type": "LInt", "val": 1},
                }
            )


class TestK3lTypePrimitives:
    def test_tbool(self):
        d = _type_roundtrip(TBool())
        assert d == {"type": "TBool"}

    def test_tint(self):
        _type_roundtrip(TInt())

    def test_tstring(self):
        _type_roundtrip(TString())

    def test_tfloat(self):
        _type_roundtrip(TFloat())

    def test_tref(self):
        d = _type_roundtrip(TRef("OrderId"))
        assert d == {"type": "TRef", "name": "OrderId"}


class TestK3lTypeCompound:
    def test_trecord(self):
        node = TRecord(fields={"name": TString(), "age": TInt()})
        d = _type_roundtrip(node)
        assert d["type"] == "TRecord"
        assert "name" in d["fields"]

    def test_tvariant(self):
        node = TVariant(variants={"ok": TInt(), "err": TString()})
        _type_roundtrip(node)

    def test_tlist(self):
        node = TList(element=TInt())
        _type_roundtrip(node)

    def test_toption(self):
        node = TOption(inner=TString())
        _type_roundtrip(node)

    def test_nested_types(self):
        node = TRecord(
            fields={
                "items": TList(
                    element=TRecord(fields={"id": TRef("ItemId"), "qty": TInt()})
                ),
                "total": TOption(inner=TFloat()),
            }
        )
        _type_roundtrip(node)


class TestK3lTypeErrors:
    def test_missing_type(self):
        with pytest.raises(K3SerdeError, match="type"):
            type_from_dict({"fields": {}})

    def test_unknown_type(self):
        with pytest.raises(K3SerdeError, match="unknown type node"):
            type_from_dict({"type": "TUnknown"})

    def test_trecord_missing_fields(self):
        with pytest.raises(K3SerdeError, match="fields"):
            type_from_dict({"type": "TRecord"})

    def test_tvariant_missing_variants(self):
        with pytest.raises(K3SerdeError, match="variants"):
            type_from_dict({"type": "TVariant"})

    def test_tlist_missing_element(self):
        with pytest.raises(K3SerdeError, match="element"):
            type_from_dict({"type": "TList"})

    def test_toption_missing_inner(self):
        with pytest.raises(K3SerdeError, match="inner"):
            type_from_dict({"type": "TOption"})

    def test_tref_missing_name(self):
        with pytest.raises(K3SerdeError, match="name"):
            type_from_dict({"type": "TRef"})
