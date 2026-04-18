"""11 — Redis-Style Key-Value Server

Simplified Redis: SET / GET / DEL / INCR / EXPIRE plus MULTI/EXEC transactions.

Demonstrates:
- Sugar (S, E, k3) with .in_() membership and arithmetic
- Validate clauses for command-level field validation
- Protocol DSL for transaction state (idle → in_multi → idle)
- Outputs (declarative) for command responses
- denied= for redis-style error messages
"""

from __future__ import annotations

from k3c import (
    Always,
    Concat,
    E,
    EventDef,
    EventField,
    FieldDef,
    Impossible,
    LStr,
    Maintain,
    Ok,
    Output,
    Permit,
    Protocol,
    Record,
    S,
    Spec,
    Universe,
    Validate,
    Violated,
    k3,
)
from k3c.ir.types import TBool, TInt, TString


# Transaction state via Protocol DSL
tx_proto = Protocol(
    name="tx",
    state_field="tx_status",
    states=("idle", "in_multi"),
    transitions=(
        ("idle",     "MULTI",   "in_multi"),
        ("in_multi", "EXEC",    "idle"),
        ("in_multi", "DISCARD", "idle"),
    ),
)


# Valid command names (used by Validate via .in_())
WRITE_CMDS = ("SET", "DEL", "INCR", "EXPIRE")
READ_CMDS = ("GET", "EXISTS", "TTL")


spec = Spec(
    name="redis",
    state0={
        "tx_status": "idle",
        "n_keys": 0,
        "n_writes": 0,
        "queued": 0,
    },
    # Declare every event type with typed fields. The engine enforces:
    #   - unknown event types -> Impossible (event_schema rule)
    #   - missing required fields -> Impossible
    #   - wrong field types -> Impossible
    events=tx_proto.event_defs() + (
        EventDef(name="SET",     fields=(FieldDef(name="key", type=TString()),
                                          FieldDef(name="value", type=TString()))),
        EventDef(name="GET",     fields=(FieldDef(name="key", type=TString()),)),
        EventDef(name="DEL",     fields=(FieldDef(name="key", type=TString()),)),
        EventDef(name="INCR",    fields=(FieldDef(name="key", type=TString()),
                                          FieldDef(name="is_integer", type=TBool()))),
        EventDef(name="EXPIRE",  fields=(FieldDef(name="key", type=TString()),
                                          FieldDef(name="ttl", type=TInt()))),
    ),
    permits=(
        # Reads + writes both need the server to be operational
        Permit(name="any_cmd", when=k3(S.n_keys >= 0)),
    ),
    validates=(
        # SET requires both key and value
        Validate(
            name="set_has_key_and_value",
            on="SET",
            check=k3((E.key != None) & (E.value != None)),  # noqa: E711
            denied=k3(LStr("(error) WRONGTYPE wrong number of arguments for 'set'")),
        ),
        # INCR target must already be an integer (we model this as a validity flag in the event)
        Validate(
            name="incr_is_integer",
            on="INCR",
            check=k3(E.is_integer == True),  # noqa: E712
            field="key",
            denied=Concat(LStr("(error) value is not an integer for key="), EventField("key")),
        ),
        # EXPIRE TTL must be positive
        Validate(
            name="expire_positive",
            on="EXPIRE",
            check=k3(E.ttl > 0),
            field="ttl",
            constraint="> 0",
        ),
    ),
    maintains=(
        # n_keys never goes negative
        Maintain(name="non_negative_keys", expr=Always(k3(S.n_keys >= 0))),
        # tx state stays valid
        *tx_proto.maintains(),
    ),
    outputs=(
        # Echo back a Redis-style "+OK" for SET / DEL / EXPIRE
        Output(
            name="ok_response",
            on="SET",
            expr=Record((("type", LStr("+OK")),)),
        ),
        # Return the queued count after MULTI commands
        Output(
            name="queued_response",
            expr=Record((
                ("type", LStr("+QUEUED")),
                ("queued", k3(S.queued)),
            )),
        ),
    ),
)


TX_TABLE = tx_proto.transition_table()


def transition(state: dict, event: dict) -> dict:
    new_state = dict(state)

    # Tx state transitions via the protocol table
    new_tx = TX_TABLE.get((state["tx_status"], event["type"]))
    if new_tx:
        new_state["tx_status"] = new_tx
        if event["type"] == "EXEC":
            # Apply queued writes — for the demo, just bump n_writes
            new_state["n_writes"] = state["n_writes"] + state["queued"]
            new_state["queued"] = 0
        elif event["type"] == "DISCARD":
            new_state["queued"] = 0
        return new_state

    # Inside MULTI: queue the command
    if state["tx_status"] == "in_multi" and event["type"] in WRITE_CMDS:
        new_state["queued"] = state["queued"] + 1
        return new_state

    # Outside MULTI: execute directly
    match event["type"]:
        case "SET":
            new_state["n_keys"] = state["n_keys"] + 1
            new_state["n_writes"] = state["n_writes"] + 1
        case "DEL":
            new_state["n_keys"] = max(0, state["n_keys"] - 1)
            new_state["n_writes"] = state["n_writes"] + 1
        case "INCR" | "EXPIRE":
            new_state["n_writes"] = state["n_writes"] + 1
    return new_state


def main() -> None:
    u = Universe(spec=spec, transition=transition)

    print("== Direct commands (event_schema enforces typed events) ==")
    for evt in [
        {"type": "SET", "key": "foo", "value": "bar"},               # ok
        {"type": "SET", "key": None, "value": "x"},                  # event_schema: key None
        {"type": "BOGUS", "key": "x"},                                # event_schema: unknown type
        {"type": "INCR", "key": "counter", "is_integer": True},       # ok
        {"type": "INCR", "key": "x"},                                 # event_schema: missing is_integer
        {"type": "EXPIRE", "key": "foo", "ttl": -5},                  # Validate: ttl > 0
    ]:
        result = u.apply(evt)
        match result:
            case Ok(state=s, outputs=outputs):
                resp = next((o["type"] for o in outputs if "type" in o), "")
                print(f"  ok       {evt['type']:8s}  {resp}  n_keys={s['n_keys']} n_writes={s['n_writes']}")
            case Impossible(why=w):
                print(f"  -SCHEMA  {evt['type']:8s}  {w.message}")
            case Violated(why=w):
                print(f"  -ERR     {evt['type']:8s}  {w.message}")

    print("\n== MULTI/EXEC transaction ==")
    for evt in [
        {"type": "MULTI"},
        {"type": "SET", "key": "a", "value": "1"},
        {"type": "SET", "key": "b", "value": "2"},
        {"type": "INCR", "key": "c", "is_integer": True},
        {"type": "EXEC"},
    ]:
        result = u.apply(evt)
        if isinstance(result, Ok):
            print(f"  ok       {evt['type']:8s}  queued={u.get('queued')} tx_status={u.get('tx_status')}")

    print(f"\nFinal: {u.state}")


if __name__ == "__main__":
    main()
