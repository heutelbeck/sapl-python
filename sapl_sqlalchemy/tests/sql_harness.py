"""Shared harness for the SQLAlchemy shim integration tests.

Every shim test drives the real enforcement path: a stubbed PDP decision flows
through ``pre_enforce`` -> the planner -> a real ``ConstraintHandlerProvider`` ->
the registered ORM listener. No test constructs an ``EnforcementPlan`` by hand;
the planner alone decides whether an obligation is dischargeable.

``DropMapperProvider`` and ``IdentityMapperProvider`` are deliberately
non-rewriting providers used to exercise the listener's contract branches (a
handler that returns DROP, a handler that returns the statement unchanged)
through the real planner, which the real ``SqlQueryManipulationProvider`` cannot
produce.
"""

from __future__ import annotations

from typing import Any

from sapl_base.pep import DROP, ScopedHandler
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision

from sapl_sqlalchemy import SQL_QUERY, SqlQueryManipulationProvider

SUBSCRIPTION = AuthorizationSubscription(subject="s", action="read", resource="patient")

BAD_OPERATOR_OBLIGATION: dict[str, Any] = {
    "type": "sql:queryManipulation",
    "criteria": [{"column": "tenant_id", "op": "BOGUS", "value": 1}],
}
DROP_OBLIGATION: dict[str, Any] = {"type": "test:drop"}
IDENTITY_OBLIGATION: dict[str, Any] = {"type": "test:identity"}


def tenant_obligation(value: int) -> dict[str, Any]:
    return {
        "type": "sql:queryManipulation",
        "criteria": [{"column": "tenant_id", "op": "=", "value": value}],
    }


def permit(*obligations: Any) -> AuthorizationDecision:
    return AuthorizationDecision(decision=Decision.PERMIT, obligations=tuple(obligations))


def default_providers() -> tuple[SqlQueryManipulationProvider]:
    return (SqlQueryManipulationProvider(),)


class StubPdp:
    """A PDP that always returns one configured decision."""

    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: Any) -> AuthorizationDecision:
        return self._decision


class DropMapperProvider:
    """Non-conforming provider whose SQL_QUERY mapper returns DROP (a contract violation)."""

    def get_handlers(self, constraint: Any) -> tuple[ScopedHandler, ...]:
        if isinstance(constraint, dict) and constraint.get("type") == "test:drop":
            return (ScopedHandler(signal=SQL_QUERY, priority=30, shape="mapper", handler=lambda _stmt: DROP),)
        return ()


class IdentityMapperProvider:
    """Provider whose SQL_QUERY mapper returns the statement unchanged."""

    def get_handlers(self, constraint: Any) -> tuple[ScopedHandler, ...]:
        if isinstance(constraint, dict) and constraint.get("type") == "test:identity":
            return (ScopedHandler(signal=SQL_QUERY, priority=30, shape="mapper", handler=lambda stmt: stmt),)
        return ()
