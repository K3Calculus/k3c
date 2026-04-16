"""Tests for k3c.ir.value — Some, Nothing, Option."""

from __future__ import annotations

import pytest

from k3c.errors import K3NothingException
from k3c.ir.value import Nothing, Some


# -- Some ----------------------------------------------------------------------


class TestSomeConstruction:
    def test_wrap_int(self):
        s = Some(42)
        assert s.val == 42

    def test_wrap_string(self):
        assert Some("hello").val == "hello"

    def test_wrap_none(self):
        assert Some(None).val is None

    def test_wrap_dict(self):
        d = {"key": "value"}
        assert Some(d).val is d

    def test_wrap_nested_some(self):
        inner = Some(1)
        outer = Some(inner)
        assert outer.val is inner

    def test_frozen(self):
        s = Some(42)
        with pytest.raises(AttributeError):
            s.val = 99  # type: ignore[misc]


class TestSomeMap:
    def test_map_transforms_value(self):
        result = Some(5).map(lambda x: x * 2)
        assert isinstance(result, Some)
        assert result.val == 10

    def test_map_changes_type(self):
        assert Some(42).map(str).val == "42"

    def test_map_chained(self):
        result = Some(2).map(lambda x: x + 1).map(lambda x: x * 10)
        assert result.val == 30


class TestSomeAndThen:
    def test_some_to_some(self):
        result = Some(10).and_then(lambda x: Some(x + 5))
        assert isinstance(result, Some)
        assert result.val == 15

    def test_some_to_nothing(self):
        result = Some(10).and_then(lambda _: Nothing("gone", "hash123"))
        assert isinstance(result, Nothing)
        assert result.field == "gone"

    def test_chained(self):
        result = Some(1).and_then(lambda x: Some(x + 1)).and_then(lambda x: Some(x + 1))
        assert result.val == 3  # type: ignore[union-attr]


class TestSomeUnwrap:
    def test_unwrap(self):
        assert Some(42).unwrap() == 42

    def test_unwrap_or_returns_value(self):
        assert Some(42).unwrap_or(0) == 42


class TestSomePredicates:
    def test_is_some(self):
        assert Some(1).is_some() is True

    def test_is_nothing(self):
        assert Some(1).is_nothing() is False


class TestSomeRepr:
    def test_repr(self):
        assert repr(Some(42)) == "Some(42)"

    def test_repr_string(self):
        assert repr(Some("hi")) == "Some('hi')"


# -- Nothing -------------------------------------------------------------------


class TestNothingConstruction:
    def test_fields(self):
        n = Nothing(field="balance", step_hash="abcdef12")
        assert n.field == "balance"
        assert n.step_hash == "abcdef12"

    def test_frozen(self):
        n = Nothing(field="x", step_hash="y")
        with pytest.raises(AttributeError):
            n.field = "z"  # type: ignore[misc]


class TestNothingPropagation:
    def test_map_returns_self(self):
        n = Nothing(field="x", step_hash="h")
        assert n.map(lambda v: v * 2) is n

    def test_map_does_not_call_function(self):
        called = []
        n = Nothing(field="x", step_hash="h")
        n.map(lambda v: called.append(v))
        assert called == []

    def test_and_then_returns_self(self):
        n = Nothing(field="x", step_hash="h")
        assert n.and_then(lambda v: Some(v)) is n

    def test_chained_preserves_original(self):
        n = Nothing(field="root_cause", step_hash="original_hash")
        result = n.map(str).map(int).and_then(lambda x: Some(x))
        assert isinstance(result, Nothing)
        assert result.field == "root_cause"
        assert result.step_hash == "original_hash"


class TestNothingUnwrapOr:
    def test_returns_default(self):
        assert Nothing(field="x", step_hash="h").unwrap_or(42) == 42

    def test_returns_default_none(self):
        assert Nothing(field="x", step_hash="h").unwrap_or(None) is None


class TestNothingPredicates:
    def test_is_some(self):
        assert Nothing(field="x", step_hash="h").is_some() is False

    def test_is_nothing(self):
        assert Nothing(field="x", step_hash="h").is_nothing() is True


class TestNothingRaise:
    def test_raises_k3_nothing_exception(self):
        n = Nothing(field="balance", step_hash="deadbeef12345678")
        with pytest.raises(K3NothingException) as exc_info:
            n.raise_()
        assert exc_info.value.field == "balance"
        assert exc_info.value.step_hash == "deadbeef12345678"


class TestNothingRepr:
    def test_repr_format(self):
        n = Nothing(field="balance", step_hash="abcdef1234567890")
        assert repr(n) == "Nothing(field='balance', step=abcdef12)"

    def test_repr_short_hash(self):
        n = Nothing(field="x", step_hash="ab")
        assert "step=ab" in repr(n)


# -- Pattern matching ----------------------------------------------------------


class TestOptionPatternMatching:
    def test_match_some(self):
        opt = Some(42)
        match opt:
            case Some(val=v):
                assert v == 42
            case Nothing():
                pytest.fail("Should not match Nothing")

    def test_match_nothing(self):
        opt = Nothing(field="x", step_hash="h")
        match opt:
            case Some():
                pytest.fail("Should not match Some")
            case Nothing(field=f, step_hash=sh):
                assert f == "x"
                assert sh == "h"

    def test_match_exhaustive(self):
        results = []
        for opt in [Some(1), Nothing("x", "h"), Some("two")]:
            match opt:
                case Some(val=v):
                    results.append(("some", v))
                case Nothing(field=f):
                    results.append(("nothing", f))
        assert results == [("some", 1), ("nothing", "x"), ("some", "two")]
