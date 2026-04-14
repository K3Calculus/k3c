# k3c.universe — The Engine Layer
"""
K3.Calc: execution engine for K3 causal systems.

Key exports:
    - universe() factory + Universe class
    - parallel_reduce() for chunked processing
    - ComposedUniverse (<||>) + BridgedUniverse (<->)
    - IsolatedUniverse for physical isolation
    - BridgeMode, RetryPolicy, FallbackStrategy
    - fuzz() for property-based testing
    - explain() for dry-run debugging
"""

from k3c.universe.bridge import BridgedUniverse
from k3c.universe.compose import Applyable, ComposedUniverse
from k3c.universe.explain import ExplainResult, TraceEntry, TracePhase, TraceVerdict
from k3c.universe.fuzz import FuzzReport, FuzzViolation
from k3c.universe.isolate import IsolatedUniverse
from k3c.universe.retry import (
    BridgeMode,
    DeadLetterEntry,
    FallbackStrategy,
    RetryPolicy,
)
from k3c.universe.universe import (
    ParallelReduceResult,
    ReduceAllResult,
    System,
    Universe,
    parallel_reduce,
    universe,
)

__all__ = [
    "universe",
    "Universe",
    "System",
    "IsolatedUniverse",
    "parallel_reduce",
    "ParallelReduceResult",
    "ReduceAllResult",
    "ComposedUniverse",
    "BridgedUniverse",
    "Applyable",
    "BridgeMode",
    "RetryPolicy",
    "FallbackStrategy",
    "DeadLetterEntry",
    "FuzzReport",
    "FuzzViolation",
    "ExplainResult",
    "TraceEntry",
    "TracePhase",
    "TraceVerdict",
]
