"""Optional transaction boundary for one-shot enforcement.

A transaction provider is a zero-argument factory returning an async context
manager that commits on clean exit and rolls back when an exception propagates --
the semantics of SQLAlchemy ``AsyncSession.begin()`` and Django
``transaction.atomic()``. ``pre_enforce`` and ``post_enforce`` wrap the
write-and-enforce region in it, so a post-write denial (an explicit DENY or an
output-obligation failure) rolls the transaction back rather than committing a
partial write.

When no provider is configured the scope is a no-op and enforcement behaves
exactly as before.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
)
from typing import Any

TransactionProvider = Callable[[], AbstractAsyncContextManager[Any]]
"""Zero-arg factory returning a commit-on-success / rollback-on-error async scope."""


@asynccontextmanager
async def _null_scope() -> AsyncGenerator[None]:
    yield


def transaction_scope(
    provider: TransactionProvider | None,
) -> AbstractAsyncContextManager[Any]:
    """Return the provider's transaction context manager, or a no-op when unset."""
    if provider is None:
        return _null_scope()
    return provider()


def from_sync_context(
    factory: Callable[[], AbstractContextManager[Any]],
) -> TransactionProvider:
    """Adapt a synchronous transaction context-manager factory into a provider.

    Use for sync transaction boundaries such as Django ``transaction.atomic`` or a sync
    SQLAlchemy ``session.begin``: ``set_transaction_provider(from_sync_context(transaction.atomic))``.
    The sync context manager commits on clean exit and rolls back on a propagated
    exception; this wraps it so the async enforcement scope can drive it.
    """

    @asynccontextmanager
    async def _scope() -> AsyncGenerator[None]:
        with factory():
            yield

    return lambda: _scope()
