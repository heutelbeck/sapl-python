from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import structlog

log = structlog.get_logger()

# Error/warning constants (sorted alphabetically by variable name)
ERROR_INVALID_FILTER_ACTION = "Invalid filter action type"
ERROR_INVALID_PATH = "Invalid or unsupported path syntax"
ERROR_MISSING_ACTIONS = "filterJsonContent constraint missing 'actions' array"
ERROR_PROTOTYPE_POLLUTION = "Path segment matches forbidden key, skipping action"
ERROR_REDOS_PATTERN = "Potentially unsafe regex pattern rejected"
WARN_PATH_NOT_FOUND = "Path not found in object during content filtering"

# Maximum regex pattern complexity to prevent ReDoS (REQ-FILTER-SEC-2)
_MAX_REGEX_LENGTH = 200
_REDOS_PATTERNS = re.compile(
    r"\([^)]*[+*][^)]*\)[+*?]"  # nested quantifier: (x+)+ or (x*)*
    r"|(\([^)]*\|[^)]*\)){3,}"  # excessive alternation: (a|b)(c|d)(e|f)
)

# Forbidden keys for prototype pollution defense (REQ-FILTER-SEC-1)
_FORBIDDEN_KEYS = frozenset({
    "__proto__",
    "__class__",
    "__dict__",
    "__globals__",
    "__builtins__",
    "__subclasses__",
})

# Unsupported path features
_UNSUPPORTED_PATH = re.compile(r"\[|\]|\*|\.\.")

# Valid path: starts with $, then dot-separated identifiers
_VALID_PATH = re.compile(r"^\$(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")

_MAX_SAFE_REPR = 200


def _safe_repr(obj: Any) -> str:
    """Safe string representation for logging (truncated)."""
    text = repr(obj)
    if len(text) <= _MAX_SAFE_REPR:
        return text
    return text[:_MAX_SAFE_REPR] + "...[truncated]"


def _identity(value: Any) -> Any:
    """Identity function for no-op handlers."""
    return value


def _parse_path(path: str) -> list[str] | None:
    """Parse ``$.field.nested`` into ``['field', 'nested']``.

    Args:
        path: A dot-notation JSON path starting with ``$``.

    Returns:
        A list of path segments, or ``None`` if the path is invalid or
        uses unsupported features (array indexing, wildcards, recursive descent).
    """
    if not isinstance(path, str):
        log.error(ERROR_INVALID_PATH, path=_safe_repr(path))
        return None

    if _UNSUPPORTED_PATH.search(path):
        log.error(ERROR_INVALID_PATH, path=path, reason="unsupported syntax")
        return None

    if not _VALID_PATH.match(path):
        log.error(ERROR_INVALID_PATH, path=path, reason="does not match expected format")
        return None

    segments = path.split(".")[1:]  # skip the leading '$'

    for segment in segments:
        if segment in _FORBIDDEN_KEYS:
            log.error(ERROR_PROTOTYPE_POLLUTION, path=path, segment=segment)
            return None

    return segments


def _navigate_to_parent(obj: Any, segments: list[str]) -> tuple[Any, str] | None:
    """Navigate to the parent of the target field.

    Args:
        obj: The root object to navigate.
        segments: Path segments (e.g., ``['a', 'b', 'c']`` navigates to ``obj['a']['b']``
                  and returns ``(obj['a']['b'], 'c')``).

    Returns:
        A tuple of ``(parent_object, last_key)`` or ``None`` if the path
        does not exist in the object.
    """
    current = obj
    for segment in segments[:-1]:
        if not isinstance(current, dict) or segment not in current:
            log.warning(WARN_PATH_NOT_FOUND, segment=segment)
            return None
        current = current[segment]
    last_key = segments[-1]
    if not isinstance(current, dict):
        log.warning(WARN_PATH_NOT_FOUND, segment=last_key)
        return None
    return current, last_key


def _blacken_value(
    value: str,
    replacement: str,
    disclose_left: int,
    disclose_right: int,
) -> str:
    """Blacken a string value, keeping disclosed characters on left and right.

    Args:
        value: The string to blacken.
        replacement: The character used to mask hidden positions.
        disclose_left: Number of characters to keep visible on the left.
        disclose_right: Number of characters to keep visible on the right.

    Returns:
        The blackened string. If disclosure totals exceed the string length
        the original value is returned unmasked.
    """
    length = len(value)
    if length == 0:
        return value
    if disclose_left + disclose_right >= length:
        return value

    left = value[:disclose_left]
    right = value[length - disclose_right:] if disclose_right > 0 else ""
    middle_len = length - disclose_left - disclose_right
    return left + (replacement * middle_len) + right


def _apply_action(obj: Any, action: dict) -> Any:
    """Apply a single filter action to the object.

    Supported action types: ``blacken``, ``replace``, ``delete``.
    Unknown action types are logged and skipped.

    Args:
        obj: The object to filter (already a deep clone).
        action: A dict describing the action with at least ``type`` and ``path``.

    Returns:
        The (possibly modified) object.
    """
    if not isinstance(action, dict):
        log.error(ERROR_INVALID_FILTER_ACTION, action=_safe_repr(action))
        return obj

    action_type = action.get("type")
    path = action.get("path")

    if not isinstance(action_type, str):
        log.error(ERROR_INVALID_FILTER_ACTION, action=_safe_repr(action))
        return obj

    segments = _parse_path(path)
    if segments is None:
        return obj

    if action_type == "blacken":
        return _apply_blacken(obj, segments, action)
    if action_type == "replace":
        return _apply_replace(obj, segments, action)
    if action_type == "delete":
        return _apply_delete(obj, segments)

    log.error(ERROR_INVALID_FILTER_ACTION, action_type=action_type)
    return obj


def _apply_blacken(obj: Any, segments: list[str], action: dict) -> Any:
    """Apply a blacken action at the given path."""
    nav = _navigate_to_parent(obj, segments)
    if nav is None:
        return obj
    parent, key = nav
    if key not in parent:
        log.warning(WARN_PATH_NOT_FOUND, segment=key)
        return obj
    current_value = parent[key]
    if not isinstance(current_value, str):
        log.warning(WARN_PATH_NOT_FOUND, segment=key, reason="value is not a string")
        return obj

    replacement = action.get("replacement", "X")
    disclose_left = action.get("discloseLeft", 0)
    disclose_right = action.get("discloseRight", 0)
    parent[key] = _blacken_value(current_value, replacement, disclose_left, disclose_right)
    return obj


def _apply_replace(obj: Any, segments: list[str], action: dict) -> Any:
    """Apply a replace action at the given path."""
    nav = _navigate_to_parent(obj, segments)
    if nav is None:
        return obj
    parent, key = nav
    if key not in parent:
        log.warning(WARN_PATH_NOT_FOUND, segment=key)
        return obj
    parent[key] = action.get("replacement")
    return obj


def _apply_delete(obj: Any, segments: list[str]) -> Any:
    """Apply a delete action at the given path."""
    nav = _navigate_to_parent(obj, segments)
    if nav is None:
        return obj
    parent, key = nav
    parent.pop(key, None)
    return obj


def _is_safe_regex(pattern: str) -> bool:
    """Check if a regex pattern is safe from ReDoS attacks.

    Rejects patterns longer than ``_MAX_REGEX_LENGTH`` or containing
    nested quantifiers / excessive alternation.

    Args:
        pattern: The regex pattern string.

    Returns:
        ``True`` if the pattern is considered safe, ``False`` otherwise.
    """
    if not isinstance(pattern, str):
        return False
    if len(pattern) > _MAX_REGEX_LENGTH:
        return False
    return not _REDOS_PATTERNS.search(pattern)


def _resolve_value(element: Any, path: str) -> Any:
    """Resolve a value at a dot-notation path within an element.

    Args:
        element: The object to query.
        path: A dot-notation path (e.g., ``$.field.nested``).

    Returns:
        The value at the path, or ``None`` if the path is invalid or absent.
        The second element of the tuple indicates whether resolution succeeded.
    """
    segments = _parse_path(path)
    if segments is None:
        return None, False

    current = element
    for segment in segments:
        if not isinstance(current, dict) or segment not in current:
            return None, False
        current = current[segment]
    return current, True


def _evaluate_condition(element: Any, condition: dict) -> bool:
    """Evaluate a single condition against an element.

    A condition has ``path``, ``operator``, and ``value`` fields.
    Supported operators: ``==``, ``!=``, ``>=``, ``<=``, ``>``, ``<``, ``=~`` (regex).

    For the ``=~`` operator, the pattern is validated for ReDoS safety before use.
    Unsafe patterns cause the condition to evaluate to ``False`` (fail-closed).

    Args:
        element: The object to evaluate against.
        condition: A dict with ``path``, ``operator``, and ``value``.

    Returns:
        ``True`` if the condition is satisfied, ``False`` otherwise.
    """
    if not isinstance(condition, dict):
        return False

    path = condition.get("path")
    operator = condition.get("operator")
    expected = condition.get("value")

    actual, found = _resolve_value(element, path)
    if not found:
        return False

    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator == ">=":
        return actual >= expected
    if operator == "<=":
        return actual <= expected
    if operator == ">":
        return actual > expected
    if operator == "<":
        return actual < expected
    if operator == "=~":
        if not isinstance(expected, str):
            return False
        if not _is_safe_regex(expected):
            log.error(ERROR_REDOS_PATTERN, pattern=_safe_repr(expected))
            return False
        if not isinstance(actual, str):
            return False
        try:
            return bool(re.search(expected, actual))
        except re.error:
            return False

    return False


class ContentFilteringProvider:
    """Built-in content filtering handler.

    Handles constraints of type ``filterJsonContent`` with actions:

    - **blacken**: mask characters with a replacement char (default ``X``)
    - **replace**: replace value at path with a fixed replacement
    - **delete**: remove key at path

    Path syntax: simple dot-notation only (e.g., ``$.field.nested``).
    No array indexing, no wildcards, no recursive descent.
    """

    def is_responsible(self, constraint: Any) -> bool:
        """Return ``True`` if the constraint type is ``filterJsonContent``."""
        return isinstance(constraint, dict) and constraint.get("type") == "filterJsonContent"

    def get_priority(self) -> int:
        """Return priority ``0`` so content filtering executes first."""
        return 0

    def get_handler(self, constraint: Any) -> Callable[[Any], Any]:
        """Return a handler that applies all filter actions.

        The handler deep-clones the input before mutation (REQ-FILTER-SEC-3).

        Args:
            constraint: A dict with ``type`` and ``actions`` fields.

        Returns:
            A callable that accepts a value and returns the filtered value.
        """
        actions = constraint.get("actions", [])
        if not isinstance(actions, list):
            log.error(ERROR_MISSING_ACTIONS, constraint=_safe_repr(constraint))
            return _identity

        def _filter_single(obj: Any) -> Any:
            result = obj
            for action in actions:
                result = _apply_action(result, action)
            return result

        def handler(value: Any) -> Any:
            cloned = copy.deepcopy(value)
            if isinstance(cloned, list):
                return [_filter_single(element) for element in cloned]
            return _filter_single(cloned)

        return handler


class ContentFilterPredicateProvider:
    """Built-in filter predicate handler.

    Handles constraints of type ``jsonContentFilterPredicate`` with conditions.
    Evaluates conditions against each element and returns ``True``/``False``.

    Multiple conditions are combined with AND logic.
    """

    def is_responsible(self, constraint: Any) -> bool:
        """Return ``True`` if the constraint type is ``jsonContentFilterPredicate``."""
        return isinstance(constraint, dict) and constraint.get("type") == "jsonContentFilterPredicate"

    def get_handler(self, constraint: Any) -> Callable[[Any], bool]:
        """Return a predicate that evaluates all conditions against an element.

        Args:
            constraint: A dict with ``type`` and ``conditions`` fields.

        Returns:
            A callable that accepts an element and returns ``True`` if all
            conditions are satisfied.
        """
        conditions = constraint.get("conditions", [])
        if not isinstance(conditions, list):
            return lambda _: True

        def predicate(element: Any) -> bool:
            return all(_evaluate_condition(element, cond) for cond in conditions)

        return predicate
