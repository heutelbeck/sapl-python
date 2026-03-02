from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    """Authorization decision values as defined by the SAPL protocol."""

    PERMIT = "PERMIT"
    DENY = "DENY"
    INDETERMINATE = "INDETERMINATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class _ResourceAbsentSentinel:
    """Sentinel to distinguish 'no resource replacement' from an explicit null resource."""

    _instance: _ResourceAbsentSentinel | None = None

    def __new__(cls) -> _ResourceAbsentSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<RESOURCE_ABSENT>"

    def __bool__(self) -> bool:
        return False


RESOURCE_ABSENT: Any = _ResourceAbsentSentinel()


@dataclass(frozen=True, slots=True)
class AuthorizationSubscription:
    """A subscription sent to the PDP describing the authorization context.

    The ``secrets`` field is transmitted to the PDP but must never appear in logs.
    """

    subject: Any = None
    action: Any = None
    resource: Any = None
    environment: Any = None
    secrets: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for PDP transmission, including secrets."""
        result: dict[str, Any] = {
            "subject": self.subject,
            "action": self.action,
            "resource": self.resource,
        }
        if self.environment is not None:
            result["environment"] = self.environment
        if self.secrets is not None:
            result["secrets"] = self.secrets
        return result

    def to_loggable_dict(self) -> dict[str, Any]:
        """Serialize for logging, excluding secrets."""
        result: dict[str, Any] = {
            "subject": self.subject,
            "action": self.action,
            "resource": self.resource,
        }
        if self.environment is not None:
            result["environment"] = self.environment
        return result


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """A decision received from the PDP.

    The ``resource`` field uses the ``RESOURCE_ABSENT`` sentinel to distinguish
    between the PDP not including a resource replacement (absent) and the PDP
    explicitly setting the resource to ``None``.
    """

    decision: Decision = Decision.INDETERMINATE
    obligations: tuple[Any, ...] = ()
    advice: tuple[Any, ...] = ()
    resource: Any = field(default=RESOURCE_ABSENT)

    @staticmethod
    def indeterminate() -> AuthorizationDecision:
        """Return a default INDETERMINATE decision."""
        return AuthorizationDecision()

    @staticmethod
    def deny() -> AuthorizationDecision:
        """Return a simple DENY decision."""
        return AuthorizationDecision(decision=Decision.DENY)

    @staticmethod
    def permit() -> AuthorizationDecision:
        """Return a simple PERMIT decision."""
        return AuthorizationDecision(decision=Decision.PERMIT)

    @property
    def has_resource(self) -> bool:
        """Return True if the PDP provided a resource replacement."""
        return self.resource is not RESOURCE_ABSENT


@dataclass(frozen=True, slots=True)
class MultiAuthorizationSubscription:
    """A bundle of named authorization subscriptions for multi-decision requests."""

    subscriptions: dict[str, AuthorizationSubscription] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for PDP transmission."""
        return {
            subscription_id: subscription.to_dict()
            for subscription_id, subscription in self.subscriptions.items()
        }

    def to_loggable_dict(self) -> dict[str, Any]:
        """Serialize for logging, excluding secrets from each subscription."""
        return {
            subscription_id: subscription.to_loggable_dict()
            for subscription_id, subscription in self.subscriptions.items()
        }


@dataclass(frozen=True, slots=True)
class IdentifiableAuthorizationDecision:
    """A decision paired with the subscription ID it belongs to."""

    subscription_id: str
    decision: AuthorizationDecision


@dataclass(frozen=True, slots=True)
class MultiAuthorizationDecision:
    """A collection of named authorization decisions from a multi-decision request."""

    decisions: dict[str, AuthorizationDecision] = field(default_factory=dict)
