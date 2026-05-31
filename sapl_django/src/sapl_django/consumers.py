from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

try:
    from channels.generic.websocket import AsyncJsonWebsocketConsumer  # type: ignore[import-untyped]

    _HAS_CHANNELS = True
except ImportError:
    _HAS_CHANNELS = False

if _HAS_CHANNELS:
    from sapl_base.pep import (
        AccessDeniedError,
        DecisionSignal,
        PRE_ENFORCE_SUPPORTED,
    )
    from sapl_base.types import AuthorizationSubscription, Decision

    from sapl_django.config import get_pdp_client, get_planner

    class SaplWebsocketConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
        """WebSocket consumer with SAPL per-message enforcement.

        Subclass and implement `build_subscription` and `handle_message`.
        On `connect` and on each `receive_json`, the consumer queries the
        PDP and runs decision-scoped enforcement. Non-PERMIT closes (on
        connect) or sends an `error` payload (on receive). Decision-scoped
        obligation failure is treated the same as a non-PERMIT.

        Per-message PEP, not streaming. The Mealy FSM is not involved.

        Usage::

            class PatientConsumer(SaplWebsocketConsumer):
                def build_subscription(self) -> AuthorizationSubscription:
                    return AuthorizationSubscription(
                        subject=self.scope["user"].username,
                        action="subscribe",
                        resource="patient_updates",
                    )

                async def handle_message(self, content):
                    await self.send_json({"update": content})
        """

        def build_subscription(self) -> AuthorizationSubscription:
            raise NotImplementedError

        async def handle_message(self, content: Any) -> None:
            raise NotImplementedError

        async def _authorize_or_deny(self) -> bool:
            """Run decision-scoped enforcement. Returns True iff PERMIT and no obligation failure."""
            subscription = self.build_subscription()
            decision = await get_pdp_client().decide_once(subscription)
            if decision.decision is not Decision.PERMIT:
                return False
            plan = get_planner().plan(decision, PRE_ENFORCE_SUPPORTED)
            result = plan.execute(DecisionSignal(decision=decision))
            return not result.failure_state

        async def connect(self) -> None:
            await self.accept()
            try:
                authorized = await self._authorize_or_deny()
            except AccessDeniedError:
                authorized = False
            if not authorized:
                await self.close(code=4403)

        async def receive_json(self, content: Any, **kwargs: Any) -> None:
            try:
                authorized = await self._authorize_or_deny()
            except AccessDeniedError:
                authorized = False
            if not authorized:
                await self.send_json({"error": "Access denied"})
                return
            await self.handle_message(content)
