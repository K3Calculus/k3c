# SSIM Processing with k3c — Architecture Guide

> How to encode IATA SSIM Chapter 7 as a k3c causal system.

---

## 1. Why SSIM Maps to k3c

An SSIM file is a **sequential stream of causal events** (200-byte records) processed
by a **deterministic state machine** with **strict structural invariants**. Each
record's legality depends on what came before, and the file hierarchy is a DFA.
This is exactly what k3c models.

The SSIM file structure:

```
RT1 → [RT2 → [RT3 → [RT4]*]* → RT5]* → EOF
```

maps to a k3c Universe where:

- Each 200-byte record is an **event**
- The DFA state (phase, current carrier, serial) is the **state**
- Structural ordering rules are **guards** (permit)
- Serial continuity and cross-record linking are **invariants** (maintain)
- Every RT2 eventually closing with RT5 is **liveness**
- File summary and integrity report are **projections**

---

## 2. The Three Layers: (I, U, K)

### Layer I — Initial (Extraction)

The JSON-LD field specs define how raw 200-byte records become typed event dicts.
Each record type has byte positions, types, padding rules.

```python
def decode_ssim_record(raw: bytes) -> dict:
    """I.decode — dispatch on byte 0 to type-specific extractors."""
    record_type = chr(raw[0])
    match record_type:
        case "1": return extract_rt1(raw)  # header.spec.jsonld positions
        case "2": return extract_rt2(raw)  # carrier.spec.jsonld positions
        case "3": return extract_rt3(raw)  # flight.spec.jsonld positions
        case "4": return extract_rt4(raw)  # segment.spec.jsonld positions
        case "5": return extract_rt5(raw)  # trailer.spec.jsonld positions
        case _:   return {"type": "Padding"}
```

Extractors can be **generated** from the JSON-LD specs — the field positions,
types, alignment, and padding rules are all machine-readable.

### Layer U — Unfolding (DFA + Invariants)

The heart of the encoding. The SSIM file structure is a deterministic finite
automaton with these states and transitions:

```
                    ┌──────────┐
           RT1      │          │  RT2
START ──────────► AFTER_RT1 ──────────► IN_CARRIER
                                          │    ^
                                     RT3  │    │ RT3
                                          v    │
                                       IN_FLIGHT
                                          │
                                     RT5  │
                    ┌─────────────────────┘
                    │
              ┌─────v──────┐
              │ code='C'?  │
              └─────┬──────┘
               yes  │  no
                    │   │
    AFTER_RT5_CONT <┘   └► END
         │
    RT2  │  (back to IN_CARRIER)
```

#### Guards (permit)

```python
.permit("rt1_permitted",
    when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("EXPECT_RT1")),
    on="RT1")

.permit("rt2_permitted",
    when=Or(
        Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("AFTER_RT1")),
        Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("AFTER_RT5_CONTINUE")),
    ),
    on="RT2")

.permit("rt3_permitted",
    when=Or(
        Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_CARRIER")),
        Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_FLIGHT")),
    ),
    on="RT3")

.permit("rt4_permitted",
    when=Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_FLIGHT")),
    on="RT4")

.permit("rt5_permitted",
    when=Or(
        Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_CARRIER")),
        Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("IN_FLIGHT")),
    ),
    on="RT5")
```

#### Transition function

```python
class SSIMParser:
    def transition(self, state, event):
        new = {**state}
        rt = event["type"]

        new["serial"] = event["record_serial_number"]
        new["counts"] = {**state["counts"]}
        new["counts"][rt] = state["counts"].get(rt, 0) + 1

        match rt:
            case "RT1":
                new["phase"] = "AFTER_RT1"
            case "RT2":
                new["phase"] = "IN_CARRIER"
                new["carrier"] = event["airline_designator"]
                new["time_mode"] = event["time_mode"]
                new["open_blocks"] = state["open_blocks"] + 1
            case "RT3":
                new["phase"] = "IN_FLIGHT"
                new["flight_key"] = {
                    "airline": event["airline_designator"],
                    "flight_number": event["flight_number"],
                    "itinerary_variation": event.get("itinerary_variation_identifier"),
                    "leg_sequence": event.get("leg_sequence_number"),
                    "service_type": event.get("service_type"),
                }
            case "RT4":
                pass  # phase stays IN_FLIGHT
            case "RT5":
                if event.get("continuation_end_code") == "C":
                    new["phase"] = "AFTER_RT5_CONTINUE"
                else:
                    new["phase"] = "END"
                new["open_blocks"] = state["open_blocks"] - 1
                new["carrier"] = None
                new["flight_key"] = None
                new["time_mode"] = None

        return new
```

#### Safety invariants (maintain Always)

```python
# Serial continuity: each record increments by 1
.maintain("serial_continuity",
    expr=Always(Compare(CmpOp.EQ,
        Field(After(Var("state")), "serial"),
        Arith(ArithOp.ADD, Field(Before(Var("state")), "serial"), LInt(1))
    )))

# RT1 is always serial 1
.maintain("rt1_is_first",
    expr=Always(Implies(
        Compare(CmpOp.EQ, EventField("type"), LStr("RT1")),
        Compare(CmpOp.EQ, EventField("record_serial_number"), LInt(1))
    )))

# RT4 must belong to current carrier
.maintain("rt4_carrier_match",
    expr=Always(Implies(
        Compare(CmpOp.EQ, EventField("type"), LStr("RT4")),
        Compare(CmpOp.EQ, EventField("airline_designator"),
                Field(Var("state"), "carrier"))
    )))

# No open carrier blocks at END
.maintain("blocks_balanced",
    expr=Always(Implies(
        Compare(CmpOp.EQ, Field(Var("state"), "phase"), LStr("END")),
        Compare(CmpOp.EQ, Field(Var("state"), "open_blocks"), LInt(0))
    )))
```

#### Liveness (maintain Eventually)

```python
# Every opened carrier block must eventually close
.maintain("carrier_closes",
    expr=Always(Eventually(
        Compare(CmpOp.LE, Field(Var("state"), "open_blocks"), LInt(0))
    )))
```

#### State design

```python
.state0({
    "phase": "EXPECT_RT1",       # DFA state
    "serial": 0,                  # last serial number
    "carrier": None,              # current RT2 airline designator
    "time_mode": None,            # current RT2 time mode (U/L)
    "flight_key": None,           # current RT3 composite key
    "open_blocks": 0,             # RT2s opened but not yet closed
    "counts": {},                 # record counts by type
})
```

### Layer K — Korrelator (Integrity)

```python
.korrelate(
    lift=lambda state: {
        "serial_valid": state["serial"] > 0,
        "structure_valid": state["phase"] != "ERROR",
        "blocks_balanced": state["open_blocks"] == 0 or state["phase"] != "END",
    },
    correlate=lambda actual, intended: all(actual.values()) == all(intended.values()),
    threshold="KC-1",
)
```

---

## 3. What apply() Results Mean for SSIM

| k3c Result    | SSIM Meaning                                             |
|---------------|----------------------------------------------------------|
| `Ok`          | Record accepted, parser state advanced                   |
| `Impossible`  | Wrong record type for current DFA state (structural error) |
| `Violated`    | Serial gap, carrier mismatch, or orphaned RT4 (corruption) |

---

## 4. Projections and Streaming Outputs

### Projections

Projections compute derived views from state. For SSIM:

```python
.project("file_summary", lambda state: {
    "total_records": sum(state["counts"].values()),
    "record_counts": state["counts"],
    "is_complete": state["phase"] == "END",
}, kind="derived")

.project("integrity_report", lambda state: {
    "serial_valid": state["serial"] == sum(state["counts"].values()),
    "blocks_balanced": state["open_blocks"] == 0,
    "has_header": state["counts"].get("RT1", 0) == 1,
    "structure_valid": state["phase"] == "END",
}, kind="derived")
```

Projections are **already streaming** — each `Ok` result from `apply()` carries
`.projections`. With `reduce_all()`, only the final projections are returned.

### Outputs (streaming side-effects)

For use cases like "parse and load", outputs emit per-event data:

```python
.output(
    "parsed_flight",
    lambda s, e, ns: {
        "type": "ParsedFlight",
        "airline": e["airline_designator"],
        "flight_number": e["flight_number"],
        "departure": e.get("departure_station"),
        "arrival": e.get("arrival_station"),
    } if e.get("type") == "RT3" else None,
)
```

### Accessing intermediate results with stream()

`universe.stream()` yields every `K3Result`, giving per-event access to
projections and outputs with constant memory:

```python
for result in u.stream(records_from_disk(path)):
    match result:
        case Ok(projections=p, outputs=o):
            for out in o:
                write_to_database(out)
        case Impossible():
            pass  # structural skip
        case Violated(why=w):
            alert_corruption(w)
```

---

## 5. File Formats in the Wild

Real SSIM files come in two variants:

### Format 1: True Multi-Carrier (continuous serials)

Example: OAG/Innovata feeds (`innov241202` — 7GB, 667 carriers, 34.9M records).

```
RT1 serial=000001
RT2 serial=000002  airline=AA           <- continuous serial
  RT3/RT4 ...
  RT4 serial=999999  airline=AA         <- overflow mid-carrier
  RT3 serial=000002  airline=AA         <- wraps to 000002
  ...
RT5 serial=296630  airline=AA  cont=C   <- more carriers
RT2 serial=296631  airline=AC           <- serial continues from RT5
  ...
RT5 serial=920937  airline=9X  cont=E   <- 667th carrier, end
```

- Serial is continuous across all carriers and overflows at 999999 -> 000002
- `cont=C` between carriers, `cont=E` only at the very end

### Format 2: Concatenated Blocks (reset serials)

Example: assembled from individual carrier files.

```
RT1 serial=000001
RT2 serial=000002  airline=EI
  ...228K records...
RT5 serial=228171  airline=EI  cont=E   <- each block says "end"
  ...padding...
RT2 serial=000002  airline=6E           <- serial RESETS
  ...
RT5 serial=031050  airline=6E  cont=E
```

- Serials reset per carrier block
- All RT5s have `cont=E`
- Zero-padding between blocks

---

## 6. Parallel Processing

### The Chunking Constraint

SSIM records have strict ownership:

- **RT3 belongs to RT2** — inherits time_mode, airline, validity period
- **RT4 belongs to RT3** — links via composite key
- **RT3 + RT4 clusters are atomic** — cannot split mid-cluster

Safe split points:

```
RT2 [carrier block start]   <- SAFE (carrier-level split)
  RT3 + RT4s (flight A)     <- SAFE (flight-level split)
  RT3 + RT4s (flight B)     <- SAFE
  RT3 + RT4                 <- NEVER split here (mid-cluster)
  ...RT4                    <- NEVER split here
RT5 [carrier block end]     <- SAFE (after RT5)
```

### Architecture: Single-Pass Streaming Dispatcher

No index scan needed. A single sequential read dispatches carrier blocks to
parallel workers as they complete:

```
File on disk (7GB)
    |
    |  sequential read (201 bytes at a time)
    v
+----------------------------------------------+
|           Dispatcher (single thread)          |
|                                               |
|  RT1 -> process inline                        |
|  RT2 -> note start offset, capture context    |
|  RT3 -> note as flight boundary               |
|  RT4 -> continue                              |
|  RT5 -> seal block, submit to worker pool     |
+--------------------+-------------------------+
                     |
          on RT5: submit carrier block
                     |
        +------------+------------+------------+
        v            v            v            v
   +---------+  +---------+  +---------+  +---------+
   |Worker 1 |  |Worker 2 |  |Worker 3 |  |Worker 4 |
   |  EI     |  |  6E     |  |  AA(1)  |  |  AA(2)  |
   | universe|  | universe|  | universe|  | universe|
   | .stream |  | .stream |  | .stream |  | .stream |
   +---------+  +---------+  +---------+  +---------+
        |            |            |            |
        +------------+------+-----+------------+
                            v
                      Merge Results
```

### Small vs Large Carrier Blocks

**Small carriers** (< 100K records): the dispatcher buffers events in memory
and submits the list to a worker.

**Large carriers** (>= 100K records, e.g., AA with 3.3M): the dispatcher records
byte offset boundaries and submits a `ChunkSource` — a frozen dataclass wrapping
a producer callable. The worker invokes it to stream events from disk on demand,
never materializing the full block:

```python
from k3c import ChunkSource

def make_chunk_source(
    file_path: str, start_line: int, end_line: int,
    decode_fn, rt2_context: dict,
) -> ChunkSource:
    """Lazy producer — reads byte range from disk on demand."""
    line_width = 201  # 200 bytes + newline

    def produce():
        # Emit a synthetic RT2 event so the worker has carrier context
        yield {"type": "RT2", **rt2_context}
        with open(file_path, "rb") as f:
            f.seek(start_line * line_width)
            for _ in range(start_line, end_line):
                raw = f.read(line_width)
                if len(raw) < 200:
                    break
                yield decode_fn(raw[:200])

    return ChunkSource(produce=produce)
```

### Flight-Level Sub-Chunking for Mega-Carriers

For carrier blocks with millions of records (e.g., AA = 3.3M), split at RT3
boundaries within the block. Each sub-chunk carries the same RT2 context:

```python
# Dispatcher tracked RT3 boundary offsets during its scan
flight_boundaries = [0, 50_000, 100_000, 150_000, ...]

sub_sources = [
    make_chunk_source(path, start, end, decode, rt2_ctx)
    for start, end in zip(flight_boundaries, flight_boundaries[1:])
]

sub_specs = [
    ssim_spec.slice(from_state={
        "phase": "IN_FLIGHT",
        "serial": boundary_serial,
        "carrier": rt2_ctx["airline_designator"],
        "time_mode": rt2_ctx["time_mode"],
        "open_blocks": 1,
        ...
    })
    for boundary_serial in boundary_serials
]

result = parallel_reduce(SSIMParser(), sub_specs, sub_sources, workers=8)
```

### Using k3c's parallel_reduce with ChunkSource

`parallel_reduce` accepts both materialized lists and `ChunkSource` instances:

```python
from k3c import parallel_reduce, ChunkSource

# Mix of small (list) and large (ChunkSource) carrier blocks
chunks: list[list[dict] | ChunkSource] = [
    small_carrier_events,           # list — buffered in memory
    make_chunk_source(...),         # ChunkSource — streams from disk
    make_chunk_source(...),
]

result = parallel_reduce(SSIMParser(), specs, chunks, workers=8)

if result.passed:
    print(f"Processed {result.total_processed} records")
    for state in result.states:
        print(f"  Carrier done: {state['carrier']}")
else:
    for chunk_idx, violated in result.violations:
        print(f"  Chunk {chunk_idx} violated: {violated.why.message}")
```

### Memory Profile

| Component          | Memory Usage                           |
|--------------------|----------------------------------------|
| Dispatcher         | O(1) — byte offsets + RT2 context only |
| Worker (list)      | O(chunk_size) — small carriers only    |
| Worker (source)    | O(1) — one event dict at a time        |
| Universe state     | O(state_size) — constant per worker    |
| Merge              | O(num_chunks) — one result per chunk   |

For a 7GB file with 667 carriers on 8 workers: peak memory is dominated by
the largest in-memory carrier block (if any) plus 8 concurrent Universe states.
With ChunkSource for all blocks, peak memory is ~O(8 * state_size).

---

## 7. Handling Serial Overflow

Real-world observation from `innov241202` (OAG feed):

```
line 1000002: RT4 serial=999995  airline=AA
line 1000006: RT4 serial=999999  airline=AA   <- max value
line 1000007: RT3 serial=000002  airline=AA   <- wraps to 000002
line 1000008: RT4 serial=000003  airline=AA
```

The serial overflows **mid-carrier** in the AA block. The invariant must handle
this. Two approaches:

**Approach A**: relaxed serial invariant that allows the 999999 -> 000002 wrap:

```python
.maintain("serial_continuity",
    expr=Always(Or(
        # Normal: next = prev + 1
        Compare(CmpOp.EQ,
            Field(After(Var("state")), "serial"),
            Arith(ArithOp.ADD, Field(Before(Var("state")), "serial"), LInt(1))),
        # Overflow: prev = 999999 and next = 2
        And(
            Compare(CmpOp.EQ, Field(Before(Var("state")), "serial"), LInt(999999)),
            Compare(CmpOp.EQ, Field(After(Var("state")), "serial"), LInt(2)),
        ),
    )))
```

**Approach B**: normalize serials in the transition function to a monotonic counter,
keeping the raw serial in a separate field for validation.

---

## 8. File Organization

```
examples/ssim/
├── specs-json/              # JSON-LD specs (field definitions)
│   ├── ssim.spec.jsonld     # Master spec
│   ├── header.spec.jsonld   # RT1
│   ├── carrier.spec.jsonld  # RT2
│   ├── flight.spec.jsonld   # RT3
│   ├── segment.spec.jsonld  # RT4
│   ├── trailer.spec.jsonld  # RT5
│   ├── shared.vocabulary.jsonld
│   └── sampledata/          # Real SSIM files for testing
├── ssim_extractors.py       # I.decode — generated from JSON-LD
├── ssim_spec.py             # k3c Spec — DFA guards, invariants, projections
├── ssim_system.py           # Transition function (System protocol)
├── ssim_dispatcher.py       # Streaming dispatcher for parallel processing
├── ssim_example.py          # End-to-end demo
├── ssim-processing-guide.md # This document
└── tests/
    └── test_ssim.py         # Tests against sampledata/
```

---

## 9. k3c Streaming API Summary

The following k3c APIs support streaming SSIM processing:

| API | Input | Memory | Use Case |
|-----|-------|--------|----------|
| `u.apply(event)` | single dict | O(1) | manual loop |
| `u.reduce(events)` | `Iterable` | O(1) with generator | fold, stop on first non-Ok |
| `u.reduce_all(events)` | `Iterable` | O(1) with generator | fold, skip Impossible |
| `u.stream(events)` | `Iterable` | O(1) with generator | yield each K3Result (projections + outputs) |
| `parallel_reduce(...)` | `list` or `ChunkSource` | O(1) per worker with ChunkSource | parallel carrier blocks |

All accept generators and iterators. `ChunkSource` is a frozen dataclass wrapping
a `produce: Callable[[], Iterable[dict]]` that streams events lazily from disk.
