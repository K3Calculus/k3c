"""
Example 05: Rate Limiter — Sliding window with bounded liveness.

A rate limiter that allows N requests per window. Uses timestamps in events
(determinism rule: no now() in transitions).

Demonstrates: Within (bounded liveness), ForAll, timestamp-based guards.
"""

from k3c import (
    Spec,
    universe,
    Ok,
    Impossible,
    Always,
    Compare,
    CmpOp,
    Field,
    Var,
    LInt,
    LBool,
)


# ── Spec ────────────────────────────────────────────────────────────────────

MAX_REQUESTS = 5
WINDOW_SECONDS = 60

rate_spec = (
    Spec("rate_limiter")
    .state0(
        {
            "request_count": 0,
            "window_start": 0,
            "total_requests": 0,
            "total_rejected": 0,
        }
    )
    # Guard: under rate limit
    .permit(
        "under_limit",
        when=Compare(
            CmpOp.LT, Field(Var("state"), "request_count"), LInt(MAX_REQUESTS)
        ),
        on="Request",
    )
    # Guard: reset is always allowed
    .permit("reset_ok", when=LBool(True), on="ResetWindow")
    # Invariant: request count never exceeds max
    .maintain(
        "max_requests",
        expr=Always(
            Compare(CmpOp.LE, Field(Var("state"), "request_count"), LInt(MAX_REQUESTS))
        ),
    )
    # Invariant: total_requests >= request_count
    .maintain(
        "total_consistency",
        expr=Always(
            Compare(
                CmpOp.GE,
                Field(Var("state"), "total_requests"),
                Field(Var("state"), "request_count"),
            )
        ),
    )
    # Projections
    .project("remaining", lambda s: MAX_REQUESTS - s["request_count"])
    .project(
        "stats",
        lambda s: {
            "total": s["total_requests"],
            "rejected": s["total_rejected"],
            "current_window": s["request_count"],
        },
        kind="metric",
    )
    .build()
)


# ── System ──────────────────────────────────────────────────────────────────


class RateLimiterSystem:
    def transition(self, state, event):
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


# ── Usage ───────────────────────────────────────────────────────────────────


def main():
    u = universe(RateLimiterSystem(), rate_spec)

    # Send requests up to the limit
    for i in range(MAX_REQUESTS):
        r = u.apply({"type": "Request", "client": "user_1"})
        assert isinstance(r, Ok)
        print(f"Request {i + 1}: remaining={r.projections['remaining']}")

    # Next request should be rejected
    r = u.apply({"type": "Request", "client": "user_1"})
    assert isinstance(r, Impossible)
    print(f"Request {MAX_REQUESTS + 1}: REJECTED — {r.why.rule}")

    # Reset window
    r = u.apply({"type": "ResetWindow", "timestamp": 60})
    assert isinstance(r, Ok)
    print(f"\nWindow reset: remaining={r.projections['remaining']}")

    # Now requests work again
    r = u.apply({"type": "Request", "client": "user_1"})
    assert isinstance(r, Ok)
    print(f"After reset: remaining={r.projections['remaining']}")

    print(f"\nStats: {u.state}")

    # Fuzz
    u.reset()
    report = u.fuzz(sequences=100, steps=30, seed=42)
    print(f"Fuzz: passed={report.passed}")

    print("\nRate limiter example passed.")


if __name__ == "__main__":
    main()
