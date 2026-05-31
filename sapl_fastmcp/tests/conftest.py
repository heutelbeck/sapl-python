"""Shared test fixtures for SAPL middleware tests."""

from collections.abc import Sequence
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.server.auth import AccessToken

from sapl_base import AuthorizationDecision
from sapl_base.pep import OUTPUT, EnforcementPlanner, ScopedHandler


@pytest.fixture
def pdp_client():
    """AsyncMock PDP client with decide_once."""
    return AsyncMock()


@pytest.fixture
def planner():
    """Real EnforcementPlanner with no registered providers."""
    return EnforcementPlanner()


@pytest.fixture
def permit_decision():
    return AuthorizationDecision.permit()


@pytest.fixture
def deny_decision():
    return AuthorizationDecision.deny()


@pytest.fixture
def indeterminate_decision():
    return AuthorizationDecision.indeterminate()


def make_token(claims=None, client_id="client-1"):
    """Create a mock OAuth token that passes isinstance(token, AccessToken)."""
    token = MagicMock(spec=AccessToken)
    token.claims = claims
    token.client_id = client_id
    return token


def make_auth_ctx(token=None, component_name="test_tool"):
    """Create a minimal AuthContext mock for auth-check and subscription tests."""
    ctx = MagicMock()
    ctx.token = token
    ctx.component = MagicMock()
    ctx.component.name = component_name
    return ctx


class FilterByClassificationProvider:
    """OUTPUT mapper: filters list results by classification level.

    Handles obligations like
    ``{"type": "filterByClassification", "allowedLevels": ["public", "internal"]}``.

    Removes list elements whose ``classification`` field is not in the
    allowed set. Non-list values pass through unchanged. Non-dict
    elements pass through unfiltered.

    Test-local copy of the demo handler for test isolation.
    """

    def get_handlers(self, constraint: Any) -> Sequence[ScopedHandler]:
        if not isinstance(constraint, dict) or constraint.get("type") != "filterByClassification":
            return ()
        allowed = set(constraint.get("allowedLevels", []))

        def handler(value: Any) -> Any:
            if not isinstance(value, list):
                return value
            return [
                element
                for element in value
                if not isinstance(element, dict)
                or element.get("classification") in allowed
            ]

        return (ScopedHandler(signal=OUTPUT, priority=20, shape="mapper", handler=handler),)
