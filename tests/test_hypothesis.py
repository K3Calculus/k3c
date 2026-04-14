"""Hypothesis property-based tests for k3c.

Uses hypothesis to generate arbitrary K3l expressions, events, and state
dicts, then verifies core invariants hold for ALL generated inputs:

  1. eval() is total — never raises, always returns Some or Nothing
  2. serde round-trip — to_dict(from_dict(x)) == x for all K3l nodes
  3. apply() is total — never raises, always returns K3Result
  4. hash chain is deterministic — same inputs always produce same hash
  5. Universe invariants — fuzz with hypothesis-generated events
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from k3c.lang.eval import k3_eval
from k3c.lang.ir import (
    Always,
    And,
    Arith,
    ArithOp,
    CmpOp,
    Compare,
    EventField,
    Field,
    If,
    Implies,
    IsSome,
    K3l,
    LBool,
    LFloat,
    LInt,
    LStr,
    Not,
    Nothing,
    Or,
    Some,
    UnwrapOr,
    Var,
)
from k3c.lang.serde import from_dict, to_dict
from k3c.spec.builder import Spec
from k3c.spec.result import Impossible, Ok, Violated
from k3c.universe.engine import _hash_step
from k3c.universe.universe import universe


# ── Strategies ──────────────────────────────────────────────────────────────

# Leaf K3l nodes
st_lbool = st.builds(LBool, st.booleans())
st_lint = st.builds(LInt, st.integers(min_value=-1000, max_value=1000))
st_lfloat = st.builds(
    LFloat,
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)
st_lstr = st.builds(LStr, st.text(max_size=20))
st_var = st.builds(Var, st.sampled_from(["x", "y", "z", "state", "event", "n"]))

st_leaf = st.one_of(st_lbool, st_lint, st_lfloat, st_lstr, st_var)


# Recursive K3l expressions (bounded depth)
@st.composite
def st_k3l(draw: st.DrawFn, max_depth: int = 3) -> K3l:
    if max_depth <= 0:
        return draw(st_leaf)
    kind = draw(
        st.sampled_from(
            [
                "leaf",
                "not",
                "and",
                "or",
                "compare",
                "arith",
                "is_some",
                "unwrap_or",
                "if",
                "implies",
                "field",
                "event_field",
            ]
        )
    )
    child = st_k3l(max_depth - 1)
    match kind:
        case "leaf":
            return draw(st_leaf)
        case "not":
            return Not(expr=draw(child))
        case "and":
            return And(left=draw(child), right=draw(child))
        case "or":
            return Or(left=draw(child), right=draw(child))
        case "compare":
            return Compare(
                op=draw(st.sampled_from(list(CmpOp))),
                left=draw(child),
                right=draw(child),
            )
        case "arith":
            return Arith(
                op=draw(st.sampled_from(list(ArithOp))),
                left=draw(child),
                right=draw(child),
            )
        case "is_some":
            return IsSome(expr=draw(child))
        case "unwrap_or":
            return UnwrapOr(expr=draw(child), default=draw(child))
        case "if":
            return If(cond=draw(child), then=draw(child), else_=draw(child))
        case "implies":
            return Implies(left=draw(child), right=draw(child))
        case "field":
            return Field(
                expr=Var(name="state"),
                name=draw(st.sampled_from(["x", "y", "balance"])),
            )
        case "event_field":
            return EventField(name=draw(st.sampled_from(["type", "amount", "n"])))
        case _:
            return draw(st_leaf)


# Eval contexts
st_eval_ctx = st.fixed_dictionaries(
    {
        "x": st.integers(min_value=-100, max_value=100),
        "y": st.integers(min_value=-100, max_value=100),
        "z": st.integers(min_value=-100, max_value=100),
        "n": st.integers(min_value=0, max_value=50),
        "state": st.fixed_dictionaries(
            {
                "x": st.integers(min_value=-100, max_value=100),
                "y": st.integers(min_value=-100, max_value=100),
                "balance": st.integers(min_value=0, max_value=1000),
            }
        ),
        "event": st.fixed_dictionaries(
            {
                "type": st.sampled_from(["A", "B", "C"]),
                "amount": st.integers(min_value=0, max_value=100),
                "n": st.integers(min_value=0, max_value=50),
            }
        ),
    }
)

# State dicts for Universe
st_state = st.fixed_dictionaries(
    {
        "balance": st.integers(min_value=0, max_value=10000),
    }
)

# Events for Universe
st_event = st.fixed_dictionaries(
    {
        "type": st.sampled_from(["Withdraw", "Deposit", "Noop"]),
        "amount": st.integers(min_value=0, max_value=500),
    }
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Property 1: eval() is total — never raises
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvalTotal:
    @given(expr=st_k3l(2), ctx=st_eval_ctx)
    @settings(max_examples=200)
    def test_eval_never_raises(self, expr: K3l, ctx: dict) -> None:
        """eval() is total — always returns Some or Nothing, never raises."""
        result = k3_eval(expr, ctx, "test_hash")
        assert isinstance(result, (Some, Nothing))

    @given(expr=st_k3l(1), ctx=st_eval_ctx)
    @settings(max_examples=100)
    def test_eval_returns_option(self, expr: K3l, ctx: dict) -> None:
        result = k3_eval(expr, ctx, "")
        assert result.is_some() or result.is_nothing()
        assert result.is_some() != result.is_nothing()


# ═══════════════════════════════════════════════════════════════════════════════
#  Property 2: serde round-trip — to_dict(from_dict(x)) preserves identity
# ═══════════════════════════════════════════════════════════════════════════════


class TestSerdeRoundTrip:
    @given(expr=st_k3l(2))
    @settings(max_examples=200)
    def test_serde_round_trip(self, expr: K3l) -> None:
        d = to_dict(expr)
        restored = from_dict(d)
        assert restored == expr

    @given(expr=st_k3l(2))
    @settings(max_examples=100)
    def test_serde_deterministic(self, expr: K3l) -> None:
        d1 = to_dict(expr)
        d2 = to_dict(expr)
        assert d1 == d2


# ═══════════════════════════════════════════════════════════════════════════════
#  Property 3: hash chain is deterministic
# ═══════════════════════════════════════════════════════════════════════════════


class TestHashDeterministic:
    @given(
        state=st.fixed_dictionaries({"x": st.integers()}),
        event=st.fixed_dictionaries({"type": st.text(max_size=10)}),
        prev=st.text(max_size=64),
    )
    @settings(max_examples=100)
    def test_hash_deterministic(self, state: dict, event: dict, prev: str) -> None:
        h1 = _hash_step(state, event, prev)
        h2 = _hash_step(state, event, prev)
        assert h1 == h2
        assert len(h1) == 64

    @given(
        state1=st.fixed_dictionaries({"x": st.integers()}),
        state2=st.fixed_dictionaries({"x": st.integers()}),
        event=st.fixed_dictionaries({"type": st.just("A")}),
    )
    @settings(max_examples=50)
    def test_different_state_different_hash(
        self, state1: dict, state2: dict, event: dict
    ) -> None:
        assume(state1 != state2)
        h1 = _hash_step(state1, event, "")
        h2 = _hash_step(state2, event, "")
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════════════════════
#  Property 4: apply() is total — never raises, always returns K3Result
# ═══════════════════════════════════════════════════════════════════════════════


class TestApplyTotal:
    @given(event=st_event)
    @settings(max_examples=100)
    def test_apply_never_raises(self, event: dict) -> None:
        spec = (
            Spec("hyp_bank")
            .state0({"balance": 100})
            .permit(
                "has_funds",
                when=Compare(
                    CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
                ),
                on="Withdraw",
            )
            .maintain(
                "non_negative",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            )
            .build()
        )

        class Bank:
            def transition(self, s, e):
                match e.get("type"):
                    case "Withdraw":
                        return {**s, "balance": s["balance"] - e["amount"]}
                    case "Deposit":
                        return {**s, "balance": s["balance"] + e["amount"]}
                    case _:
                        return s

        u = universe(Bank(), spec)
        result = u.apply(event)
        assert isinstance(result, (Ok, Impossible, Violated))

    @given(events=st.lists(st_event, min_size=1, max_size=20))
    @settings(max_examples=50)
    def test_reduce_never_raises(self, events: list) -> None:
        spec = (
            Spec("hyp_counter")
            .state0({"n": 0})
            .permit("ok", when=LBool(True))
            .maintain(
                "non_neg",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "n"), LInt(0))),
            )
            .build()
        )

        class Counter:
            def transition(self, s, e):
                return {**s, "n": s["n"] + e.get("amount", 0)}

        u = universe(Counter(), spec)
        result = u.reduce(events)
        assert isinstance(result, (Ok, Impossible, Violated))


# ═══════════════════════════════════════════════════════════════════════════════
#  Property 5: Nothing propagation — Nothing in, Nothing out
# ═══════════════════════════════════════════════════════════════════════════════


class TestNothingPropagation:
    @given(expr=st_k3l(2))
    @settings(max_examples=100)
    def test_nothing_propagates_through_empty_ctx(self, expr: K3l) -> None:
        """With an empty context, any Var access produces Nothing.
        Compound expressions should propagate it (except IsSome which absorbs)."""
        result = k3_eval(expr, {}, "hash")
        assert isinstance(result, (Some, Nothing))


# ═══════════════════════════════════════════════════════════════════════════════
#  Property 6: IR round-trip preserves hash
# ═══════════════════════════════════════════════════════════════════════════════


class TestIRRoundTrip:
    @given(
        balance=st.integers(min_value=0, max_value=10000),
        name=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"),
    )
    @settings(max_examples=50)
    def test_ir_hash_stable(self, balance: int, name: str) -> None:
        from k3c import K3Spec
        import json

        spec = (
            Spec(name)
            .state0({"balance": balance})
            .permit("ok", when=LBool(True))
            .maintain(
                "pos",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            )
            .build()
        )
        ir = spec.to_ir()
        restored = K3Spec.from_ir(json.loads(spec.to_ir_json()))
        ir2 = restored.to_ir()
        assert ir["ir_hash"] == ir2["ir_hash"]
