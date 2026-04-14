"""Tests for k3c.lang.compile — K3Spec → CompiledSpec compilation."""

from __future__ import annotations

import pytest

from k3c.lang.compile import (
    CompiledSpec,
    MaintainKind,
    classify_maintain,
    compile_spec,
)
from k3c.lang.ir import (
    Always,
    And,
    CmpOp,
    Compare,
    Eventually,
    EventField,
    Field,
    ForAll,
    Implies,
    LBool,
    LInt,
    LStr,
    Not,
    Or,
    Until,
    Var,
    Within,
)
from k3c.spec.builder import MaintainClause, Spec


class TestClassifyMaintain:
    def test_always_phi_is_safety(self):
        clause = MaintainClause("rule", expr=Always(LBool(True)))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.SAFETY
        assert c.expr == LBool(True)

    def test_bare_phi_is_safety(self):
        clause = MaintainClause("rule", expr=LBool(True))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.SAFETY
        assert c.expr == LBool(True)

    def test_always_within_is_bounded(self):
        clause = MaintainClause("rule", expr=Always(Within(LBool(True), n=10)))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.BOUNDED
        assert c.n == 10

    def test_always_eventually_is_liveness(self):
        clause = MaintainClause("rule", expr=Always(Eventually(LBool(True))))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.LIVENESS

    def test_always_until_is_liveness(self):
        clause = MaintainClause("rule", expr=Always(Until(LBool(True), LBool(False))))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.LIVENESS

    def test_always_implies_within_is_bounded(self):
        """□(trigger ⇒ Within(φ, n)) — the common real-world pattern."""
        clause = MaintainClause(
            "time_wait",
            expr=Always(
                Implies(
                    Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("TIME_WAIT")),
                    Within(
                        Compare(
                            CmpOp.EQ, Field(Var("state"), "status"), LStr("CLOSED")
                        ),
                        n=240,
                    ),
                )
            ),
        )
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.BOUNDED
        assert c.n == 240

    def test_always_implies_eventually_is_liveness(self):
        """□(trigger ⇒ ◇φ) — response pattern."""
        clause = MaintainClause(
            "handshake",
            expr=Always(
                Implies(
                    Compare(CmpOp.EQ, Field(Var("state"), "status"), LStr("SYN_SENT")),
                    Eventually(
                        Compare(
                            CmpOp.EQ, Field(Var("state"), "status"), LStr("ESTABLISHED")
                        )
                    ),
                )
            ),
        )
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.LIVENESS

    def test_always_and_within_is_bounded(self):
        """□(cond ∧ Within(φ, n))."""
        clause = MaintainClause(
            "rule",
            expr=Always(
                And(
                    LBool(True),
                    Within(LBool(True), n=5),
                )
            ),
        )
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.BOUNDED
        assert c.n == 5

    def test_always_or_eventually_is_liveness(self):
        clause = MaintainClause(
            "rule",
            expr=Always(
                Or(
                    LBool(False),
                    Eventually(LBool(True)),
                )
            ),
        )
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.LIVENESS

    def test_nested_not_eventually_is_liveness(self):
        clause = MaintainClause("rule", expr=Always(Not(Eventually(LBool(True)))))
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.LIVENESS

    def test_preserves_original(self):
        original = Always(Within(LBool(True), n=10))
        clause = MaintainClause("rule", expr=original)
        c = classify_maintain(clause)
        assert c.original is original

    def test_preserves_name(self):
        clause = MaintainClause("my_rule", expr=Always(LBool(True)))
        c = classify_maintain(clause)
        assert c.name == "my_rule"

    def test_complex_safety_with_forall(self):
        """ForAll without temporal → safety."""
        clause = MaintainClause(
            "log_match",
            expr=Always(
                ForAll(
                    "a",
                    Field(Var("state"), "log"),
                    ForAll(
                        "b",
                        Field(Var("state"), "log"),
                        Implies(
                            And(
                                Compare(
                                    CmpOp.EQ,
                                    Field(Var("a"), "idx"),
                                    Field(Var("b"), "idx"),
                                ),
                                Compare(
                                    CmpOp.EQ,
                                    Field(Var("a"), "term"),
                                    Field(Var("b"), "term"),
                                ),
                            ),
                            Compare(
                                CmpOp.EQ, Field(Var("a"), "cmd"), Field(Var("b"), "cmd")
                            ),
                        ),
                    ),
                )
            ),
        )
        c = classify_maintain(clause)
        assert c.kind == MaintainKind.SAFETY


class TestCompileSpec:
    def _build_spec(self):
        return (
            Spec("test")
            .state0({"balance": 0, "status": "active"})
            .permit(
                "has_funds",
                when=Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0)),
            )
            .permit("is_active", when=LBool(True), on="Withdraw")
            .require("debit", on="Withdraw", transition=Var("new_state"))
            .require("credit", on="Deposit", transition=Var("new_state"))
            .maintain(
                "non_neg",
                expr=Always(Compare(CmpOp.GE, Field(Var("state"), "balance"), LInt(0))),
            )
            .maintain(
                "settle",
                expr=Always(
                    Implies(
                        Compare(CmpOp.EQ, EventField("type"), LStr("Withdraw")),
                        Eventually(
                            Compare(
                                CmpOp.EQ, Field(Var("state"), "status"), LStr("settled")
                            )
                        ),
                    )
                ),
            )
            .maintain(
                "fast_settle",
                expr=Always(
                    Implies(
                        Compare(CmpOp.EQ, EventField("type"), LStr("Withdraw")),
                        Within(
                            Compare(
                                CmpOp.EQ, Field(Var("state"), "status"), LStr("settled")
                            ),
                            n=5,
                        ),
                    )
                ),
            )
            .korrelate(lift=lambda s: {"balance": s["balance"]})
            .build()
        )

    def test_returns_compiled_spec(self):
        compiled = compile_spec(self._build_spec())
        assert isinstance(compiled, CompiledSpec)

    def test_name_preserved(self):
        compiled = compile_spec(self._build_spec())
        assert compiled.name == "test"

    def test_state0_preserved(self):
        compiled = compile_spec(self._build_spec())
        assert compiled.state0 == {"balance": 0, "status": "active"}

    def test_permits_preserved(self):
        compiled = compile_spec(self._build_spec())
        assert len(compiled.permits) == 2
        assert compiled.permits[0].name == "has_funds"

    def test_requires_indexed_by_event(self):
        compiled = compile_spec(self._build_spec())
        assert "Withdraw" in compiled.requires
        assert "Deposit" in compiled.requires
        assert compiled.requires["Withdraw"].name == "debit"
        assert compiled.requires["Deposit"].name == "credit"

    def test_safety_clauses(self):
        compiled = compile_spec(self._build_spec())
        assert len(compiled.safety) == 1
        assert compiled.safety[0].name == "non_neg"

    def test_bounded_clauses(self):
        compiled = compile_spec(self._build_spec())
        assert len(compiled.bounded) == 1
        assert compiled.bounded[0].name == "fast_settle"
        assert compiled.bounded[0].n == 5

    def test_liveness_clauses(self):
        compiled = compile_spec(self._build_spec())
        assert len(compiled.liveness) == 1
        assert compiled.liveness[0].name == "settle"

    def test_korrelator_preserved(self):
        compiled = compile_spec(self._build_spec())
        assert compiled.korrelator is not None
        assert compiled.korrelator.lift({"balance": 42}) == {"balance": 42}

    def test_hash_fn_default(self):
        compiled = compile_spec(self._build_spec())
        assert compiled.hash_fn == "sha256"

    def test_hash_fn_custom(self):
        compiled = compile_spec(self._build_spec(), hash_fn="blake2b")
        assert compiled.hash_fn == "blake2b"

    def test_protocol_start(self):
        compiled = compile_spec(self._build_spec())
        assert compiled.protocol_start == "__start__"

    def test_compiled_is_frozen(self):
        compiled = compile_spec(self._build_spec())
        with pytest.raises(AttributeError):
            compiled.name = "x"  # type: ignore[misc]

    def test_empty_spec(self):
        spec = Spec("empty").state0({"x": 0}).build()
        compiled = compile_spec(spec)
        assert compiled.safety == ()
        assert compiled.bounded == ()
        assert compiled.liveness == ()
        assert compiled.permits == ()
        assert compiled.requires == {}
        assert compiled.korrelator is None


class TestMaintainKind:
    def test_is_str_enum(self):
        assert MaintainKind.SAFETY == "safety"
        assert MaintainKind.BOUNDED == "bounded"
        assert MaintainKind.LIVENESS == "liveness"
