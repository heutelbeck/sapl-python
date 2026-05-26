"""Constants shared between HTTP and RSocket transports.

Route names match the SAPL Node's wire surface. The RSocket
acceptor performs a byte-equality match against pre-encoded route
bytes; do not rename without coordinating with the server.

Reconnection defaults: 1 s initial backoff, exponential x2 with
multiplicative jitter, 30 s cap, 5-attempt warn-to-error log
escalation.
"""

from __future__ import annotations

from enum import StrEnum

PDP_API_PREFIX = "/api/pdp/"


class PdpRoute(StrEnum):
    """Endpoint route names exposed by the SAPL Node PDP.

    The HTTP transport prefixes each with `PDP_API_PREFIX`. The
    RSocket transport sends the bare route name as raw UTF-8 bytes
    in the per-request metadata (the SAPL Node performs
    byte-equality matching).
    """

    DECIDE_ONCE = "decide-once"
    DECIDE = "decide"
    MULTI_DECIDE = "multi-decide"
    MULTI_DECIDE_ALL = "multi-decide-all"
    MULTI_DECIDE_ALL_ONCE = "multi-decide-all-once"


DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_RETRY_BASE_DELAY_SECONDS = 1.0
DEFAULT_RETRY_MAX_DELAY_SECONDS = 30.0

MAX_SSE_BUFFER_BYTES = 65_536
"""Cap on per-stream SSE buffer in bytes. Decision frames are
sub-1 KB in practice; this cap bounds memory against a misbehaving
PDP that never terminates a frame."""

MAX_CONSTRAINT_COUNT = 100
"""Soft cap on obligations / advice array length per decision.
Above this the client emits a WARN log; dispatch is not blocked."""

RETRY_ESCALATION_THRESHOLD = 5
"""Reconnect attempts below this log at WARN; at or above log at ERROR."""

LOOPBACK_HOSTS: frozenset[str] = frozenset(["localhost", "127.0.0.1", "::1"])
