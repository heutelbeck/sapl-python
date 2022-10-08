from typing import Any

from sapl_base.constraint_handling.constraint_handler_provider import OnDecisionConstraintHandlerProvider, \
    ErrorConstraintHandlerProvider, ResultConstraintHandlerProvider, FunctionArgumentsConstraintHandlerProvider


class ConstraintHandlerBundle:
    # TODO Use a Dictionary instead of an array to distinguish which handler shall be called at what stage
    # TODO async handling of Constraints
    _on_decision_handler: list[OnDecisionConstraintHandlerProvider] = []
    _error_handler: list[ErrorConstraintHandlerProvider] = []
    _result_handler: list[ResultConstraintHandlerProvider] = []

    def execute_on_decision_handler(self, decision):
        for handler in self._on_decision_handler:
            handler.handle(decision)

    def execute_on_error_handler(self, exception: Exception):
        for handler in self._error_handler:
            handler.handle(exception)

    def execute_result_handler(self, result: Any) -> Any:
        current_result = result
        for handler in self._result_handler:
            current_result = handler.handle(result)
        return current_result


class PreEnforceConstraintHandlerBundle(ConstraintHandlerBundle):

    _function_arguments_mapper: list[FunctionArgumentsConstraintHandlerProvider] = []

    def execute_function_arguments_mapper(self, arguments: dict) -> None:
        for handler in self._function_arguments_mapper:
            handler.handle(arguments)
