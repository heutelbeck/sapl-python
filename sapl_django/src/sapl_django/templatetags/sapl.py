from __future__ import annotations

import asyncio
from typing import Any

import structlog
from django import template

from sapl_base.types import AuthorizationSubscription, Decision

from sapl_django.config import get_pdp_client

log = structlog.get_logger()

register = template.Library()

ERROR_TEMPLATE_DECIDE_FAILED = "Template tag sapl_enforce decision failed, denying"


@register.simple_tag(takes_context=True)
def sapl_enforce(context: dict[str, Any], action: Any, resource: Any, **kwargs: Any) -> bool:
    """Template tag for conditional rendering based on SAPL authorization.

    Usage::

        {% load sapl %}
        {% sapl_enforce "read" "patient_record" as can_read %}
        {% if can_read %}
            <div>Sensitive content</div>
        {% endif %}

    The subject defaults to the template context's ``request.user.username``.
    Additional subscription fields can be passed as keyword arguments:
    ``subject``, ``environment``, ``secrets``.

    Args:
        context: The Django template rendering context.
        action: The action field for the authorization subscription.
        resource: The resource field for the authorization subscription.
        **kwargs: Optional overrides for subject, environment, secrets.

    Returns:
        True if the PDP returns PERMIT, False otherwise.
    """
    subject = kwargs.get("subject")
    if subject is None:
        request = context.get("request")
        if request is not None:
            user = getattr(request, "user", None)
            if user is not None and hasattr(user, "username") and user.username:
                subject = user.username
        if subject is None:
            subject = "anonymous"

    subscription = AuthorizationSubscription(
        subject=subject,
        action=action,
        resource=resource,
        environment=kwargs.get("environment"),
        secrets=kwargs.get("secrets"),
    )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            future = asyncio.ensure_future(_decide(subscription))
            # In async context (ASGI), we cannot block. Create a new thread.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                decision = pool.submit(_run_sync, subscription).result(timeout=5.0)
        else:
            decision = loop.run_until_complete(_decide(subscription))
    except RuntimeError:
        decision = asyncio.run(_decide(subscription))
    except Exception:
        log.error(ERROR_TEMPLATE_DECIDE_FAILED)
        return False

    return decision.decision == Decision.PERMIT


async def _decide(subscription: AuthorizationSubscription) -> Any:
    """Call the PDP client for a one-shot decision."""
    pdp = get_pdp_client()
    return await pdp.decide_once(subscription)


def _run_sync(subscription: AuthorizationSubscription) -> Any:
    """Run the async decide call in a new event loop (for use from sync context)."""
    return asyncio.run(_decide(subscription))
