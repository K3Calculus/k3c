# k3c/ir/eval.py
"""
Total interpreter for K3 expressions.

k3_eval() returns Some[object] | Nothing on every path. It never raises.
Nothing propagates through every operation - like NaN in IEEE 754.
And/Or short-circuit: the right side is never evaluated when the
left decides the outcome.
"""

from __future__ import annotations

import operator
import re as _regex
from typing import TYPE_CHECKING, assert_never, cast

from k3c.ir.expr import (
    Abs,
    Actual,
    After,
    AllOf,
    Always,
    And,
    AnyOf,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    Concat,
    Contains,
    Described,
    EventField,
    Eventually,
    Exists,
    Expr,
    Field,
    Filter,
    Fold,
    ForAll,
    If,
    Implies,
    In,
    Index,
    Intended,
    IsSome,
    LBool,
    Length,
    LFloat,
    LInt,
    LList,
    LNull,
    LStr,
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
    Str,
    Trim,
    Until,
    UnwrapOr,
    Var,
    With,
    Within,
)
from k3c.ir.value import K3Option, Nothing, Some

if TYPE_CHECKING:
    from typing import Any

# -- Operator dispatch tables --------------------------------------------------

_CMP_OPS: dict[CmpOp, Any] = {
    CmpOp.EQ: operator.eq,
    CmpOp.NE: operator.ne,
    CmpOp.LT: operator.lt,
    CmpOp.LE: operator.le,
    CmpOp.GT: operator.gt,
    CmpOp.GE: operator.ge,
}

_ARITH_OPS: dict[ArithOp, Any] = {
    ArithOp.ADD: operator.add,
    ArithOp.SUB: operator.sub,
    ArithOp.MUL: operator.mul,
}

# -- Shorthand type ------------------------------------------------------------

type _Res = K3Option[object]

# -- Eval helpers --------------------------------------------------------------


def _nothing(field: str, sh: str) -> Nothing:
    return Nothing(field=field, step_hash=sh)


def _expect_bool(result: Some[object], sh: str) -> _Res:
    if isinstance(result.val, bool):
        return result
    return _nothing("expected-bool", sh)


def _unwrap(expr: Expr, ctx: dict[str, object], sh: str) -> Some[object] | Nothing:
    """Eval and return; caller checks for Nothing."""
    return k3_eval(expr, ctx, sh)


def _expect_list(result: Some[object], sh: str) -> list[object] | Nothing:
    if isinstance(result.val, (list, tuple)):
        return list(result.val)
    return _nothing("expected-list", sh)


# -- Extracted handlers --------------------------------------------------------


def _eval_field(base: Expr, name: str, ctx: dict[str, object], sh: str) -> _Res:
    result = k3_eval(base, ctx, sh)
    if isinstance(result, Nothing):
        return result
    raw = result.val
    if not isinstance(raw, dict):
        return _nothing(name, sh)
    val = cast("dict[str, object]", raw)
    if name in val:
        return Some(val[name])
    return _nothing(name, sh)


def _eval_and(le: Expr, re: Expr, ctx: dict[str, object], sh: str) -> _Res:
    left = k3_eval(le, ctx, sh)
    if isinstance(left, Nothing):
        return left
    checked = _expect_bool(left, sh)
    if isinstance(checked, Nothing):
        return checked
    if checked.val is False:
        return Some(False)
    right = k3_eval(re, ctx, sh)
    if isinstance(right, Nothing):
        return right
    return _expect_bool(right, sh)


def _eval_or(le: Expr, re: Expr, ctx: dict[str, object], sh: str) -> _Res:
    left = k3_eval(le, ctx, sh)
    if isinstance(left, Nothing):
        return left
    checked = _expect_bool(left, sh)
    if isinstance(checked, Nothing):
        return checked
    if checked.val is True:
        return Some(True)
    right = k3_eval(re, ctx, sh)
    if isinstance(right, Nothing):
        return right
    return _expect_bool(right, sh)


def _eval_not(expr: Expr, ctx: dict[str, object], sh: str) -> _Res:
    result = k3_eval(expr, ctx, sh)
    if isinstance(result, Nothing):
        return result
    checked = _expect_bool(result, sh)
    if isinstance(checked, Nothing):
        return checked
    return Some(not checked.val)


def _eval_if(c: Expr, t: Expr, e: Expr, ctx: dict[str, object], sh: str) -> _Res:
    cond = k3_eval(c, ctx, sh)
    if isinstance(cond, Nothing):
        return cond
    checked = _expect_bool(cond, sh)
    if isinstance(checked, Nothing):
        return checked
    return k3_eval(t, ctx, sh) if checked.val is True else k3_eval(e, ctx, sh)


def _eval_implies(le: Expr, re: Expr, ctx: dict[str, object], sh: str) -> _Res:
    left = k3_eval(le, ctx, sh)
    if isinstance(left, Nothing):
        return left
    checked = _expect_bool(left, sh)
    if isinstance(checked, Nothing):
        return checked
    if checked.val is False:
        return Some(True)
    return k3_eval(re, ctx, sh)


def _eval_all_of(exprs: tuple[Expr, ...], ctx: dict[str, object], sh: str) -> _Res:
    """Variadic AND. Short-circuits on False or Nothing."""
    for e in exprs:
        result = k3_eval(e, ctx, sh)
        if isinstance(result, Nothing):
            return result
        if result.val is False:
            return Some(False)
    return Some(True)


def _eval_any_of(exprs: tuple[Expr, ...], ctx: dict[str, object], sh: str) -> _Res:
    """Variadic OR. Short-circuits on True."""
    for e in exprs:
        result = k3_eval(e, ctx, sh)
        if isinstance(result, Nothing):
            return result
        if result.val is True:
            return Some(True)
    return Some(False)


def _eval_in(expr: Expr, vals: tuple[Expr, ...], ctx: dict[str, object], sh: str) -> _Res:
    """Membership test: expr in values."""
    target = k3_eval(expr, ctx, sh)
    if isinstance(target, Nothing):
        return target
    for v in vals:
        vr = k3_eval(v, ctx, sh)
        if isinstance(vr, Nothing):
            continue
        if target.val == vr.val:
            return Some(True)
    return Some(False)


def _eval_binary(fn: Any, le: Expr, re: Expr, ctx: dict[str, object], sh: str) -> _Res:
    lv = k3_eval(le, ctx, sh)
    if isinstance(lv, Nothing):
        return lv
    rv = k3_eval(re, ctx, sh)
    if isinstance(rv, Nothing):
        return rv
    try:
        return Some(fn(lv.val, rv.val))
    except TypeError:
        return _nothing("type-error", sh)


def _eval_div(le: Expr, re: Expr, ctx: dict[str, object], sh: str) -> _Res:
    lv = k3_eval(le, ctx, sh)
    if isinstance(lv, Nothing):
        return lv
    rv = k3_eval(re, ctx, sh)
    if isinstance(rv, Nothing):
        return rv
    if isinstance(rv.val, (int, float)) and rv.val == 0:
        return _nothing("div-by-zero", sh)
    try:
        return Some(operator.truediv(lv.val, rv.val))
    except TypeError:
        return _nothing("type-error", sh)


def _eval_mod(le: Expr, re: Expr, ctx: dict[str, object], sh: str) -> _Res:
    lv = k3_eval(le, ctx, sh)
    if isinstance(lv, Nothing):
        return lv
    rv = k3_eval(re, ctx, sh)
    if isinstance(rv, Nothing):
        return rv
    if isinstance(rv.val, (int, float)) and rv.val == 0:
        return _nothing("mod-by-zero", sh)
    try:
        return Some(operator.mod(lv.val, rv.val))
    except TypeError:
        return _nothing("type-error", sh)


def _eval_unary_numeric(expr: Expr, fn: Any, ctx: dict[str, object], sh: str) -> _Res:
    result = k3_eval(expr, ctx, sh)
    if isinstance(result, Nothing):
        return result
    if not isinstance(result.val, (int, float)):
        return _nothing("expected-numeric", sh)
    return Some(fn(result.val))


def _eval_temporal(ctx: dict[str, object], key: str, field: str, sh: str) -> _Res:
    prefix = {"__prev_state__": "before", "__new_state__": "after"}.get(key, key)
    raw = ctx.get(key)
    if not isinstance(raw, dict):
        return _nothing(f"{prefix}.{field}", sh)
    source = cast("dict[str, object]", raw)
    if field in source:
        return Some(source[field])
    return _nothing(f"{prefix}.{field}", sh)


def _eval_index(expr: Expr, idx: int, ctx: dict[str, object], sh: str) -> _Res:
    result = k3_eval(expr, ctx, sh)
    if isinstance(result, Nothing):
        return result
    if isinstance(result.val, (list, tuple)) and 0 <= idx < len(result.val):
        return Some(result.val[idx])
    return _nothing(f"[{idx}]", sh)


def _eval_quantifier(
    var: str,
    coll: Expr,
    pred: Expr,
    ctx: dict[str, object],
    sh: str,
    *,
    is_forall: bool,
) -> _Res:
    coll_r = k3_eval(coll, ctx, sh)
    if isinstance(coll_r, Nothing):
        return coll_r
    items = _expect_list(coll_r, sh)
    if isinstance(items, Nothing):
        return items
    for item in items:
        result = k3_eval(pred, {**ctx, var: item}, sh)
        if isinstance(result, Nothing):
            return result
        checked = _expect_bool(result, sh)
        if isinstance(checked, Nothing):
            return checked
        if is_forall and checked.val is False:
            return Some(False)
        if not is_forall and checked.val is True:
            return Some(True)
    return Some(True if is_forall else False)


def _eval_length(expr: Expr, ctx: dict[str, object], sh: str) -> _Res:
    result = k3_eval(expr, ctx, sh)
    if isinstance(result, Nothing):
        return result
    if isinstance(result.val, (list, tuple, str)):
        return Some(len(result.val))
    return _nothing("expected-sized", sh)


def _eval_contains(coll: Expr, elem: Expr, ctx: dict[str, object], sh: str) -> _Res:
    cv = k3_eval(coll, ctx, sh)
    if isinstance(cv, Nothing):
        return cv
    ev = k3_eval(elem, ctx, sh)
    if isinstance(ev, Nothing):
        return ev
    if isinstance(cv.val, (list, tuple)):
        return Some(ev.val in cv.val)
    if isinstance(cv.val, str) and isinstance(ev.val, str):
        return Some(ev.val in cv.val)
    return _nothing("expected-collection", sh)


def _eval_map(
    var: str, coll: Expr, body: Expr, ctx: dict[str, object], sh: str
) -> _Res:
    coll_r = k3_eval(coll, ctx, sh)
    if isinstance(coll_r, Nothing):
        return coll_r
    items = _expect_list(coll_r, sh)
    if isinstance(items, Nothing):
        return items
    results = []
    for item in items:
        result = k3_eval(body, {**ctx, var: item}, sh)
        if isinstance(result, Nothing):
            return result
        results.append(result.val)
    return Some(results)


def _eval_filter(
    var: str, coll: Expr, pred: Expr, ctx: dict[str, object], sh: str
) -> _Res:
    coll_r = k3_eval(coll, ctx, sh)
    if isinstance(coll_r, Nothing):
        return coll_r
    items = _expect_list(coll_r, sh)
    if isinstance(items, Nothing):
        return items
    results = []
    for item in items:
        result = k3_eval(pred, {**ctx, var: item}, sh)
        if isinstance(result, Nothing):
            return result
        checked = _expect_bool(result, sh)
        if isinstance(checked, Nothing):
            return checked
        if checked.val is True:
            results.append(item)
    return Some(results)


def _eval_fold(
    init: Expr,
    coll: Expr,
    acc_var: str,
    elem_var: str,
    body: Expr,
    ctx: dict[str, object],
    sh: str,
) -> _Res:
    acc = k3_eval(init, ctx, sh)
    if isinstance(acc, Nothing):
        return acc
    coll_r = k3_eval(coll, ctx, sh)
    if isinstance(coll_r, Nothing):
        return coll_r
    items = _expect_list(coll_r, sh)
    if isinstance(items, Nothing):
        return items
    for item in items:
        acc = k3_eval(body, {**ctx, acc_var: acc.val, elem_var: item}, sh)
        if isinstance(acc, Nothing):
            return acc
    return acc


def _eval_concat(le: Expr, re: Expr, ctx: dict[str, object], sh: str) -> _Res:
    lv = k3_eval(le, ctx, sh)
    if isinstance(lv, Nothing):
        return lv
    rv = k3_eval(re, ctx, sh)
    if isinstance(rv, Nothing):
        return rv
    # Auto-coerce non-string operands so denied=Concat(LStr, Field) "just works"
    return Some(str(lv.val) + str(rv.val))


def _eval_trim(expr: Expr, ctx: dict[str, object], sh: str) -> _Res:
    result = k3_eval(expr, ctx, sh)
    if isinstance(result, Nothing):
        return result
    if isinstance(result.val, str):
        return Some(result.val.strip())
    return _nothing("expected-string", sh)


def _eval_slice(
    expr: Expr, start: Expr, end: Expr, ctx: dict[str, object], sh: str
) -> _Res:
    ev = k3_eval(expr, ctx, sh)
    if isinstance(ev, Nothing):
        return ev
    sv = k3_eval(start, ctx, sh)
    if isinstance(sv, Nothing):
        return sv
    env = k3_eval(end, ctx, sh)
    if isinstance(env, Nothing):
        return env
    if isinstance(ev.val, (str, list, tuple)):
        return Some(ev.val[sv.val : env.val])
    return _nothing("expected-sliceable", sh)


def _eval_matches(expr: Expr, pattern: str, ctx: dict[str, object], sh: str) -> _Res:
    result = k3_eval(expr, ctx, sh)
    if isinstance(result, Nothing):
        return result
    if isinstance(result.val, str):
        return Some(bool(_regex.search(pattern, result.val)))
    return _nothing("expected-string", sh)


def _eval_record(
    fields: tuple[tuple[str, Expr], ...], ctx: dict[str, object], sh: str
) -> _Res:
    result_dict: dict[str, object] = {}
    for name, expr in fields:
        val = k3_eval(expr, ctx, sh)
        if isinstance(val, Nothing):
            return val
        result_dict[name] = val.val
    return Some(result_dict)


def _eval_with(
    base: Expr, updates: tuple[tuple[str, Expr], ...], ctx: dict[str, object], sh: str
) -> _Res:
    bv = k3_eval(base, ctx, sh)
    if isinstance(bv, Nothing):
        return bv
    if not isinstance(bv.val, dict):
        return _nothing("expected-record", sh)
    result_dict = dict(cast("dict[str, object]", bv.val))
    for name, expr in updates:
        val = k3_eval(expr, ctx, sh)
        if isinstance(val, Nothing):
            return val
        result_dict[name] = val.val
    return Some(result_dict)


def _eval_llist(elements: tuple[Expr, ...], ctx: dict[str, object], sh: str) -> _Res:
    results = []
    for elem in elements:
        result = k3_eval(elem, ctx, sh)
        if isinstance(result, Nothing):
            return result
        results.append(result.val)
    return Some(results)


# -- k3_eval() - total interpreter ---------------------------------------------


def k3_eval(
    expr: Expr,
    ctx: dict[str, object],
    step_hash: str = "",
) -> _Res:
    """
    Evaluate a K3 expression against a context.

    Total: always returns Some(value) or Nothing(field, step_hash).
    Never raises. Nothing propagates through every compound expression.

    ctx is a flat dict - typically:
        {"state": {...}, "event": {...}, "__ctx__": SpecCtx}

    step_hash is threaded into every Nothing for audit trail continuity.
    """
    match expr:
        case LNull():
            return Some(None)
        case LBool(val=v) | LInt(val=v) | LFloat(val=v) | LStr(val=v):
            return Some(v)
        case Var(name=name):
            return Some(ctx[name]) if name in ctx else _nothing(name, step_hash)
        case Field(expr=e, name=name):
            return _eval_field(e, name, ctx, step_hash)
        case Index(expr=e, idx=i):
            return _eval_index(e, i, ctx, step_hash)
        case EventField(name=name):
            return _eval_field(Var("event"), name, ctx, step_hash)
        case Actual(field=f):
            return _eval_temporal(ctx, "__actual__", f, step_hash)
        case Intended(field=f):
            return _eval_temporal(ctx, "__intended__", f, step_hash)
        case And(left=le, right=re):
            return _eval_and(le, re, ctx, step_hash)
        case Or(left=le, right=re):
            return _eval_or(le, re, ctx, step_hash)
        case Not(expr=e):
            return _eval_not(e, ctx, step_hash)
        case If(cond=c, then=t, else_=e):
            return _eval_if(c, t, e, ctx, step_hash)
        case Implies(left=le, right=re):
            return _eval_implies(le, re, ctx, step_hash)
        case AllOf(exprs=exprs):
            return _eval_all_of(exprs, ctx, step_hash)
        case AnyOf(exprs=exprs):
            return _eval_any_of(exprs, ctx, step_hash)
        case In(expr=e, values=vals):
            return _eval_in(e, vals, ctx, step_hash)
        case Compare(op=op, left=le, right=re):
            fn = _CMP_OPS.get(op)
            if fn is None:
                return _nothing(f"unknown-cmp:{op}", step_hash)
            return _eval_binary(fn, le, re, ctx, step_hash)
        case Arith(op=ArithOp.DIV, left=le, right=re):
            return _eval_div(le, re, ctx, step_hash)
        case Arith(op=op, left=le, right=re):
            fn = _ARITH_OPS.get(op)
            if fn is None:
                return _nothing(f"unknown-arith:{op}", step_hash)
            return _eval_binary(fn, le, re, ctx, step_hash)
        case Mod(left=le, right=re):
            return _eval_mod(le, re, ctx, step_hash)
        case Negate(expr=e):
            return _eval_unary_numeric(e, operator.neg, ctx, step_hash)
        case Abs(expr=e):
            return _eval_unary_numeric(e, abs, ctx, step_hash)
        case Min(left=le, right=re):
            return _eval_binary(min, le, re, ctx, step_hash)
        case Max(left=le, right=re):
            return _eval_binary(max, le, re, ctx, step_hash)
        case IsSome(expr=e):
            result = k3_eval(e, ctx, step_hash)
            return Some(False) if isinstance(result, Nothing) else Some(True)
        case UnwrapOr(expr=e, default=d):
            result = k3_eval(e, ctx, step_hash)
            return (
                k3_eval(d, ctx, step_hash)
                if isinstance(result, Nothing)
                else Some(result.val)
            )
        case ForAll(var=v, collection=coll, predicate=pred):
            return _eval_quantifier(v, coll, pred, ctx, step_hash, is_forall=True)
        case Exists(var=v, collection=coll, predicate=pred):
            return _eval_quantifier(v, coll, pred, ctx, step_hash, is_forall=False)
        case Length(expr=e):
            return _eval_length(e, ctx, step_hash)
        case Contains(collection=coll, element=elem):
            return _eval_contains(coll, elem, ctx, step_hash)
        case Map(var=v, collection=coll, body=body):
            return _eval_map(v, coll, body, ctx, step_hash)
        case Filter(var=v, collection=coll, predicate=pred):
            return _eval_filter(v, coll, pred, ctx, step_hash)
        case Fold(init=init, collection=coll, acc_var=av, elem_var=ev, body=body):
            return _eval_fold(init, coll, av, ev, body, ctx, step_hash)
        case Concat(left=le, right=re):
            return _eval_concat(le, re, ctx, step_hash)
        case Trim(expr=e):
            return _eval_trim(e, ctx, step_hash)
        case Str(expr=e):
            r = k3_eval(e, ctx, step_hash)
            return r if isinstance(r, Nothing) else Some(str(r.val))
        case Slice(expr=e, start=s, end=en):
            return _eval_slice(e, s, en, ctx, step_hash)
        case Matches(expr=e, pattern=pat):
            return _eval_matches(e, pat, ctx, step_hash)
        case Record(fields=fields):
            return _eval_record(fields, ctx, step_hash)
        case With(base=b, updates=updates):
            return _eval_with(b, updates, ctx, step_hash)
        case LList(elements=elems):
            return _eval_llist(elems, ctx, step_hash)
        case Before(field=f):
            return _eval_temporal(ctx, "__prev_state__", f, step_hash)
        case After(field=f):
            return _eval_temporal(ctx, "__new_state__", f, step_hash)
        case Always(expr=e) | Eventually(expr=e) | Within(expr=e):
            return k3_eval(e, ctx, step_hash)
        case Until(right=re):
            return k3_eval(re, ctx, step_hash)
        case Named(expr=e) | Described(expr=e):
            return k3_eval(e, ctx, step_hash)
        case unreachable:
            assert_never(unreachable)
