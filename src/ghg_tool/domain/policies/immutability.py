"""Domain policy: immutability invariants.

Raises ``ImmutabilityViolationError`` if any in-memory mutation of an
append-only domain entity is attempted.  Defence-in-depth alongside the
PostgreSQL ``deny_emissions_mutation`` trigger.

No framework imports.
"""

from __future__ import annotations


class ImmutabilityViolationError(Exception):
    """Raised when a mutation of an immutable domain entity is attempted."""


def assert_no_mutation(entity_name: str, attempted_field: str) -> None:
    """Raise ImmutabilityViolationError for any attempted mutation.

    Intended to be called from ``__setattr__`` or equivalent in domain
    entities that must be immutable in-memory (complementing DB trigger).

    Args:
        entity_name: Name of the entity class (for error message).
        attempted_field: Field whose mutation was attempted.

    Raises:
        ImmutabilityViolationError: Always.
    """
    raise ImmutabilityViolationError(
        f"Mutation of {entity_name}.{attempted_field} is forbidden. "
        "Use correction-as-new-row workflow (FR-21 / calc.fn_emit_correction)."
    )
