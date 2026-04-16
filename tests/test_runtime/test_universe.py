"""Tests for k3c.runtime.universe -- Universe class."""

from __future__ import annotations

import pytest

from k3c.engine.result import Impossible, Ok, Violated
from k3c.errors import K3WellFormednessError
from k3c.ir.expr import Always, CmpOp, Compare, EventField, Field, LInt, Var
from k3c.runtime.universe import Universe
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


def _bank_transition(state, event):
    match event.get("type"):
        case "Deposit":
            return {**state, "balance": state["balance"] + event["amount"]}
        case "Withdraw":
            return {**state, "balance": state["balance"] - event["amount"]}
        case _:
            return state


def _bank_universe(**kwargs):
    return Universe(spec=_bank_spec(), transition=_bank_transition, **kwargs)


class TestConstruction:
    def test_basic(self):
        u = _bank_universe()
        assert u.id == "bank"
        assert u.state == {"balance": 100}

    def test_custom_id(self):
        u = _bank_universe(id="my_bank")
        assert u.id == "my_bank"

    def test_custom_state(self):
        u = _bank_universe(state={"balance": 500})
        assert u.state == {"balance": 500}

    def test_well_formedness_violation(self):
        bad_spec = Spec(
            name="bad",
            state0={"x": -1},
            maintains=(
                Maintain(
                    name="positive",
                    expr=Always(Compare(CmpOp.GT, Field(Var("state"), "x"), LInt(0))),
                ),
            ),
        )
        with pytest.raises(K3WellFormednessError):
            Universe(spec=bad_spec, transition=lambda s, e: s)

    def test_empty_state0_rejected(self):
        bad_spec = Spec(name="empty", state0={})
        with pytest.raises(K3WellFormednessError):
            Universe(spec=bad_spec, transition=lambda s, e: s)


class TestApply:
    def test_ok_deposit(self):
        u = _bank_universe()
        r = u.apply({"type": "Deposit", "amount": 50})
        assert isinstance(r, Ok)
        assert u.state["balance"] == 150

    def test_ok_withdraw(self):
        u = _bank_universe()
        r = u.apply({"type": "Withdraw", "amount": 30})
        assert isinstance(r, Ok)
        assert u.state["balance"] == 70

    def test_impossible(self):
        u = _bank_universe()
        r = u.apply({"type": "Withdraw", "amount": 200})
        assert isinstance(r, Impossible)
        assert u.state["balance"] == 100  # unchanged

    def test_state_advances_on_ok(self):
        u = _bank_universe()
        u.apply({"type": "Deposit", "amount": 10})
        u.apply({"type": "Deposit", "amount": 20})
        assert u.state["balance"] == 130

    def test_state_unchanged_on_impossible(self):
        u = _bank_universe()
        u.apply({"type": "Withdraw", "amount": 999})
        assert u.state["balance"] == 100


class TestReduce:
    def test_all_ok(self):
        u = _bank_universe()
        r = u.reduce(
            [
                {"type": "Deposit", "amount": 50},
                {"type": "Withdraw", "amount": 30},
            ]
        )
        assert isinstance(r, Ok)
        assert u.state["balance"] == 120

    def test_stops_on_impossible(self):
        u = _bank_universe()
        r = u.reduce(
            [
                {"type": "Deposit", "amount": 50},
                {"type": "Withdraw", "amount": 999},
                {"type": "Deposit", "amount": 10},  # not reached
            ]
        )
        assert isinstance(r, Impossible)
        assert u.state["balance"] == 150  # deposit succeeded, withdraw blocked


class TestReduceAll:
    def test_skips_impossible(self):
        u = _bank_universe()
        result = u.reduce_all(
            [
                {"type": "Deposit", "amount": 50},
                {"type": "Withdraw", "amount": 999},
                {"type": "Deposit", "amount": 10},
            ]
        )
        assert result.passed
        assert result.processed == 2
        assert len(result.skipped) == 1

    def test_stops_on_violated(self):
        spec = Spec(
            name="strict",
            state0={"balance": 100},
            maintains=(
                Maintain(
                    name="non_negative",
                    expr=Always(
                        Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))
                    ),
                ),
            ),
        )
        u = Universe(spec=spec, transition=_bank_transition)
        result = u.reduce_all(
            [
                {"type": "Withdraw", "amount": 200},
            ]
        )
        assert not result.passed
        assert isinstance(result.final, Violated)


class TestStream:
    def test_yields_all(self):
        u = _bank_universe()
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

    def test_stops_on_violated(self):
        spec = Spec(
            name="strict",
            state0={"balance": 100},
            maintains=(
                Maintain(
                    name="inv",
                    expr=Always(
                        Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))
                    ),
                ),
            ),
        )
        u = Universe(spec=spec, transition=_bank_transition)
        results = list(
            u.stream(
                [
                    {"type": "Withdraw", "amount": 200},
                    {"type": "Deposit", "amount": 10},  # not reached
                ]
            )
        )
        assert len(results) == 1
        assert isinstance(results[0], Violated)


class TestReset:
    def test_reset_to_initial(self):
        u = _bank_universe()
        u.apply({"type": "Deposit", "amount": 50})
        assert u.state["balance"] == 150
        u.reset()
        assert u.state["balance"] == 100

    def test_reset_with_custom_state(self):
        u = _bank_universe(state={"balance": 500})
        u.apply({"type": "Withdraw", "amount": 100})
        assert u.state["balance"] == 400
        u.reset()
        assert u.state["balance"] == 500


class TestRepr:
    def test_repr(self):
        u = _bank_universe()
        assert "Universe" in repr(u)
        assert "bank" in repr(u)
