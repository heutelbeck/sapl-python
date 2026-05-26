from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sapl_base.pep import DECISION, OUTPUT, ConstraintHandlerProvider, ScopedHandler


class _ConformingProvider:
    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "audit":
            return ()
        return (
            ScopedHandler(
                signal=DECISION,
                priority=0,
                shape="runner",
                handler=lambda: None,
            ),
        )


class _NonConformingClass:
    """Has the right method name but wrong signature."""

    def get_handlers(self) -> Sequence[ScopedHandler]:  # type: ignore[override]
        return ()


def test_conforming_class_is_recognised_as_provider() -> None:
    instance = _ConformingProvider()
    assert isinstance(instance, ConstraintHandlerProvider)


def test_empty_sequence_means_not_responsible() -> None:
    provider = _ConformingProvider()
    assert provider.get_handlers({"type": "something-else"}) == ()


def test_claim_returns_one_or_more_scoped_handlers() -> None:
    provider = _ConformingProvider()
    handlers = provider.get_handlers({"type": "audit"})
    assert len(handlers) == 1
    assert handlers[0].signal is DECISION


def test_scoped_handler_is_immutable() -> None:
    handler = ScopedHandler(
        signal=OUTPUT, priority=0, shape="mapper", handler=lambda v: v
    )
    try:
        handler.priority = 99  # type: ignore[misc]
    except (AttributeError, TypeError):
        return
    raise AssertionError("ScopedHandler should be frozen")
