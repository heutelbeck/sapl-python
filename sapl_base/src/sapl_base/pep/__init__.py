"""Policy Enforcement Point layer.

Public surface: the constraint-handler-provider Protocol, the plan
and planner, the boundary signal types, the subscription context,
the open signal taxonomy, and the one-shot enforcement helpers
together with their signal kinds and signal dataclasses.
"""

from sapl_base.pep.boundary_signals import (
    AccessDeniedError,
    AccessGrantedSignal,
    AccessSuspendedSignal,
)
from sapl_base.pep.plan import (
    ABSENT,
    DROP,
    EnforcementPlan,
    PlanEntry,
    PlanResult,
)
from sapl_base.pep.enforce import (
    DECISION,
    ERROR,
    INPUT,
    OUTPUT,
    POST_ENFORCE_SUPPORTED,
    PRE_ENFORCE_SUPPORTED,
    DecisionSignal,
    ErrorSignal,
    InputSignal,
    OutputSignal,
    post_enforce,
    pre_enforce,
)
from sapl_base.pep.planner import EnforcementPlanner
from sapl_base.pep.runtime import PepRuntime
from sapl_base.pep.shim_signals import (
    register_shim_signal,
    shim_signals,
    unregister_shim_signal,
)
from sapl_base.pep.provider import (
    ConstraintHandlerProvider,
    ConstraintTag,
    HandlerShape,
    ScopedHandler,
)
from sapl_base.pep.signal import Signal, SignalKind
from sapl_base.pep.subscription_context import SubscriptionContext
from sapl_base.pep.transaction import (
    SyncTransactionProvider,
    TransactionProvider,
    from_sync_context,
    transaction_scope,
    transaction_scope_sync,
)

__all__ = [
    "ABSENT",
    "AccessDeniedError",
    "AccessGrantedSignal",
    "AccessSuspendedSignal",
    "ConstraintHandlerProvider",
    "ConstraintTag",
    "DECISION",
    "DROP",
    "DecisionSignal",
    "ERROR",
    "EnforcementPlan",
    "EnforcementPlanner",
    "ErrorSignal",
    "HandlerShape",
    "INPUT",
    "InputSignal",
    "OUTPUT",
    "OutputSignal",
    "POST_ENFORCE_SUPPORTED",
    "PRE_ENFORCE_SUPPORTED",
    "PepRuntime",
    "PlanEntry",
    "PlanResult",
    "ScopedHandler",
    "Signal",
    "SignalKind",
    "SubscriptionContext",
    "SyncTransactionProvider",
    "TransactionProvider",
    "from_sync_context",
    "post_enforce",
    "pre_enforce",
    "register_shim_signal",
    "shim_signals",
    "transaction_scope",
    "transaction_scope_sync",
    "unregister_shim_signal",
]
