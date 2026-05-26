"""Transport-independent PDP client Protocol.

Both `HttpPdpClient` and `RsocketPdpClient` conform to this Protocol.
Higher-level code that wires a PEP to a PDP holds the Protocol type;
the concrete transport is chosen at construction time.

Contract:

- Fail-closed. When the PDP is unreachable, the codec rejects a
  payload, or auth setup fails, one-shot methods return a fresh
  `INDETERMINATE` decision and streaming methods yield
  `INDETERMINATE` rather than raising.
- Reconnect. Streaming methods reconnect on transport failure and
  yield `INDETERMINATE` across the gap. Consecutive equal decisions
  are suppressed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from sapl_base.types import (
    AuthorizationDecision,
    AuthorizationSubscription,
    IdentifiableAuthorizationDecision,
    MultiAuthorizationDecision,
    MultiAuthorizationSubscription,
)


@runtime_checkable
class PdpClient(Protocol):
    """Transport-agnostic surface for SAPL PDP communication.

    See module docstring for the fail-closed and reconnect contracts.
    """

    async def decide_once(
        self,
        subscription: AuthorizationSubscription,
    ) -> AuthorizationDecision:
        """Single one-shot authorization request.

        Returns the PDP's decision, or `INDETERMINATE` on transport
        or parse failure.
        """
        ...

    def decide(
        self,
        subscription: AuthorizationSubscription,
    ) -> AsyncIterator[AuthorizationDecision]:
        """Subscribe to a continuous PDP stream for one subscription.

        The PDP emits a new decision whenever its evaluation changes;
        the client suppresses consecutive duplicates. The stream
        reconnects on transport failure and yields `INDETERMINATE`
        across the gap.
        """
        ...

    def multi_decide(
        self,
        subscription: MultiAuthorizationSubscription,
    ) -> AsyncIterator[IdentifiableAuthorizationDecision]:
        """Multi-subscription stream where decisions arrive individually."""
        ...

    def multi_decide_all(
        self,
        subscription: MultiAuthorizationSubscription,
    ) -> AsyncIterator[MultiAuthorizationDecision]:
        """Multi-subscription stream where each emission is a snapshot of all decisions."""
        ...

    async def multi_decide_all_once(
        self,
        subscription: MultiAuthorizationSubscription,
    ) -> MultiAuthorizationDecision:
        """One-shot multi-subscription request returning a snapshot."""
        ...

    async def close(self) -> None:
        """Release persistent resources (connection pools, refresh timers, sockets).

        Idempotent.
        """
        ...
