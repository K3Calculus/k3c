"""06 — Compose, Pipeline, and Bridge

Three universe-algebra primitives:
- compose_many: route events to N named universes by name
- Pipeline: apply event to every stage in order
- Bridge: source applies, then forwards transformed event to target.
  In synchronous mode, target's Ok flows back as merged outputs.

Demonstrates:
- compose_many({name: u}, router=...)
- Pipeline([s1, s2, s3])
- BridgedUniverse with synchronous mode + target outputs returned
"""

from __future__ import annotations

from k3c import (
    BridgedUniverse,
    BridgeMode,
    LStr,
    Ok,
    Output,
    Permit,
    Pipeline,
    S,
    Spec,
    Universe,
    compose_many,
    k3,
)


def make_counter(name: str) -> Universe:
    spec = Spec(
        name=name,
        state0={"count": 0},
        permits=(Permit(name="ok", when=k3(S.count >= 0)),),
        outputs=(Output(name="ack", expr=k3(LStr(f"{name}-ack"))),),
    )
    return Universe(
        spec=spec, transition=lambda s, e: {**s, "count": s["count"] + 1}
    )


# -- compose_many: route events to one of N named universes -------------------


def compose_demo() -> None:
    print("== compose_many: route by name ==")
    orders = make_counter("orders")
    payments = make_counter("payments")
    audit = make_counter("audit")

    composed = compose_many(
        {"orders": orders, "payments": payments, "audit": audit},
        router=lambda e: "audit" if e["type"].startswith("Audit") else (
            "payments" if e["type"].startswith("Pay") else "orders"
        ),
    )

    composed.apply({"type": "Place"})
    composed.apply({"type": "Pay"})
    composed.apply({"type": "Audit"})
    composed.apply({"type": "Place"})

    state = composed.state
    print(f"  orders.count={state['orders']['count']}  "
          f"payments.count={state['payments']['count']}  "
          f"audit.count={state['audit']['count']}")


# -- Pipeline: apply event to every stage -------------------------------------


def pipeline_demo() -> None:
    print("\n== Pipeline: apply to every stage ==")
    s1 = make_counter("validate")
    s2 = make_counter("transform")
    s3 = make_counter("publish")

    pipe = Pipeline([s1, s2, s3])
    for _ in range(3):
        pipe.apply({"type": "Process"})

    print(f"  validate.count={s1.get('count')}  "
          f"transform.count={s2.get('count')}  "
          f"publish.count={s3.get('count')}")


# -- Bridge: synchronous returns target outputs -------------------------------


def bridge_demo() -> None:
    print("\n== Bridge (synchronous): target outputs flow back ==")
    main_u = make_counter("main")
    audit_u = make_counter("audit")

    bridged = BridgedUniverse(
        source=main_u,
        target=audit_u,
        mapper=lambda state, event, new_state: {"type": "AuditEntry", "src_event": event["type"]},
        mode=BridgeMode.SYNCHRONOUS,
    )

    result = bridged.apply({"type": "Update"})
    if isinstance(result, Ok):
        print(f"  combined state: {result.state}")
        print(f"  outputs (source + target): {list(result.outputs)}")
        # Target projections are namespaced as 'target.<name>'
        if result.projections:
            print(f"  projections: {dict(result.projections)}")


def main() -> None:
    compose_demo()
    pipeline_demo()
    bridge_demo()


if __name__ == "__main__":
    main()
