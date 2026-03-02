from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from sapl_base.constraint_bundle import AccessDeniedError
from sapl_base.constraint_types import MethodInvocationContext
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sapl_base.constraint_engine import ConstraintEnforcementService
    from sapl_base.pdp_client import PdpClient

log = structlog.get_logger()

ERROR_ACCESS_DENIED = "Access denied"
ERROR_OBLIGATION_FAILED = "Obligation handler failed during enforcement"
ERROR_PROTECTED_METHOD_FAILED = "Protected method raised an exception"
WARN_BEST_EFFORT_FAILED = "Best-effort handlers failed on deny path"
WARN_ON_DENY_CALLBACK_FAILED = "onDeny callback raised an exception"


async def pre_enforce(
    pdp_client: PdpClient,
    constraint_service: ConstraintEnforcementService,
    subscription: AuthorizationSubscription,
    protected_function: Callable[..., Awaitable[Any]],
    args: list[Any],
    kwargs: dict[str, Any],
    function_name: str,
    on_deny: Callable[[AuthorizationDecision], Any] | None = None,
    class_name: str = "",
    request: Any = None,
) -> Any:
    """PreEnforce: authorize BEFORE method execution.

    Flow (Section 7.1):
    1. Call pdpClient.decide_once(subscription)
    2. If not PERMIT -> deny path
    3. Resolve constraint handlers (deny if unhandled obligation)
    4. Execute on-decision handlers
    5. Execute method-invocation handlers (may modify args/kwargs)
    6. Execute protected method
    7. Apply return-value handlers (resource -> filter -> consumer -> mapping)
    8. If obligation handler fails -> deny

    Args:
        pdp_client: PDP client for authorization queries.
        constraint_service: Service for resolving constraint handlers.
        subscription: The authorization subscription to evaluate.
        protected_function: The async function to protect.
        args: Positional arguments for the protected function.
        kwargs: Keyword arguments for the protected function.
        function_name: Name of the protected function (for context).
        on_deny: Optional callback invoked on deny (REQ-ERROR-1/2/3).
        class_name: Qualified class name (empty for plain functions).
        request: Framework request object, or None for service-layer calls.

    Returns:
        The (possibly transformed) result of the protected function.

    Raises:
        AccessDeniedError: When access is denied and no on_deny callback.
    """
    decision = await pdp_client.decide_once(subscription)

    if decision.decision != Decision.PERMIT:
        return await _handle_deny(decision, constraint_service, on_deny)

    # Resolve handlers - deny if unhandled obligation (REQ-OBLIGATION-1)
    try:
        bundle = constraint_service.pre_enforce_bundle_for(decision)
    except AccessDeniedError:
        log.error(ERROR_OBLIGATION_FAILED, decision=decision.decision.value)
        return await _handle_deny(decision, constraint_service, on_deny)

    # Execute on-decision handlers
    try:
        bundle.handle_on_decision_constraints()
    except AccessDeniedError:
        log.error(ERROR_OBLIGATION_FAILED)
        return await _handle_deny(decision, constraint_service, on_deny)

    # Execute method-invocation handlers (may modify args/kwargs)
    context = MethodInvocationContext(
        args=list(args), kwargs=dict(kwargs), function_name=function_name,
        class_name=class_name, request=request,
    )
    try:
        bundle.handle_method_invocation_handlers(context)
    except AccessDeniedError:
        log.error(ERROR_OBLIGATION_FAILED)
        return await _handle_deny(decision, constraint_service, on_deny)

    # Execute protected method with potentially modified args/kwargs
    try:
        result = await protected_function(*context.args, **context.kwargs)
    except Exception as error:
        # REQ-ERROR-4: method errors go through error handlers, then re-raise
        transformed_error = bundle.handle_all_on_error_constraints(error)
        raise transformed_error from error

    # Apply return-value handlers
    try:
        result = bundle.handle_all_on_next_constraints(result)
    except AccessDeniedError:
        log.error(ERROR_OBLIGATION_FAILED)
        return await _handle_deny(decision, constraint_service, on_deny)

    return result


async def post_enforce(
    pdp_client: PdpClient,
    constraint_service: ConstraintEnforcementService,
    subscription_builder: Callable[[Any], AuthorizationSubscription],
    protected_function: Callable[..., Awaitable[Any]],
    args: list[Any],
    kwargs: dict[str, Any],
    function_name: str,
    on_deny: Callable[[AuthorizationDecision], Any] | None = None,
    class_name: str = "",
    request: Any = None,
) -> Any:
    """PostEnforce: authorize AFTER method execution.

    Flow (Section 7.2):
    1. Execute protected method FIRST (no auth yet)
    2. Build subscription (includes return value)
    3. Call pdpClient.decide_once(subscription)
    4. If not PERMIT -> deny
    5. Resolve constraint handlers
    6. Execute on-decision handlers
    7. Apply return-value handlers (NO method-invocation handlers)
    8. Return result

    Note: subscription_builder is a callable that takes the return value and
    produces an AuthorizationSubscription. This allows the subscription to
    include the return value for policy decisions.

    Args:
        pdp_client: PDP client for authorization queries.
        constraint_service: Service for resolving constraint handlers.
        subscription_builder: Builds a subscription from the method return value.
        protected_function: The async function to protect.
        args: Positional arguments for the protected function.
        kwargs: Keyword arguments for the protected function.
        function_name: Name of the protected function (for context).
        on_deny: Optional callback invoked on deny (REQ-ERROR-1/2/3).
        class_name: Qualified class name (empty for plain functions).
        request: Framework request object, or None for service-layer calls.

    Returns:
        The (possibly transformed) result of the protected function.

    Raises:
        AccessDeniedError: When access is denied and no on_deny callback.
    """
    # Step 1: Execute method first (F17: if method throws, propagate directly)
    result = await protected_function(*args, **kwargs)

    # Step 2: Build subscription with return value
    subscription = subscription_builder(result)

    # Step 3: Query PDP
    decision = await pdp_client.decide_once(subscription)

    if decision.decision != Decision.PERMIT:
        return await _handle_deny(decision, constraint_service, on_deny)

    # PostEnforce uses post_enforce_bundle (no method invocation handlers)
    try:
        bundle = constraint_service.post_enforce_bundle_for(decision)
    except AccessDeniedError:
        log.error(ERROR_OBLIGATION_FAILED)
        return await _handle_deny(decision, constraint_service, on_deny)

    try:
        bundle.handle_on_decision_constraints()
    except AccessDeniedError:
        log.error(ERROR_OBLIGATION_FAILED)
        return await _handle_deny(decision, constraint_service, on_deny)

    # NO method invocation handlers for PostEnforce

    try:
        result = bundle.handle_all_on_next_constraints(result)
    except AccessDeniedError:
        log.error(ERROR_OBLIGATION_FAILED)
        return await _handle_deny(decision, constraint_service, on_deny)

    return result


async def _handle_deny(
    decision: AuthorizationDecision,
    constraint_service: ConstraintEnforcementService,
    on_deny: Callable[[AuthorizationDecision], Any] | None,
) -> Any:
    """Handle deny path. REQ-DENY-BESTEFF-1, REQ-ERROR-1/2/3.

    1. Build best-effort bundle and execute handlers (audit, logging).
    2. If on_deny callback: invoke it and return its result.
    3. Otherwise: raise AccessDeniedError.
    """
    # Best-effort handlers on deny path (e.g., audit logging)
    try:
        best_effort_bundle = constraint_service.best_effort_bundle_for(decision)
        best_effort_bundle.handle_on_decision_constraints()
    except Exception:
        log.warning(WARN_BEST_EFFORT_FAILED)

    if on_deny is not None:
        try:
            return on_deny(decision)
        except Exception:
            # F19: onDeny callback throws -> WARN + default deny
            log.warning(WARN_ON_DENY_CALLBACK_FAILED)

    raise AccessDeniedError(ERROR_ACCESS_DENIED)
