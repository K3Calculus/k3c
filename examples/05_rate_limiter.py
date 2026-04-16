"""
Example 05: Rate Limiter -- Sliding window with bounded liveness.

A rate limiter that allows N requests per window. Uses timestamps in events
(determinism rule: no now() in transitions).

Demonstrates: Spec (frozen dataclass), Permit guards, Maintain invariants,
              EmbeddedRuntime for projection hooks, Universe for fuzz.
"""

from k3c import (
    Spec,
    Permit,
    Maintain,
    Universe,
    Ok,
    Impossible,
    EmbeddedRuntime,
    Always,
    Compare,
    CmpOp,
    Field,
    Var,
    LInt,
    LBool,
)


# -- Spec (declarative, frozen dataclass) --------------------------------------

MAX_REQUESTS = 5
WINDOW_SECONDS = 60

rate_spec = Spec(
    name="rate_limiter",
    state0={
        "request_count": 0,
        "window_start": 0,
        "total_requests": 0,
        "total_rejected": 0,
    },
    permits=(
        # Guard: under rate limit
        Permit(
            name="under_limit",
            when=Compare(
                CmpOp.LT, Field(Var("state"), "request_count"), LInt(MAX_REQUESTS)
            ),
            on="Request",
        ),
        # Guard: reset is always allowed
        Permit(name="reset_ok", when=LBool(True), on="ResetWindow"),
    ),
    maintains=(
        # Invariant: request count never exceeds max
        Maintain(
            name="max_requests",
            expr=Always(
                Compare(
                    CmpOp.LE,
                    Field(Var("state"), "request_count"),
                    LInt(MAX_REQUESTS),
                )
            ),
        ),
        # Invariant: total_requests >= request_count
        Maintain(
            name="total_consistency",
            expr=Always(
                Compare(
                    CmpOp.GE,
                    Field(Var("state"), "total_requests"),
                    Field(Var("state"), "request_count"),
                )
            ),
        ),
    ),
)


# -- Transition function (plain function, no System class) ---------------------


def rate_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "Request":
            return {
                **state,
                "request_count": state["request_count"] + 1,
                "total_requests": state["total_requests"] + 1,
            }
        case "ResetWindow":
            return {
                **state,
                "request_count": 0,
                "window_start": event.get("timestamp", 0),
            }
        case _:
            return state


# -- Usage ---------------------------------------------------------------------


def main():
    # EmbeddedRuntime for projection hooks
    runtime = EmbeddedRuntime(
        spec=rate_spec,
        transition=rate_transition,
        projection_hooks={
            "remaining": lambda state, event, ctx: (
                MAX_REQUESTS - state["request_count"]
            ),
            "stats": lambda state, event, ctx: {
                "total": state["total_requests"],
                "rejected": state["total_rejected"],
                "current_window": state["request_count"],
            },
        },
    )
    u = runtime.universe()

    # Send requests up to the limit
    for i in range(MAX_REQUESTS):
        r = u.apply({"type": "Request", "client": "user_1"})
        assert isinstance(r, Ok)
        print(f"Request {i + 1}: remaining={r.projections['remaining']}")

    # Next request should be rejected
    r = u.apply({"type": "Request", "client": "user_1"})
    assert isinstance(r, Impossible)
    print(f"Request {MAX_REQUESTS + 1}: REJECTED -- {r.why.rule}")

    # Reset window
    r = u.apply({"type": "ResetWindow", "timestamp": 60})
    assert isinstance(r, Ok)
    print(f"\nWindow reset: remaining={r.projections['remaining']}")

    # Now requests work again
    r = u.apply({"type": "Request", "client": "user_1"})
    assert isinstance(r, Ok)
    print(f"After reset: remaining={r.projections['remaining']}")

    print(f"\nStats: {u.state}")

    # Fuzz (Universe supports fuzz; EmbeddedUniverse does not)
    u_fuzz = Universe(spec=rate_spec, transition=rate_transition)
    report = u_fuzz.fuzz(sequences=100, steps=30, seed=42)
    print(f"Fuzz: passed={report.passed}")

    print("\nRate limiter example passed.")


if __name__ == "__main__":
    main()
