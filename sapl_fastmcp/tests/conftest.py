"""Shared test fixtures for SAPL middleware tests."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.server.auth import AccessToken

from sapl_base import AuthorizationDecision
from sapl_base.constraint_engine import ConstraintEnforcementService


@pytest.fixture
def pdp_client():
    """AsyncMock PDP client with decide_once."""
    return AsyncMock()


@pytest.fixture
def constraint_service():
    """Real ConstraintEnforcementService (no registered providers)."""
    return ConstraintEnforcementService()


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
    """Filters list results by classification level.

    Handles obligations like:
    {"type": "filterByClassification", "allowedLevels": ["public", "internal"]}

    Removes list elements whose ``classification`` field is not in the
    allowed set. Non-dict elements pass through unfiltered.

    Test-local copy of the demo handler for test isolation.
    """

    def is_responsible(self, constraint: Any) -> bool:
        return isinstance(constraint, dict) and constraint.get("type") == "filterByClassification"

    def get_handler(self, constraint: Any) -> Callable[[Any], bool]:
        allowed = set(constraint.get("allowedLevels", []))

        def predicate(element: Any) -> bool:
            if isinstance(element, dict):
                return element.get("classification") in allowed
            return True

        return predicate
