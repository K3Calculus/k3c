"""07 — Raft Consensus

Encode Raft's safety properties as Maintain invariants.

Demonstrates:
- Real-world safety invariants in declarative form
- Term monotonicity (After >= Before)
- AnyOf for valid role enumeration
- Sub-expression diagnostics on Maintain failure
"""

from __future__ import annotations

from k3c import (
    After,
    Always,
    AnyOf,
    Before,
    CmpOp,
    Compare,
    Field,
    LInt,
    LStr,
    Maintain,
    Ok,
    Permit,
    S,
    Spec,
    Universe,
    Var,
    Violated,
    Warning,
    k3,
)


# Raft roles
LEADER = "leader"
CANDIDATE = "candidate"
FOLLOWER = "follower"


spec = Spec(
    name="raft_node",
    state0={
        "role": FOLLOWER,
        "term": 0,
        "voted_for": None,
        "log_index": 0,
    },
    permits=(
        # All events permitted as long as basic shape holds
        Permit(name="any", when=k3(S.term >= 0)),
    ),
    maintains=(
        # SAFETY: term is monotonic (never decreases)
        Maintain(
            name="term_monotone",
            expr=Always(Compare(CmpOp.GE, After("term"), Before("term"))),
        ),
        # SAFETY: role is one of {follower, candidate, leader}
        Maintain(
            name="valid_role",
            expr=Always(AnyOf(exprs=(
                Compare(CmpOp.EQ, Field(Var("state"), "role"), LStr(FOLLOWER)),
                Compare(CmpOp.EQ, Field(Var("state"), "role"), LStr(CANDIDATE)),
                Compare(CmpOp.EQ, Field(Var("state"), "role"), LStr(LEADER)),
            ))),
        ),
        # SAFETY: log index is monotonic
        Maintain(
            name="log_monotone",
            expr=Always(Compare(CmpOp.GE, After("log_index"), Before("log_index"))),
        ),
        # SAFETY: a node can only vote once per term
        Maintain(
            name="single_vote_per_term",
            expr=Always(k3(
                (S.voted_for == None) | (S.term > 0)  # noqa: E711
            )),
        ),
    ),
)


def transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "BecomeCandidate":
            return {**state, "role": CANDIDATE, "term": state["term"] + 1, "voted_for": "self"}
        case "BecomeLeader":
            return {**state, "role": LEADER}
        case "BecomeFollower":
            return {**state, "role": FOLLOWER, "voted_for": None}
        case "AppendEntry":
            return {**state, "log_index": state["log_index"] + 1}
        case "BUG_RegressTerm":
            # Simulated bug: regress term — should trigger Violated
            return {**state, "term": state["term"] - 1}
        case _:
            return state


def main() -> None:
    u = Universe(spec=spec, transition=transition)

    print("== Normal Raft trajectory ==")
    happy_path = [
        {"type": "BecomeCandidate"},   # follower -> candidate, term++
        {"type": "BecomeLeader"},      # candidate -> leader
        {"type": "AppendEntry"},
        {"type": "AppendEntry"},
        {"type": "BecomeFollower"},    # step down
    ]
    for event in happy_path:
        result = u.apply(event)
        marker = "ok      " if isinstance(result, Ok) else "warning " if isinstance(result, Warning) else "BUG     "
        print(f"  {marker} {event['type']:20s}  term={u.get('term')} role={u.get('role')} log_index={u.get('log_index')}")

    print("\n== Inject a bug: regress term ==")
    result = u.apply({"type": "BUG_RegressTerm"})
    if isinstance(result, Violated):
        print(f"  Violated rule: {result.why.rule}")
        # Sub-expression diagnostics show exactly which sub-clause failed
        for line in result.why.messages:
            print(f"    {line}")


if __name__ == "__main__":
    main()
