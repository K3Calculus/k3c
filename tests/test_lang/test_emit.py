"""Tests for k3c.lang.emit — K3l to TypeScript/SQL/Python emitters."""

from __future__ import annotations


from k3c.lang.emit import to_python, to_sql, to_typescript
from k3c.lang.ir import (
    Abs,
    After,
    Always,
    And,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    Concat,
    Contains,
    EventField,
    Exists,
    Field,
    Filter,
    Fold,
    ForAll,
    If,
    Implies,
    Index,
    IsSome,
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
    Negate,
    Not,
    Or,
    Record,
    Slice,
    Trim,
    UnwrapOr,
    Var,
    With,
)


class TestTypeScriptLiterals:
    def test_bool(self):
        assert to_typescript(LBool(True)) == "true"
        assert to_typescript(LBool(False)) == "false"

    def test_int(self):
        assert to_typescript(LInt(42)) == "42"

    def test_float(self):
        assert to_typescript(LFloat(3.14)) == "3.14"

    def test_string(self):
        assert to_typescript(LStr("hello")) == '"hello"'

    def test_list(self):
        assert to_typescript(LList((LInt(1), LInt(2)))) == "[1, 2]"


class TestTypeScriptVariables:
    def test_var(self):
        assert to_typescript(Var("x")) == "x"

    def test_field(self):
        assert to_typescript(Field(Var("state"), "balance")) == "state.balance"

    def test_index(self):
        assert to_typescript(Index(Var("items"), 0)) == "items[0]"

    def test_event_field(self):
        assert to_typescript(EventField("amount")) == "event.amount"


class TestTypeScriptLogic:
    def test_and(self):
        assert to_typescript(And(LBool(True), LBool(False))) == "(true && false)"

    def test_or(self):
        assert to_typescript(Or(LBool(True), LBool(False))) == "(true || false)"

    def test_not(self):
        assert to_typescript(Not(LBool(True))) == "!true"

    def test_if(self):
        assert to_typescript(If(LBool(True), LInt(1), LInt(2))) == "(true ? 1 : 2)"

    def test_implies(self):
        assert to_typescript(Implies(LBool(True), LBool(False))) == "(!true || false)"


class TestTypeScriptComparison:
    def test_eq(self):
        result = to_typescript(Compare(CmpOp.EQ, Var("x"), LInt(0)))
        assert result == "(x === 0)"

    def test_ne(self):
        result = to_typescript(Compare(CmpOp.NE, Var("x"), LInt(0)))
        assert result == "(x !== 0)"

    def test_ge(self):
        result = to_typescript(
            Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount"))
        )
        assert result == "(state.balance >= event.amount)"


class TestTypeScriptArithmetic:
    def test_add(self):
        assert to_typescript(Arith(ArithOp.ADD, Var("x"), LInt(1))) == "(x + 1)"

    def test_div(self):
        assert to_typescript(Arith(ArithOp.DIV, Var("x"), LInt(2))) == "(x / 2)"

    def test_mod(self):
        assert to_typescript(Mod(Var("x"), LInt(3))) == "(x % 3)"

    def test_negate(self):
        assert to_typescript(Negate(Var("x"))) == "(-x)"

    def test_abs(self):
        assert to_typescript(Abs(Var("x"))) == "Math.abs(x)"

    def test_min_max(self):
        assert to_typescript(Min(Var("a"), Var("b"))) == "Math.min(a, b)"
        assert to_typescript(Max(Var("a"), Var("b"))) == "Math.max(a, b)"


class TestTypeScriptOption:
    def test_is_some(self):
        assert to_typescript(IsSome(Var("x"))) == "(x != null)"

    def test_unwrap_or(self):
        assert to_typescript(UnwrapOr(Var("x"), LInt(0))) == "(x ?? 0)"


class TestTypeScriptCollections:
    def test_for_all(self):
        expr = ForAll("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert to_typescript(expr) == "items.every((x) => (x > 0))"

    def test_exists(self):
        expr = Exists("x", Var("items"), Compare(CmpOp.LT, Var("x"), LInt(0)))
        assert to_typescript(expr) == "items.some((x) => (x < 0))"

    def test_length(self):
        assert to_typescript(Length(Var("items"))) == "items.length"

    def test_contains(self):
        assert to_typescript(Contains(Var("items"), LInt(5))) == "items.includes(5)"

    def test_map(self):
        expr = Map("x", Var("items"), Arith(ArithOp.MUL, Var("x"), LInt(2)))
        assert to_typescript(expr) == "items.map((x) => (x * 2))"

    def test_filter(self):
        expr = Filter("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        assert to_typescript(expr) == "items.filter((x) => (x > 0))"

    def test_fold(self):
        expr = Fold(
            LInt(0), Var("items"), "acc", "x", Arith(ArithOp.ADD, Var("acc"), Var("x"))
        )
        assert to_typescript(expr) == "items.reduce((acc, x) => (acc + x), 0)"


class TestTypeScriptString:
    def test_concat(self):
        assert to_typescript(Concat(LStr("a"), LStr("b"))) == '("a" + "b")'

    def test_trim(self):
        assert to_typescript(Trim(Var("s"))) == "s.trim()"

    def test_slice(self):
        assert to_typescript(Slice(Var("s"), LInt(1), LInt(3))) == "s.slice(1, 3)"

    def test_matches(self):
        assert to_typescript(Matches(Var("s"), r"\d+")) == r"/\d+/.test(s)"


class TestTypeScriptRecord:
    def test_record(self):
        result = to_typescript(Record((("a", LInt(1)), ("b", LStr("x")))))
        assert result == '{ a: 1, b: "x" }'

    def test_with(self):
        result = to_typescript(With(Var("state"), (("x", LInt(99)),)))
        assert result == "{ ...state, x: 99 }"


class TestTypeScriptTemporal:
    def test_before_after(self):
        assert to_typescript(Before("balance")) == "before.balance"
        assert to_typescript(After("balance")) == "after.balance"

    def test_always_transparent(self):
        assert to_typescript(Always(LBool(True))) == "true"


class TestTypeScriptCompound:
    def test_guard_expression(self):
        expr = And(
            Compare(CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")),
            Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("active")),
        )
        result = to_typescript(expr)
        assert "state.balance >= event.amount" in result
        assert 'state.status === "active"' in result
        assert "&&" in result

    def test_invariant_with_before_after(self):
        expr = Compare(
            CmpOp.EQ,
            After("balance"),
            Arith(ArithOp.SUB, Before("balance"), EventField("amount")),
        )
        result = to_typescript(expr)
        assert "after.balance" in result
        assert "before.balance" in result


class TestSQLBasic:
    def test_bool(self):
        assert to_sql(LBool(True)) == "TRUE"
        assert to_sql(LBool(False)) == "FALSE"

    def test_string(self):
        assert to_sql(LStr("hello")) == "'hello'"

    def test_comparison(self):
        assert to_sql(Compare(CmpOp.EQ, Var("x"), LInt(0))) == "(x = 0)"
        assert to_sql(Compare(CmpOp.NE, Var("x"), LInt(0))) == "(x <> 0)"

    def test_and_or(self):
        assert to_sql(And(LBool(True), LBool(False))) == "(TRUE AND FALSE)"
        assert to_sql(Or(LBool(True), LBool(False))) == "(TRUE OR FALSE)"

    def test_not(self):
        assert to_sql(Not(LBool(True))) == "NOT (TRUE)"

    def test_if_case(self):
        result = to_sql(If(LBool(True), LInt(1), LInt(2)))
        assert "CASE WHEN" in result
        assert "THEN" in result
        assert "ELSE" in result

    def test_is_some_coalesce(self):
        assert to_sql(IsSome(Var("x"))) == "(x IS NOT NULL)"
        assert to_sql(UnwrapOr(Var("x"), LInt(0))) == "COALESCE(x, 0)"

    def test_before_after_old_new(self):
        assert to_sql(Before("balance")) == "OLD.balance"
        assert to_sql(After("balance")) == "NEW.balance"

    def test_abs_min_max(self):
        assert to_sql(Abs(Var("x"))) == "ABS(x)"
        assert to_sql(Min(Var("a"), Var("b"))) == "LEAST(a, b)"
        assert to_sql(Max(Var("a"), Var("b"))) == "GREATEST(a, b)"

    def test_contains_in(self):
        assert to_sql(Contains(Var("items"), LInt(5))) == "(5 IN items)"

    def test_concat_pipe(self):
        assert to_sql(Concat(LStr("a"), LStr("b"))) == "('a' || 'b')"


class TestPythonBasic:
    def test_bool(self):
        assert to_python(LBool(True)) == "True"

    def test_string(self):
        assert to_python(LStr("hello")) == "'hello'"

    def test_field_bracket(self):
        assert to_python(Field(Var("state"), "balance")) == 'state["balance"]'

    def test_comparison(self):
        assert to_python(Compare(CmpOp.EQ, Var("x"), LInt(0))) == "(x == 0)"
        assert to_python(Compare(CmpOp.NE, Var("x"), LInt(0))) == "(x != 0)"

    def test_and_or(self):
        assert to_python(And(LBool(True), LBool(False))) == "(True and False)"
        assert to_python(Or(LBool(True), LBool(False))) == "(True or False)"

    def test_for_all(self):
        expr = ForAll("x", Var("items"), Compare(CmpOp.GT, Var("x"), LInt(0)))
        result = to_python(expr)
        assert "all(" in result
        assert "for x in items" in result

    def test_map(self):
        expr = Map("x", Var("items"), Arith(ArithOp.MUL, Var("x"), LInt(2)))
        result = to_python(expr)
        assert "for x in items" in result

    def test_record(self):
        result = to_python(Record((("a", LInt(1)), ("b", LStr("x")))))
        assert '"a": 1' in result
        assert "\"b\": 'x'" in result

    def test_before_after(self):
        assert to_python(Before("balance")) == 'prev_state["balance"]'
        assert to_python(After("balance")) == 'new_state["balance"]'


class TestComposeParallel:
    def test_parallel_mode_both(self):
        from k3c import Spec, universe, Ok, LBool

        spec_a = Spec("a").state0({"x": 0}).permit("ok", when=LBool(True)).build()
        spec_b = Spec("b").state0({"y": 0}).permit("ok", when=LBool(True)).build()

        class A:
            def transition(self, s, e):
                return {**s, "x": s["x"] + 1}

        class B:
            def transition(self, s, e):
                return {**s, "y": s["y"] + 1}

        ua = universe(A(), spec_a)
        ub = universe(B(), spec_b)
        composed = ua.compose(ub, lambda e: "both")

        r = composed.apply({"type": "Inc"}, mode="parallel")
        assert isinstance(r, Ok)
        assert composed.state["left"]["x"] == 1
        assert composed.state["right"]["y"] == 1

    def test_parallel_same_as_sequential(self):
        from k3c import Spec, universe, Ok, LBool

        spec = Spec("s").state0({"n": 0}).permit("ok", when=LBool(True)).build()

        class Counter:
            def transition(self, s, e):
                return {**s, "n": s["n"] + 1}

        u1 = universe(Counter(), spec)
        u2 = universe(Counter(), spec)
        seq = u1.compose(u2, lambda e: "both")

        u3 = universe(Counter(), spec)
        u4 = universe(Counter(), spec)
        par = u3.compose(u4, lambda e: "both")

        r_seq = seq.apply({"type": "X"}, mode="sequential")
        r_par = par.apply({"type": "X"}, mode="parallel")

        assert isinstance(r_seq, Ok)
        assert isinstance(r_par, Ok)
        assert seq.state == par.state

    def test_parallel_routing_left(self):
        from k3c import Spec, universe, Ok, LBool

        spec = Spec("s").state0({"n": 0}).permit("ok", when=LBool(True)).build()

        class Counter:
            def transition(self, s, e):
                return {**s, "n": s["n"] + 1}

        composed = universe(Counter(), spec).compose(
            universe(Counter(), spec), lambda e: "left"
        )
        r = composed.apply({"type": "X"}, mode="parallel")
        assert isinstance(r, Ok)
        assert composed.state["left"]["n"] == 1
        assert composed.state["right"]["n"] == 0
