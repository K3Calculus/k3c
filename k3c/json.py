# k3c/json.py
"""
Configurable JSON serialization — auto-detects orjson for performance.

Priority:
  1. orjson (5-10x faster, pip install orjson)
  2. stdlib json (zero dependencies, always available)

Usage:
    from k3c.json import dumps, loads

    dumps({"key": "value"})          # sorted keys, default=str
    loads(b'{"key": "value"}')       # standard parse
"""

from __future__ import annotations

import json as _json
from typing import Any

# ── Auto-detect orjson ──────────────────────────────────────────────────────

_USE_ORJSON = False
try:
    import orjson as _orjson  # type: ignore[import-untyped]

    _USE_ORJSON = True
except ImportError:
    _orjson = None  # type: ignore[assignment]


# ── Public API ──────────────────────────────────────────────────────────────


def dumps(obj: Any, *, sort_keys: bool = True) -> bytes:
    """Serialize to JSON bytes. Uses orjson if available."""
    if _USE_ORJSON:
        flags = _orjson.OPT_SORT_KEYS if sort_keys else 0
        flags |= _orjson.OPT_NON_STR_KEYS
        try:
            return _orjson.dumps(obj, option=flags, default=_default)
        except TypeError:
            # Fallback for types orjson can't handle (e.g. >64-bit ints)
            return _json.dumps(obj, sort_keys=sort_keys, default=str).encode()
    return _json.dumps(obj, sort_keys=sort_keys, default=str).encode()


def dumps_str(obj: Any, *, sort_keys: bool = True) -> str:
    """Serialize to JSON string. Uses orjson if available."""
    return dumps(obj, sort_keys=sort_keys).decode()


def loads(data: bytes | str) -> Any:
    """Deserialize from JSON."""
    if _USE_ORJSON:
        return _orjson.loads(data)
    return _json.loads(data)


def dumps_pretty(obj: Any, *, indent: int = 2) -> str:
    """Serialize to pretty-printed JSON string. Always uses stdlib for formatting."""
    return _json.dumps(obj, indent=indent, sort_keys=False, default=str)


def _default(obj: Any) -> Any:
    """Default serializer for types orjson doesn't handle natively."""
    return str(obj)


# ── Info ────────────────────────────────────────────────────────────────────


def backend() -> str:
    """Return which JSON backend is active."""
    return "orjson" if _USE_ORJSON else "stdlib"
