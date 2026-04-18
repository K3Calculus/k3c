"""05 — Rate Limiter

Sliding-window counter with In() membership test and Permit denied=.

Demonstrates:
- IR sugar: AnyOf via |, In via .in_()
- Permit denied= for rich rejection messages
- u.stream() for processing event sequences
"""

from __future__ import annotations

from k3c import (
    Always,
    Concat,
    Field,
    Impossible,
    LStr,
    Maintain,
    Ok,
    Permit,
    S,
    Spec,
    Universe,
    Var,
    k3,
)


WINDOW_LIMIT = 5


spec = Spec(
    name="rate_limiter",
    state0={"count": 0, "window_start": 0, "current_time": 0},
    permits=(
        # Allow Request only if under the window limit
        Permit(
            name="under_limit",
            on="Request",
            when=k3(S.count < WINDOW_LIMIT),
            denied=Concat(
                Concat(LStr("rate limit exceeded: "), Field(Var("state"), "count")),
                LStr(f"/{WINDOW_LIMIT}"),
            ),
        ),
        # Tick to advance time is always allowed
        Permit(name="tick", on="Tick", when=k3(S.current_time >= 0)),
        # Reset is allowed at any time
        Permit(name="reset", on="Reset", when=k3(S.count >= 0)),
    ),
    maintains=(
        # Counter never exceeds window limit
        Maintain(name="bounded", expr=Always(k3(S.count <= WINDOW_LIMIT))),
    ),
)


WINDOW_SIZE = 10  # logical time units


def transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Request":
            return {**state, "count": state["count"] + 1}
        case "Tick":
            new_time = state["current_time"] + 1
            # Reset window if we've moved past it
            if new_time - state["window_start"] >= WINDOW_SIZE:
                return {**state, "current_time": new_time, "window_start": new_time, "count": 0}
            return {**state, "current_time": new_time}
        case "Reset":
            return {**state, "count": 0, "window_start": state["current_time"]}
        case _:
            return state


def main() -> None:
    u = Universe(spec=spec, transition=transition)

    # 6 requests in a row — 5 should pass, 6th rejected
    events = [{"type": "Request"} for _ in range(6)]
    for i, result in enumerate(u.stream(events), 1):
        match result:
            case Ok(state=s):
                print(f"  req {i}: ok    count={s['count']}")
            case Impossible(why=w):
                print(f"  req {i}: deny  {w.message}")

    # After Reset, requests resume
    print("\nAfter Reset:")
    u.apply({"type": "Reset"})
    r = u.apply({"type": "Request"})
    print(f"  req: ok  count={u.get('count')}" if isinstance(r, Ok) else "  unexpected")


if __name__ == "__main__":
    main()
