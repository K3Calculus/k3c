"""Tests for k3c public API surface — verifies all exports work."""

from __future__ import annotations


class TestTopLevelImports:
    """Verify everything importable from `from k3c import ...`."""

    def test_version(self):
        from k3c import __version__

        assert isinstance(__version__, str)
        assert "." in __version__

    def test_spec_builder(self):
        from k3c import Spec, K3Spec

        spec = Spec("test").state0({"x": 1}).build()
        assert isinstance(spec, K3Spec)
        assert spec.name == "test"

    def test_clause_types(self):
        from k3c import FieldDef, PermitClause, RequireClause, MaintainClause
        from k3c import ProjectionDef, OutputDef, KorrelatorDef

        assert FieldDef is not None
        assert PermitClause is not None
        assert RequireClause is not None
        assert MaintainClause is not None
        assert ProjectionDef is not None
        assert OutputDef is not None
        assert KorrelatorDef is not None

    def test_result_types(self):
        from k3c import Ok, Impossible, Violated, Why, WhyKind

        assert Ok is not None
        assert Impossible is not None
        assert Violated is not None
        assert Why is not None
        assert WhyKind is not None

    def test_context(self):
        from k3c import SpecCtx

        ctx = SpecCtx.initial({"x": 1})
        assert ctx.spec_state == {"x": 1}

    def test_k3l_nodes(self):
        from k3c import (
            LBool,
            CmpOp,
            ArithOp,
        )

        assert LBool(True).val is True
        assert CmpOp.EQ == "Eq"
        assert ArithOp.ADD == "Add"

    def test_universe_factory(self):
        from k3c import universe, Universe, System

        assert universe is not None
        assert Universe is not None
        assert System is not None

    def test_universe_result_types(self):
        from k3c import ReduceAllResult, ParallelReduceResult

        assert ReduceAllResult is not None
        assert ParallelReduceResult is not None

    def test_algebra_types(self):
        from k3c import ComposedUniverse, BridgedUniverse

        assert ComposedUniverse is not None
        assert BridgedUniverse is not None

    def test_bridge_types(self):
        from k3c import BridgeMode, RetryPolicy

        assert BridgeMode.SYNCHRONOUS == "synchronous"
        assert BridgeMode.ASYNC == "async"
        assert BridgeMode.BEST_EFFORT == "best_effort"
        assert RetryPolicy.no_retry().max_attempts == 1

    def test_testing_types(self):
        from k3c import FuzzReport, FuzzViolation, ExplainResult

        assert FuzzReport is not None
        assert FuzzViolation is not None
        assert ExplainResult is not None

    def test_error_types(self):
        from k3c import (
            K3Error,
            K3NothingException,
            K3ViolatedException,
            K3WellFormednessError,
            K3BridgeError,
        )

        assert issubclass(K3NothingException, K3Error)
        assert issubclass(K3ViolatedException, K3Error)
        assert issubclass(K3WellFormednessError, K3Error)
        assert issubclass(K3BridgeError, K3Error)


class TestSubpackageImports:
    """Verify subpackage imports work."""

    def test_lang_subpackage(self):
        from k3c.lang import k3_eval, LBool, Some

        result = k3_eval(LBool(True), {})
        assert isinstance(result, Some)
        assert result.val is True

    def test_lang_serde(self):
        from k3c.lang import to_dict, from_dict, LInt

        d = to_dict(LInt(42))
        restored = from_dict(d)
        assert restored == LInt(42)

    def test_lang_type_serde(self):
        from k3c.lang import type_to_dict, type_from_dict, TInt

        d = type_to_dict(TInt())
        restored = type_from_dict(d)
        assert restored == TInt()

    def test_spec_subpackage(self):
        from k3c.spec import Spec, K3Spec, SpecCtx

        assert Spec is not None
        assert K3Spec is not None
        assert SpecCtx is not None

    def test_spec_extractors(self):
        from k3c.spec import ByteSlice, TextEncoding

        b = ByteSlice(start=0, length=3)
        assert b.encoding == TextEncoding.ASCII

    def test_universe_subpackage(self):
        from k3c.universe import (
            universe,
            parallel_reduce,
        )

        assert universe is not None
        assert parallel_reduce is not None


class TestEndToEnd:
    """Full workflow using only public API imports."""

    def test_bank_account_workflow(self):
        from k3c import (
            Spec,
            universe,
            Ok,
            Impossible,
            Compare,
            CmpOp,
            Field,
            Var,
            EventField,
            Always,
            LInt,
        )

        spec = (
            Spec("bank")
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
            .project("balance_view", lambda s: s["balance"])
            .output(
                "receipt",
                lambda s, e, ns: {"type": "Receipt", "balance": ns["balance"]},
                on="Withdraw",
            )
            .build()
        )

        class BankSystem:
            def transition(self, state, event):
                if event.get("type") == "Withdraw":
                    return {**state, "balance": state["balance"] - event["amount"]}
                if event.get("type") == "Deposit":
                    return {**state, "balance": state["balance"] + event["amount"]}
                return state

        u = universe(BankSystem(), spec)

        # Ok
        r1 = u.apply({"type": "Deposit", "amount": 50})
        assert isinstance(r1, Ok)
        assert u.state["balance"] == 150
        assert r1.projections["balance_view"] == 150

        # Ok with output
        r2 = u.apply({"type": "Withdraw", "amount": 30})
        assert isinstance(r2, Ok)
        assert u.state["balance"] == 120
        assert len(r2.outputs) == 1
        assert r2.outputs[0]["type"] == "Receipt"

        # Impossible
        r3 = u.apply({"type": "Withdraw", "amount": 999})
        assert isinstance(r3, Impossible)
        assert u.state["balance"] == 120

        # Reduce
        u.reset()
        r4 = u.reduce(
            [
                {"type": "Deposit", "amount": 200},
                {"type": "Withdraw", "amount": 50},
            ]
        )
        assert isinstance(r4, Ok)
        assert u.state["balance"] == 250

        # Fuzz
        u.reset()
        report = u.fuzz(sequences=20, steps=10, seed=42)
        assert report.passed

        # Explain
        u.reset()
        explanation = u.explain({"type": "Withdraw", "amount": 30})
        assert explanation.passed
        assert len(explanation.trace) > 0
        assert u.state["balance"] == 100  # explain doesn't mutate

    def test_compose_and_bridge(self):
        from k3c import (
            Spec,
            universe,
            Ok,
            BridgeMode,
            LBool,
        )

        spec_a = Spec("a").state0({"x": 0}).permit("ok", when=LBool(True)).build()
        spec_b = Spec("b").state0({"y": 0}).permit("ok", when=LBool(True)).build()

        class SysA:
            def transition(self, s, e):
                return {**s, "x": s["x"] + 1}

        class SysB:
            def transition(self, s, e):
                return {**s, "y": s["y"] + e.get("n", 0)}

        ua = universe(SysA(), spec_a)
        ub = universe(SysB(), spec_b)

        # Compose
        composed = ua.compose(
            ub, lambda e: "left" if e.get("target") != "b" else "right"
        )
        r = composed.apply({"target": "a"})
        assert isinstance(r, Ok)
        assert composed.state["left"]["x"] == 1

        # Bridge
        ua2 = universe(SysA(), spec_a)
        ub2 = universe(SysB(), spec_b)
        bridged = ua2.bridge(
            ub2,
            lambda s, e, ns: {"type": "Bridged", "n": ns["x"]},
            BridgeMode.SYNCHRONOUS,
        )
        r2 = bridged.apply({"type": "Inc"})
        assert isinstance(r2, Ok)
        assert bridged.state["source"]["x"] == 1
        assert bridged.state["target"]["y"] == 1

    def test_parallel_reduce(self):
        from k3c import Spec, parallel_reduce, LBool

        spec = Spec("counter").state0({"n": 0}).permit("ok", when=LBool(True)).build()

        class Counter:
            def transition(self, s, e):
                return {**s, "n": s["n"] + 1}

        chunks = [[{"type": "Inc"}] * 5] * 3
        specs = [spec.slice(from_state={"n": i * 100}) for i in range(3)]
        result = parallel_reduce(Counter(), specs, chunks, workers=1)
        assert result.passed
        assert result.total_processed == 15
