"""Hypothesis-based property tests for calc invariants.

Covers:
  * GWP enforcement (no mixed AR6/AR5 within a correlation_id)
  * MB ≤ LB invariant for (site, year)
  * Non-negativity of tco2e
  * Mass conservation for Scope 1 process (stoichiometric)
  * Biogenic split coherence (ADR-007)
"""
