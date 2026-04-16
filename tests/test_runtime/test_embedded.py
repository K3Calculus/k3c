"""Tests for k3c.runtime.embedded -- EmbeddedRuntime and EmbeddedUniverse."""

from __future__ import annotations

from k3c.engine.result import Ok, Violated
from k3c.ir.expr import Always, CmpOp, Compare, EventField, Field, LInt, Var
from k3c.runtime.embedded import EmbeddedRuntime, EmbeddedUniverse
from k3c.spec.model import Maintain, Permit, Spec


def _bank_spec():
    return Spec(
        name="bank",
        state0={"balance": 100},
        permits=(
            Permit(
                name="has_funds",
                on="Withdraw",
                when=Compare(
                    CmpOp.GE, Field(Var("state"), "balance"), EventField("amount")
                ),
            ),
        ),
        maintains=(
            Maintain(
                name="non_negative",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            ),
        ),
    )


def _bank_t(s, e):
    match e.get("type"):
        case "Deposit":
            return {**s, "balance": s["balance"] + e["amount"]}
        case "Withdraw":
            return {**s, "balance": s["balance"] - e["amount"]}
        case _:
            return s


class TestEmbeddedRuntime:
    def test_universe_creation(self):
        rt = EmbeddedRuntime(spec=_bank_spec(), transition=_bank_t)
        u = rt.universe()
        assert isinstance(u, EmbeddedUniverse)
        assert u.id == "bank"

    def test_projection_hooks(self):
        rt = EmbeddedRuntime(
            spec=_bank_spec(),
            transition=_bank_t,
            projection_hooks={
                "doubled": lambda s, e, ctx: s["balance"] * 2,
            },
        )
        u = rt.universe()
        r = u.apply({"type": "Deposit", "amount": 50})
        assert isinstance(r, Ok)
        assert r.projections["doubled"] == 300

    def test_output_hooks(self):
        rt = EmbeddedRuntime(
            spec=_bank_spec(),
            transition=_bank_t,
            output_hooks={
                "alert": lambda s, e, ns: (
                    {"type": "alert"} if ns["balance"] < 20 else None
                ),
            },
        )
        u = rt.universe()
        r = u.apply({"type": "Withdraw", "amount": 90})
        assert isinstance(r, Ok)
        assert len(r.outputs) == 1
        assert r.outputs[0]["type"] == "alert"

    def test_output_hooks_skip_none(self):
        rt = EmbeddedRuntime(
            spec=_bank_spec(),
            transition=_bank_t,
            output_hooks={
                "alert": lambda s, e, ns: None,
            },
        )
        u = rt.universe()
        r = u.apply({"type": "Deposit", "amount": 50})
        assert isinstance(r, Ok)
        assert len(r.outputs) == 0

    def test_decode_hook(self):
        rt = EmbeddedRuntime(
            spec=_bank_spec(),
            transition=_bank_t,
            decode_hook=lambda raw: {"type": "Deposit", "amount": raw["n"]},
        )
        u = rt.universe()
        r = u.apply({"n": 25})
        assert isinstance(r, Ok)
        assert u.state["balance"] == 125

    def test_korrelate_hook_pass(self):
        rt = EmbeddedRuntime(
            spec=_bank_spec(),
            transition=_bank_t,
            korrelate_hook=lambda actual, intended: True,
        )
        u = rt.universe()
        r = u.apply({"type": "Deposit", "amount": 50})
        assert isinstance(r, Ok)

    def test_korrelate_hook_fail(self):
        rt = EmbeddedRuntime(
            spec=_bank_spec(),
            transition=_bank_t,
            korrelate_hook=lambda actual, intended: False,
        )
        u = rt.universe()
        r = u.apply({"type": "Deposit", "amount": 50})
        assert isinstance(r, Violated)

    def test_reset(self):
        rt = EmbeddedRuntime(spec=_bank_spec(), transition=_bank_t)
        u = rt.universe()
        u.apply({"type": "Deposit", "amount": 50})
        assert u.state["balance"] == 150
        u.reset()
        assert u.state["balance"] == 100

    def test_stream(self):
        rt = EmbeddedRuntime(spec=_bank_spec(), transition=_bank_t)
        u = rt.universe()
        results = list(
            u.stream(
                [
                    {"type": "Deposit", "amount": 10},
                    {"type": "Deposit", "amount": 20},
                ]
            )
        )
        assert len(results) == 2
        assert all(isinstance(r, Ok) for r in results)

    def test_repr(self):
        rt = EmbeddedRuntime(
            spec=_bank_spec(),
            transition=_bank_t,
            projection_hooks={"p": lambda s, e, c: None},
            output_hooks={"o": lambda s, e, ns: None},
        )
        u = rt.universe()
        r = repr(u)
        assert "EmbeddedUniverse" in r
        assert "projections" in r
        assert "outputs" in r
