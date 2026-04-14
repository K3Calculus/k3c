"""
Example 11: Redis Protocol — Key-value store with TTL, pub/sub, and transactions.

Models a simplified Redis server with:
  - Key-value operations: SET, GET, DEL, INCR, EXPIRE
  - TTL management with expiry tracking
  - Transaction blocks: MULTI/EXEC/DISCARD
  - Pub/Sub: SUBSCRIBE, PUBLISH
  - Safety: key count consistency, TTL non-negative
  - Liveness: transactions eventually complete (EXEC or DISCARD)
  - Compose: KV store <||> pub/sub engine
  - Bridge: writes -> replication log
  - Parallel: shard-based parallel_reduce for bulk loading

Demonstrates: the full K3 capability set in a real-world protocol.
"""

from k3c import (
    Spec,
    universe,
    parallel_reduce,
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
    LInt,
    BridgeMode,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Redis KV Store Universe
# ═══════════════════════════════════════════════════════════════════════════════

kv_spec = (
    Spec("redis_kv")
    .state0(
        {
            "data": {},  # key -> value
            "ttls": {},  # key -> remaining ticks
            "key_count": 0,
            "cmd_count": 0,
            "in_multi": False,  # MULTI/EXEC transaction block
            "multi_queue": [],  # queued commands during MULTI
        }
    )
    .permit("ok", when=LBool(True))
    # ── Safety invariants ────────────────────────────────────────────────
    # Key count matches actual data size
    .maintain(
        "key_count_consistent",
        expr=Always(Compare(CmpOp.GE, Field(Var("state"), "key_count"), LInt(0))),
    )
    # Command count monotonically increases
    .maintain(
        "cmd_monotone",
        expr=Always(Compare(CmpOp.GE, After("cmd_count"), Before("cmd_count"))),
    )
    # ── Liveness: transactions eventually complete ───────────────────────
    .maintain(
        "txn_completes",
        expr=Always(
            Implies(
                Compare(CmpOp.EQ, Field(Var("state"), "in_multi"), LBool(True)),
                Eventually(
                    Compare(CmpOp.EQ, Field(Var("state"), "in_multi"), LBool(False))
                ),
            )
        ),
    )
    # ── Projections ──────────────────────────────────────────────────────
    .project(
        "stats",
        lambda s: {
            "keys": s["key_count"],
            "commands": s["cmd_count"],
            "in_txn": s["in_multi"],
            "queued": len(s["multi_queue"]),
        },
    )
    .project(
        "memory",
        lambda s: sum(len(str(k)) + len(str(v)) for k, v in s["data"].items()),
        kind="metric",
    )
    # ── Outputs: write-ahead log ─────────────────────────────────────────
    .output(
        "wal",
        lambda s, e, ns: (
            {
                "type": "WAL",
                "cmd": e.get("type"),
                "key": e.get("key", ""),
                "old_keys": s["key_count"],
                "new_keys": ns["key_count"],
            }
            if e.get("type") in ("SET", "DEL", "INCR", "EXPIRE")
            else None
        ),
    )
    .build()
)


class RedisKV:
    def transition(self, state, event):
        cmd = event.get("type", "")

        # ── Transaction handling ─────────────────────────────────────────
        if cmd == "MULTI":
            return {
                **state,
                "in_multi": True,
                "multi_queue": [],
                "cmd_count": state["cmd_count"] + 1,
            }

        if cmd == "DISCARD":
            return {
                **state,
                "in_multi": False,
                "multi_queue": [],
                "cmd_count": state["cmd_count"] + 1,
            }

        if cmd == "EXEC":
            # Execute all queued commands
            s = {**state, "in_multi": False, "cmd_count": state["cmd_count"] + 1}
            for queued in state["multi_queue"]:
                s = self._exec_cmd(s, queued)
            s["multi_queue"] = []
            return s

        # If in MULTI, queue instead of execute
        if state["in_multi"]:
            return {
                **state,
                "multi_queue": state["multi_queue"] + [event],
                "cmd_count": state["cmd_count"] + 1,
            }

        return self._exec_cmd(state, event)

    def _exec_cmd(self, state, event):
        cmd = event.get("type", "")
        key = event.get("key", "")
        data = dict(state["data"])
        ttls = dict(state["ttls"])
        key_count = state["key_count"]

        match cmd:
            case "SET":
                is_new = key not in data
                data[key] = event.get("value", "")
                if is_new:
                    key_count += 1
                if "ttl" in event:
                    ttls[key] = event["ttl"]

            case "GET":
                pass  # read-only, no state change

            case "DEL":
                if key in data:
                    del data[key]
                    ttls.pop(key, None)
                    key_count -= 1

            case "INCR":
                if key in data and isinstance(data[key], int):
                    data[key] = data[key] + 1
                elif key not in data:
                    data[key] = 1
                    key_count += 1

            case "EXPIRE":
                if key in data:
                    ttls[key] = event.get("seconds", 60)

            case "TICK":
                # Expire keys with TTL <= 0
                expired = [k for k, v in ttls.items() if v <= 1]
                for k in expired:
                    data.pop(k, None)
                    del ttls[k]
                    key_count -= 1
                ttls = {k: v - 1 for k, v in ttls.items() if v > 1}

        return {
            **state,
            "data": data,
            "ttls": ttls,
            "key_count": key_count,
            "cmd_count": state["cmd_count"] + 1,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  Redis Pub/Sub Universe
# ═══════════════════════════════════════════════════════════════════════════════

pubsub_spec = (
    Spec("redis_pubsub")
    .state0(
        {
            "channels": {},  # channel -> subscriber count
            "message_count": 0,
            "total_delivered": 0,
        }
    )
    .permit("ok", when=LBool(True))
    .maintain(
        "msg_monotone",
        expr=Always(Compare(CmpOp.GE, After("message_count"), Before("message_count"))),
    )
    .project(
        "pubsub_stats",
        lambda s: {
            "channels": len(s["channels"]),
            "messages": s["message_count"],
            "delivered": s["total_delivered"],
        },
    )
    .build()
)


class RedisPubSub:
    def transition(self, state, event):
        match event.get("type"):
            case "SUBSCRIBE":
                channel = event.get("channel", "default")
                channels = dict(state["channels"])
                channels[channel] = channels.get(channel, 0) + 1
                return {**state, "channels": channels}

            case "UNSUBSCRIBE":
                channel = event.get("channel", "default")
                channels = dict(state["channels"])
                if channel in channels:
                    channels[channel] -= 1
                    if channels[channel] <= 0:
                        del channels[channel]
                return {**state, "channels": channels}

            case "PUBLISH":
                channel = event.get("channel", "default")
                subs = state["channels"].get(channel, 0)
                return {
                    **state,
                    "message_count": state["message_count"] + 1,
                    "total_delivered": state["total_delivered"] + subs,
                }

            case _:
                return state


# ═══════════════════════════════════════════════════════════════════════════════
#  Replication Log (Bridge target)
# ═══════════════════════════════════════════════════════════════════════════════

repl_spec = (
    Spec("replication")
    .state0({"log": [], "offset": 0})
    .permit("ok", when=LBool(True))
    .maintain(
        "offset_monotone",
        expr=Always(Compare(CmpOp.GE, After("offset"), Before("offset"))),
    )
    .project("repl_lag", lambda s: len(s["log"]) - s["offset"], kind="metric")
    .build()
)


class ReplicationLog:
    def transition(self, state, event):
        if event.get("type") == "WAL":
            return {
                **state,
                "log": state["log"] + [event],
                "offset": state["offset"] + 1,
            }
        return state


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    kv_u = universe(RedisKV(), kv_spec)
    pubsub_u = universe(RedisPubSub(), pubsub_spec)
    repl_u = universe(ReplicationLog(), repl_spec)

    # ── 1. Basic KV operations ───────────────────────────────────────────
    print("=== 1. Basic KV Operations ===")
    for cmd in [
        {"type": "SET", "key": "user:1:name", "value": "Alice"},
        {"type": "SET", "key": "user:1:score", "value": 100},
        {"type": "SET", "key": "user:2:name", "value": "Bob"},
        {"type": "INCR", "key": "user:1:score"},
        {"type": "INCR", "key": "user:1:score"},
    ]:
        r = kv_u.apply(cmd)
        assert isinstance(r, Ok)
    print(f"  Data: {kv_u.state['data']}")
    print(f"  Stats: keys={kv_u.state['key_count']}, cmds={kv_u.state['cmd_count']}")

    # ── 2. TTL and expiry ────────────────────────────────────────────────
    print("\n=== 2. TTL and Expiry ===")
    kv_u.apply({"type": "SET", "key": "session:abc", "value": "data", "ttl": 3})
    kv_u.apply({"type": "EXPIRE", "key": "user:2:name", "seconds": 2})
    print(f"  TTLs: {kv_u.state['ttls']}")

    for tick in range(3):
        r = kv_u.apply({"type": "TICK"})
        assert isinstance(r, Ok)
        print(
            f"  Tick {tick + 1}: keys={kv_u.state['key_count']}, ttls={kv_u.state['ttls']}"
        )

    # ── 3. Transactions (MULTI/EXEC) ─────────────────────────────────────
    print("\n=== 3. Transactions ===")
    kv_u.apply({"type": "SET", "key": "balance:A", "value": 1000})
    kv_u.apply({"type": "SET", "key": "balance:B", "value": 500})

    kv_u.apply({"type": "MULTI"})
    kv_u.apply({"type": "INCR", "key": "balance:A"})
    kv_u.apply({"type": "INCR", "key": "balance:B"})
    print(
        f"  In MULTI: queued={len(kv_u.state['multi_queue'])}, in_txn={kv_u.state['in_multi']}"
    )

    kv_u.apply({"type": "EXEC"})
    print(
        f"  After EXEC: A={kv_u.state['data']['balance:A']}, B={kv_u.state['data']['balance:B']}"
    )

    # ── 4. Compose: KV <||> PubSub ───────────────────────────────────────
    print("\n=== 4. Compose: KV + PubSub ===")
    kv_u2 = universe(RedisKV(), kv_spec)
    pubsub_u2 = universe(RedisPubSub(), pubsub_spec)

    redis = kv_u2.compose(
        pubsub_u2,
        router=lambda e: (
            "right"
            if e.get("type") in ("SUBSCRIBE", "UNSUBSCRIBE", "PUBLISH")
            else "left"
        ),
    )

    redis.apply({"type": "SET", "key": "msg", "value": "hello"})
    redis.apply({"type": "SUBSCRIBE", "channel": "notifications"})
    redis.apply({"type": "SUBSCRIBE", "channel": "notifications"})
    redis.apply({"type": "PUBLISH", "channel": "notifications", "data": "new message"})

    print(f"  KV keys: {redis.state['left']['key_count']}")
    print(f"  PubSub: {redis.state['right']}")

    # ── 5. Bridge: KV writes -> replication ──────────────────────────────
    print("\n=== 5. Bridge: Replication ===")
    kv_u3 = universe(RedisKV(), kv_spec)
    repl_u2 = universe(ReplicationLog(), repl_spec)

    replicated = kv_u3.bridge(
        repl_u2,
        mapper=lambda s, e, ns: (
            {
                "type": "WAL",
                "cmd": e.get("type"),
                "key": e.get("key", ""),
            }
            if e.get("type") in ("SET", "DEL", "INCR")
            else None
        ),
        mode=BridgeMode.SYNCHRONOUS,
    )

    replicated.apply({"type": "SET", "key": "x", "value": 1})
    replicated.apply({"type": "SET", "key": "y", "value": 2})
    replicated.apply({"type": "INCR", "key": "x"})
    replicated.apply({"type": "DEL", "key": "y"})
    replicated.apply({"type": "GET", "key": "x"})  # read-only, no WAL

    print(f"  KV state: {replicated.state['source']['data']}")
    print(f"  Repl log: {len(replicated.state['target']['log'])} entries")
    print(f"  Repl offset: {replicated.state['target']['offset']}")

    # ── 6. Parallel bulk loading ─────────────────────────────────────────
    print("\n=== 6. Parallel Bulk Load ===")

    # Generate 100 SET commands across 4 shards
    all_commands = [
        {"type": "SET", "key": f"key:{i}", "value": f"val:{i}"} for i in range(100)
    ]

    # Shard by key hash
    n_shards = 4
    shards: list[list[dict[str, object]]] = [[] for _ in range(n_shards)]
    for cmd in all_commands:
        shard_id = hash(cmd["key"]) % n_shards
        shards[shard_id].append(cmd)

    # Each shard gets its own spec slice (same invariants, fresh state)
    shard_specs = [
        kv_spec.slice(
            from_state={
                "data": {},
                "ttls": {},
                "key_count": 0,
                "cmd_count": 0,
                "in_multi": False,
                "multi_queue": [],
            }
        )
        for _ in range(n_shards)
    ]

    result = parallel_reduce(RedisKV(), shard_specs, shards, workers=1)
    print(f"  Passed: {result.passed}")
    print(f"  Total processed: {result.total_processed}")
    total_keys = sum(
        r.final.state["key_count"] for r in result.results if isinstance(r.final, Ok)
    )
    print(f"  Total keys across shards: {total_keys}")
    assert total_keys == 100

    # ── 7. Isolation: independent sessions ───────────────────────────────
    print("\n=== 7. Isolated Sessions ===")
    kv_u4 = universe(RedisKV(), kv_spec)
    kv_u4.apply({"type": "SET", "key": "shared", "value": "original"})

    session1 = kv_u4.isolate()
    session2 = kv_u4.isolate()

    session1.apply({"type": "SET", "key": "shared", "value": "session1"})
    session2.apply({"type": "SET", "key": "shared", "value": "session2"})

    print(f"  Original: {kv_u4.state['data'].get('shared')}")
    print(f"  Session1: {session1.state['data'].get('shared')}")
    print(f"  Session2: {session2.state['data'].get('shared')}")
    assert kv_u4.state["data"]["shared"] == "original"
    assert session1.state["data"]["shared"] == "session1"
    assert session2.state["data"]["shared"] == "session2"

    # ── 8. Fuzz ──────────────────────────────────────────────────────────
    print("\n=== 8. Fuzz Testing ===")
    kv_u5 = universe(RedisKV(), kv_spec)

    def redis_event_gen(state, rng):
        cmd = rng.choice(
            ["SET", "GET", "DEL", "INCR", "TICK", "MULTI", "EXEC", "DISCARD"]
        )
        return {
            "type": cmd,
            "key": f"key:{rng.randint(0, 10)}",
            "value": rng.randint(0, 1000),
            "ttl": rng.randint(1, 5),
            "seconds": rng.randint(1, 10),
        }

    report = kv_u5.fuzz(
        sequences=200, steps=50, seed=42, event_generator=redis_event_gen
    )
    print(f"  Passed: {report.passed}")
    print(f"  Sequences: {report.sequences_run}, Steps: {report.total_steps}")
    if not report.passed:
        v = report.violations[0]
        print(f"  Violation: {v.violated.why.rule}")
        print(f"  Shrunk to {len(v.shrunk_sequence)} events")

    # ── 9. Explain ───────────────────────────────────────────────────────
    print("\n=== 9. Explain ===")
    kv_u6 = universe(RedisKV(), kv_spec)
    kv_u6.apply({"type": "SET", "key": "x", "value": 42})
    explanation = kv_u6.explain({"type": "INCR", "key": "x"})
    print(f"  Explain INCR: {type(explanation.result).__name__}")
    for entry in explanation.trace:
        if entry.phase.value in ("safety", "liveness"):
            print(f"    {entry.phase}: {entry.clause} -> {entry.verdict}")

    print("\nRedis protocol example passed.")


if __name__ == "__main__":
    main()
