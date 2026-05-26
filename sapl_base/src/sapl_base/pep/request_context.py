"""ContextVar that carries the active EnforcementPlan across an awaited call chain.

The PEP entry points (`pre_enforce`, `post_enforce`) set the plan before
invoking the protected method and reset it after. Shim packages
(`sapl_sqlalchemy`, future siblings) read it when a host event fires
inside the wrapped invocation.

Greenlet-bridged libraries that copy `contextvars.Context` into a
worker (SQLAlchemy's asyncio bridge does this) observe the value
without further wiring.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from sapl_base.pep.plan import EnforcementPlan

_current_plan: ContextVar[EnforcementPlan | None] = ContextVar(
    "sapl_current_plan", default=None
)


def current_plan() -> EnforcementPlan | None:
    return _current_plan.get()


def set_current_plan(plan: EnforcementPlan | None) -> Token[EnforcementPlan | None]:
    return _current_plan.set(plan)


def reset_current_plan(token: Token[EnforcementPlan | None]) -> None:
    _current_plan.reset(token)
