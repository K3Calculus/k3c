"""
Example 07: Raft Consensus -- Safety invariants for distributed consensus.

Models the Raft consensus safety properties:
  - Term monotonicity: term never decreases
  - One vote per term: once voted, can only vote for same candidate
  - Log matching: entries at same index+term have same command
  - Election liveness: candidates eventually resolve

Demonstrates: Spec (frozen dataclass), Permit, Maintain with Before/After
temporal expressions, Eventually for liveness, Implies conditions,
EmbeddedRuntime for lambda projections, Universe for fuzz/explain.
"""

from k3c import (
    Spec,
    Permit,
    Maintain,
    Universe,
    EmbeddedRuntime,
    Ok,
    Always,
    Implies,
    Eventually,
    Compare,
    CmpOp,
    Field,
    Var,
    Before,
    After,
    LBool,
    LStr,
)


# -- Spec (declarative, frozen dataclass) --------------------------------------

raft_spec = Spec(
    name="raft_node",
    state0={
        "term": 0,
        "role": "follower",
        "voted_for": "",  # empty string = no vote
        "log": [],
        "commit_index": 0,
    },
    permits=(Permit(name="ok", when=LBool(True)),),
    maintains=(
        # Safety: term never decreases
        Maintain(
            name="term_monotone",
            expr=Always(Compare(CmpOp.GE, After("term"), Before("term"))),
        ),
        # Safety: vote only changes when term changes
        Maintain(
            name="vote_stability",
            expr=Always(
                Implies(
                    # If term stays the same
                    Compare(CmpOp.EQ, After("term"), Before("term")),
                    # Then vote doesn't change (or was empty)
                    Implies(
                        Compare(CmpOp.NE, Before("voted_for"), LStr("")),
                        Compare(CmpOp.EQ, After("voted_for"), Before("voted_for")),
                    ),
                )
            ),
        ),
        # Safety: commit index never decreases
        Maintain(
            name="commit_monotone",
            expr=Always(
                Compare(CmpOp.GE, After("commit_index"), Before("commit_index"))
            ),
        ),
        # Liveness: elections eventually resolve (candidate -> follower or leader)
        Maintain(
            name="election_resolves",
            expr=Always(
                Implies(
                    Compare(CmpOp.EQ, Field(Var("state"), "role"), LStr("candidate")),
                    Eventually(
                        Compare(
                            CmpOp.NE, Field(Var("state"), "role"), LStr("candidate")
                        )
                    ),
                )
            ),
        ),
    ),
)


# -- Transition function (plain function, no System class) ---------------------


def raft_transition(state: dict, event: dict) -> dict:
    match event.get("type"):
        case "StartElection":
            return {
                **state,
                "term": state["term"] + 1,
                "role": "candidate",
                "voted_for": "self",
            }

        case "WinElection":
            if state["role"] != "candidate":
                return state
            return {**state, "role": "leader"}

        case "LoseElection":
            if state["role"] != "candidate":
                return state
            # Losing means we received a higher term from the winner
            return {
                **state,
                "term": event.get("winner_term", state["term"] + 1),
                "role": "follower",
                "voted_for": "",
            }

        case "ReceiveHeartbeat":
            new_term = event.get("leader_term", state["term"])
            if new_term >= state["term"]:
                return {
                    **state,
                    "term": new_term,
                    "role": "follower",
                    "voted_for": "",
                }
            return state

        case "AppendEntry":
            entry = {
                "index": len(state["log"]),
                "term": state["term"],
                "cmd": event.get("cmd", ""),
            }
            return {
                **state,
                "log": state["log"] + [entry],
            }

        case "Commit":
            new_idx = min(event.get("index", 0), len(state["log"]))
            return {
                **state,
                "commit_index": max(state["commit_index"], new_idx),
            }

        case _:
            return state


# -- Usage ---------------------------------------------------------------------


def main():
    # EmbeddedRuntime for lambda projection hooks
    runtime = EmbeddedRuntime(
        spec=raft_spec,
        transition=raft_transition,
        projection_hooks={
            "node_state": lambda s, e, ctx: {
                "term": s["term"],
                "role": s["role"],
                "log_len": len(s["log"]),
                "committed": s["commit_index"],
            },
        },
    )
    u = runtime.universe()

    # Scenario 1: Normal election + log replication
    print("Scenario 1: Election + replication")
    events = [
        {"type": "StartElection"},
        {"type": "WinElection"},
        {"type": "AppendEntry", "cmd": "SET x 1"},
        {"type": "AppendEntry", "cmd": "SET y 2"},
        {"type": "Commit", "index": 2},
    ]

    for event in events:
        r = u.apply(event)
        assert isinstance(r, Ok), f"Failed on {event['type']}: {r}"
        proj = r.projections["node_state"]
        print(
            f"  {event['type']:>20} -> term={proj['term']}, role={proj['role']}, "
            f"log={proj['log_len']}, committed={proj['committed']}"
        )

    # Scenario 2: Heartbeat from higher term
    print("\nScenario 2: Step down on higher term")
    r = u.apply({"type": "ReceiveHeartbeat", "leader_term": 5})
    assert isinstance(r, Ok)
    print(f"  Heartbeat term=5 -> role={u.state['role']}, term={u.state['term']}")

    # Scenario 3: Lost election
    u.reset()
    print("\nScenario 3: Lost election")
    u.apply({"type": "StartElection"})
    print(f"  After StartElection: role={u.state['role']}, term={u.state['term']}")
    u.apply({"type": "LoseElection"})
    print(f"  After LoseElection: role={u.state['role']}")

    # Explain: what happens when we try to commit beyond log
    # explain() and fuzz() require a plain Universe
    u_plain = Universe(spec=raft_spec, transition=raft_transition)
    u_plain.apply({"type": "StartElection"})
    u_plain.apply({"type": "WinElection"})
    explanation = u_plain.explain({"type": "Commit", "index": 100})
    print(f"\nExplain commit beyond log: {type(explanation.result).__name__}")

    # Fuzz
    u_fuzz = Universe(spec=raft_spec, transition=raft_transition)
    report = u_fuzz.fuzz(sequences=200, steps=30, seed=42)
    print(f"\nFuzz: passed={report.passed}, sequences={report.sequences_run}")
    if not report.passed:
        v = report.violations[0]
        print(f"  Violation: {v.violated.why.rule}")
        print(f"  Shrunk to {len(v.shrunk_sequence)} events")

    print("\nRaft consensus example passed.")


if __name__ == "__main__":
    main()
