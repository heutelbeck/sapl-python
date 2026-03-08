"""Gate-level constraint enforcement for SAPL decisions.

This module handles ON_DECISION constraint handlers only. It is used for
binary allow/deny checks in the listing filter and auth= path. The full
constraint lifecycle (method invocation, resource replacement, filter
predicates, error mapping) is handled by ``sapl_base.enforcement`` via
the middleware access path.
"""

import logging
from collections.abc import Callable

from sapl_base import AuthorizationDecision, Decision
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.constraint_types import Signal

logger = logging.getLogger("sapl.mcp")


def enforce_decision_gate(
    service: ConstraintEnforcementService,
    decision: AuthorizationDecision,
) -> bool:
    """Run ON_DECISION constraint handlers and return a binary allow/deny.

    Gate-level enforcement for listing filters and auth= checks. Only
    ON_DECISION handlers execute here; there is no resource replacement,
    argument modification, or error mapping. For the full constraint
    lifecycle, see ``sapl_base.enforcement.pre_enforce`` /
    ``post_enforce`` used in the middleware access path.

    Runs all matched handlers without short-circuiting so that audit and
    logging handlers always fire regardless of earlier failures.

    Obligations are strict: unhandled obligations, handler failures, or a
    resource replacement field all force denial. Advice is best-effort:
    unhandled advice is ignored, handler failures are logged but do not
    affect the outcome.

    Returns True only when the decision is PERMIT and all obligations
    are satisfied. Returns False for DENY or any obligation failure.
    """
    deny = False

    if decision.has_resource:
        logger.warning("DENY: resource replacement not supported in auth scope")
        deny = True

    obligation_handlers = _collect_decision_handlers(service, decision.obligations)
    if obligation_handlers.has_unhandled:
        logger.warning(
            "DENY: unhandled obligations in auth scope: %s",
            obligation_handlers.unhandled,
        )
        deny = True

    for handler in obligation_handlers.matched:
        try:
            handler()
        except Exception:
            logger.error("DENY: obligation handler failed", exc_info=True)
            deny = True

    advice_handlers = _collect_decision_handlers(service, decision.advice)
    for handler in advice_handlers.matched:
        try:
            handler()
        except Exception:
            logger.warning("Advice handler failed (ignored)", exc_info=True)

    if deny:
        return False
    return decision.decision == Decision.PERMIT


class _CollectedHandlers:
    """Result of scanning constraints against registered providers."""

    __slots__ = ("matched", "unhandled")

    def __init__(
        self,
        matched: list[Callable[[], None]],
        unhandled: list[object],
    ) -> None:
        self.matched = matched
        self.unhandled = unhandled

    @property
    def has_unhandled(self) -> bool:
        return bool(self.unhandled)


def _collect_decision_handlers(
    service: ConstraintEnforcementService,
    constraints: list[object] | None,
) -> _CollectedHandlers:
    """Match constraints to ON_DECISION runnable providers, return handlers and gaps."""
    matched: list[Callable[[], None]] = []
    unhandled: list[object] = []
    if not constraints:
        return _CollectedHandlers(matched, unhandled)

    for constraint in constraints:
        handlers = service.get_runnable_handlers(constraint, Signal.ON_DECISION)
        if handlers:
            matched.extend(handlers)
        else:
            unhandled.append(constraint)

    return _CollectedHandlers(matched, unhandled)
