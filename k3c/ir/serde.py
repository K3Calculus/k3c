# k3c/ir/serde.py
"""
Round-trip serialization for Expr and ExprType nodes.

to_dict(node) -> plain dict (JSON-ready)
from_dict(data) -> frozen Expr or ExprType node

Every node serializes to {"type": "<ClassName>", ...fields}.
The format is deterministic - same node always produces the same dict.
"""

from __future__ import annotations

from typing import assert_never, cast

from k3c.errors import K3SerdeError
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
    Index,
    Intended,
    IsSome,
    LBool,
    Length,
    LFloat,
    LInt,
    LList,
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
    Trim,
    Until,
    UnwrapOr,
    Var,
    With,
    Within,
)
from k3c.ir.types import (
    DateFormat,
    ExprType,
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

# -- Expr serialization --------------------------------------------------------


def _fields_to_list(fields: tuple[tuple[str, Expr], ...]) -> list[dict[str, object]]:
    return [{"name": n, "expr": to_dict(e)} for n, e in fields]


def to_dict(node: Expr) -> dict[str, object]:
    """Serialize an Expr node to a plain dict."""
    match node:
        # Literals
        case LBool(val=v):
            return {"type": "LBool", "val": v}
        case LInt(val=v):
            return {"type": "LInt", "val": v}
        case LFloat(val=v):
            return {"type": "LFloat", "val": v}
        case LStr(val=v):
            return {"type": "LStr", "val": v}
        case LList(elements=elems):
            return {"type": "LList", "elements": [to_dict(e) for e in elems]}

        # Variables and access
        case Var(name=n):
            return {"type": "Var", "name": n}
        case Field(expr=e, name=n):
            return {"type": "Field", "expr": to_dict(e), "name": n}
        case Index(expr=e, idx=i):
            return {"type": "Index", "expr": to_dict(e), "idx": i}
        case EventField(name=n):
            return {"type": "EventField", "name": n}
        case Actual(field=f):
            return {"type": "Actual", "field": f}
        case Intended(field=f):
            return {"type": "Intended", "field": f}

        # Logic
        case And(left=le, right=re):
            return {"type": "And", "left": to_dict(le), "right": to_dict(re)}
        case Or(left=le, right=re):
            return {"type": "Or", "left": to_dict(le), "right": to_dict(re)}
        case Not(expr=e):
            return {"type": "Not", "expr": to_dict(e)}
        case If(cond=c, then=t, else_=e):
            return {
                "type": "If",
                "cond": to_dict(c),
                "then": to_dict(t),
                "else_": to_dict(e),
            }
        case Implies(left=le, right=re):
            return {"type": "Implies", "left": to_dict(le), "right": to_dict(re)}

        # Comparison and arithmetic
        case Compare(op=op, left=le, right=re):
            return {
                "type": "Compare",
                "op": op,
                "left": to_dict(le),
                "right": to_dict(re),
            }
        case Arith(op=op, left=le, right=re):
            return {
                "type": "Arith",
                "op": op,
                "left": to_dict(le),
                "right": to_dict(re),
            }
        case Mod(left=le, right=re):
            return {"type": "Mod", "left": to_dict(le), "right": to_dict(re)}
        case Negate(expr=e):
            return {"type": "Negate", "expr": to_dict(e)}
        case Abs(expr=e):
            return {"type": "Abs", "expr": to_dict(e)}
        case Min(left=le, right=re):
            return {"type": "Min", "left": to_dict(le), "right": to_dict(re)}
        case Max(left=le, right=re):
            return {"type": "Max", "left": to_dict(le), "right": to_dict(re)}

        # Option operations
        case IsSome(expr=e):
            return {"type": "IsSome", "expr": to_dict(e)}
        case UnwrapOr(expr=e, default=d):
            return {"type": "UnwrapOr", "expr": to_dict(e), "default": to_dict(d)}

        # Collections
        case ForAll(var=v, collection=coll, predicate=pred):
            return {
                "type": "ForAll",
                "var": v,
                "collection": to_dict(coll),
                "predicate": to_dict(pred),
            }
        case Exists(var=v, collection=coll, predicate=pred):
            return {
                "type": "Exists",
                "var": v,
                "collection": to_dict(coll),
                "predicate": to_dict(pred),
            }
        case Length(expr=e):
            return {"type": "Length", "expr": to_dict(e)}
        case Contains(collection=coll, element=elem):
            return {
                "type": "Contains",
                "collection": to_dict(coll),
                "element": to_dict(elem),
            }
        case Map(var=v, collection=coll, body=body):
            return {
                "type": "Map",
                "var": v,
                "collection": to_dict(coll),
                "body": to_dict(body),
            }
        case Filter(var=v, collection=coll, predicate=pred):
            return {
                "type": "Filter",
                "var": v,
                "collection": to_dict(coll),
                "predicate": to_dict(pred),
            }
        case Fold(init=init, collection=coll, acc_var=av, elem_var=ev, body=body):
            return {
                "type": "Fold",
                "init": to_dict(init),
                "collection": to_dict(coll),
                "acc_var": av,
                "elem_var": ev,
                "body": to_dict(body),
            }

        # String operations
        case Concat(left=le, right=re):
            return {"type": "Concat", "left": to_dict(le), "right": to_dict(re)}
        case Trim(expr=e):
            return {"type": "Trim", "expr": to_dict(e)}
        case Slice(expr=e, start=s, end=en):
            return {
                "type": "Slice",
                "expr": to_dict(e),
                "start": to_dict(s),
                "end": to_dict(en),
            }
        case Matches(expr=e, pattern=pat):
            return {"type": "Matches", "expr": to_dict(e), "pattern": pat}

        # Record construction
        case Record(fields=fields):
            return {"type": "Record", "fields": _fields_to_list(fields)}
        case With(base=b, updates=updates):
            return {
                "type": "With",
                "base": to_dict(b),
                "updates": _fields_to_list(updates),
            }

        # Temporal
        case Before(field=f):
            return {"type": "Before", "field": f}
        case After(field=f):
            return {"type": "After", "field": f}

        # Spec nodes
        case Always(expr=e):
            return {"type": "Always", "expr": to_dict(e)}
        case Eventually(expr=e):
            return {"type": "Eventually", "expr": to_dict(e)}
        case Within(expr=e, n=n):
            return {"type": "Within", "expr": to_dict(e), "n": n}
        case Until(left=le, right=re):
            return {"type": "Until", "left": to_dict(le), "right": to_dict(re)}

        # Annotation
        case Named(name=n, expr=e):
            return {"type": "Named", "name": n, "expr": to_dict(e)}
        case Described(description=desc, expr=e):
            return {"type": "Described", "description": desc, "expr": to_dict(e)}

        case unreachable:
            assert_never(unreachable)


# -- Expr deserialization ------------------------------------------------------

_EXPR_NODES: dict[str, type] = {
    "Not": Not,
    "IsSome": IsSome,
    "Always": Always,
    "Eventually": Eventually,
    "Negate": Negate,
    "Abs": Abs,
    "Length": Length,
    "Trim": Trim,
}

_BINARY_NODES: dict[str, type] = {
    "And": And,
    "Or": Or,
    "Implies": Implies,
    "Mod": Mod,
    "Concat": Concat,
    "Min": Min,
    "Max": Max,
    "Until": Until,
}

_QUANTIFIER_NODES: dict[str, type] = {
    "ForAll": ForAll,
    "Exists": Exists,
    "Filter": Filter,
}

_STR_FIELD_NODES: dict[str, type] = {
    "Before": Before,
    "After": After,
    "EventField": EventField,
    "Actual": Actual,
    "Intended": Intended,
}


def _fields_from_list(data: list[object], node: str) -> tuple[tuple[str, Expr], ...]:
    result = []
    for item in data:
        d = _ensure_dict(item, node)
        result.append(
            (_str_field(d, node, "name"), from_dict(_dict_field(d, node, "expr")))
        )
    return tuple(result)


def _from_dict_literal(node_type: str, data: dict[str, object]) -> Expr | None:
    """Parse literal nodes. Returns None if node_type is not a literal."""
    match node_type:
        case "LBool":
            val = data["val"]
            if not isinstance(val, bool):
                raise K3SerdeError(
                    node="LBool", message=f"expected bool, got {type(val).__name__}"
                )
            return LBool(val)
        case "LInt":
            val = data["val"]
            if not isinstance(val, int) or isinstance(val, bool):
                raise K3SerdeError(
                    node="LInt", message=f"expected int, got {type(val).__name__}"
                )
            return LInt(val)
        case "LFloat":
            val = data["val"]
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise K3SerdeError(
                    node="LFloat", message=f"expected float, got {type(val).__name__}"
                )
            return LFloat(float(val))
        case "LStr":
            val = data["val"]
            if not isinstance(val, str):
                raise K3SerdeError(
                    node="LStr", message=f"expected str, got {type(val).__name__}"
                )
            return LStr(val)
        case "LList":
            elements = _list_field(data, "LList", "elements")
            return LList(
                elements=tuple(
                    from_dict(_ensure_dict(elem, "LList")) for elem in elements
                )
            )
        case _:
            return None


def _from_dict_compound(node_type: str, data: dict[str, object]) -> Expr | None:
    """Parse compound/structural nodes. Returns None if not handled."""
    match node_type:
        case "Var":
            return Var(name=_str_field(data, "Var", "name"))
        case "Field":
            return Field(
                expr=from_dict(_dict_field(data, "Field", "expr")),
                name=_str_field(data, "Field", "name"),
            )
        case "Index":
            return Index(
                expr=from_dict(_dict_field(data, "Index", "expr")),
                idx=_int_field(data, "Index", "idx"),
            )
        case "If":
            return If(
                cond=from_dict(_dict_field(data, "If", "cond")),
                then=from_dict(_dict_field(data, "If", "then")),
                else_=from_dict(_dict_field(data, "If", "else_")),
            )
        case "UnwrapOr":
            return UnwrapOr(
                expr=from_dict(_dict_field(data, "UnwrapOr", "expr")),
                default=from_dict(_dict_field(data, "UnwrapOr", "default")),
            )
        case "Contains":
            return Contains(
                collection=from_dict(_dict_field(data, "Contains", "collection")),
                element=from_dict(_dict_field(data, "Contains", "element")),
            )
        case "Map":
            return Map(
                var=_str_field(data, "Map", "var"),
                collection=from_dict(_dict_field(data, "Map", "collection")),
                body=from_dict(_dict_field(data, "Map", "body")),
            )
        case "Fold":
            return Fold(
                init=from_dict(_dict_field(data, "Fold", "init")),
                collection=from_dict(_dict_field(data, "Fold", "collection")),
                acc_var=_str_field(data, "Fold", "acc_var"),
                elem_var=_str_field(data, "Fold", "elem_var"),
                body=from_dict(_dict_field(data, "Fold", "body")),
            )
        case "Slice":
            return Slice(
                expr=from_dict(_dict_field(data, "Slice", "expr")),
                start=from_dict(_dict_field(data, "Slice", "start")),
                end=from_dict(_dict_field(data, "Slice", "end")),
            )
        case "Matches":
            return Matches(
                expr=from_dict(_dict_field(data, "Matches", "expr")),
                pattern=_str_field(data, "Matches", "pattern"),
            )
        case "Record":
            return Record(
                fields=_fields_from_list(
                    _list_field(data, "Record", "fields"), "Record"
                )
            )
        case "With":
            return With(
                base=from_dict(_dict_field(data, "With", "base")),
                updates=_fields_from_list(_list_field(data, "With", "updates"), "With"),
            )
        case "Within":
            return Within(
                expr=from_dict(_dict_field(data, "Within", "expr")),
                n=_int_field(data, "Within", "n"),
            )
        case "Named":
            return Named(
                name=_str_field(data, "Named", "name"),
                expr=from_dict(_dict_field(data, "Named", "expr")),
            )
        case "Described":
            return Described(
                description=_str_field(data, "Described", "description"),
                expr=from_dict(_dict_field(data, "Described", "expr")),
            )
        case _:
            return None


def from_dict(data: dict[str, object]) -> Expr:
    """Deserialize a plain dict to an Expr node."""
    node_type = data.get("type")
    if not isinstance(node_type, str):
        raise K3SerdeError(node="unknown", message="missing or non-string 'type' field")

    # Literals
    result = _from_dict_literal(node_type, data)
    if result is not None:
        return result

    # Single "expr" child nodes
    if node_type in _EXPR_NODES:
        return _EXPR_NODES[node_type](
            expr=from_dict(_dict_field(data, node_type, "expr"))
        )

    # Binary "left"/"right" nodes
    if node_type in _BINARY_NODES:
        return _BINARY_NODES[node_type](
            left=from_dict(_dict_field(data, node_type, "left")),
            right=from_dict(_dict_field(data, node_type, "right")),
        )

    # "op" + binary nodes
    if node_type == "Compare":
        return Compare(
            op=CmpOp(_str_field(data, "Compare", "op")),
            left=from_dict(_dict_field(data, "Compare", "left")),
            right=from_dict(_dict_field(data, "Compare", "right")),
        )
    if node_type == "Arith":
        return Arith(
            op=ArithOp(_str_field(data, "Arith", "op")),
            left=from_dict(_dict_field(data, "Arith", "left")),
            right=from_dict(_dict_field(data, "Arith", "right")),
        )

    # String-field-only nodes
    if node_type in _STR_FIELD_NODES:
        field_name = (
            "name" if node_type in ("EventField", "Actual", "Intended") else "field"
        )
        if node_type in ("Actual", "Intended"):
            field_name = "field"
        return _STR_FIELD_NODES[node_type](
            **{field_name: _str_field(data, node_type, field_name)}
        )

    # Quantifier-like nodes
    if node_type in _QUANTIFIER_NODES:
        return _QUANTIFIER_NODES[node_type](
            var=_str_field(data, node_type, "var"),
            collection=from_dict(_dict_field(data, node_type, "collection")),
            predicate=from_dict(_dict_field(data, node_type, "predicate")),
        )

    # Compound/structural nodes
    result = _from_dict_compound(node_type, data)
    if result is not None:
        return result

    raise K3SerdeError(node=node_type, message=f"unknown node type {node_type!r}")


# -- ExprType serialization ----------------------------------------------------


def type_to_dict(node: ExprType) -> dict[str, object]:
    """Serialize an ExprType node to a plain dict."""
    match node:
        case TBool():
            return {"type": "TBool"}
        case TInt():
            return {"type": "TInt"}
        case TString():
            return {"type": "TString"}
        case TFloat():
            return {"type": "TFloat"}
        case TUnit():
            return {"type": "TUnit"}
        case TBytes(length=length):
            return {"type": "TBytes", "length": length}
        case TDate(format=fmt):
            return {"type": "TDate", "format": fmt}
        case TTime(format=fmt):
            return {"type": "TTime", "format": fmt}
        case TEnum(values=vals):
            return {"type": "TEnum", "values": list(vals)}
        case TRecord(fields=fields):
            return {
                "type": "TRecord",
                "fields": {k: type_to_dict(v) for k, v in fields.items()},
            }
        case TVariant(variants=variants):
            return {
                "type": "TVariant",
                "variants": {k: type_to_dict(v) for k, v in variants.items()},
            }
        case TList(element=elem):
            return {"type": "TList", "element": type_to_dict(elem)}
        case TOption(inner=inner):
            return {"type": "TOption", "inner": type_to_dict(inner)}
        case TRef(name=n):
            return {"type": "TRef", "name": n}
        case unreachable:
            assert_never(unreachable)


# -- ExprType deserialization --------------------------------------------------


def type_from_dict(data: dict[str, object]) -> ExprType:
    """Deserialize a plain dict to an ExprType node."""
    node_type = data.get("type")
    if not isinstance(node_type, str):
        raise K3SerdeError(node="unknown", message="missing or non-string 'type' field")

    match node_type:
        case "TBool":
            return TBool()
        case "TInt":
            return TInt()
        case "TString":
            return TString()
        case "TFloat":
            return TFloat()
        case "TUnit":
            return TUnit()
        case "TBytes":
            length = data.get("length")
            if length is not None and (
                not isinstance(length, int) or isinstance(length, bool)
            ):
                raise K3SerdeError(
                    node="TBytes", message="'length' must be int or null"
                )
            return TBytes(length=length)
        case "TDate":
            return TDate(format=DateFormat(_str_field(data, "TDate", "format")))
        case "TTime":
            return TTime(format=TimeFormat(_str_field(data, "TTime", "format")))
        case "TEnum":
            values = _list_field(data, "TEnum", "values")
            if not all(isinstance(v, str) for v in values):
                raise K3SerdeError(
                    node="TEnum", message="'values' must be a list of strings"
                )
            return TEnum(values=tuple(cast("list[str]", values)))
        case "TRecord":
            fields = _dict_field(data, "TRecord", "fields")
            return TRecord(
                fields={
                    k: type_from_dict(_dict_field(fields, "TRecord", k)) for k in fields
                }
            )
        case "TVariant":
            variants = _dict_field(data, "TVariant", "variants")
            return TVariant(
                variants={
                    k: type_from_dict(_dict_field(variants, "TVariant", k))
                    for k in variants
                }
            )
        case "TList":
            return TList(element=type_from_dict(_dict_field(data, "TList", "element")))
        case "TOption":
            return TOption(inner=type_from_dict(_dict_field(data, "TOption", "inner")))
        case "TRef":
            return TRef(name=_str_field(data, "TRef", "name"))
        case _:
            raise K3SerdeError(
                node=node_type, message=f"unknown type node {node_type!r}"
            )


# -- Field extraction helpers --------------------------------------------------


def _str_field(data: dict[str, object], node: str, field: str) -> str:
    val = data.get(field)
    if not isinstance(val, str):
        raise K3SerdeError(node=node, message=f"missing or non-string '{field}'")
    return val


def _int_field(data: dict[str, object], node: str, field: str) -> int:
    val = data.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise K3SerdeError(
            node=node, message=f"expected int for '{field}', got {type(val).__name__}"
        )
    return val


def _list_field(data: dict[str, object], node: str, field: str) -> list[object]:
    val = data.get(field)
    if not isinstance(val, list):
        raise K3SerdeError(node=node, message=f"missing or non-list '{field}'")
    return cast("list[object]", val)


def _dict_field(data: dict[str, object], node: str, field: str) -> dict[str, object]:
    val = data.get(field)
    if not isinstance(val, dict):
        raise K3SerdeError(node=node, message=f"missing or non-dict '{field}'")
    return cast("dict[str, object]", val)


def _ensure_dict(val: object, node: str) -> dict[str, object]:
    if not isinstance(val, dict):
        raise K3SerdeError(
            node=node, message=f"expected dict, got {type(val).__name__}"
        )
    return cast("dict[str, object]", val)
