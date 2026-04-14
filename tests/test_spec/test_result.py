"""Tests for k3c.spec.result — WhyKind, Why, Impossible, Violated, Ok, K3Result."""

from __future__ import annotations

import json

import pytest

from k3c.errors import K3ViolatedException
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import Impossible, Ok, Violated, Why, WhyKind


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ctx() -> SpecCtx:
    return SpecCtx.initial({"x": 1})


def _make_why(**overrides: object) -> Why:
    defaults: dict = {
        "rule": "check_balance",
        "kind": WhyKind.MAINTAIN,
        "messages": ("balance must be positive",),
        "before": {"balance": 100},
        "after": {"balance": -5},
        "event": {"type": "withdraw", "amount": 105},
        "ctx": _ctx(),
        "expected": None,
        "trace": (),
        "step_hash": "abcdef1234567890abcdef1234567890",
    }
    defaults.update(overrides)
    return Why(**defaults)


# ═══════════════════════════════════════════════════════════════════════════════
#  WhyKind
# ═══════════════════════════════════════════════════════════════════════════════


class TestWhyKind:
    def test_all_variants_exist(self):
        assert WhyKind.PERMIT == "permit"
        assert WhyKind.MISSING == "missing"
        assert WhyKind.MAINTAIN == "maintain"
        assert WhyKind.KORRELATE == "korrelate"
        assert WhyKind.TIMER == "timer"
        assert WhyKind.LIVENESS == "liveness"

    def test_is_str(self):
        assert isinstance(WhyKind.PERMIT, str)

    def test_json_serializable(self):
        assert json.dumps({"kind": WhyKind.MAINTAIN}) == '{"kind": "maintain"}'

    def test_comparison_with_string(self):
        assert WhyKind.PERMIT == "permit"

    def test_iteration(self):
        names = list(WhyKind)
        assert len(names) == 6

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_invalid_variant(self):
        with pytest.raises(ValueError):
            WhyKind("nonexistent")


# ═══════════════════════════════════════════════════════════════════════════════
#  Why
# ═══════════════════════════════════════════════════════════════════════════════


class TestWhyConstruction:
    def test_basic_construction(self):
        why = _make_why()
        assert why.rule == "check_balance"
        assert why.kind == WhyKind.MAINTAIN
        assert why.messages == ("balance must be positive",)

    def test_frozen(self):
        why = _make_why()
        with pytest.raises(AttributeError):
            why.rule = "changed"  # type: ignore[misc]


class TestWhyMessage:
    def test_message_returns_first(self):
        why = _make_why(messages=("first", "second", "third"))
        assert why.message == "first"

    def test_message_empty_tuple(self):
        why = _make_why(messages=())
        assert why.message == ""

    def test_message_single(self):
        why = _make_why(messages=("only one",))
        assert why.message == "only one"


class TestWhyFingerprint:
    def test_fingerprint_is_16_hex_chars(self):
        why = _make_why()
        fp = why.fingerprint
        assert len(fp) == 16
        int(fp, 16)  # must be valid hex

    def test_fingerprint_stable(self):
        a = _make_why()
        b = _make_why()
        assert a.fingerprint == b.fingerprint

    def test_fingerprint_differs_by_rule(self):
        a = _make_why(rule="rule_a")
        b = _make_why(rule="rule_b")
        assert a.fingerprint != b.fingerprint

    def test_fingerprint_differs_by_kind(self):
        a = _make_why(kind=WhyKind.MAINTAIN)
        b = _make_why(kind=WhyKind.KORRELATE)
        assert a.fingerprint != b.fingerprint

    def test_fingerprint_differs_by_message(self):
        a = _make_why(messages=("msg_a",))
        b = _make_why(messages=("msg_b",))
        assert a.fingerprint != b.fingerprint

    def test_fingerprint_ignores_state_changes(self):
        a = _make_why(before={"x": 1})
        b = _make_why(before={"x": 999})
        assert a.fingerprint == b.fingerprint

    def test_fingerprint_ignores_step_hash(self):
        a = _make_why(step_hash="aaaa")
        b = _make_why(step_hash="bbbb")
        assert a.fingerprint == b.fingerprint


class TestWhyToDict:
    def test_contains_all_fields(self):
        why = _make_why()
        d = why.to_dict()
        assert d["rule"] == "check_balance"
        assert d["kind"] == WhyKind.MAINTAIN
        assert d["messages"] == ("balance must be positive",)
        assert d["before"] == {"balance": 100}
        assert d["after"] == {"balance": -5}
        assert d["event"] == {"type": "withdraw", "amount": 105}
        assert d["expected"] is None
        assert d["trace"] == []
        assert d["step_hash"] == "abcdef1234567890abcdef1234567890"
        assert d["fingerprint"] == why.fingerprint
        assert d["ctx"] == why.ctx.spec_state

    def test_trace_converted_to_list(self):
        why = _make_why(trace=({"e": 1}, {"e": 2}))
        d = why.to_dict()
        assert isinstance(d["trace"], list)
        assert d["trace"] == [{"e": 1}, {"e": 2}]


class TestWhyToPrompt:
    def test_contains_kind_and_rule(self):
        why = _make_why()
        prompt = why.to_prompt()
        assert "[MAINTAIN]" in prompt
        assert "check_balance" in prompt

    def test_contains_step_hash_prefix(self):
        why = _make_why(step_hash="abcdef12xxxxxxxx")
        prompt = why.to_prompt()
        assert "step:abcdef12" in prompt

    def test_contains_messages(self):
        why = _make_why(messages=("msg1", "msg2"))
        prompt = why.to_prompt()
        assert "msg1" in prompt
        assert "msg2" in prompt

    def test_omits_after_when_none(self):
        why = _make_why(after=None)
        prompt = why.to_prompt()
        assert "After:" not in prompt

    def test_includes_after_when_present(self):
        why = _make_why(after={"x": 2})
        prompt = why.to_prompt()
        assert "After:" in prompt

    def test_omits_expected_when_none(self):
        why = _make_why(expected=None)
        prompt = why.to_prompt()
        assert "Expected:" not in prompt

    def test_includes_expected_when_present(self):
        why = _make_why(expected={"x": 99})
        prompt = why.to_prompt()
        assert "Expected:" in prompt

    def test_contains_fingerprint(self):
        why = _make_why()
        prompt = why.to_prompt()
        assert f"fingerprint: {why.fingerprint}" in prompt


class TestWhyToLogRecord:
    def test_severity_warn_for_permit(self):
        why = _make_why(kind=WhyKind.PERMIT)
        record = why.to_log_record()
        assert record["severity"] == "WARN"
        assert record["severityText"] == "IMPOSSIBLE"

    def test_severity_warn_for_missing(self):
        why = _make_why(kind=WhyKind.MISSING)
        record = why.to_log_record()
        assert record["severity"] == "WARN"
        assert record["severityText"] == "IMPOSSIBLE"

    def test_severity_error_for_maintain(self):
        why = _make_why(kind=WhyKind.MAINTAIN)
        record = why.to_log_record()
        assert record["severity"] == "ERROR"
        assert record["severityText"] == "VIOLATED"

    def test_severity_error_for_korrelate(self):
        why = _make_why(kind=WhyKind.KORRELATE)
        record = why.to_log_record()
        assert record["severity"] == "ERROR"

    def test_severity_error_for_timer(self):
        why = _make_why(kind=WhyKind.TIMER)
        record = why.to_log_record()
        assert record["severity"] == "ERROR"

    def test_severity_error_for_liveness(self):
        why = _make_why(kind=WhyKind.LIVENESS)
        record = why.to_log_record()
        assert record["severity"] == "ERROR"

    def test_contains_k3c_fields(self):
        why = _make_why()
        record = why.to_log_record()
        assert record["k3c.rule"] == "check_balance"
        assert record["k3c.kind"] == WhyKind.MAINTAIN
        assert record["k3c.step_hash"] == why.step_hash
        assert record["k3c.fingerprint"] == why.fingerprint
        assert record["k3c.protocol_pos"] == why.ctx.protocol_pos

    def test_json_fields_are_strings(self):
        why = _make_why()
        record = why.to_log_record()
        for key in (
            "k3c.before",
            "k3c.after",
            "k3c.event",
            "k3c.expected",
            "k3c.spec_state",
        ):
            assert isinstance(record[key], str)
            json.loads(record[key])  # must be valid JSON


# ═══════════════════════════════════════════════════════════════════════════════
#  Impossible
# ═══════════════════════════════════════════════════════════════════════════════


class TestImpossible:
    def test_construction(self):
        why = _make_why(kind=WhyKind.PERMIT)
        imp = Impossible(why=why)
        assert imp.why is why

    def test_frozen(self):
        imp = Impossible(why=_make_why())
        with pytest.raises(AttributeError):
            imp.why = _make_why()  # type: ignore[misc]

    def test_map_short_circuits(self):
        imp = Impossible(why=_make_why())
        result = imp.map(lambda x: x * 2)
        assert result is imp

    def test_map_does_not_call_function(self):
        called = []
        imp = Impossible(why=_make_why())
        imp.map(lambda x: called.append(x))
        assert called == []

    def test_and_then_short_circuits(self):
        imp = Impossible(why=_make_why())
        result = imp.and_then(lambda s, c: Ok(state=s, ctx=c, step_hash="h"))
        assert result is imp

    def test_and_then_does_not_call_function(self):
        called = []
        imp = Impossible(why=_make_why())
        imp.and_then(lambda s, c: called.append((s, c)))
        assert called == []


# ═══════════════════════════════════════════════════════════════════════════════
#  Violated
# ═══════════════════════════════════════════════════════════════════════════════


class TestViolated:
    def test_construction(self):
        why = _make_why(kind=WhyKind.MAINTAIN)
        v = Violated(why=why)
        assert v.why is why

    def test_frozen(self):
        v = Violated(why=_make_why())
        with pytest.raises(AttributeError):
            v.why = _make_why()  # type: ignore[misc]

    def test_map_short_circuits(self):
        v = Violated(why=_make_why())
        result = v.map(lambda x: x * 2)
        assert result is v

    def test_and_then_short_circuits(self):
        v = Violated(why=_make_why())
        result = v.and_then(lambda s, c: Ok(state=s, ctx=c, step_hash="h"))
        assert result is v

    def test_raise_raises_k3_violated_exception(self):
        why = _make_why()
        v = Violated(why=why)
        with pytest.raises(K3ViolatedException) as exc_info:
            v.raise_()
        assert exc_info.value.why is why

    def test_raise_exception_str_matches_to_prompt(self):
        why = _make_why()
        v = Violated(why=why)
        with pytest.raises(K3ViolatedException) as exc_info:
            v.raise_()
        assert str(exc_info.value) == why.to_prompt()


# ═══════════════════════════════════════════════════════════════════════════════
#  Ok
# ═══════════════════════════════════════════════════════════════════════════════


class TestOk:
    def test_construction(self):
        ctx = _ctx()
        ok = Ok(state={"balance": 200}, ctx=ctx, step_hash="h123")
        assert ok.state == {"balance": 200}
        assert ok.ctx is ctx
        assert ok.step_hash == "h123"

    def test_frozen(self):
        ok = Ok(state=1, ctx=_ctx(), step_hash="h")
        with pytest.raises(AttributeError):
            ok.state = 2  # type: ignore[misc]


class TestOkMap:
    def test_transforms_state(self):
        ok = Ok(state=5, ctx=_ctx(), step_hash="h")
        result = ok.map(lambda x: x * 10)
        assert isinstance(result, Ok)
        assert result.state == 50

    def test_preserves_ctx(self):
        ctx = _ctx()
        ok = Ok(state=1, ctx=ctx, step_hash="h")
        result = ok.map(lambda x: x + 1)
        assert result.ctx is ctx

    def test_preserves_step_hash(self):
        ok = Ok(state=1, ctx=_ctx(), step_hash="original")
        result = ok.map(lambda x: x + 1)
        assert result.step_hash == "original"

    def test_changes_type(self):
        ok = Ok(state=42, ctx=_ctx(), step_hash="h")
        result = ok.map(str)
        assert result.state == "42"

    def test_chained_map(self):
        ok = Ok(state=2, ctx=_ctx(), step_hash="h")
        result = ok.map(lambda x: x + 1).map(lambda x: x * 10)
        assert result.state == 30


class TestOkAndThen:
    def test_chains_ok_to_ok(self):
        ctx = _ctx()
        ok = Ok(state=10, ctx=ctx, step_hash="h1")
        result = ok.and_then(lambda s, c: Ok(state=s + 5, ctx=c, step_hash="h2"))
        assert isinstance(result, Ok)
        assert result.state == 15
        assert result.step_hash == "h2"

    def test_chains_ok_to_impossible(self):
        why = _make_why(kind=WhyKind.PERMIT)
        ok = Ok(state=10, ctx=_ctx(), step_hash="h1")
        result = ok.and_then(lambda s, c: Impossible(why=why))
        assert isinstance(result, Impossible)

    def test_chains_ok_to_violated(self):
        why = _make_why(kind=WhyKind.MAINTAIN)
        ok = Ok(state=10, ctx=_ctx(), step_hash="h1")
        result = ok.and_then(lambda s, c: Violated(why=why))
        assert isinstance(result, Violated)

    def test_chained_and_then_propagates_failure(self):
        why = _make_why(kind=WhyKind.PERMIT)
        result = (
            Ok(state=1, ctx=_ctx(), step_hash="h1")
            .and_then(lambda s, c: Impossible(why=why))
            .and_then(lambda s, c: Ok(state=999, ctx=c, step_hash="h3"))
        )
        assert isinstance(result, Impossible)

    def test_and_then_passes_state_and_ctx(self):
        ctx = _ctx()
        received = []
        ok = Ok(state=42, ctx=ctx, step_hash="h")
        ok.and_then(
            lambda s, c: (received.append((s, c)), Ok(state=s, ctx=c, step_hash="h"))[1]
        )
        assert received == [(42, ctx)]


class TestOkUnwrap:
    def test_unwrap_returns_state_and_ctx(self):
        ctx = _ctx()
        ok = Ok(state="data", ctx=ctx, step_hash="h")
        state, returned_ctx = ok.unwrap()
        assert state == "data"
        assert returned_ctx is ctx


class TestOkRepr:
    def test_repr_format(self):
        ok = Ok(state=42, ctx=_ctx(), step_hash="abcdef1234567890")
        r = repr(ok)
        assert "Ok(" in r
        assert "42" in r
        assert "abcdef12" in r

    def test_repr_truncates_step_hash(self):
        ok = Ok(state=1, ctx=_ctx(), step_hash="a" * 64)
        assert "aaaaaaaa" in repr(ok)


# ═══════════════════════════════════════════════════════════════════════════════
#  K3Result pattern matching
# ═══════════════════════════════════════════════════════════════════════════════


class TestK3ResultPatternMatching:
    def test_match_ok(self):
        result = Ok(state=42, ctx=_ctx(), step_hash="h")
        match result:
            case Ok(state=s):
                assert s == 42
            case _:
                pytest.fail("Should match Ok")

    def test_match_impossible(self):
        result = Impossible(why=_make_why(kind=WhyKind.PERMIT))
        match result:
            case Impossible(why=w):
                assert w.kind == WhyKind.PERMIT
            case _:
                pytest.fail("Should match Impossible")

    def test_match_violated(self):
        result = Violated(why=_make_why(kind=WhyKind.MAINTAIN))
        match result:
            case Violated(why=w):
                assert w.kind == WhyKind.MAINTAIN
            case _:
                pytest.fail("Should match Violated")

    def test_exhaustive_match(self):
        results = [
            Ok(state=1, ctx=_ctx(), step_hash="h"),
            Impossible(why=_make_why(kind=WhyKind.PERMIT)),
            Violated(why=_make_why(kind=WhyKind.MAINTAIN)),
        ]
        labels = []
        for r in results:
            match r:
                case Ok():
                    labels.append("ok")
                case Impossible():
                    labels.append("impossible")
                case Violated():
                    labels.append("violated")
        assert labels == ["ok", "impossible", "violated"]
