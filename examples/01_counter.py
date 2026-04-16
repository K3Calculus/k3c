"""
Example 01: Counter -- The simplest possible K3 system.

A counter that increments. One state field, one event type, one invariant.
Demonstrates: Spec (dataclass), Universe (constructor), apply, Ok, maintain.
"""

from k3c.engine.result import Impossible, Ok, Violated
from k3c.ir.expr import Always, CmpOp, Compare, Field, LBool, LInt, Var
from k3c.runtime.universe import Universe
from k3c.spec.model import Maintain, Permit, Spec

# -- Spec (declarative, no builder) -------------------------------------------

spec = Spec(
    name="counter",
    state0={"count": 0},
    permits=(Permit(name="always_ok", when=LBool(True), on="Inc"),),
    maintains=(
        Maintain(
            name="non_negative",
            expr=Always(Compare(CmpOp.GE, Field(Var("state"), "count"), LInt(0))),
        ),
    ),
)


# -- Transition function (plain function, no System class) ---------------------


def counter_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Inc":
            return {**state, "count": state["count"] - event.get("n", 1)}
        case _:
            return state


# -- Usage ---------------------------------------------------------------------


def main():
    u = Universe(spec=spec, transition=counter_transition)
    print(f"Initial: {u.state}")

    # Increment by 1
    r = u.apply({"type": "Inc", "n": 1})
    match r:
        case Ok(state=s):
            print(f"After +1: {s}")
        case Impossible(why=why):
            print("impossible", why)
            return
        case Violated(why=why):
            print("violated", why)
            return

    # Increment by 5
    r = u.apply({"type": "Inc", "n": 5})
    assert isinstance(r, Ok)
    print(f"After +5: {u.state}")

    # Reduce a batch
    u.reset()
    r = u.reduce([{"type": "Inc", "n": i} for i in range(1, 6)])
    assert isinstance(r, Ok)
    print(f"After 1+2+3+4+5: {u.state}")

    # Stream
    u.reset()
    for result in u.stream([{"type": "Inc", "n": 10}, {"type": "Inc", "n": 20}]):
        match result:
            case Ok(state=s):
                print(f"  stream step: count={s['count']}")

    print("Counter example passed.")


if __name__ == "__main__":
    main()
