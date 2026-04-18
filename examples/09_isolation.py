"""09 — Isolation

Deep-copy a Universe to create independent sessions sharing no state.
Useful for thread-safe sessions, speculative execution, fuzz workers.

Demonstrates:
- u.isolate() — deep-copy isolation, no shared references
- Independent state evolution per isolated copy
- Safe parallel use without locks
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from k3c import Permit, S, Spec, Universe, k3


spec = Spec(
    name="user_session",
    state0={"user_id": None, "actions": 0},
    permits=(Permit(name="any", when=k3(S.actions >= 0)),),
)


def transition(state: dict, event: dict) -> dict:
    return {
        **state,
        "user_id": event.get("user_id", state["user_id"]),
        "actions": state["actions"] + 1,
    }


def main() -> None:
    template = Universe(spec=spec, transition=transition, validate=False)

    # Spawn 5 independent sessions
    sessions = [template.isolate() for _ in range(5)]
    user_ids = ["alice", "bob", "carol", "dave", "eve"]

    # Use threads — sessions don't share state, so no locks needed
    def session_work(idx: int) -> tuple[int, dict]:
        s = sessions[idx]
        s.apply({"type": "Login", "user_id": user_ids[idx]})
        for _ in range(idx + 1):  # Different number of actions per session
            s.apply({"type": "Click"})
        return idx, s.state

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(session_work, range(5)))

    print("Per-session final state (no cross-contamination):")
    for idx, state in results:
        print(f"  session {idx}: user={state['user_id']:5s}  actions={state['actions']}")

    # Template is unchanged
    print(f"\nTemplate state: {template.state}")


if __name__ == "__main__":
    main()
