"""Transaction rollback proof for the one-shot enforcement port.

A denial that lands AFTER the protected method has written to the DB must roll the
transaction back. These tests drive ``pre_enforce`` / ``post_enforce`` directly with a
real async sqlite database, a stub PDP, and a failing OUTPUT-obligation provider, and
assert the row is ABSENT after each post-write denial and PRESENT after a clean permit.

Triggers covered:
- post_enforce DENY (method always runs first).
- post_enforce output-obligation failure.
- pre_enforce output-obligation failure (permit before the method, obligation after it).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import pytest

from sapl_base.pep import (
    OUTPUT,
    AccessDeniedError,
    EnforcementPlanner,
    ScopedHandler,
    post_enforce,
    pre_enforce,
)
from sapl_base.types import AuthorizationDecision, AuthorizationSubscription, Decision

FAIL_OUTPUT = {"type": "failOutput"}
SUBSCRIPTION = AuthorizationSubscription(subject="s", action="a", resource="r")


class Base(DeclarativeBase):
    pass


class Widget(Base):
    __tablename__ = "widget"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class StubPdp:
    """A PDP that always returns one configured decision."""

    def __init__(self, decision: AuthorizationDecision) -> None:
        self._decision = decision

    async def decide_once(self, subscription: AuthorizationSubscription) -> AuthorizationDecision:
        return self._decision

    def decide(self, subscription: AuthorizationSubscription) -> Any:  # pragma: no cover - unused
        raise NotImplementedError


class FailingOutputProvider:
    """Claims the ``failOutput`` obligation with an OUTPUT consumer that raises."""

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if isinstance(constraint, dict) and constraint.get("type") == "failOutput":
            def _raise(value: Any) -> None:
                raise RuntimeError("output obligation handler failed")

            return [ScopedHandler(signal=OUTPUT, priority=0, shape="consumer", handler=_raise)]
        return []


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/rollback.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _widget_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(Widget)) or 0


def _writer(session: AsyncSession):
    async def write_widget() -> dict[str, Any]:
        session.add(Widget(name="created"))
        return {"created": True}

    return write_widget


# -- post_enforce ---------------------------------------------------------------------


async def test_post_enforce_permit_commits(session_factory):
    async with session_factory() as session:
        result = await post_enforce(
            _writer(session),
            pdp_client=StubPdp(AuthorizationDecision(decision=Decision.PERMIT)),
            planner=EnforcementPlanner(),
            subscription_builder=lambda _r: SUBSCRIPTION,
            transaction=lambda: session.begin(),
        )
    assert result == {"created": True}
    assert await _widget_count(session_factory) == 1


async def test_post_enforce_deny_rolls_back(session_factory):
    async with session_factory() as session:
        with pytest.raises(AccessDeniedError):
            await post_enforce(
                _writer(session),
                pdp_client=StubPdp(AuthorizationDecision(decision=Decision.DENY)),
                planner=EnforcementPlanner(),
                subscription_builder=lambda _r: SUBSCRIPTION,
                transaction=lambda: session.begin(),
            )
    assert await _widget_count(session_factory) == 0


async def test_post_enforce_output_obligation_failure_rolls_back(session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    async with session_factory() as session:
        with pytest.raises(AccessDeniedError):
            await post_enforce(
                _writer(session),
                pdp_client=StubPdp(decision),
                planner=EnforcementPlanner(providers=(FailingOutputProvider(),)),
                subscription_builder=lambda _r: SUBSCRIPTION,
                transaction=lambda: session.begin(),
            )
    assert await _widget_count(session_factory) == 0


# -- pre_enforce ----------------------------------------------------------------------


async def test_pre_enforce_permit_commits(session_factory):
    async with session_factory() as session:
        result = await pre_enforce(
            _writer(session),
            pdp_client=StubPdp(AuthorizationDecision(decision=Decision.PERMIT)),
            planner=EnforcementPlanner(),
            subscription=SUBSCRIPTION,
            transaction=lambda: session.begin(),
        )
    assert result == {"created": True}
    assert await _widget_count(session_factory) == 1


async def test_pre_enforce_output_obligation_failure_rolls_back(session_factory):
    decision = AuthorizationDecision(decision=Decision.PERMIT, obligations=(FAIL_OUTPUT,))
    async with session_factory() as session:
        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                _writer(session),
                pdp_client=StubPdp(decision),
                planner=EnforcementPlanner(providers=(FailingOutputProvider(),)),
                subscription=SUBSCRIPTION,
                transaction=lambda: session.begin(),
            )
    assert await _widget_count(session_factory) == 0
