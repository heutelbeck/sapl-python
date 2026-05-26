"""Streaming PEP public surface.

The Mealy FSM types (states, events, emissions, sentinels) live in
`sapl_base.pep.streaming.mealy`. Import them from there if you need
to drive the FSM directly. The default consumer surface is the
pipeline runner, the lifecycle signal kinds and dataclasses, and the
subscriber-side `on_*` helpers.
"""

from sapl_base.pep.streaming.pipeline import (
    CANCEL_SIGNAL,
    COMPLETE,
    STREAM_SUPPORTED,
    TERMINATION,
    CancelSignal,
    CompleteSignal,
    TerminationSignal,
    run_pipeline,
)
from sapl_base.pep.streaming.transition_signals import (
    on_granted,
    on_suspend,
    on_transitions,
)

__all__ = [
    "CANCEL_SIGNAL",
    "COMPLETE",
    "CancelSignal",
    "CompleteSignal",
    "STREAM_SUPPORTED",
    "TERMINATION",
    "TerminationSignal",
    "on_granted",
    "on_suspend",
    "on_transitions",
    "run_pipeline",
]
