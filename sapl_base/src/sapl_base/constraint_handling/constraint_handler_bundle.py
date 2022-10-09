from typing import Any, Callable, Union


class ConstraintHandlerBundle:
    # TODO Use a Dictionary instead of an array to distinguish which handler shall be called at what stage
    # TODO async handling of Constraints
    _on_decision_handler: list[Callable[[Any], None]]  # Change to decision
    _error_handler: list[Callable[[Exception], None]]
    _result_handler: list[Callable[[Any], Any]]
    _function_arguments_mapper: list[Callable[[dict], None]]

    def __init__(self, on_decision_handler, error_handler, result_handler,
                 function_arguments_mapper: Union[list[Callable[[dict], None]], Any] = None):

        if function_arguments_mapper is None:
            self._function_arguments_mapper = []
        else:
            self._function_arguments_mapper = function_arguments_mapper
        self._on_decision_handler = on_decision_handler
        self._result_handler = result_handler
        self._error_handler = error_handler

    def execute_on_decision_handler(self, decision):
        try:
            for handler in self._on_decision_handler:
                handler(decision)
        except Exception as e:
            raise self.execute_on_error_handler(e)

    def execute_on_error_handler(self, exception: Exception):
        for handler in self._error_handler:
            exception = handler(exception)
        raise exception

    def execute_result_handler(self, result: Any) -> Any:
        current_result = result
        try:
            for handler in self._result_handler:
                current_result = handler(current_result)
        except Exception as e:
            raise self.execute_on_error_handler(e)
        return current_result

    def execute_function_arguments_mapper(self, arguments: dict) -> None:
        try:
            for handler in self._function_arguments_mapper:
                handler(arguments)
        except Exception as e:
            raise self.execute_on_error_handler(e)
