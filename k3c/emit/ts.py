# k3c/emit/ts.py
"""Emit K3 expressions as TypeScript source code."""

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

_TS_CMP: dict[CmpOp, str] = {
    CmpOp.EQ: "===",
    CmpOp.NE: "!==",
    CmpOp.LT: "<",
    CmpOp.LE: "<=",
    CmpOp.GT: ">",
    CmpOp.GE: ">=",
}
_TS_ARITH: dict[ArithOp, str] = {
    ArithOp.ADD: "+",
    ArithOp.SUB: "-",
    ArithOp.MUL: "*",
    ArithOp.DIV: "/",
}


def _escape_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def to_typescript(expr: Expr) -> str:
    """Emit an Expr as TypeScript source code."""
    match expr:
        case LBool(val=v):
            return "true" if v else "false"
        case LInt(val=v) | LFloat(val=v):
            return str(v)
        case LStr(val=v):
            return f'"{_escape_str(v)}"'
        case LList(elements=elems):
            return f"[{', '.join(to_typescript(e) for e in elems)}]"
        case Var(name=n):
            return n
        case Field(expr=e, name=n):
            return f"{to_typescript(e)}.{n}"
        case Index(expr=e, idx=i):
            return f"{to_typescript(e)}[{i}]"
        case EventField(name=n):
            return f"event.{n}"
        case Actual(field=f):
            return f"actual.{f}"
        case Intended(field=f):
            return f"intended.{f}"
        case And(left=le, right=re):
            return f"({to_typescript(le)} && {to_typescript(re)})"
        case Or(left=le, right=re):
            return f"({to_typescript(le)} || {to_typescript(re)})"
        case Not(expr=e):
            return f"!{to_typescript(e)}"
        case If(cond=c, then=t, else_=e):
            return f"({to_typescript(c)} ? {to_typescript(t)} : {to_typescript(e)})"
        case Implies(left=le, right=re):
            return f"(!{to_typescript(le)} || {to_typescript(re)})"
        case Compare(op=op, left=le, right=re):
            return f"({to_typescript(le)} {_TS_CMP.get(op, '===')} {to_typescript(re)})"
        case Arith(op=op, left=le, right=re):
            return f"({to_typescript(le)} {_TS_ARITH.get(op, '+')} {to_typescript(re)})"
        case Mod(left=le, right=re):
            return f"({to_typescript(le)} % {to_typescript(re)})"
        case Negate(expr=e):
            return f"(-{to_typescript(e)})"
        case Abs(expr=e):
            return f"Math.abs({to_typescript(e)})"
        case Min(left=le, right=re):
            return f"Math.min({to_typescript(le)}, {to_typescript(re)})"
        case Max(left=le, right=re):
            return f"Math.max({to_typescript(le)}, {to_typescript(re)})"
        case IsSome(expr=e):
            return f"({to_typescript(e)} != null)"
        case UnwrapOr(expr=e, default=d):
            return f"({to_typescript(e)} ?? {to_typescript(d)})"
        case ForAll(var=v, collection=coll, predicate=pred):
            return f"{to_typescript(coll)}.every(({v}) => {to_typescript(pred)})"
        case Exists(var=v, collection=coll, predicate=pred):
            return f"{to_typescript(coll)}.some(({v}) => {to_typescript(pred)})"
        case Length(expr=e):
            return f"{to_typescript(e)}.length"
        case Contains(collection=coll, element=elem):
            return f"{to_typescript(coll)}.includes({to_typescript(elem)})"
        case Map(var=v, collection=coll, body=body):
            return f"{to_typescript(coll)}.map(({v}) => {to_typescript(body)})"
        case Filter(var=v, collection=coll, predicate=pred):
            return f"{to_typescript(coll)}.filter(({v}) => {to_typescript(pred)})"
        case Fold(init=init, collection=coll, acc_var=av, elem_var=ev, body=body):
            return f"{to_typescript(coll)}.reduce(({av}, {ev}) => {to_typescript(body)}, {to_typescript(init)})"
        case Concat(left=le, right=re):
            return f"({to_typescript(le)} + {to_typescript(re)})"
        case Trim(expr=e):
            return f"{to_typescript(e)}.trim()"
        case Slice(expr=e, start=s, end=en):
            return f"{to_typescript(e)}.slice({to_typescript(s)}, {to_typescript(en)})"
        case Matches(expr=e, pattern=pat):
            return f"/{pat}/.test({to_typescript(e)})"
        case Record(fields=fields):
            return f"{{ {', '.join(f'{n}: {to_typescript(e)}' for n, e in fields)} }}"
        case With(base=b, updates=updates):
            return f"{{ ...{to_typescript(b)}, {', '.join(f'{n}: {to_typescript(e)}' for n, e in updates)} }}"
        case Before(field=f):
            return f"before.{f}"
        case After(field=f):
            return f"after.{f}"
        case Always(expr=e):
            return to_typescript(e)
        case Eventually(expr=e):
            return f"/* eventually */ {to_typescript(e)}"
        case Within(expr=e, n=n):
            return f"/* within {n} steps */ {to_typescript(e)}"
        case Until(left=le, right=re):
            return f"/* {to_typescript(le)} until */ {to_typescript(re)}"
        case Named(expr=e) | Described(expr=e):
            return to_typescript(e)
        case unreachable:
            assert_never(unreachable)
