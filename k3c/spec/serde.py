# k3c/spec/serde.py
"""
Round-trip serialization for Spec and all clause types.

spec_to_dict(spec) -> plain dict (JSON-ready)
spec_from_dict(data) -> Spec

Covers: Spec, Permit, Require, Maintain, Validate, Projection, Output,
        Korrelator, FieldDef, DecodePlan, Extractors.
"""

from __future__ import annotations

from typing import cast

from k3c.ir.serde import from_dict as expr_from_dict
from k3c.ir.serde import to_dict as expr_to_dict
from k3c.ir.serde import type_from_dict, type_to_dict
from k3c.spec.extract import (
    AvroField,
    BitField,
    ByteSlice,
    ColumnIdx,
    ColumnName,
    Computed,
    DecodeDispatch,
    DecodeFields,
    DecodeIdentity,
    DecodePlan,
    Extractor,
    FieldNum,
    Identity,
    JsonPath,
    MapKey,
    Switch,
    TextEncoding,
    XmlPath,
)
from k3c.spec.model import (
    CompareMode,
    FieldDef,
    Korrelator,
    Maintain,
    Output,
    Permit,
    Projection,
    Require,
    Severity,
    Spec,
    Validate,
)


# -- Extractor serde -----------------------------------------------------------


def extractor_to_dict(ext: Extractor) -> dict[str, object]:
    """Serialize an Extractor to a plain dict."""
    match ext:
        case ByteSlice(start=s, length=l, encoding=enc, trim=t, cast=c):
            d: dict[str, object] = {
                "type": "ByteSlice",
                "start": s,
                "length": l,
            }
            if enc != TextEncoding.ASCII:
                d["encoding"] = enc.value
            if not t:
                d["trim"] = False
            if c is not None:
                d["cast"] = c
            return d
        case BitField(byte_offset=bo, bit_offset=bi, width=w):
            return {"type": "BitField", "byte_offset": bo, "bit_offset": bi, "width": w}
        case JsonPath(path=p):
            return {"type": "JsonPath", "path": p}
        case XmlPath(path=p):
            return {"type": "XmlPath", "path": p}
        case MapKey(key=k):
            return {"type": "MapKey", "key": k}
        case FieldNum(number=n):
            return {"type": "FieldNum", "number": n}
        case AvroField(name=n):
            return {"type": "AvroField", "name": n}
        case ColumnName(name=n):
            return {"type": "ColumnName", "name": n}
        case ColumnIdx(index=i):
            return {"type": "ColumnIdx", "index": i}
        case Computed(expr=e):
            return {"type": "Computed", "expr": expr_to_dict(e)}
        case Switch(discriminant=disc, cases=cases):
            return {
                "type": "Switch",
                "discriminant": expr_to_dict(disc),
                "cases": [[cv, extractor_to_dict(ce)] for cv, ce in cases],
            }
        case Identity():
            return {"type": "Identity"}
    return {"type": "Unknown"}  # pragma: no cover


def extractor_from_dict(data: dict[str, object]) -> Extractor:
    """Deserialize a dict to an Extractor."""
    t = data.get("type")
    match t:
        case "ByteSlice":
            return ByteSlice(
                start=int(data["start"]),  # type: ignore[arg-type]
                length=int(data["length"]),  # type: ignore[arg-type]
                encoding=TextEncoding(data.get("encoding", "ASCII")),
                trim=bool(data.get("trim", True)),
                cast=data.get("cast"),  # type: ignore[arg-type]
            )
        case "BitField":
            return BitField(
                byte_offset=int(data["byte_offset"]),  # type: ignore[arg-type]
                bit_offset=int(data["bit_offset"]),  # type: ignore[arg-type]
                width=int(data["width"]),  # type: ignore[arg-type]
            )
        case "JsonPath":
            return JsonPath(path=str(data["path"]))
        case "XmlPath":
            return XmlPath(path=str(data["path"]))
        case "MapKey":
            return MapKey(key=str(data["key"]))
        case "FieldNum":
            return FieldNum(number=int(data["number"]))  # type: ignore[arg-type]
        case "AvroField":
            return AvroField(name=str(data["name"]))
        case "ColumnName":
            return ColumnName(name=str(data["name"]))
        case "ColumnIdx":
            return ColumnIdx(index=int(data["index"]))  # type: ignore[arg-type]
        case "Computed":
            return Computed(expr=expr_from_dict(cast("dict[str, object]", data["expr"])))
        case "Switch":
            disc = expr_from_dict(cast("dict[str, object]", data["discriminant"]))
            raw_cases = cast("list[list[object]]", data["cases"])
            cases = tuple(
                (c[0], extractor_from_dict(cast("dict[str, object]", c[1])))
                for c in raw_cases
            )
            return Switch(discriminant=disc, cases=cases)
        case "Identity":
            return Identity()
        case _:
            msg = f"Unknown extractor type: {t!r}"
            raise ValueError(msg)


# -- DecodePlan serde ----------------------------------------------------------


def decode_to_dict(plan: DecodePlan) -> dict[str, object]:
    """Serialize a DecodePlan to a plain dict."""
    match plan:
        case DecodeIdentity():
            return {"type": "DecodeIdentity"}
        case DecodeFields(fields=fields):
            return {
                "type": "DecodeFields",
                "fields": [[n, extractor_to_dict(e)] for n, e in fields],
            }
        case DecodeDispatch(discriminant=disc, cases=cases, default=default):
            d: dict[str, object] = {
                "type": "DecodeDispatch",
                "discriminant": extractor_to_dict(disc),
                "cases": [[cv, decode_to_dict(cp)] for cv, cp in cases],
            }
            if default == "skip":
                d["default"] = "skip"
            elif default is not None:
                d["default"] = decode_to_dict(default)
            return d
    return {"type": "Unknown"}  # pragma: no cover


def decode_from_dict(data: dict[str, object]) -> DecodePlan:
    """Deserialize a dict to a DecodePlan."""
    t = data.get("type")
    match t:
        case "DecodeIdentity":
            return DecodeIdentity()
        case "DecodeFields":
            raw_fields = cast("list[list[object]]", data["fields"])
            fields = tuple(
                (str(f[0]), extractor_from_dict(cast("dict[str, object]", f[1])))
                for f in raw_fields
            )
            return DecodeFields(fields=fields)
        case "DecodeDispatch":
            disc = extractor_from_dict(cast("dict[str, object]", data["discriminant"]))
            raw_cases = cast("list[list[object]]", data["cases"])
            cases = tuple(
                (c[0], decode_from_dict(cast("dict[str, object]", c[1])))
                for c in raw_cases
            )
            raw_default = data.get("default")
            if raw_default == "skip":
                default: DecodePlan | str | None = "skip"
            elif isinstance(raw_default, dict):
                default = decode_from_dict(raw_default)
            else:
                default = None
            return DecodeDispatch(discriminant=disc, cases=cases, default=default)
        case _:
            msg = f"Unknown decode plan type: {t!r}"
            raise ValueError(msg)


# -- Clause serde --------------------------------------------------------------


def _permit_to_dict(p: Permit) -> dict[str, object]:
    d: dict[str, object] = {"name": p.name, "when": expr_to_dict(p.when)}
    if p.on is not None:
        d["on"] = p.on
    return d


def _permit_from_dict(data: dict[str, object]) -> Permit:
    return Permit(
        name=str(data["name"]),
        when=expr_from_dict(cast("dict[str, object]", data["when"])),
        on=data.get("on"),  # type: ignore[arg-type]
    )


def _require_to_dict(r: Require) -> dict[str, object]:
    return {"name": r.name, "on": r.on, "transition": expr_to_dict(r.transition)}


def _require_from_dict(data: dict[str, object]) -> Require:
    return Require(
        name=str(data["name"]),
        on=str(data["on"]),
        transition=expr_from_dict(cast("dict[str, object]", data["transition"])),
    )


def _maintain_to_dict(m: Maintain) -> dict[str, object]:
    d: dict[str, object] = {"name": m.name, "expr": expr_to_dict(m.expr)}
    if m.severity != Severity.ERROR:
        d["severity"] = m.severity.value
    return d


def _maintain_from_dict(data: dict[str, object]) -> Maintain:
    return Maintain(
        name=str(data["name"]),
        expr=expr_from_dict(cast("dict[str, object]", data["expr"])),
        severity=Severity(data.get("severity", "error")),
    )


def _validate_to_dict(v: Validate) -> dict[str, object]:
    d: dict[str, object] = {
        "name": v.name,
        "on": v.on,
        "check": expr_to_dict(v.check),
    }
    if v.severity != Severity.ERROR:
        d["severity"] = v.severity.value
    if v.field is not None:
        d["field"] = v.field
    if v.constraint is not None:
        d["constraint"] = v.constraint
    return d


def _validate_from_dict(data: dict[str, object]) -> Validate:
    return Validate(
        name=str(data["name"]),
        on=str(data["on"]),
        check=expr_from_dict(cast("dict[str, object]", data["check"])),
        severity=Severity(data.get("severity", "error")),
        field=data.get("field"),  # type: ignore[arg-type]
        constraint=data.get("constraint"),  # type: ignore[arg-type]
    )


def _projection_to_dict(p: Projection) -> dict[str, object]:
    d: dict[str, object] = {"name": p.name, "expr": expr_to_dict(p.expr)}
    if p.kind != "derived":
        d["kind"] = p.kind
    return d


def _projection_from_dict(data: dict[str, object]) -> Projection:
    return Projection(
        name=str(data["name"]),
        expr=expr_from_dict(cast("dict[str, object]", data["expr"])),
        kind=str(data.get("kind", "derived")),
    )


def _output_to_dict(o: Output) -> dict[str, object]:
    d: dict[str, object] = {"name": o.name, "expr": expr_to_dict(o.expr)}
    if o.on is not None:
        d["on"] = o.on
    return d


def _output_from_dict(data: dict[str, object]) -> Output:
    return Output(
        name=str(data["name"]),
        expr=expr_from_dict(cast("dict[str, object]", data["expr"])),
        on=data.get("on"),  # type: ignore[arg-type]
    )


def _korrelator_to_dict(k: Korrelator) -> dict[str, object]:
    return {
        "actual": expr_to_dict(k.actual),
        "intended": expr_to_dict(k.intended),
        "mode": k.mode.value,
    }


def _korrelator_from_dict(data: dict[str, object]) -> Korrelator:
    return Korrelator(
        actual=expr_from_dict(cast("dict[str, object]", data["actual"])),
        intended=expr_from_dict(cast("dict[str, object]", data["intended"])),
        mode=CompareMode(data.get("mode", "exact")),
    )


def _field_def_to_dict(f: FieldDef) -> dict[str, object]:
    d: dict[str, object] = {"name": f.name, "type": type_to_dict(f.type)}
    if f.description:
        d["description"] = f.description
    if not f.required:
        d["required"] = False
    if f.extract is not None:
        d["extract"] = extractor_to_dict(f.extract)
    return d


def _field_def_from_dict(data: dict[str, object]) -> FieldDef:
    extract = data.get("extract")
    return FieldDef(
        name=str(data["name"]),
        type=type_from_dict(cast("dict[str, object]", data["type"])),
        description=str(data.get("description", "")),
        required=bool(data.get("required", True)),
        extract=extractor_from_dict(cast("dict[str, object]", extract))
        if extract is not None
        else None,
    )


# -- Spec serde ----------------------------------------------------------------


def spec_to_dict(spec: Spec) -> dict[str, object]:
    """Serialize a complete Spec to a plain dict (JSON-ready).

    Round-trips with spec_from_dict(). All clause types, extractors, decode
    plans, and the new Validate/Severity are fully serialized.
    """
    d: dict[str, object] = {
        "name": spec.name,
        "state0": spec.state0,
    }

    if spec.fields:
        d["fields"] = [_field_def_to_dict(f) for f in spec.fields]

    if spec.decode is not None:
        d["decode"] = decode_to_dict(spec.decode)

    if spec.permits:
        d["permits"] = [_permit_to_dict(p) for p in spec.permits]

    if spec.requires:
        d["requires"] = [_require_to_dict(r) for r in spec.requires]

    if spec.maintains:
        d["maintains"] = [_maintain_to_dict(m) for m in spec.maintains]

    if spec.validates:
        d["validates"] = [_validate_to_dict(v) for v in spec.validates]

    if spec.projections:
        d["projections"] = [_projection_to_dict(p) for p in spec.projections]

    if spec.outputs:
        d["outputs"] = [_output_to_dict(o) for o in spec.outputs]

    if spec.korrelator is not None:
        d["korrelator"] = _korrelator_to_dict(spec.korrelator)

    if spec.protocol_start != "__start__":
        d["protocol_start"] = spec.protocol_start

    return d


def spec_from_dict(data: dict[str, object]) -> Spec:
    """Deserialize a plain dict to a Spec.

    Round-trips with spec_to_dict(). Handles all clause types including
    Validate, Severity, decode plans, and extractors.
    """
    fields_raw = cast("list[dict[str, object]]", data.get("fields", []))
    permits_raw = cast("list[dict[str, object]]", data.get("permits", []))
    requires_raw = cast("list[dict[str, object]]", data.get("requires", []))
    maintains_raw = cast("list[dict[str, object]]", data.get("maintains", []))
    validates_raw = cast("list[dict[str, object]]", data.get("validates", []))
    projections_raw = cast("list[dict[str, object]]", data.get("projections", []))
    outputs_raw = cast("list[dict[str, object]]", data.get("outputs", []))
    korr_raw = data.get("korrelator")
    decode_raw = data.get("decode")

    return Spec(
        name=str(data["name"]),
        state0=cast("dict[str, object]", data["state0"]),
        fields=tuple(_field_def_from_dict(f) for f in fields_raw),
        decode=decode_from_dict(cast("dict[str, object]", decode_raw))
        if decode_raw is not None
        else None,
        permits=tuple(_permit_from_dict(p) for p in permits_raw),
        requires=tuple(_require_from_dict(r) for r in requires_raw),
        maintains=tuple(_maintain_from_dict(m) for m in maintains_raw),
        validates=tuple(_validate_from_dict(v) for v in validates_raw),
        projections=tuple(_projection_from_dict(p) for p in projections_raw),
        outputs=tuple(_output_from_dict(o) for o in outputs_raw),
        korrelator=_korrelator_from_dict(cast("dict[str, object]", korr_raw))
        if korr_raw is not None
        else None,
        protocol_start=str(data.get("protocol_start", "__start__")),
    )
