"""Boundary signals between the FSM and the subscriber.

Three types, two channels:

- `AccessDeniedError` rides the error channel. Raising it terminates
  the subscription.
- `AccessSuspendedSignal` rides the next channel as a non-terminal
  sentinel when the FSM enters `Suspended`. Subscribers detect it
  with `isinstance` and may surface it via the helpers in
  `transition_signals.py`.
- `AccessGrantedSignal` rides the next channel as a non-terminal
  sentinel when the FSM enters `Permitting` from another state.
  Subscribers detect it the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sapl_base.types import AuthorizationDecision


class AccessDeniedError(Exception):
    """Terminal denial: the subscription is over.

    Carries the originating decision in `decision` and a short
    machine-readable reason for log audit. Subscribers should
    `except AccessDeniedError` to handle the denial; they MUST
    NOT inspect the message text to branch on cause.
    """

    def __init__(
        self,
        message: str = "Access denied",
        *,
        decision: AuthorizationDecision | None = None,
        reason: str = "DENIED",
    ) -> None:
        super().__init__(message)
        self.decision = decision
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AccessSuspendedSignal:
    """Non-terminal: the subscription has entered the Suspended state.

    Items will not be delivered until a subsequent `AccessGrantedSignal`.
    """

    decision: AuthorizationDecision


@dataclass(frozen=True, slots=True)
class AccessGrantedSignal:
    """Non-terminal: the subscription has entered the Permitting state.

    Carries the decision that authorised the grant for audit.
    """

    decision: AuthorizationDecision
