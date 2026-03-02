from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sapl_base.constraint_bundle import AccessDeniedError, ConstraintHandlerBundle
from sapl_base.constraint_engine import ConstraintEnforcementService
from sapl_base.constraint_types import MethodInvocationContext
from sapl_base.enforcement import (
    ERROR_ACCESS_DENIED,
    WARN_BEST_EFFORT_FAILED,
    WARN_ON_DENY_CALLBACK_FAILED,
    post_enforce,
    pre_enforce,
)
from sapl_base.types import (
    RESOURCE_ABSENT,
    AuthorizationDecision,
    AuthorizationSubscription,
    Decision,
)


def _noop() -> None:
    pass


def _noop_consumer(_value: Any) -> None:
    pass


def _identity(value: Any) -> Any:
    return value


def _always_true(_value: Any) -> bool:
    return True


def _noop_error_handler(_error: Exception) -> None:
    pass


def _identity_error(error: Exception) -> Exception:
    return error


def _noop_method_invocation(_context: MethodInvocationContext) -> None:
    pass


def _make_bundle(
    on_decision_handlers: Any = None,
    method_invocation_handlers: Any = None,
    on_next_consumers: Any = None,
    on_next_mappings: Any = None,
    filter_predicates: Any = None,
    on_error_handlers: Any = None,
    on_error_mappings: Any = None,
    resource_replacement: Any = RESOURCE_ABSENT,
) -> ConstraintHandlerBundle:
    return ConstraintHandlerBundle(
        on_decision_handlers=on_decision_handlers or _noop,
        method_invocation_handlers=method_invocation_handlers or _noop_method_invocation,
        on_next_consumers=on_next_consumers or _noop_consumer,
        on_next_mappings=on_next_mappings or _identity,
        filter_predicates=filter_predicates or _always_true,
        on_error_handlers=on_error_handlers or _noop_error_handler,
        on_error_mappings=on_error_mappings or _identity_error,
        resource_replacement=resource_replacement,
    )


def _make_permit_decision(**overrides: Any) -> AuthorizationDecision:
    defaults: dict[str, Any] = {"decision": Decision.PERMIT}
    defaults.update(overrides)
    return AuthorizationDecision(**defaults)


def _make_deny_decision(**overrides: Any) -> AuthorizationDecision:
    defaults: dict[str, Any] = {"decision": Decision.DENY}
    defaults.update(overrides)
    return AuthorizationDecision(**defaults)


def _make_subscription() -> AuthorizationSubscription:
    return AuthorizationSubscription(subject="user", action="read", resource="data")


@pytest.fixture
def pdp_client() -> AsyncMock:
    client = AsyncMock()
    client.decide_once = AsyncMock()
    return client


@pytest.fixture
def constraint_service() -> MagicMock:
    service = MagicMock(spec=ConstraintEnforcementService)
    return service


@pytest.fixture
def protected_function() -> AsyncMock:
    fn = AsyncMock(return_value="result")
    fn.__name__ = "test_fn"
    return fn


class TestPreEnforce:
    """PreEnforce: authorize before method execution."""

    async def test_whenPermitThenMethodExecutes(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        constraint_service.pre_enforce_bundle_for.return_value = _make_bundle()

        result = await pre_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription=_make_subscription(),
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
        )

        assert result == "result"
        protected_function.assert_awaited_once()

    async def test_whenDenyThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_deny_decision()
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        protected_function.assert_not_awaited()

    async def test_whenIndeterminateThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = AuthorizationDecision(
            decision=Decision.INDETERMINATE,
        )
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        protected_function.assert_not_awaited()

    async def test_whenNotApplicableThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = AuthorizationDecision(
            decision=Decision.NOT_APPLICABLE,
        )
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        protected_function.assert_not_awaited()

    async def test_whenUnhandledObligationThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        constraint_service.pre_enforce_bundle_for.side_effect = AccessDeniedError(
            "unhandled obligation",
        )
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        protected_function.assert_not_awaited()

    async def test_whenOnDecisionHandlerFailsThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        bundle = _make_bundle(
            on_decision_handlers=MagicMock(side_effect=AccessDeniedError("obligation failed")),
        )
        constraint_service.pre_enforce_bundle_for.return_value = bundle
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        protected_function.assert_not_awaited()

    async def test_whenMethodInvocationHandlersModifyArgsThenModifiedArgsUsed(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()

        def modify_args(ctx: MethodInvocationContext) -> None:
            ctx.args = ["modified_arg"]
            ctx.kwargs = {"key": "modified_value"}

        bundle = _make_bundle(method_invocation_handlers=modify_args)
        constraint_service.pre_enforce_bundle_for.return_value = bundle

        received_args: list[Any] = []
        received_kwargs: list[dict[str, Any]] = []

        async def capturing_function(*args: Any, **kwargs: Any) -> str:
            received_args.extend(args)
            received_kwargs.append(kwargs)
            return "result"

        result = await pre_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription=_make_subscription(),
            protected_function=capturing_function,
            args=["original_arg"],
            kwargs={"key": "original_value"},
            function_name="test_fn",
        )

        assert result == "result"
        assert received_args == ["modified_arg"]
        assert received_kwargs == [{"key": "modified_value"}]

    async def test_whenProtectedMethodThrowsThenErrorHandlersInvokedAndReRaised(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        original_error = RuntimeError("method failed")
        transformed_error = ValueError("transformed")

        error_handler_called = []
        bundle = _make_bundle(
            on_error_handlers=lambda e: error_handler_called.append(e),
            on_error_mappings=lambda _e: transformed_error,
        )
        constraint_service.pre_enforce_bundle_for.return_value = bundle

        async def failing_function() -> None:
            raise original_error

        with pytest.raises(ValueError, match="transformed") as exc_info:
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=failing_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        assert exc_info.value is transformed_error
        assert exc_info.value.__cause__ is original_error
        assert error_handler_called == [original_error]

    async def test_whenReturnValueHandlersTransformResultThenTransformedReturned(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        bundle = _make_bundle(on_next_mappings=lambda v: v.upper())
        constraint_service.pre_enforce_bundle_for.return_value = bundle

        result = await pre_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription=_make_subscription(),
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
        )

        assert result == "RESULT"

    async def test_whenDecisionHasResourceThenResourceReplacesReturnValue(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision(
            resource={"replacement": True},
        )
        bundle = _make_bundle(resource_replacement={"replacement": True})
        constraint_service.pre_enforce_bundle_for.return_value = bundle

        result = await pre_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription=_make_subscription(),
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
        )

        assert result == {"replacement": True}

    async def test_whenOnDenyCallbackThenCallbackResultReturned(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        deny_decision = _make_deny_decision()
        pdp_client.decide_once.return_value = deny_decision
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        on_deny = MagicMock(return_value="denied_response")

        result = await pre_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription=_make_subscription(),
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
            on_deny=on_deny,
        )

        assert result == "denied_response"
        on_deny.assert_called_once_with(deny_decision)

    async def test_whenOnDenyCallbackFailsThenAccessDeniedRaised(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_deny_decision()
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        on_deny = MagicMock(side_effect=RuntimeError("callback failed"))

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
                on_deny=on_deny,
            )

    async def test_whenMethodInvocationHandlerFailsThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()

        def failing_handler(_ctx: MethodInvocationContext) -> None:
            raise AccessDeniedError("invocation handler failed")

        bundle = _make_bundle(method_invocation_handlers=failing_handler)
        constraint_service.pre_enforce_bundle_for.return_value = bundle
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        protected_function.assert_not_awaited()

    async def test_whenOnNextHandlerFailsThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        bundle = _make_bundle(
            filter_predicates=lambda _v: False,
        )
        constraint_service.pre_enforce_bundle_for.return_value = bundle
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )


class TestPostEnforce:
    """PostEnforce: authorize after method execution."""

    async def test_whenPermitThenMethodRunsFirstThenAuthorized(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        constraint_service.post_enforce_bundle_for.return_value = _make_bundle()

        result = await post_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription_builder=lambda rv: _make_subscription(),
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
        )

        assert result == "result"
        protected_function.assert_awaited_once()

    async def test_whenDenyThenMethodRunsButResultDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_deny_decision()
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await post_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription_builder=lambda rv: _make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        # Method STILL executes in PostEnforce before authorization
        protected_function.assert_awaited_once()

    async def test_whenMethodThrowsThenExceptionPropagatesDirectly(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
    ) -> None:
        original_error = RuntimeError("method failed")

        async def failing_function() -> None:
            raise original_error

        with pytest.raises(RuntimeError, match="method failed"):
            await post_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription_builder=lambda rv: _make_subscription(),
                protected_function=failing_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        # PDP should never be consulted when method throws (F17)
        pdp_client.decide_once.assert_not_awaited()

    async def test_whenSubscriptionBuilderReceivesReturnValue(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        constraint_service.post_enforce_bundle_for.return_value = _make_bundle()

        received_values: list[Any] = []

        def subscription_builder(return_value: Any) -> AuthorizationSubscription:
            received_values.append(return_value)
            return AuthorizationSubscription(
                subject="user", action="read", resource=return_value,
            )

        await post_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription_builder=subscription_builder,
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
        )

        assert received_values == ["result"]

    async def test_whenPostEnforceThenNoMethodInvocationHandlers(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        constraint_service.post_enforce_bundle_for.return_value = _make_bundle()

        await post_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription_builder=lambda rv: _make_subscription(),
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
        )

        # post_enforce_bundle_for is used (not pre_enforce_bundle_for)
        constraint_service.post_enforce_bundle_for.assert_called_once()
        constraint_service.pre_enforce_bundle_for.assert_not_called()

    async def test_whenDecisionHasResourceThenResourceReplacesReturnValue(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision(
            resource={"replacement": True},
        )
        bundle = _make_bundle(resource_replacement={"replacement": True})
        constraint_service.post_enforce_bundle_for.return_value = bundle

        result = await post_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription_builder=lambda rv: _make_subscription(),
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
        )

        assert result == {"replacement": True}

    async def test_whenOnDenyCallbackThenCallbackResultReturned(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        deny_decision = _make_deny_decision()
        pdp_client.decide_once.return_value = deny_decision
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        on_deny = MagicMock(return_value="denied_response")

        result = await post_enforce(
            pdp_client=pdp_client,
            constraint_service=constraint_service,
            subscription_builder=lambda rv: _make_subscription(),
            protected_function=protected_function,
            args=[],
            kwargs={},
            function_name="test_fn",
            on_deny=on_deny,
        )

        assert result == "denied_response"
        on_deny.assert_called_once_with(deny_decision)

    async def test_whenUnhandledObligationThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        constraint_service.post_enforce_bundle_for.side_effect = AccessDeniedError(
            "unhandled obligation",
        )
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await post_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription_builder=lambda rv: _make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

    async def test_whenOnDecisionHandlerFailsThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        bundle = _make_bundle(
            on_decision_handlers=MagicMock(side_effect=AccessDeniedError("obligation failed")),
        )
        constraint_service.post_enforce_bundle_for.return_value = bundle
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await post_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription_builder=lambda rv: _make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

    async def test_whenOnNextHandlerFailsThenAccessDenied(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_permit_decision()
        bundle = _make_bundle(filter_predicates=lambda _v: False)
        constraint_service.post_enforce_bundle_for.return_value = bundle
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError):
            await post_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription_builder=lambda rv: _make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )


class TestDenyHandling:
    """Deny path: best-effort handlers, on_deny callback, error messages."""

    async def test_whenDenyThenBestEffortHandlersExecute(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_deny_decision()
        best_effort_called = []
        bundle = _make_bundle(
            on_decision_handlers=lambda: best_effort_called.append(True),
        )
        constraint_service.best_effort_bundle_for.return_value = bundle

        with pytest.raises(AccessDeniedError):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        assert best_effort_called == [True]

    async def test_whenBestEffortHandlerFailsThenDenyStillRaised(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_deny_decision()
        constraint_service.best_effort_bundle_for.side_effect = RuntimeError(
            "best effort failed",
        )

        with pytest.raises(AccessDeniedError, match=ERROR_ACCESS_DENIED):
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

    async def test_whenAccessDeniedThenGenericMessage(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_deny_decision()
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        with pytest.raises(AccessDeniedError) as exc_info:
            await pre_enforce(
                pdp_client=pdp_client,
                constraint_service=constraint_service,
                subscription=_make_subscription(),
                protected_function=protected_function,
                args=[],
                kwargs={},
                function_name="test_fn",
            )

        # REQ-ERROR-1: generic message, no policy details leaked
        assert str(exc_info.value) == ERROR_ACCESS_DENIED

    async def test_whenOnDenyCallbackFailsThenWarnLogged(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_deny_decision()
        constraint_service.best_effort_bundle_for.return_value = _make_bundle()

        on_deny = MagicMock(side_effect=RuntimeError("callback failed"))

        with patch("sapl_base.enforcement.log") as mock_log:
            with pytest.raises(AccessDeniedError):
                await pre_enforce(
                    pdp_client=pdp_client,
                    constraint_service=constraint_service,
                    subscription=_make_subscription(),
                    protected_function=protected_function,
                    args=[],
                    kwargs={},
                    function_name="test_fn",
                    on_deny=on_deny,
                )

            mock_log.warning.assert_any_call(WARN_ON_DENY_CALLBACK_FAILED)

    async def test_whenBestEffortHandlerFailsThenWarnLogged(
        self,
        pdp_client: AsyncMock,
        constraint_service: MagicMock,
        protected_function: AsyncMock,
    ) -> None:
        pdp_client.decide_once.return_value = _make_deny_decision()
        constraint_service.best_effort_bundle_for.side_effect = RuntimeError(
            "best effort exploded",
        )

        with patch("sapl_base.enforcement.log") as mock_log:
            with pytest.raises(AccessDeniedError):
                await pre_enforce(
                    pdp_client=pdp_client,
                    constraint_service=constraint_service,
                    subscription=_make_subscription(),
                    protected_function=protected_function,
                    args=[],
                    kwargs={},
                    function_name="test_fn",
                )

            mock_log.warning.assert_any_call(WARN_BEST_EFFORT_FAILED)
