"""Process-global registry of shim-contributed signals.

A query-rewriting ORM shim (such as ``sapl_sqlalchemy``) installs an execution
hook that discharges a shim signal during method execution. By registering that
signal here, the shim advertises the capability to the planner: ``pre_enforce``
unions these signals into the supported set it plans against, so a matching
obligation is scheduled and discharged rather than rejected as inadmissible and
failed closed.

This mirrors the Spring PEP, where each active store shim contributes its signal
to the supported set passed to the planner. The supported set must reflect the
PEP's true deployed capabilities: declaring a signal the PEP cannot honour, or
omitting one it can, both break the planner's fail-closed guarantee.
"""

from __future__ import annotations

import threading

from sapl_base.pep.signal import SignalKind

_lock = threading.Lock()
_signals: set[SignalKind] = set()


def register_shim_signal(signal: SignalKind) -> None:
    """Advertise that a shim discharges ``signal`` during method execution."""
    with _lock:
        _signals.add(signal)


def unregister_shim_signal(signal: SignalKind) -> None:
    """Withdraw a previously registered shim signal. Idempotent."""
    with _lock:
        _signals.discard(signal)


def shim_signals() -> frozenset[SignalKind]:
    """Snapshot of the currently registered shim signals."""
    with _lock:
        return frozenset(_signals)
