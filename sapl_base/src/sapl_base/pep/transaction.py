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

from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from typing import Any

TransactionProvider = Callable[[], AbstractAsyncContextManager[Any]]
"""Zero-arg factory returning a commit-on-success / rollback-on-error async scope."""

SyncTransactionProvider = Callable[[], AbstractContextManager[Any]]
"""Zero-arg factory returning a commit-on-success / rollback-on-error sync scope.

The blocking enforcement path uses this directly (no async wrapping): SQLAlchemy
``session.begin()`` or Django ``transaction.atomic()`` are already sync context managers.
"""


@asynccontextmanager
async def _null_scope() -> AsyncGenerator[None]:
    yield


@contextmanager
def _null_scope_sync() -> Generator[None]:
    yield


def transaction_scope(
    provider: TransactionProvider | None,
) -> AbstractAsyncContextManager[Any]:
    """Return the provider's transaction context manager, or a no-op when unset."""
    if provider is None:
        return _null_scope()
    return provider()


def transaction_scope_sync(
    provider: SyncTransactionProvider | None,
) -> AbstractContextManager[Any]:
    """Return the provider's sync transaction context manager, or a no-op when unset."""
    if provider is None:
        return _null_scope_sync()
    return provider()


def from_sync_context(
    factory: Callable[[], AbstractContextManager[Any]],
) -> TransactionProvider:
    """Adapt a synchronous transaction context-manager factory into a provider.

    Use this to drive a sync transaction boundary, such as a sync SQLAlchemy
    ``session.begin``, from the async enforcement scope:
    ``set_transaction_provider(from_sync_context(lambda: session.begin()))``. The sync
    context manager commits on clean exit and rolls back on a propagated exception.

    The wrapped context manager is entered on the event loop thread, so it must not touch
    a resource that forbids sync access there. Django's ``transaction.atomic`` is one such
    resource (it raises ``SynchronousOnlyOperation`` under a running loop), so back an
    async view with an async provider and reserve ``transaction.atomic`` for sync views,
    where the blocking core uses it directly without this adapter.
    """

    @asynccontextmanager
    async def _scope() -> AsyncGenerator[None]:
        with factory():
            yield

    return lambda: _scope()
