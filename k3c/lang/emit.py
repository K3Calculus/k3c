# k3c/lang/emit.py
"""
Emit K3l expressions to target languages.

Write K3l once — all forms emerge.

Currently supported:
    to_typescript(expr) → TypeScript predicate / expression
    to_sql(expr)        → SQL WHERE / CHECK clause
    to_python(expr)     → Python source code

Each emitter is a recursive tree walk over K3l nodes.
"""

from __future__ import annotations

from typing import assert_never

from k3c.lang.ir import (
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
    Field,
    Filter,
    Fold,
    ForAll,
    If,
    Implies,
    Index,
    Intended,
    IsSome,
    K3l,
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
    UnwrapOr,
    Until,
    Var,
    With,
    Within,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  TypeScript
# ═══════════════════════════════════════════════════════════════════════════════

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


def to_typescript(expr: K3l) -> str:
    """Emit a K3l expression as TypeScript source code."""
    match expr:
        # Literals
        case LBool(val=v):
            return "true" if v else "false"
        case LInt(val=v) | LFloat(val=v):
            return str(v)
        case LStr(val=v):
            return f'"{_escape_str(v)}"'
        case LList(elements=elems):
            items = ", ".join(to_typescript(e) for e in elems)
            return f"[{items}]"

        # Variables
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

        # Logic
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

        # Comparison
        case Compare(op=op, left=le, right=re):
            ts_op = _TS_CMP.get(op, "===")
            return f"({to_typescript(le)} {ts_op} {to_typescript(re)})"

        # Arithmetic
        case Arith(op=op, left=le, right=re):
            ts_op = _TS_ARITH.get(op, "+")
            return f"({to_typescript(le)} {ts_op} {to_typescript(re)})"
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

        # Option operations
        case IsSome(expr=e):
            return f"({to_typescript(e)} != null)"
        case UnwrapOr(expr=e, default=d):
            return f"({to_typescript(e)} ?? {to_typescript(d)})"

        # Collections
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

        # String operations
        case Concat(left=le, right=re):
            return f"({to_typescript(le)} + {to_typescript(re)})"
        case Trim(expr=e):
            return f"{to_typescript(e)}.trim()"
        case Slice(expr=e, start=s, end=en):
            return f"{to_typescript(e)}.slice({to_typescript(s)}, {to_typescript(en)})"
        case Matches(expr=e, pattern=pat):
            return f"/{pat}/.test({to_typescript(e)})"

        # Record construction
        case Record(fields=fields):
            pairs = ", ".join(f"{n}: {to_typescript(e)}" for n, e in fields)
            return f"{{ {pairs} }}"
        case With(base=b, updates=updates):
            pairs = ", ".join(f"{n}: {to_typescript(e)}" for n, e in updates)
            return f"{{ ...{to_typescript(b)}, {pairs} }}"

        # Temporal
        case Before(field=f):
            return f"before.{f}"
        case After(field=f):
            return f"after.{f}"

        # Spec nodes — emit the inner expression
        case Always(expr=e):
            return to_typescript(e)
        case Eventually(expr=e):
            return f"/* eventually */ {to_typescript(e)}"
        case Within(expr=e, n=n):
            return f"/* within {n} steps */ {to_typescript(e)}"
        case Until(left=le, right=re):
            return f"/* {to_typescript(le)} until */ {to_typescript(re)}"

        # Annotation — transparent
        case Named(expr=e):
            return to_typescript(e)
        case Described(expr=e):
            return to_typescript(e)

        case unreachable:
            assert_never(unreachable)


# ═══════════════════════════════════════════════════════════════════════════════
#  SQL
# ═══════════════════════════════════════════════════════════════════════════════

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


def to_sql(expr: K3l) -> str:
    """Emit a K3l expression as a SQL expression (WHERE / CHECK clause)."""
    match expr:
        case LBool(val=v):
            return "TRUE" if v else "FALSE"
        case LInt(val=v) | LFloat(val=v):
            return str(v)
        case LStr(val=v):
            return f"'{_escape_sql(v)}'"
        case LList(elements=elems):
            items = ", ".join(to_sql(e) for e in elems)
            return f"({items})"

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
            sql_op = _SQL_CMP.get(op, "=")
            return f"({to_sql(le)} {sql_op} {to_sql(re)})"
        case Arith(op=op, left=le, right=re):
            sql_op = _SQL_ARITH.get(op, "+")
            return f"({to_sql(le)} {sql_op} {to_sql(re)})"
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


# ═══════════════════════════════════════════════════════════════════════════════
#  Python source
# ═══════════════════════════════════════════════════════════════════════════════


def to_python(expr: K3l) -> str:
    """Emit a K3l expression as Python source code."""
    match expr:
        case LBool(val=v):
            return "True" if v else "False"
        case LInt(val=v) | LFloat(val=v):
            return repr(v)
        case LStr(val=v):
            return repr(v)
        case LList(elements=elems):
            items = ", ".join(to_python(e) for e in elems)
            return f"[{items}]"

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
            pairs = ", ".join(f'"{n}": {to_python(e)}' for n, e in fields)
            return f"{{{pairs}}}"
        case With(base=b, updates=updates):
            pairs = ", ".join(f'"{n}": {to_python(e)}' for n, e in updates)
            return f"{{**{to_python(b)}, {pairs}}}"

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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _escape_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_sql(s: str) -> str:
    return s.replace("'", "''")
