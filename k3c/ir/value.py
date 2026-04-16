# k3c/ir/value.py
"""
Option[T] = Some(T) | Nothing

The return type of eval(). Always a value. Never raises. Never None.

Design principles:
  1. Nothing carries context  - field (which was absent) and step_hash
     (which apply() call produced this). The audit trail is unbroken.
  2. Nothing propagates       - through And, Or, Compare, Arith, Field, etc.
     Like NaN in IEEE 754: one Nothing anywhere in the expression tree
     makes the whole expression Nothing.
  3. IsSome absorbs Nothing   - always returns Some(True|False). The one
     operation that converts Nothing to a boolean cleanly.
  4. UnwrapOr recovers        - Nothing becomes the default. Safe extraction.
  5. raise_() is caller opt-in - eval() never calls it. Only the client
     calls it when it decides an absent field is fatal.

Relation to StepResult:
  Option     is the eval() level - value expressions, field access, guards
  StepResult is the apply() level - causal steps, invariants, liveness
  Nothing    at the apply() boundary -> Impossible(Why(kind='missing'))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Generic, Never, TypeVar

from k3c.errors import K3NothingException

if TYPE_CHECKING:
    from typing import Any

T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True)
class Some(Generic[T]):
    """
    A present value. eval() found what it was looking for.

    Frozen - immutable, hashable, safe across the causal step.
    Generic over T so the type checker knows what val contains.
    """

    val: T

    def map(self, f: Callable[[T], U]) -> Some[U]:
        """Transform the value. Always returns Some."""
        return Some(f(self.val))

    def and_then(self, f: Callable[[T], K3Option[U]]) -> K3Option[U]:
        """Chain an operation that may itself return Nothing."""
        return f(self.val)

    def unwrap(self) -> T:
        """Extract the value. Safe - Some always has a value."""
        return self.val

    def unwrap_or(self, default: T) -> T:
        """Extract or use default. Always returns the value for Some."""
        return self.val

    def is_some(self) -> bool:
        return True

    def is_nothing(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"Some({self.val!r})"


@dataclass(frozen=True)
class Nothing:
    """
    An absent value. eval() could not resolve the expression.

    Carries field and step_hash so the audit trail is preserved when
    this Nothing surfaces at the apply() boundary and becomes
    Impossible(Why(kind='missing', ...)).

    Propagation rule: any operation on Nothing returns Nothing with
    the ORIGINAL field and step_hash - the first absence in a chain
    is the root cause.
    """

    field: str
    step_hash: str

    def map(self, f: Callable[..., object]) -> Nothing:
        """Nothing propagates - f is never called."""
        return self

    def and_then(self, f: Callable[..., object]) -> Nothing:
        """Nothing propagates - f is never called."""
        return self

    def unwrap_or(self, default: Any) -> Any:
        """Recover with a default."""
        return default

    def is_some(self) -> bool:
        return False

    def is_nothing(self) -> bool:
        return True

    def raise_(self) -> Never:
        """
        Escalate to K3NothingException.

        Never called by eval(). Never called by apply().
        Only called by client code that decides an absent field is fatal.
        """
        raise K3NothingException(
            field=self.field,
            step_hash=self.step_hash,
        )

    def __repr__(self) -> str:
        return f"Nothing(field={self.field!r}, step={self.step_hash[:8]})"


type K3Option[T] = Some[T] | Nothing
