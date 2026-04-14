"""Tests for k3c.errors — all exception classes."""

from __future__ import annotations

import pytest

from k3c.errors import (
    K3BridgeError,
    K3ComposeError,
    K3Error,
    K3NothingException,
    K3SchemaError,
    K3SerdeError,
    K3ViolatedException,
    K3WellFormednessError,
)
from k3c.spec.ctx import SpecCtx
from k3c.spec.result import Why, WhyKind


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_why(**overrides: object) -> Why:
    ctx = SpecCtx.initial({"x": 1})
    defaults: dict = {
        "rule": "test_rule",
        "kind": WhyKind.MAINTAIN,
        "messages": ("invariant failed",),
        "before": {"x": 1},
        "after": {"x": 2},
        "event": {"type": "update"},
        "ctx": ctx,
        "expected": None,
        "trace": (),
        "step_hash": "abc12345deadbeef",
    }
    defaults.update(overrides)
    return Why(**defaults)


# ── K3Error base ─────────────────────────────────────────────────────────────


class TestK3ErrorHierarchy:
    def test_all_exceptions_inherit_from_k3error(self):
        classes = [
            K3NothingException,
            K3ViolatedException,
            K3WellFormednessError,
            K3BridgeError,
            K3ComposeError,
            K3SchemaError,
            K3SerdeError,
        ]
        for cls in classes:
            assert issubclass(cls, K3Error)

    def test_k3error_is_exception(self):
        assert issubclass(K3Error, Exception)

    def test_catch_k3error_catches_subclasses(self):
        with pytest.raises(K3Error):
            raise K3NothingException(field="balance", step_hash="aabbccdd")


# ── K3NothingException ───────────────────────────────────────────────────────


class TestK3NothingException:
    def test_construction_and_fields(self):
        exc = K3NothingException(field="balance", step_hash="abcdef1234567890")
        assert exc.field == "balance"
        assert exc.step_hash == "abcdef1234567890"

    def test_str_format(self):
        exc = K3NothingException(field="amount", step_hash="1234567890abcdef")
        assert str(exc) == "Required field 'amount' absent step:12345678"

    def test_str_truncates_step_hash_to_8(self):
        exc = K3NothingException(field="f", step_hash="a" * 64)
        assert "step:aaaaaaaa" in str(exc)

    def test_super_init_receives_message(self):
        exc = K3NothingException(field="x", step_hash="abcd1234")
        assert exc.args[0] == str(exc)

    def test_raise_and_catch(self):
        with pytest.raises(K3NothingException) as exc_info:
            raise K3NothingException(field="missing_field", step_hash="deadbeef")
        assert exc_info.value.field == "missing_field"

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_missing_field_arg_raises_type_error(self):
        with pytest.raises(TypeError):
            K3NothingException(step_hash="abc")  # type: ignore[call-arg]

    def test_missing_step_hash_arg_raises_type_error(self):
        with pytest.raises(TypeError):
            K3NothingException(field="x")  # type: ignore[call-arg]

    def test_no_args_raises_type_error(self):
        with pytest.raises(TypeError):
            K3NothingException()  # type: ignore[call-arg]

    def test_short_step_hash_still_works(self):
        exc = K3NothingException(field="x", step_hash="ab")
        assert "step:ab" in str(exc)

    def test_empty_step_hash(self):
        exc = K3NothingException(field="x", step_hash="")
        assert "step:" in str(exc)


# ── K3ViolatedException ──────────────────────────────────────────────────────


class TestK3ViolatedException:
    def test_construction_and_why(self):
        why = _make_why()
        exc = K3ViolatedException(why=why)
        assert exc.why is why

    def test_str_delegates_to_why_to_prompt(self):
        why = _make_why()
        exc = K3ViolatedException(why=why)
        assert str(exc) == why.to_prompt()

    def test_fingerprint_delegates_to_why(self):
        why = _make_why()
        exc = K3ViolatedException(why=why)
        assert exc.fingerprint() == why.fingerprint

    def test_super_init_receives_message(self):
        why = _make_why()
        exc = K3ViolatedException(why=why)
        assert exc.args[0] == str(exc)

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_no_args_raises_type_error(self):
        with pytest.raises(TypeError):
            K3ViolatedException()  # type: ignore[call-arg]


# ── K3WellFormednessError ────────────────────────────────────────────────────


class TestK3WellFormednessError:
    def test_construction_and_fields(self):
        exc = K3WellFormednessError(rule=3, message="duplicate permit name")
        assert exc.rule == 3
        assert exc.message == "duplicate permit name"

    def test_str_format(self):
        exc = K3WellFormednessError(rule=5, message="empty transition")
        assert str(exc) == "Well-formedness rule 5 violated: empty transition"

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_missing_rule_raises_type_error(self):
        with pytest.raises(TypeError):
            K3WellFormednessError(message="x")  # type: ignore[call-arg]


# ── K3BridgeError ────────────────────────────────────────────────────────────


class TestK3BridgeError:
    def test_construction_and_fields(self):
        exc = K3BridgeError(
            source_id="order",
            target_id="payment",
            bridge_event={"type": "pay"},
            attempts=3,
            last_reason="timeout",
        )
        assert exc.source_id == "order"
        assert exc.target_id == "payment"
        assert exc.bridge_event == {"type": "pay"}
        assert exc.attempts == 3
        assert exc.last_reason == "timeout"

    def test_str_format(self):
        exc = K3BridgeError(
            source_id="A",
            target_id="B",
            bridge_event={},
            attempts=5,
            last_reason="connection refused",
        )
        result = str(exc)
        assert "'A'" in result
        assert "'B'" in result
        assert "5 attempts" in result
        assert "connection refused" in result

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_missing_args_raises_type_error(self):
        with pytest.raises(TypeError):
            K3BridgeError(source_id="A")  # type: ignore[call-arg]


# ── K3ComposeError ───────────────────────────────────────────────────────────


class TestK3ComposeError:
    def test_construction_and_fields(self):
        exc = K3ComposeError(
            left_id="spec_a", right_id="spec_b", message="incompatible events"
        )
        assert exc.left_id == "spec_a"
        assert exc.right_id == "spec_b"
        assert exc.message == "incompatible events"

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_missing_args_raises_type_error(self):
        with pytest.raises(TypeError):
            K3ComposeError(left_id="a")  # type: ignore[call-arg]


# ── K3SchemaError ────────────────────────────────────────────────────────────


class TestK3SchemaError:
    def test_construction_and_fields(self):
        exc = K3SchemaError(path="permits[0].when", message="not a valid expression")
        assert exc.path == "permits[0].when"
        assert exc.message == "not a valid expression"

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_missing_args_raises_type_error(self):
        with pytest.raises(TypeError):
            K3SchemaError(path="x")  # type: ignore[call-arg]


# ── K3SerdeError ─────────────────────────────────────────────────────────────


class TestK3SerdeError:
    def test_construction_and_fields(self):
        exc = K3SerdeError(node="And", message="missing 'left' field")
        assert exc.node == "And"
        assert exc.message == "missing 'left' field"

    # ── Negative ──────────────────────────────────────────────────────────────

    def test_missing_args_raises_type_error(self):
        with pytest.raises(TypeError):
            K3SerdeError(node="X")  # type: ignore[call-arg]
