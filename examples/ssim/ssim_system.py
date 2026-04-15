# examples/ssim/ssim_system.py
"""
SSIM transition function — the System protocol for SSIM file parsing.

The transition function T(s, e) -> s' advances the DFA state based on
the record type and updates counters, carrier context, and flight context.

Flight accumulation: RT3 events start a new flight accumulator. RT4 events
append segments to the current flight. When a new RT3 or RT5 arrives, the
previous flight (with all its segments) is sealed into `pending_flight` for
the output layer to emit.
"""

from __future__ import annotations

from ssim_spec import validate_event


def _seal_current_flight(state: dict[str, object]) -> dict[str, object] | None:
    """Seal the current flight record with its accumulated segments.

    Returns the sealed flight dict, or None if no flight is in progress.
    """
    current = state.get("current_flight_record")
    if current is None:
        return None
    flight = dict(current)  # type: ignore[arg-type]
    flight["segments"] = list(state.get("current_segments", []))  # type: ignore[arg-type]
    return flight


class SSIMSystem:
    """SSIM parser transition function.

    Advances the DFA:
        EXPECT_RT1 --RT1--> AFTER_RT1
        AFTER_RT1 --RT2--> IN_CARRIER
        IN_CARRIER --RT3--> IN_FLIGHT
        IN_CARRIER --RT5--> AFTER_RT5_CONTINUE | END
        IN_FLIGHT --RT3--> IN_FLIGHT
        IN_FLIGHT --RT4--> IN_FLIGHT
        IN_FLIGHT --RT5--> AFTER_RT5_CONTINUE | END
        AFTER_RT5_CONTINUE --RT2--> IN_CARRIER
    """

    def transition(
        self, state: dict[str, object], event: dict[str, object]
    ) -> dict[str, object]:
        rt = event["type"]
        new: dict[str, object] = {
            **state,
            "serial": event["record_serial_number"],
            "counts": {**state["counts"]},  # type: ignore[arg-type]
            "pending_flight": None,  # reset each step
        }
        counts: dict[str, int] = new["counts"]  # type: ignore[assignment]
        counts[rt] = counts.get(rt, 0) + 1

        # Field-level validation (from JSON-LD specs)
        field_errors = validate_event(event)
        if field_errors:
            all_errors = list(state.get("validation_errors", []))  # type: ignore[arg-type]
            all_errors.extend(field_errors)
            new["validation_errors"] = all_errors

        if rt == "RT1":
            new["phase"] = "AFTER_RT1"
            new["dataset_serial"] = event.get("data_set_serial_number", 0)

        elif rt == "RT2":
            new["phase"] = "IN_CARRIER"
            new["carrier"] = event["airline_designator"]
            new["time_mode"] = event.get("time_mode")
            new["open_blocks"] = int(state.get("open_blocks", 0)) + 1  # type: ignore[arg-type]
            new["carrier_validity_from"] = event.get("period_of_validity_from")
            new["carrier_validity_to"] = event.get("period_of_validity_to")
            new["current_flight_record"] = None
            new["current_segments"] = []

        elif rt == "RT3":
            # Seal previous flight (if any) before starting new one
            new["pending_flight"] = _seal_current_flight(state)

            new["phase"] = "IN_FLIGHT"
            new["flight_key"] = (
                f"{event['airline_designator']}|"
                f"{event['flight_number']}|"
                f"{event.get('itinerary_variation_identifier', 0)}|"
                f"{event.get('leg_sequence_number', 0)}|"
                f"{event.get('service_type', '')}"
            )
            # Start new flight accumulator — store all RT3 fields + carrier context
            flight_record = {k: v for k, v in event.items() if k != "type"}
            flight_record["time_mode"] = state.get("time_mode")
            new["current_flight_record"] = flight_record
            new["current_segments"] = []

        elif rt == "RT4":
            # Append segment to current flight — store all RT4 fields
            segments = list(state.get("current_segments", []))  # type: ignore[arg-type]
            segment_record = {k: v for k, v in event.items() if k != "type"}
            segments.append(segment_record)
            new["current_segments"] = segments

        elif rt == "RT5":
            # Seal last flight before closing carrier block
            new["pending_flight"] = _seal_current_flight(state)

            cont = event.get("continuation_end_code", "E")
            new["phase"] = "AFTER_RT5_CONTINUE" if cont == "C" else "END"
            new["continuation_end_code"] = cont
            new["open_blocks"] = int(state.get("open_blocks", 0)) - 1  # type: ignore[arg-type]
            new["carrier"] = None
            new["time_mode"] = None
            new["flight_key"] = None
            new["current_flight_record"] = None
            new["current_segments"] = []

        return new
