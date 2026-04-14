"""Tests for k3c.cache — K3LRU, K3Cache, key helpers."""

from __future__ import annotations

import pytest

from k3c.cache import (
    K3Cache,
    K3LRU,
    eval_cache_key,
    invariant_cache_key,
    ir_cache_key,
    projection_cache_key,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  K3LRU
# ═══════════════════════════════════════════════════════════════════════════════


class TestK3LRUGetPut:
    def test_put_and_get(self):
        c = K3LRU[int](capacity=4)
        c.put("a", 1)
        assert c.get("a") == 1

    def test_get_missing_returns_none(self):
        c = K3LRU[int](capacity=4)
        assert c.get("missing") is None

    def test_put_overwrites_existing_value(self):
        c = K3LRU[str](capacity=4)
        c.put("k", "old")
        c.put("k", "new")
        assert c.get("k") == "new"

    def test_put_multiple_keys(self):
        c = K3LRU[int](capacity=8)
        for i in range(5):
            c.put(str(i), i * 10)
        for i in range(5):
            assert c.get(str(i)) == i * 10


class TestK3LRUEviction:
    def test_evicts_lru_when_full(self):
        c = K3LRU[int](capacity=3)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)
        c.put("d", 4)  # evicts "a"
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("d") == 4

    def test_get_refreshes_lru_order(self):
        c = K3LRU[int](capacity=3)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)
        c.get("a")  # refresh "a" — now "b" is LRU
        c.put("d", 4)  # evicts "b"
        assert c.get("a") == 1
        assert c.get("b") is None

    def test_put_existing_refreshes_lru_order(self):
        c = K3LRU[int](capacity=3)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)
        c.put("a", 10)  # refresh "a" — now "b" is LRU
        c.put("d", 4)  # evicts "b"
        assert c.get("a") == 10
        assert c.get("b") is None

    def test_capacity_one(self):
        c = K3LRU[int](capacity=1)
        c.put("a", 1)
        c.put("b", 2)
        assert c.get("a") is None
        assert c.get("b") == 2

    def test_never_exceeds_capacity(self):
        c = K3LRU[int](capacity=5)
        for i in range(100):
            c.put(str(i), i)
        assert c.stats()["size"] == 5


class TestK3LRUInvalidate:
    def test_invalidate_existing(self):
        c = K3LRU[int](capacity=4)
        c.put("a", 1)
        c.invalidate("a")
        assert c.get("a") is None

    def test_invalidate_missing_is_noop(self):
        c = K3LRU[int](capacity=4)
        c.invalidate("nonexistent")  # should not raise

    def test_invalidate_frees_slot(self):
        c = K3LRU[int](capacity=2)
        c.put("a", 1)
        c.put("b", 2)
        c.invalidate("a")
        c.put("c", 3)  # should not evict "b"
        assert c.get("b") == 2
        assert c.get("c") == 3


class TestK3LRUClear:
    def test_clear_empties_cache(self):
        c = K3LRU[int](capacity=4)
        c.put("a", 1)
        c.put("b", 2)
        c.clear()
        assert c.get("a") is None
        assert c.get("b") is None
        assert c.stats()["size"] == 0

    def test_clear_does_not_reset_stats(self):
        c = K3LRU[int](capacity=4)
        c.put("a", 1)
        c.get("a")
        c.get("miss")
        c.clear()
        assert c.hits == 1
        assert c.misses == 1


class TestK3LRUStats:
    def test_initial_stats(self):
        c = K3LRU[int](capacity=10)
        s = c.stats()
        assert s == {
            "hits": 0,
            "misses": 0,
            "size": 0,
            "capacity": 10,
            "hit_rate": 0.0,
        }

    def test_hit_miss_tracking(self):
        c = K3LRU[int](capacity=4)
        c.put("a", 1)
        c.get("a")  # hit
        c.get("b")  # miss
        c.get("a")  # hit
        assert c.hits == 2
        assert c.misses == 1

    def test_hit_rate_calculation(self):
        c = K3LRU[int](capacity=4)
        c.put("a", 1)
        c.get("a")  # hit
        c.get("b")  # miss
        assert c.hit_rate == pytest.approx(0.5)

    def test_hit_rate_zero_when_no_accesses(self):
        c = K3LRU[int](capacity=4)
        assert c.hit_rate == 0.0

    def test_hit_rate_one_when_all_hits(self):
        c = K3LRU[int](capacity=4)
        c.put("a", 1)
        c.get("a")
        c.get("a")
        c.get("a")
        assert c.hit_rate == pytest.approx(1.0)

    def test_stats_size_tracks_current_entries(self):
        c = K3LRU[int](capacity=4)
        c.put("a", 1)
        c.put("b", 2)
        assert c.stats()["size"] == 2
        c.invalidate("a")
        assert c.stats()["size"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  K3Cache
# ═══════════════════════════════════════════════════════════════════════════════


class TestK3CacheConstruction:
    def test_default_construction(self):
        cache = K3Cache()
        assert isinstance(cache.lang_eval, K3LRU)
        assert isinstance(cache.spec_invariant, K3LRU)
        assert isinstance(cache.spec_projection, K3LRU)

    def test_instances_are_independent(self):
        a = K3Cache()
        b = K3Cache()
        a.lang_eval.put("k", "v")
        assert b.lang_eval.get("k") is None

    def test_lang_compiled_is_shared(self):
        a = K3Cache()
        b = K3Cache()
        assert a.lang_compiled is b.lang_compiled
        assert a.lang_compiled is K3Cache.lang_compiled


class TestK3CacheStats:
    def test_stats_contains_all_layers(self):
        cache = K3Cache()
        s = cache.stats()
        assert "lang_eval" in s
        assert "spec_invariant" in s
        assert "spec_projection" in s
        assert "compiled_spec" in s

    def test_stats_reflects_usage(self):
        cache = K3Cache()
        cache.lang_eval.put("k", "v")
        cache.lang_eval.get("k")
        s = cache.stats()
        assert s["lang_eval"]["size"] == 1
        assert s["lang_eval"]["hits"] == 1


class TestK3CacheClear:
    def test_clear_empties_instance_caches(self):
        cache = K3Cache()
        cache.lang_eval.put("a", 1)
        cache.spec_invariant.put("b", 2)
        cache.spec_projection.put("c", 3)
        cache.clear()
        assert cache.lang_eval.get("a") is None
        assert cache.spec_invariant.get("b") is None
        assert cache.spec_projection.get("c") is None

    def test_clear_does_not_touch_compiled_by_default(self):
        K3Cache.lang_compiled.put("spec_x", "compiled_data")
        cache = K3Cache()
        cache.clear()
        assert K3Cache.lang_compiled.get("spec_x") == "compiled_data"
        # cleanup
        K3Cache.lang_compiled.invalidate("spec_x")

    def test_clear_with_include_compiled(self):
        K3Cache.lang_compiled.put("spec_y", "compiled_data")
        cache = K3Cache()
        cache.clear(include_compiled=True)
        assert K3Cache.lang_compiled.get("spec_y") is None


# ═══════════════════════════════════════════════════════════════════════════════
#  Key construction helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvalCacheKey:
    def test_deterministic(self):
        a = eval_cache_key("expr1", "hash1234567890ab")
        b = eval_cache_key("expr1", "hash1234567890ab")
        assert a == b

    def test_different_expr_different_key(self):
        a = eval_cache_key("expr_a", "same_hash")
        b = eval_cache_key("expr_b", "same_hash")
        assert a != b

    def test_different_step_hash_different_key(self):
        a = eval_cache_key("same_expr", "hash_a_longenough")
        b = eval_cache_key("same_expr", "hash_b_longenough")
        assert a != b

    def test_step_hash_truncated_to_16(self):
        key = eval_cache_key("e", "a" * 64)
        _, step_part = key.split(":")
        assert len(step_part) == 16

    def test_format_is_colon_separated(self):
        key = eval_cache_key("x", "y" * 16)
        assert ":" in key
        parts = key.split(":")
        assert len(parts) == 2


class TestInvariantCacheKey:
    def test_returns_step_hash_as_is(self):
        assert invariant_cache_key("abc123") == "abc123"

    def test_deterministic(self):
        assert invariant_cache_key("x") == invariant_cache_key("x")


class TestProjectionCacheKey:
    def test_deterministic(self):
        state = {"balance": 100}
        a = projection_cache_key(state, "total")
        b = projection_cache_key(state, "total")
        assert a == b

    def test_different_state_different_key(self):
        a = projection_cache_key({"x": 1}, "proj")
        b = projection_cache_key({"x": 2}, "proj")
        assert a != b

    def test_different_proj_name_different_key(self):
        state = {"x": 1}
        a = projection_cache_key(state, "proj_a")
        b = projection_cache_key(state, "proj_b")
        assert a != b

    def test_key_order_independent(self):
        a = projection_cache_key({"a": 1, "b": 2}, "p")
        b = projection_cache_key({"b": 2, "a": 1}, "p")
        assert a == b

    def test_format_is_colon_separated(self):
        key = projection_cache_key({"x": 1}, "proj")
        parts = key.split(":")
        assert len(parts) == 2
        assert parts[1] == "proj"


class TestIrCacheKey:
    def test_deterministic(self):
        ir = {"permits": [], "maintains": []}
        a = ir_cache_key(ir)
        b = ir_cache_key(ir)
        assert a == b

    def test_different_ir_different_key(self):
        a = ir_cache_key({"permits": []})
        b = ir_cache_key({"permits": ["rule1"]})
        assert a != b

    def test_key_order_independent(self):
        a = ir_cache_key({"a": 1, "b": 2})
        b = ir_cache_key({"b": 2, "a": 1})
        assert a == b

    def test_returns_full_sha256(self):
        key = ir_cache_key({"x": 1})
        assert len(key) == 64
        int(key, 16)  # valid hex
