# examples/ssim/ssim_extractors.py
"""
SSIM record extractors — decode 200-byte fixed-width records to typed dicts.

Field positions match the JSON-LD specs in specs-json/ exactly.
All positions are 0-based, inclusive end (matching JSON-LD position.start/end).
"""

from __future__ import annotations

RECORD_WIDTH = 200


def _s(raw: bytes, start: int, end: int) -> str:
    """Extract string field (inclusive end), strip trailing blanks."""
    return raw[start : end + 1].decode("ascii", errors="replace").rstrip()


def _s_raw(raw: bytes, start: int, end: int) -> str:
    """Extract string field without stripping (preserves padding)."""
    return raw[start : end + 1].decode("ascii", errors="replace")


def _int(raw: bytes, start: int, end: int) -> int:
    """Extract zero-padded integer field."""
    val = raw[start : end + 1].decode("ascii", errors="replace").strip()
    if not val or not val.isdigit():
        return 0
    return int(val)


def _serial(raw: bytes) -> int:
    """Extract record_serial_number (bytes 194-199)."""
    return _int(raw, 194, 199)


# ── RT1: Header Record (header.spec.jsonld) ────────────────────────────────
# [0]       record_type          M
# [1-34]    title_of_contents    M
# [35-39]   spare_1              M (skip)
# [40]      number_of_seasons    O
# [41-190]  spare_2              M (skip)
# [191-193] data_set_serial_number M
# [194-199] record_serial_number M


def extract_rt1(raw: bytes) -> dict[str, object]:
    return {
        "type": "RT1",
        "record_type": "1",
        "title_of_contents": _s(raw, 1, 34),
        "number_of_seasons": _s(raw, 40, 40),
        "data_set_serial_number": _int(raw, 191, 193),
        "record_serial_number": _serial(raw),
    }


# ── RT2: Carrier Record (carrier.spec.jsonld) ──────────────────────────────
# [0]       record_type                        M
# [1]       time_mode                          M
# [2-4]     airline_designator                 M
# [5-9]     spare_1                            M (skip)
# [10-12]   season                             O
# [13]      spare_2                            M (skip)
# [14-20]   period_of_validity_from            M
# [21-27]   period_of_validity_to              M
# [28-34]   creation_date                      M
# [35-63]   title_of_data                      O
# [64-70]   release_date                       O
# [71]      schedule_status                    M
# [72-106]  creator_reference                  O
# [107]     duplicate_airline_designator_marker C
# [108-168] general_information                O
# [169-187] in_flight_service_info_defaults    O
# [188-189] electronic_ticketing_info          O
# [190-193] creation_time                      M
# [194-199] record_serial_number               M


def extract_rt2(raw: bytes) -> dict[str, object]:
    return {
        "type": "RT2",
        "record_type": "2",
        "time_mode": _s(raw, 1, 1),
        "airline_designator": _s_raw(raw, 2, 4),
        "season": _s(raw, 10, 12),
        "period_of_validity_from": _s(raw, 14, 20),
        "period_of_validity_to": _s(raw, 21, 27),
        "creation_date": _s(raw, 28, 34),
        "title_of_data": _s(raw, 35, 63),
        "release_date": _s(raw, 64, 70),
        "schedule_status": _s(raw, 71, 71),
        "creator_reference": _s(raw, 72, 106),
        "duplicate_airline_designator_marker": _s(raw, 107, 107),
        "general_information": _s(raw, 108, 168),
        "in_flight_service_info_defaults": _s(raw, 169, 187),
        "electronic_ticketing_info": _s(raw, 188, 189),
        "creation_time": _s(raw, 190, 193),
        "record_serial_number": _serial(raw),
    }


# ── RT3: Flight Leg Record (flight.spec.jsonld) ────────────────────────────
# [0]       record_type                            M
# [1]       operational_suffix                     C
# [2-4]     airline_designator                     M
# [5-8]     flight_number                          M
# [9-10]    itinerary_variation_identifier          M
# [11-12]   leg_sequence_number                    M
# [13]      service_type                           M
# [14-20]   period_of_operation_from               M
# [21-27]   period_of_operation_to                 M
# [28-34]   days_of_operation                      M
# [35]      frequency_rate                         C
# [36-38]   departure_station                      M
# [39-42]   passenger_std                          M
# [43-46]   aircraft_std                           M
# [47-51]   departure_utc_variation                M
# [52-53]   departure_terminal                     C
# [54-56]   arrival_station                        M
# [57-60]   aircraft_sta                           M
# [61-64]   passenger_sta                          M
# [65-69]   arrival_utc_variation                  M
# [70-71]   arrival_terminal                       C
# [72-74]   aircraft_type                          M
# [75-94]   passenger_reservations_booking_designator C
# [95-99]   passenger_reservations_booking_modifier C
# [100-109] meal_service_note                      O
# [110-118] joint_operation_airline_designators     C
# [119-120] mct_international_domestic_status       O
# [121]     secure_flight_indicator                O
# [122-126] spare_1                                M (skip)
# [127]     itinerary_variation_identifier_overflow C
# [128-130] aircraft_owner                         C
# [131-133] cockpit_crew_employer                  C
# [134-136] cabin_crew_employer                    C
# [137-139] onward_airline_designator              M
# [140-143] onward_flight_number                   M
# [144]     aircraft_rotation_layover              C
# [145]     onward_operational_suffix              C
# [146]     spare_2                                M (skip)
# [147]     flight_transit_layover                 C
# [148]     operating_airline_disclosure_marker     C
# [149-159] traffic_restriction_code               C
# [160]     traffic_restriction_code_leg_overflow   C
# [161-171] spare_3                                M (skip)
# [172-191] aircraft_configuration_version         C
# [192-193] date_variation                         O
# [194-199] record_serial_number                   M


def extract_rt3(raw: bytes) -> dict[str, object]:
    return {
        "type": "RT3",
        "record_type": "3",
        "operational_suffix": _s(raw, 1, 1),
        "airline_designator": _s_raw(raw, 2, 4),
        "flight_number": _s_raw(raw, 5, 8),
        "itinerary_variation_identifier": _int(raw, 9, 10),
        "leg_sequence_number": _int(raw, 11, 12),
        "service_type": _s(raw, 13, 13),
        "period_of_operation_from": _s(raw, 14, 20),
        "period_of_operation_to": _s(raw, 21, 27),
        "days_of_operation": _s_raw(raw, 28, 34),
        "frequency_rate": _s(raw, 35, 35),
        "departure_station": _s(raw, 36, 38),
        "passenger_std": _s(raw, 39, 42),
        "aircraft_std": _s(raw, 43, 46),
        "departure_utc_variation": _s(raw, 47, 51),
        "departure_terminal": _s(raw, 52, 53),
        "arrival_station": _s(raw, 54, 56),
        "aircraft_sta": _s(raw, 57, 60),
        "passenger_sta": _s(raw, 61, 64),
        "arrival_utc_variation": _s(raw, 65, 69),
        "arrival_terminal": _s(raw, 70, 71),
        "aircraft_type": _s(raw, 72, 74),
        "passenger_reservations_booking_designator": _s(raw, 75, 94),
        "passenger_reservations_booking_modifier": _s(raw, 95, 99),
        "meal_service_note": _s(raw, 100, 109),
        "joint_operation_airline_designators": _s(raw, 110, 118),
        "mct_international_domestic_status": _s(raw, 119, 120),
        "secure_flight_indicator": _s(raw, 121, 121),
        "itinerary_variation_identifier_overflow": _s(raw, 127, 127),
        "aircraft_owner": _s(raw, 128, 130),
        "cockpit_crew_employer": _s(raw, 131, 133),
        "cabin_crew_employer": _s(raw, 134, 136),
        "onward_airline_designator": _s(raw, 137, 139),
        "onward_flight_number": _s(raw, 140, 143),
        "aircraft_rotation_layover": _s(raw, 144, 144),
        "onward_operational_suffix": _s(raw, 145, 145),
        "flight_transit_layover": _s(raw, 147, 147),
        "operating_airline_disclosure_marker": _s(raw, 148, 148),
        "traffic_restriction_code": _s(raw, 149, 159),
        "traffic_restriction_code_leg_overflow": _s(raw, 160, 160),
        "aircraft_configuration_version": _s(raw, 172, 191),
        "date_variation": _s(raw, 192, 193),
        "record_serial_number": _serial(raw),
    }


# ── RT4: Segment Data Record (segment.spec.jsonld) ─────────────────────────
# [0]       record_type                            M
# [1]       operational_suffix                     C
# [2-4]     airline_designator                     M
# [5-8]     flight_number                          M
# [9-10]    itinerary_variation_identifier          M
# [11-12]   leg_sequence_number                    M
# [13]      service_type                           M
# [14-26]   spare_1                                M (skip)
# [27]      itinerary_variation_identifier_overflow C
# [28]      board_point_indicator                  M
# [29]      off_point_indicator                    M
# [30-32]   data_element_identifier                M
# [33-35]   board_point                            M
# [36-38]   off_point                              M
# [39-193]  segment_data                           C
# [194-199] record_serial_number                   M


def extract_rt4(raw: bytes) -> dict[str, object]:
    return {
        "type": "RT4",
        "record_type": "4",
        "operational_suffix": _s(raw, 1, 1),
        "airline_designator": _s_raw(raw, 2, 4),
        "flight_number": _s_raw(raw, 5, 8),
        "itinerary_variation_identifier": _int(raw, 9, 10),
        "leg_sequence_number": _int(raw, 11, 12),
        "service_type": _s(raw, 13, 13),
        "itinerary_variation_identifier_overflow": _s(raw, 27, 27),
        "board_point_indicator": _s(raw, 28, 28),
        "off_point_indicator": _s(raw, 29, 29),
        "data_element_identifier": _s(raw, 30, 32),
        "board_point": _s(raw, 33, 35),
        "off_point": _s(raw, 36, 38),
        "segment_data": _s(raw, 39, 193),
        "record_serial_number": _serial(raw),
    }


# ── RT5: Trailer Record (trailer.spec.jsonld) ──────────────────────────────
# [0]       record_type                    M
# [1]       spare_1                        M (skip)
# [2-4]     airline_designator             M
# [5-11]    release_sell_date              O
# [12-186]  spare_2                        M (skip)
# [187-192] serial_number_check_reference  M
# [193]     continuation_end_code          M
# [194-199] record_serial_number           M


def extract_rt5(raw: bytes) -> dict[str, object]:
    return {
        "type": "RT5",
        "record_type": "5",
        "airline_designator": _s_raw(raw, 2, 4),
        "release_sell_date": _s(raw, 5, 11),
        "serial_number_check_reference": _int(raw, 187, 192),
        "continuation_end_code": _s(raw, 193, 193),
        "record_serial_number": _serial(raw),
    }


# ── Dispatch ───────────────────────────────────────────────────────────────

_EXTRACTORS = {
    ord("1"): extract_rt1,
    ord("2"): extract_rt2,
    ord("3"): extract_rt3,
    ord("4"): extract_rt4,
    ord("5"): extract_rt5,
}


def decode_record(raw: bytes) -> dict[str, object] | None:
    """Decode a 200-byte SSIM record. Returns None for padding/invalid."""
    if len(raw) < RECORD_WIDTH:
        return None
    extractor = _EXTRACTORS.get(raw[0])
    if extractor is None:
        return None  # padding or invalid
    return extractor(raw)


def records_from_file(path: str):
    """Yield decoded event dicts from an SSIM file. Skips padding."""
    with open(path, "rb") as f:
        data = f.read()
    for line in data.split(b"\n"):
        line = line.rstrip(b"\r")
        if len(line) < RECORD_WIDTH:
            continue
        event = decode_record(line)
        if event is not None:
            yield event
