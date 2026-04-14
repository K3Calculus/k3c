# k3c/cache.py
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import ClassVar, Generic, TypeVar

T = TypeVar("T")


# ── LRU cache — bounded, thread-safe enough for synchronous engine ────────────
class K3LRU(Generic[T]):
    """Bounded LRU cache. Fixed capacity. O(1) get/put via OrderedDict."""

    def __init__(self, capacity: int = 256):
        self._cap = capacity
        self._data: OrderedDict[str, T] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> T | None:
        if key not in self._data:
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return self._data[key]

    def put(self, key: str, value: T) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        if len(self._data) > self._cap:
            self._data.popitem(last=False)  # evict LRU

    def invalidate(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def stats(self) -> dict[str, object]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self._data),
            "capacity": self._cap,
            "hit_rate": round(self.hit_rate, 3),
        }


# ── Per-layer cache containers ────────────────────────────────────────────────
@dataclass
class K3Cache:
    """
    Cache layer for k3c. Lives on CompiledSpec — one cache per Universe.
    All keys are content-addressed hashes — correctness cannot be affected
    by eviction. The cache is a pure optimisation.

    Layer structure mirrors the package structure:
      lang_eval      → eval() results  keyed on (expr_hash, step_hash)
      spec_invariant → N results       keyed on step_hash
      spec_projection→ P(s) results    keyed on (state_hash, proj_name)
      universe_spec  → CompiledSpec    keyed on ir_hash  [process-level]
    """

    # k3c.lang — eval() result cache
    # Key: SHA-256[:16](expr repr) + ':' + step_hash[:16]
    lang_eval: K3LRU = field(default_factory=lambda: K3LRU(512))

    # k3c.specs — invariant check cache
    # Key: step_hash  (uniquely identifies the (prev_state, new_state, event) triple)
    spec_invariant: K3LRU = field(default_factory=lambda: K3LRU(256))

    # k3c.specs — projection cache
    # Key: state_hash + ':' + projection_name
    spec_projection: K3LRU = field(default_factory=lambda: K3LRU(256))

    # k3c.lang — compiled AST cache
    # Key: SHA-256(json.dumps(k3l_ir, sort_keys=True))
    # Shared across all Universes in the process — class-level
    lang_compiled: ClassVar[K3LRU] = K3LRU(capacity=64)

    def stats(self) -> dict[str, object]:
        return {
            "lang_eval": self.lang_eval.stats(),
            "spec_invariant": self.spec_invariant.stats(),
            "spec_projection": self.spec_projection.stats(),
            "compiled_spec": K3Cache.lang_compiled.stats(),
        }

    def clear(self, include_compiled: bool = False) -> None:
        self.lang_eval.clear()
        self.spec_invariant.clear()
        self.spec_projection.clear()
        if include_compiled:
            K3Cache.lang_compiled.clear()


# ── Key construction helpers ──────────────────────────────────────────────────
def eval_cache_key(expr: object, step_hash: str) -> str:
    expr_hash = hashlib.sha256(repr(expr).encode()).hexdigest()[:16]
    return f"{expr_hash}:{step_hash[:16]}"


def invariant_cache_key(step_hash: str) -> str:
    return step_hash  # step_hash already uniquely identifies the inputs


def projection_cache_key(state: dict[str, object], proj_name: str) -> str:
    state_hash = hashlib.sha256(
        json.dumps(state, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return f"{state_hash}:{proj_name}"


def ir_cache_key(ir: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(ir, sort_keys=True).encode()).hexdigest()
