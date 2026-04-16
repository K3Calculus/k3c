# examples/ssim/ssim_spec.py
"""
SSIM k3c Spec — DFA guards, field validations, invariants, projections, outputs.

Encodes the SSIM Chapter 7 file structure as a k3c causal system:
  - Guards enforce the DFA + field-level validation from JSON-LD specs
  - Invariants enforce serial continuity, block balancing
  - Projections compute file_summary and integrity_report (via EmbeddedRuntime hooks)
  - Outputs emit complete flights (RT3 + nested RT4 segments) and carrier blocks
    (via EmbeddedRuntime hooks)

Field validations come from the JSON-LD record specs:
  - RT1: title_of_contents constant, record_serial_number == 1
  - RT2: time_mode in {U, L}, schedule_status in {P, C}
  - RT3: departure_station != arrival_station (3-letter IATA codes)
  - RT4: DEI is 3-digit zero-padded, board/off points are 3-letter codes
  - RT5: continuation_end_code in {C, E}, serial_check_ref == serial - 1
"""

from __future__ import annotations

import re

from k3c import (
    After,
    Always,
    And,
    Arith,
    ArithOp,
    Before,
    CmpOp,
    Compare,
    EmbeddedRuntime,
    EventField,
    Field,
    Implies,
    LInt,
    LStr,
    Maintain,
    Or,
    Permit,
    Spec,
    Var,
)

# ── State ───────────────────────────────────────────────────────────────────

INITIAL_STATE: dict[str, object] = {
    "phase": "EXPECT_RT1",
    "serial": 0,
    "carrier": None,
    "time_mode": None,
    "flight_key": None,
    "open_blocks": 0,
    "dataset_serial": 0,
    "carrier_validity_from": None,
    "carrier_validity_to": None,
    "counts": {},
    "pending_flight": None,
    "current_flight_record": None,
    "current_segments": [],
    "validation_errors": [],
}


# ── Field validation (from JSON-LD specs) ──────────────────────────────────

_IATA_STATION = re.compile(r"^[A-Z]{3}$")
_IATA_AIRLINE = re.compile(r"^[A-Z0-9]{2}[A-Z0-9 ]$")
_DEI_PATTERN = re.compile(r"^\d{3}$")
_FLIGHT_NUM = re.compile(r"^[A-Z0-9 ]{4}$")
_SSIM_TITLE = "AIRLINE STANDARD SCHEDULE DATA SET"


def validate_rt1(event: dict[str, object]) -> list[str]:
    """Validate RT1 fields per header.spec.jsonld."""
    errors = []
    title = str(event.get("title_of_contents", ""))
    if title != _SSIM_TITLE:
        errors.append(f"RT1: title_of_contents must be '{_SSIM_TITLE}', got '{title}'")
    serial = event.get("record_serial_number", 0)
    if serial != 1:
        errors.append(f"RT1: record_serial_number must be 1, got {serial}")
    ds = event.get("data_set_serial_number", 0)
    if not (1 <= int(ds) <= 999):  # type: ignore[arg-type]
        errors.append(f"RT1: data_set_serial_number must be 1-999, got {ds}")
    seasons = str(event.get("number_of_seasons", " "))
    if seasons not in (" ", "", "1", "2"):
        errors.append(f"RT1: number_of_seasons must be blank/1/2, got '{seasons}'")
    return errors


def validate_rt2(event: dict[str, object]) -> list[str]:
    """Validate RT2 fields per carrier.spec.jsonld."""
    errors = []
    tm = str(event.get("time_mode", ""))
    if tm not in ("U", "L"):
        errors.append(f"RT2: time_mode must be 'U' or 'L', got '{tm}'")
    airline = str(event.get("airline_designator", ""))
    if not _IATA_AIRLINE.match(airline):
        errors.append(f"RT2: invalid airline_designator '{airline}'")
    status = str(event.get("schedule_status", ""))
    if status and status not in ("P", "C"):
        errors.append(f"RT2: schedule_status must be 'P' or 'C', got '{status}'")
    return errors


def validate_rt3(event: dict[str, object]) -> list[str]:
    """Validate RT3 fields per flight.spec.jsonld."""
    errors = []
    airline = str(event.get("airline_designator", ""))
    if not _IATA_AIRLINE.match(airline):
        errors.append(f"RT3: invalid airline_designator '{airline}'")
    fnum = str(event.get("flight_number", ""))
    if not _FLIGHT_NUM.match(fnum):
        errors.append(f"RT3: invalid flight_number '{fnum}'")
    dep = str(event.get("departure_station", ""))
    arr = str(event.get("arrival_station", ""))
    if dep and not _IATA_STATION.match(dep):
        errors.append(f"RT3: invalid departure_station '{dep}'")
    if arr and not _IATA_STATION.match(arr):
        errors.append(f"RT3: invalid arrival_station '{arr}'")
    if dep and arr and dep == arr:
        errors.append(f"RT3: departure_station == arrival_station ('{dep}')")
    svc = str(event.get("service_type", ""))
    if svc and svc not in "JFCQGHPABMKLREONVPQTISFUMAGX":
        errors.append(f"RT3: invalid service_type '{svc}'")
    return errors


def validate_rt4(event: dict[str, object]) -> list[str]:
    """Validate RT4 fields per segment.spec.jsonld."""
    errors = []
    airline = str(event.get("airline_designator", ""))
    if not _IATA_AIRLINE.match(airline):
        errors.append(f"RT4: invalid airline_designator '{airline}'")
    dei = str(event.get("data_element_identifier", ""))
    if not _DEI_PATTERN.match(dei):
        errors.append(f"RT4: DEI must be 3-digit zero-padded, got '{dei}'")
    bp = str(event.get("board_point", ""))
    op = str(event.get("off_point", ""))
    if bp and not _IATA_STATION.match(bp):
        errors.append(f"RT4: invalid board_point '{bp}'")
    if op and not _IATA_STATION.match(op):
        errors.append(f"RT4: invalid off_point '{op}'")
    return errors


def validate_rt5(event: dict[str, object]) -> list[str]:
    """Validate RT5 fields per trailer.spec.jsonld."""
    errors = []
    cont = str(event.get("continuation_end_code", ""))
    if cont not in ("C", "E"):
        errors.append(f"RT5: continuation_end_code must be 'C' or 'E', got '{cont}'")
    serial = int(event.get("record_serial_number", 0))  # type: ignore[arg-type]
    check_ref = int(event.get("serial_number_check_reference", 0))  # type: ignore[arg-type]
    if serial > 0 and check_ref > 0 and check_ref != serial - 1:
        errors.append(
            f"RT5: serial_number_check_reference ({check_ref}) "
            f"must equal record_serial_number - 1 ({serial - 1})"
        )
    airline = str(event.get("airline_designator", ""))
    if not _IATA_AIRLINE.match(airline):
        errors.append(f"RT5: invalid airline_designator '{airline}'")
    return errors


_VALIDATORS = {
    "RT1": validate_rt1,
    "RT2": validate_rt2,
    "RT3": validate_rt3,
    "RT4": validate_rt4,
    "RT5": validate_rt5,
}


def validate_event(event: dict[str, object]) -> list[str]:
    """Run field-level validations for any record type."""
    rt = str(event.get("type", ""))
    validator = _VALIDATORS.get(rt)
    if validator is None:
        return [f"Unknown record type '{rt}'"]
    return validator(event)


# ── Projections ─────────────────────────────────────────────────────────────


def _file_summary(state: dict[str, object]) -> object:
    counts: dict[str, int] = state.get("counts", {})  # type: ignore[assignment]
    return {
        "total_records": sum(counts.values()),
        "record_counts": dict(counts),
        "is_complete": state["phase"] == "END",
    }


def _integrity_report(state: dict[str, object]) -> object:
    counts: dict[str, int] = state.get("counts", {})  # type: ignore[assignment]
    return {
        "serial": state["serial"],
        "expected_records": sum(counts.values()),
        "blocks_balanced": state["open_blocks"] == 0,
        "has_header": counts.get("RT1", 0) == 1,
        "has_trailer": counts.get("RT5", 0) >= 1,
        "structure_valid": state["phase"] in ("END", "AFTER_RT5_CONTINUE"),
        "validation_errors": list(state.get("validation_errors", [])),  # type: ignore[arg-type]
    }


# ── Projection hooks (new signature: state, event, ctx) ───────────────────


def _file_summary_hook(state, event, ctx):
    return _file_summary(state)


def _integrity_report_hook(state, event, ctx):
    return _integrity_report(state)


# ── Outputs ─────────────────────────────────────────────────────────────────


def _emit_header(
    state: dict[str, object],
    event: dict[str, object],
    new_state: dict[str, object],
) -> dict[str, object] | None:
    """Emit the parsed RT1 header record."""
    return {
        "output_type": "Header",
        "record_type": event.get("record_type"),
        "record_serial_number": event.get("record_serial_number"),
        "title_of_contents": event.get("title_of_contents"),
        "number_of_seasons": event.get("number_of_seasons"),
        "data_set_serial_number": event.get("data_set_serial_number"),
    }


def _emit_carrier(
    state: dict[str, object],
    event: dict[str, object],
    new_state: dict[str, object],
) -> dict[str, object] | None:
    """Emit the parsed RT2 carrier record — all fields from carrier.spec.jsonld."""
    carrier = {k: v for k, v in event.items() if k != "type"}
    carrier["output_type"] = "Carrier"
    return carrier


def _emit_sealed_flight(
    state: dict[str, object],
    event: dict[str, object],
    new_state: dict[str, object],
) -> dict[str, object] | None:
    """Emit the sealed flight from pending_flight (set by transition on RT3/RT5).

    A sealed flight contains the full RT3 record with nested RT4 segments.
    Emitted when a new RT3 arrives (sealing the previous) or RT5 closes the block.
    This output fires on RT3 and RT5 — returns None if no pending flight.
    """
    pending = new_state.get("pending_flight")
    if pending is None:
        return None
    flight = dict(pending)  # type: ignore[arg-type]
    flight["output_type"] = "Flights"
    return flight


def _emit_carrier_complete(
    state: dict[str, object],
    event: dict[str, object],
    new_state: dict[str, object],
) -> dict[str, object] | None:
    """Emit CarrierComplete — all RT5 fields + carrier context + computed counts."""
    counts: dict[str, int] = new_state.get("counts", {})  # type: ignore[assignment]
    trailer = {k: v for k, v in event.items() if k != "type"}
    trailer["output_type"] = "CarrierComplete"
    trailer["time_mode"] = state.get("time_mode")
    trailer["flight_count"] = counts.get("RT3", 0)
    trailer["segment_count"] = counts.get("RT4", 0)
    return trailer


# ── Helpers for K3l expressions ─────────────────────────────────────────────

_phase = Field(Var("state"), "phase")
_event_type = EventField("type")


def _phase_eq(val: str) -> Compare:
    return Compare(CmpOp.EQ, _phase, LStr(val))


# ── Spec (declarative, frozen dataclass) ───────────────────────────────────

ssim_spec = Spec(
    name="ssim_ch7",
    state0=INITIAL_STATE,
    # ── Guards (DFA transitions) ────────────────────────────────────
    permits=(
        Permit(
            name="rt1_permitted",
            when=_phase_eq("EXPECT_RT1"),
            on="RT1",
        ),
        Permit(
            name="rt2_permitted",
            when=Or(_phase_eq("AFTER_RT1"), _phase_eq("AFTER_RT5_CONTINUE")),
            on="RT2",
        ),
        Permit(
            name="rt3_permitted",
            when=Or(_phase_eq("IN_CARRIER"), _phase_eq("IN_FLIGHT")),
            on="RT3",
        ),
        Permit(
            name="rt4_permitted",
            when=_phase_eq("IN_FLIGHT"),
            on="RT4",
        ),
        Permit(
            name="rt5_permitted",
            when=Or(_phase_eq("IN_CARRIER"), _phase_eq("IN_FLIGHT")),
            on="RT5",
        ),
    ),
    # ── Safety Invariants ───────────────────────────────────────────
    #
    # Serial continuity: next serial == prev serial + 1
    # OR overflow: prev == 999999 and next == 2
    # OR serial reset at carrier block boundary (concatenated files)
    maintains=(
        Maintain(
            name="serial_continuity",
            expr=Always(
                Or(
                    # Normal: increment by 1
                    Compare(
                        CmpOp.EQ,
                        After("serial"),
                        Arith(ArithOp.ADD, Before("serial"), LInt(1)),
                    ),
                    Or(
                        # Overflow: 999999 -> 2
                        And(
                            Compare(CmpOp.EQ, Before("serial"), LInt(999999)),
                            Compare(CmpOp.EQ, After("serial"), LInt(2)),
                        ),
                        # Serial reset at carrier boundary (concatenated format)
                        Compare(CmpOp.LT, After("serial"), Before("serial")),
                    ),
                )
            ),
        ),
        # Blocks balanced after RT5
        Maintain(
            name="blocks_balanced_after_rt5",
            expr=Always(
                Implies(
                    Or(_phase_eq("END"), _phase_eq("AFTER_RT5_CONTINUE")),
                    Compare(
                        CmpOp.EQ,
                        Field(Var("state"), "open_blocks"),
                        LInt(0),
                    ),
                )
            ),
        ),
    ),
)


# ── EmbeddedRuntime (projections + outputs use Python callables) ───────────

# Import the transition function (must be after ssim_spec is defined
# to avoid circular imports — ssim_system imports validate_event from here)
from ssim_system import ssim_transition  # noqa: E402

ssim_runtime = EmbeddedRuntime(
    spec=ssim_spec,
    transition=ssim_transition,
    projection_hooks={
        "file_summary": _file_summary_hook,
        "integrity_report": _integrity_report_hook,
    },
    output_hooks={
        "header": lambda s, e, ns: (
            _emit_header(s, e, ns) if e.get("type") == "RT1" else None
        ),
        "carrier": lambda s, e, ns: (
            _emit_carrier(s, e, ns) if e.get("type") == "RT2" else None
        ),
        "sealed_flight_on_rt3": lambda s, e, ns: (
            _emit_sealed_flight(s, e, ns) if e.get("type") == "RT3" else None
        ),
        "sealed_flight_on_rt5": lambda s, e, ns: (
            _emit_sealed_flight(s, e, ns) if e.get("type") == "RT5" else None
        ),
        "carrier_complete": lambda s, e, ns: (
            _emit_carrier_complete(s, e, ns) if e.get("type") == "RT5" else None
        ),
    },
    hash_fn="blake3",
)
