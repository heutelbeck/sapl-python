from typing import Any, Callable

from sapl_base.constraint_handling.constraint_handler_provider import FunctionArgumentsConstraintHandlerProvider, \
    ErrorConstraintHandlerProvider, OnDecisionConstraintHandlerProvider, ResultConstraintHandlerProvider, \
    ConstraintHandlerProvider
from sapl_base.decision import Decision


class ConstraintHandlerBundle:
    """
    Contains lists with handle() methods of all ConstraintHandlerProvider, which are responsible for the obligations
    and advices of the provided Decision. The ConstraintHandlerBundle is created by the ConstraintHandlerService and
    is only created, when for every obligation is at least one ConstraintHandlerProvider responsible, otherwise an
    Exception is thrown.
    """

    _on_decision_handler: list[Callable[[Decision], None]]
    _error_handler: list[Callable[[Exception], Exception]]
    _result_handler: list[Callable[[Any], Any]]
    _function_arguments_mapper: list[Callable[[dict], dict]]

    def __init__(self,
                 on_decision_handler: list[OnDecisionConstraintHandlerProvider],
                 error_handler: list[ErrorConstraintHandlerProvider],
                 result_handler: list[ResultConstraintHandlerProvider],
                 function_arguments_mapper: list[FunctionArgumentsConstraintHandlerProvider] = None):
        """
        :param on_decision_handler: sorted List of OnDecisionConstraintHandlerProvider, of which their handle()
        methods are saved as a list[Callable[[Decision], None]]
        :param error_handler: sorted List of ErrorConstraintHandlerProvider, of which their handle()
        methods are saved as a list[Callable[[Exception], Exception]]
        :param result_handler: sorted List of ResultConstraintHandlerProvider, of which their handle()
        methods are saved as a list[Callable[[Any], Any]]
        :param function_arguments_mapper: sorted List of FunctionArgumentsConstraintHandlerProvider, of which their handle()
        methods are saved as a list[Callable[[dict], dict]]
        """

        if function_arguments_mapper is not None:
            self._function_arguments_mapper = self._add_handler_to_bundle(function_arguments_mapper)
        else:
            self._function_arguments_mapper = []

        self._on_decision_handler = self._add_handler_to_bundle(on_decision_handler)

        self._result_handler = self._add_handler_to_bundle(result_handler)

        self._error_handler = self._add_handler_to_bundle(error_handler)

    @staticmethod
    def _add_handler_to_bundle(handler_provider_list: list[ConstraintHandlerProvider]) -> list[callable]:
        """
        Creates a list[callable] of the handle() methods from the provided list[ConstraintHandlerProvider]

        :param handler_provider_list: List of ConstraintHandlerProvider, of which the handle() methods are added to a
        list[callable]

        :return: list of the handle() methods from the provided list[ConstraintHandlerProvider]
        """
        callable_list = []
        for handler in handler_provider_list:
            callable_list.append(handler.handle)
        return callable_list

    def execute_on_decision_handler(self, decision: Decision) -> None:
        """
        calls the handle() method of every responsible OnDecisionConstraintHandlerProvider with the given decision as
        argument.

        :param decision: a Decision received from the PolicyDecisionPoint
        """
        try:
            for handler in self._on_decision_handler:
                handler(decision)
        except Exception as e:
            raise self.execute_on_error_handler(e)

    def execute_on_error_handler(self, exception: Exception) -> None:
        """
        calls the handle() method of every responsible ErrorConstraintHandlerProvider with the given exception as
        argument.

        :param exception: an exception which was thrown, which will be handled by the ErrorConstraintHandlerProvider
        :raise Exception:
        """
        current_exception = exception
        for handler in self._error_handler:
            current_exception = handler(current_exception)
        raise current_exception

    def execute_result_handler(self, result: Any) -> Any:
        """
        calls the handle() method of every responsible ResultConstraintHandlerProvider with the given result as
        argument.

        :param result: the result from executing the enforced function
        :return: An object, which will be treated as the result of the enforced function
        """
        current_result = result
        try:
            for handler in self._result_handler:
                current_result = handler(current_result)
            return current_result
        except Exception as e:
            raise self.execute_on_error_handler(e)

    def execute_function_arguments_mapper(self, arguments: dict) -> dict:
        """
        calls the handle() method of every responsible FunctionArgumentsConstraintHandlerProvider with the given dict as
        argument.

        :param arguments: a dict containing the arguments, with which the enforced function will be called
        :return: a dict, with which the enforced function will be called
        """
        args = arguments
        try:
            for handler in self._function_arguments_mapper:
                args = handler(args)
            return args
        except Exception as e:
            raise self.execute_on_error_handler(e)
