# k3c.runtime - Application-Facing APIs
"""
K3 Runtime: application-facing APIs for K3 causal systems.

Key exports:
    - Universe -- the main entry point
    - ComposedUniverse -- parallel composition
    - BridgedUniverse -- cross-universe bridging
    - ReduceAllResult -- batch processing result
"""

from k3c.runtime.bridge import (
    BridgedUniverse,
    BridgeMode,
    DeadLetterEntry,
    FallbackStrategy,
    RetryPolicy,
)
from k3c.runtime.compose import Applyable, ComposedUniverse
from k3c.runtime.embedded import EmbeddedRuntime, EmbeddedUniverse
from k3c.runtime.isolate import IsolatedUniverse
from k3c.runtime.parallel import ChunkSource, ParallelReduceResult, parallel_reduce
from k3c.runtime.samsara import (
    ReplayMismatch,
    ReplayResult,
    RunResult,
    TraceRecord,
)
from k3c.runtime.universe import ReduceAllResult, Universe

__all__ = [
    "Universe",
    "ReduceAllResult",
    "ComposedUniverse",
    "Applyable",
    "BridgedUniverse",
    "BridgeMode",
    "FallbackStrategy",
    "RetryPolicy",
    "DeadLetterEntry",
    "EmbeddedRuntime",
    "EmbeddedUniverse",
    "IsolatedUniverse",
    "ChunkSource",
    "ParallelReduceResult",
    "parallel_reduce",
    # Samsara (KC-3)
    "TraceRecord",
    "RunResult",
    "ReplayResult",
    "ReplayMismatch",
]
