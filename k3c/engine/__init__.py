# k3c.engine - The Causal Step Engine
"""
K3 Engine: deterministic causal step execution.

Key exports:
    - apply_step() -- the pure causal step function
    - SpecCtx -- the ambient witness
    - Ok, Impossible, Violated -- step results
    - Why, WhyKind -- failure explanation
    - StepResult -- the result union type
    - TransitionFn -- the user-supplied transition function type
"""

from k3c.engine.ctx import SpecCtx, TimerTickResult
from k3c.engine.explain import (
    ExplainResult,
    TraceEntry,
    TracePhase,
    TraceVerdict,
    explain,
)
from k3c.engine.result import Impossible, Ok, StepResult, Violated, Why, WhyKind
from k3c.engine.step import TransitionFn, apply_step

__all__ = [
    "apply_step",
    "TransitionFn",
    "SpecCtx",
    "TimerTickResult",
    "Ok",
    "Impossible",
    "Violated",
    "Why",
    "WhyKind",
    "StepResult",
    "ExplainResult",
    "TraceEntry",
    "TracePhase",
    "TraceVerdict",
    "explain",
]
