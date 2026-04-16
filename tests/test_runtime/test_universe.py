"""Tests for k3c.runtime.universe -- Universe class."""

from __future__ import annotations

import pytest

from k3c.engine.result import ErrorAction, Impossible, Ok, StepError, Violated
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


class TestStreamErrors:
    def test_yields_impossible(self):
        u = _bank_universe()
        events = [
            {"type": "Deposit", "amount": 50},
            {"type": "Withdraw", "amount": 300},  # rejected
            {"type": "Deposit", "amount": 10},
        ]
        errors = list(u.stream_errors(events))
        assert len(errors) == 1
        assert isinstance(errors[0], StepError)
        assert errors[0].offset == 1
        assert errors[0].why.rule == "has_funds"
        assert not errors[0].is_violation
        # Processing continued past the Impossible
        assert u.state["balance"] == 160  # 100 + 50 + 10

    def test_aborts_on_violated_by_default(self):
        u = _bank_universe()
        events = [
            {"type": "Deposit", "amount": 50},
            {"type": "Deposit", "amount": -250},  # no guard on Deposit, balance goes -100
            {"type": "Deposit", "amount": 10},  # should not be reached
        ]
        errors = list(u.stream_errors(events))
        assert len(errors) == 1
        assert errors[0].is_violation
        assert errors[0].offset == 1

    def test_on_error_controls_flow(self):
        u = _bank_universe()
        events = [
            {"type": "Withdraw", "amount": 200},  # rejected
            {"type": "Withdraw", "amount": 300},  # rejected
            {"type": "Deposit", "amount": 10},
        ]
        errors = list(
            u.stream_errors(events, on_error=lambda e: ErrorAction.SKIP)
        )
        assert len(errors) == 2
        assert u.state["balance"] == 110

    def test_on_error_abort_all(self):
        u = _bank_universe()
        events = [
            {"type": "Withdraw", "amount": 200},  # rejected
            {"type": "Deposit", "amount": 10},  # should not be reached
        ]
        errors = list(
            u.stream_errors(events, on_error=lambda e: ErrorAction.ABORT_ALL)
        )
        assert len(errors) == 1
        assert u.state["balance"] == 100  # no deposits processed

    def test_error_carries_event_and_state(self):
        u = _bank_universe()
        u.apply({"type": "Deposit", "amount": 50})  # balance = 150
        events = [{"type": "Withdraw", "amount": 200}]
        errors = list(u.stream_errors(events))
        assert len(errors) == 1
        assert errors[0].why.event == {"type": "Withdraw", "amount": 200}
        assert errors[0].why.before == {"balance": 150}

    def test_no_errors_yields_nothing(self):
        u = _bank_universe()
        events = [{"type": "Deposit", "amount": 50}]
        errors = list(u.stream_errors(events))
        assert len(errors) == 0
        assert u.state["balance"] == 150


class TestRepr:
    def test_repr(self):
        u = _bank_universe()
        assert "Universe" in repr(u)
        assert "bank" in repr(u)
