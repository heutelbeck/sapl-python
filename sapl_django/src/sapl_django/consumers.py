from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

ERROR_CHANNELS_NOT_INSTALLED = (
    "Django Channels is required for WebSocket enforcement. "
    "Install with: pip install sapl-django[channels]"
)

try:
    from channels.generic.websocket import AsyncJsonWebsocketConsumer  # type: ignore[import-untyped]

    _HAS_CHANNELS = True
except ImportError:
    _HAS_CHANNELS = False

if _HAS_CHANNELS:
    from sapl_base.constraint_bundle import AccessDeniedError
    from sapl_base.types import AuthorizationSubscription, Decision
    from sapl_django.config import get_constraint_service, get_pdp_client

    class SaplWebsocketConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
        """WebSocket consumer with SAPL streaming enforcement.

        Subclass this and implement ``build_subscription`` and ``handle_message``.

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
            """Build the authorization subscription for this WebSocket connection.

            Override this method in subclasses to provide connection-specific
            subscription fields.

            Returns:
                The authorization subscription for the PDP query.

            Raises:
                NotImplementedError: If not overridden by a subclass.
            """
            raise NotImplementedError

        async def handle_message(self, content: Any) -> None:
            """Handle an authorized incoming message.

            Override this method to process messages that have passed enforcement.

            Args:
                content: The JSON-decoded message content.

            Raises:
                NotImplementedError: If not overridden by a subclass.
            """
            raise NotImplementedError

        async def connect(self) -> None:
            """Accept the connection and verify initial authorization."""
            await self.accept()
            subscription = self.build_subscription()
            pdp = get_pdp_client()
            decision = await pdp.decide_once(subscription)

            if decision.decision != Decision.PERMIT:
                await self.close(code=4403)
                return

            try:
                constraint_service = get_constraint_service()
                bundle = constraint_service.pre_enforce_bundle_for(decision)
                bundle.handle_on_decision_constraints()
            except AccessDeniedError:
                await self.close(code=4403)

        async def receive_json(self, content: Any, **kwargs: Any) -> None:
            """Receive and enforce an incoming JSON message.

            Args:
                content: The JSON-decoded message content.
                **kwargs: Additional keyword arguments from Channels.
            """
            subscription = self.build_subscription()
            pdp = get_pdp_client()
            decision = await pdp.decide_once(subscription)

            if decision.decision != Decision.PERMIT:
                await self.send_json({"error": "Access denied"})
                return

            try:
                constraint_service = get_constraint_service()
                bundle = constraint_service.pre_enforce_bundle_for(decision)
                bundle.handle_on_decision_constraints()
            except AccessDeniedError:
                await self.send_json({"error": "Access denied"})
                return

            await self.handle_message(content)
