# k3c/ir/diagnose.py
"""
Diagnostic eval — walks an Expr tree and records each sub-result.

When a Maintain or Validate fails on a complex compound expression like
Always(Implies(And(A, B), C)), the user wants to know *which* sub-clause
evaluated to what. Standard k3_eval just returns Some(False) or Nothing.

diagnose() returns a tree of (expr_summary, value) pairs, surfacing the
exact path through the expression that produced the failure.

This is opt-in and slightly slower than plain eval — only run on failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from k3c.ir.eval import k3_eval
from k3c.ir.expr import (
    AllOf,
    And,
    AnyOf,
    Compare,
    EventField,
    Expr,
    Field,
    If,
    Implies,
    In,
    LBool,
    LFloat,
    LInt,
    LStr,
    Not,
    Or,
    Var,
)
from k3c.ir.value import Nothing, Some


@dataclass(frozen=True)
class DiagNode:
    """One node in the diagnostic trace.

    summary: short human-readable description of the sub-expression
    value: the result string ("True", "False", "Nothing(field=...)", or actual value)
    children: nested DiagNodes for compound expressions
    """

    summary: str
    value: str
    children: tuple[DiagNode, ...] = field(default_factory=tuple)


def _expr_summary(expr: Expr) -> str:
    """One-line description of an expression for diagnostics."""
    match expr:
        case LBool(val=v):
            return f"{v}"
        case LInt(val=v):
            return f"{v}"
        case LFloat(val=v):
            return f"{v}"
        case LStr(val=v):
            return f"'{v}'"
        case Var(name=n):
            return n
        case Field(expr=e, name=n):
            return f"{_expr_summary(e)}.{n}"
        case EventField(name=n):
            return f"event.{n}"
        case Compare(op=op, left=le, right=re):
            return f"({_expr_summary(le)} {op.value} {_expr_summary(re)})"
        case And(left=le, right=re):
            return f"({_expr_summary(le)} AND {_expr_summary(re)})"
        case Or(left=le, right=re):
            return f"({_expr_summary(le)} OR {_expr_summary(re)})"
        case Not(expr=e):
            return f"NOT {_expr_summary(e)}"
        case Implies(left=le, right=re):
            return f"({_expr_summary(le)} => {_expr_summary(re)})"
        case AllOf(exprs=exprs):
            return "AllOf(" + ", ".join(_expr_summary(e) for e in exprs) + ")"
        case AnyOf(exprs=exprs):
            return "AnyOf(" + ", ".join(_expr_summary(e) for e in exprs) + ")"
        case In(expr=e, values=vals):
            vs = ", ".join(_expr_summary(v) for v in vals)
            return f"({_expr_summary(e)} IN [{vs}])"
        case If(cond=c, then=t, else_=e):
            return f"if {_expr_summary(c)} then {_expr_summary(t)} else {_expr_summary(e)}"
        case _:
            return type(expr).__name__


def _value_to_str(result: object) -> str:
    if isinstance(result, Some):
        v = result.val
        if v is True:
            return "True"
        if v is False:
            return "False"
        return repr(v)
    if isinstance(result, Nothing):
        return f"Nothing(field={result.field!r})"
    return repr(result)


def diagnose(expr: Expr, ctx: dict[str, object], step_hash: str) -> DiagNode:
    """Walk an expression, recording each sub-result.

    Returns a DiagNode tree. Compound expressions surface child evaluations
    so the failure path is visible.
    """
    result = k3_eval(expr, ctx, step_hash)
    summary = _expr_summary(expr)
    value = _value_to_str(result)

    children: tuple[DiagNode, ...] = ()
    match expr:
        case And(left=le, right=re) | Or(left=le, right=re) | Implies(left=le, right=re):
            children = (
                diagnose(le, ctx, step_hash),
                diagnose(re, ctx, step_hash),
            )
        case Not(expr=e):
            children = (diagnose(e, ctx, step_hash),)
        case AllOf(exprs=exprs) | AnyOf(exprs=exprs):
            children = tuple(diagnose(e, ctx, step_hash) for e in exprs)
        case Compare(op=_, left=le, right=re):
            children = (
                diagnose(le, ctx, step_hash),
                diagnose(re, ctx, step_hash),
            )
        case _:
            pass

    return DiagNode(summary=summary, value=value, children=children)


def format_diagnosis(node: DiagNode, indent: int = 0) -> str:
    """Render a DiagNode tree as indented text."""
    pad = "  " * indent
    lines = [f"{pad}{node.summary} => {node.value}"]
    for child in node.children:
        lines.append(format_diagnosis(child, indent + 1))
    return "\n".join(lines)
