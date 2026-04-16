# k3c/emit/sql.py
"""Emit K3 expressions as SQL WHERE / CHECK clauses."""

from __future__ import annotations

from typing import assert_never

from k3c.ir.expr import (
    Abs,
    Actual,
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
    Described,
    Eventually,
    EventField,
    Exists,
    Expr,
    Field,
    Filter,
    Fold,
    ForAll,
    If,
    Implies,
    Index,
    Intended,
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
    Named,
    Negate,
    Not,
    Or,
    Record,
    Slice,
    Trim,
    Until,
    UnwrapOr,
    Var,
    With,
    Within,
)

_SQL_CMP: dict[CmpOp, str] = {
    CmpOp.EQ: "=",
    CmpOp.NE: "<>",
    CmpOp.LT: "<",
    CmpOp.LE: "<=",
    CmpOp.GT: ">",
    CmpOp.GE: ">=",
}
_SQL_ARITH: dict[ArithOp, str] = {
    ArithOp.ADD: "+",
    ArithOp.SUB: "-",
    ArithOp.MUL: "*",
    ArithOp.DIV: "/",
}


def _escape_sql(s: str) -> str:
    return s.replace("'", "''")


def to_sql(expr: Expr) -> str:
    """Emit an Expr as a SQL expression."""
    match expr:
        case LBool(val=v):
            return "TRUE" if v else "FALSE"
        case LInt(val=v) | LFloat(val=v):
            return str(v)
        case LStr(val=v):
            return f"'{_escape_sql(v)}'"
        case LList(elements=elems):
            return f"({', '.join(to_sql(e) for e in elems)})"
        case Var(name=n):
            return n
        case Field(expr=e, name=n):
            return f"{to_sql(e)}.{n}"
        case Index(expr=e, idx=i):
            return f"{to_sql(e)}[{i}]"
        case EventField(name=n):
            return f"event.{n}"
        case Actual(field=f):
            return f"actual.{f}"
        case Intended(field=f):
            return f"intended.{f}"
        case And(left=le, right=re):
            return f"({to_sql(le)} AND {to_sql(re)})"
        case Or(left=le, right=re):
            return f"({to_sql(le)} OR {to_sql(re)})"
        case Not(expr=e):
            return f"NOT ({to_sql(e)})"
        case If(cond=c, then=t, else_=e):
            return f"CASE WHEN {to_sql(c)} THEN {to_sql(t)} ELSE {to_sql(e)} END"
        case Implies(left=le, right=re):
            return f"(NOT ({to_sql(le)}) OR {to_sql(re)})"
        case Compare(op=op, left=le, right=re):
            return f"({to_sql(le)} {_SQL_CMP.get(op, '=')} {to_sql(re)})"
        case Arith(op=op, left=le, right=re):
            return f"({to_sql(le)} {_SQL_ARITH.get(op, '+')} {to_sql(re)})"
        case Mod(left=le, right=re):
            return f"({to_sql(le)} % {to_sql(re)})"
        case Negate(expr=e):
            return f"(-{to_sql(e)})"
        case Abs(expr=e):
            return f"ABS({to_sql(e)})"
        case Min(left=le, right=re):
            return f"LEAST({to_sql(le)}, {to_sql(re)})"
        case Max(left=le, right=re):
            return f"GREATEST({to_sql(le)}, {to_sql(re)})"
        case IsSome(expr=e):
            return f"({to_sql(e)} IS NOT NULL)"
        case UnwrapOr(expr=e, default=d):
            return f"COALESCE({to_sql(e)}, {to_sql(d)})"
        case Length(expr=e):
            return f"LENGTH({to_sql(e)})"
        case Contains(collection=coll, element=elem):
            return f"({to_sql(elem)} IN {to_sql(coll)})"
        case Concat(left=le, right=re):
            return f"({to_sql(le)} || {to_sql(re)})"
        case Trim(expr=e):
            return f"TRIM({to_sql(e)})"
        case Matches(expr=e, pattern=pat):
            return f"({to_sql(e)} ~ '{_escape_sql(pat)}')"
        case Before(field=f):
            return f"OLD.{f}"
        case After(field=f):
            return f"NEW.{f}"
        case Always(expr=e):
            return to_sql(e)
        case Eventually(expr=e):
            return f"/* eventually */ {to_sql(e)}"
        case Within(expr=e):
            return to_sql(e)
        case Until(right=re):
            return to_sql(re)
        case Named(expr=e) | Described(expr=e):
            return to_sql(e)
        case (
            ForAll()
            | Exists()
            | Map()
            | Filter()
            | Fold()
            | Slice()
            | Record()
            | With()
            | LList()
        ):
            return f"/* unsupported: {type(expr).__name__} */"
        case unreachable:
            assert_never(unreachable)


def to_python(expr: Expr) -> str:
    """Emit an Expr as Python source code."""
    match expr:
        case LBool(val=v):
            return "True" if v else "False"
        case LInt(val=v) | LFloat(val=v):
            return repr(v)
        case LStr(val=v):
            return repr(v)
        case LList(elements=elems):
            return f"[{', '.join(to_python(e) for e in elems)}]"
        case Var(name=n):
            return n
        case Field(expr=e, name=n):
            return f'{to_python(e)}["{n}"]'
        case Index(expr=e, idx=i):
            return f"{to_python(e)}[{i}]"
        case EventField(name=n):
            return f'event["{n}"]'
        case Actual(field=f):
            return f'actual["{f}"]'
        case Intended(field=f):
            return f'intended["{f}"]'
        case And(left=le, right=re):
            return f"({to_python(le)} and {to_python(re)})"
        case Or(left=le, right=re):
            return f"({to_python(le)} or {to_python(re)})"
        case Not(expr=e):
            return f"not {to_python(e)}"
        case If(cond=c, then=t, else_=e):
            return f"({to_python(t)} if {to_python(c)} else {to_python(e)})"
        case Implies(left=le, right=re):
            return f"(not {to_python(le)} or {to_python(re)})"
        case Compare(op=op, left=le, right=re):
            py_op = {
                "Eq": "==",
                "Ne": "!=",
                "Lt": "<",
                "Le": "<=",
                "Gt": ">",
                "Ge": ">=",
            }[str(op)]
            return f"({to_python(le)} {py_op} {to_python(re)})"
        case Arith(op=op, left=le, right=re):
            py_op = {"Add": "+", "Sub": "-", "Mul": "*", "Div": "/"}[str(op)]
            return f"({to_python(le)} {py_op} {to_python(re)})"
        case Mod(left=le, right=re):
            return f"({to_python(le)} % {to_python(re)})"
        case Negate(expr=e):
            return f"(-{to_python(e)})"
        case Abs(expr=e):
            return f"abs({to_python(e)})"
        case Min(left=le, right=re):
            return f"min({to_python(le)}, {to_python(re)})"
        case Max(left=le, right=re):
            return f"max({to_python(le)}, {to_python(re)})"
        case IsSome(expr=e):
            return f"({to_python(e)} is not None)"
        case UnwrapOr(expr=e, default=d):
            return f"({to_python(e)} if {to_python(e)} is not None else {to_python(d)})"
        case ForAll(var=v, collection=coll, predicate=pred):
            return f"all({to_python(pred)} for {v} in {to_python(coll)})"
        case Exists(var=v, collection=coll, predicate=pred):
            return f"any({to_python(pred)} for {v} in {to_python(coll)})"
        case Length(expr=e):
            return f"len({to_python(e)})"
        case Contains(collection=coll, element=elem):
            return f"({to_python(elem)} in {to_python(coll)})"
        case Map(var=v, collection=coll, body=body):
            return f"[{to_python(body)} for {v} in {to_python(coll)}]"
        case Filter(var=v, collection=coll, predicate=pred):
            return f"[{v} for {v} in {to_python(coll)} if {to_python(pred)}]"
        case Fold(init=init, collection=coll, acc_var=av, elem_var=ev, body=body):
            return f"functools.reduce(lambda {av}, {ev}: {to_python(body)}, {to_python(coll)}, {to_python(init)})"
        case Concat(left=le, right=re):
            return f"({to_python(le)} + {to_python(re)})"
        case Trim(expr=e):
            return f"{to_python(e)}.strip()"
        case Slice(expr=e, start=s, end=en):
            return f"{to_python(e)}[{to_python(s)}:{to_python(en)}]"
        case Matches(expr=e, pattern=pat):
            return f"bool(re.search({pat!r}, {to_python(e)}))"
        case Record(fields=fields):
            return f"{{{', '.join('"' + n + '": ' + to_python(e) for n, e in fields)}}}"
        case With(base=b, updates=updates):
            return f"{{**{to_python(b)}, {', '.join('"' + n + '": ' + to_python(e) for n, e in updates)}}}"
        case Before(field=f):
            return f'prev_state["{f}"]'
        case After(field=f):
            return f'new_state["{f}"]'
        case Always(expr=e) | Eventually(expr=e) | Within(expr=e):
            return to_python(e)
        case Until(right=re):
            return to_python(re)
        case Named(expr=e) | Described(expr=e):
            return to_python(e)
        case unreachable:
            assert_never(unreachable)
