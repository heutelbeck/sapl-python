"""Rich context passed to subscription-field callables.

Decorators in the framework wrappers (django / fastapi / flask /
tornado / fastmcp) accept `subject` / `action` / `resource` /
`environment` / `secrets` either as plain values or as callables.
When a callable is supplied, the framework wrapper invokes it with
a `SubscriptionContext` so the callable can derive its value from
the request, path params, body, or (in the post-enforce path) the
return value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SubscriptionContext:
    """Context for callable subscription fields.

    Args:
        args: Named arguments of the protected method.
        function_name: Name of the protected method.
        class_name: Qualified class name, empty for plain functions.
        request: Framework request object, or None for service-layer
            calls.
        params: Route or path parameters.
        query: Query-string parameters.
        body: Parsed request body, or None.
        return_value: Return value of the method (set only on the
            post-enforce path).
    """

    args: dict[str, Any] = field(default_factory=dict)
    function_name: str = ""
    class_name: str = ""
    request: Any = None
    params: dict[str, str] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    return_value: Any = None
