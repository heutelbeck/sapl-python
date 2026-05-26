"""Type alias for handlers attached to SQL_QUERY."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

SqlQueryMapper = Callable[[Any], Any]
"""A mapper takes the current SQLAlchemy Executable (Select, Update,
Delete, or Insert) and returns the transformed Executable. Returning
the DROP sentinel is undefined; mappers raise to deny."""
