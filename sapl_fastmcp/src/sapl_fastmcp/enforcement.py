"""Gate-level constraint enforcement for SAPL decisions.

This module handles DECISION-signal constraint handlers only. It is used
for binary allow/deny checks in the listing filter and the auth= path.
The full constraint lifecycle (input transformation, output mapping,
error mapping) is handled by ``sapl_base.pep`` via the middleware
access path.
"""

from __future__ import annotations

import logging

from sapl_base.pep import DECISION, DecisionSignal, EnforcementPlanner
from sapl_base.types import AuthorizationDecision, Decision

logger = logging.getLogger("sapl.mcp")

_DECISION_ONLY = frozenset({DECISION})


def enforce_decision_gate(
    planner: EnforcementPlanner,
    decision: AuthorizationDecision,
) -> bool:
    """Run DECISION-signal constraint handlers and return a binary allow/deny.

    Gate-level enforcement for listing filters and the auth= check.
    Builds a DECISION-only plan from the configured providers and runs
    it against the decision signal. Returns True iff:

    - the decision verb is PERMIT, AND
    - no obligation handler raised, AND
    - there is no resource replacement (resource replacement is not
      meaningful at the auth scope).

    A constraint with no provider claim, an ambiguous claim, or a claim
    that is inadmissible at DECISION (e.g. an OUTPUT mapper) produces a
    synthetic failure runner at DECISION and forces denial. Advice
    failures are logged but do not affect the outcome.
    """
    if decision.has_resource:
        logger.warning("DENY: resource replacement not supported in auth scope")
        return False

    plan = planner.plan(decision, _DECISION_ONLY)
    result = plan.execute(DecisionSignal(decision=decision))

    if result.failure_state:
        return False
    return decision.decision == Decision.PERMIT
