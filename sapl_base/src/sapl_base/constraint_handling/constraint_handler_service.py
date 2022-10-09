from typing import Any, Callable, Union

from sapl_base.constraint_handling.constraint_handler_bundle import ConstraintHandlerBundle
from sapl_base.constraint_handling.constraint_handler_provider import OnDecisionConstraintHandlerProvider, \
    ErrorConstraintHandlerProvider, FunctionArgumentsConstraintHandlerProvider, ResultConstraintHandlerProvider, \
    ConstraintHandlerProvider


class ConstraintHandlerService:
    # TODO Search project for classes which inherit from ConstraintHandlerProvider and add them to the
    #  ConstraintHandlerService instead of registering all ConstraintHandler manually

    _on_decision_handler: list[OnDecisionConstraintHandlerProvider] = []
    _error_handler: list[ErrorConstraintHandlerProvider] = []
    _result_handler: list[ResultConstraintHandlerProvider] = []
    _function_arguments_mapper: list[FunctionArgumentsConstraintHandlerProvider] = []

    def __init__(self):
        pass

    def build_post_enforce_bundle(self, decision) -> ConstraintHandlerBundle:
        obligations, advices = self._get_obligations_and_advices(decision)
        unhandled_obligations = []
        for obligation in obligations:
            unhandled_obligations.append(obligation)
        on_decision_handler, error_handler, result_handler = self._build_basic_bundle(obligations, advices,
                                                                                      unhandled_obligations)

        if unhandled_obligations is not None:
            raise Exception
        return ConstraintHandlerBundle(on_decision_handler, error_handler, result_handler)

    def build_pre_enforce_bundle(self, decision) -> ConstraintHandlerBundle:
        obligations, advices = self._get_obligations_and_advices(decision)
        unhandled_obligations = []
        for obligation in obligations:
            unhandled_obligations.append(obligation)
        on_decision_handler, error_handler, result_handler = self._build_basic_bundle(obligations, advices,
                                                                                      unhandled_obligations)

        function_arguments_mapper = self._create_function_argument_mapper(obligations, unhandled_obligations)
        function_arguments_mapper.extend(self._create_function_argument_mapper(advices))
        if unhandled_obligations is not None:
            raise Exception
        ConstraintHandlerBundle(on_decision_handler, error_handler, result_handler, function_arguments_mapper)

    def _build_basic_bundle(self, obligations, advices, unhandled_obligations):
        on_decision_handler = self._create_on_decision_handler(obligations, unhandled_obligations)
        on_decision_handler.extend(self._create_on_decision_handler(advices))
        error_handler = self._create_on_error_handler(obligations, unhandled_obligations)
        error_handler.extend(self._create_on_error_handler(advices))
        result_handler = self._create_result_handler(obligations, unhandled_obligations)
        result_handler.extend(self._create_result_handler(advices))
        return on_decision_handler, error_handler, result_handler

    def _create_on_decision_handler(self, constraints: list, unhandled_obligations: Union[list, None] = None) -> \
            list[Callable[[Any], None]]:
        if unhandled_obligations is None:
            unhandled_obligations = []
        handler_list = []
        for constraint in constraints:
            for handler in self._on_decision_handler:
                self._add_responsible_handler(handler, constraint, handler_list, unhandled_obligations)
        handler_list.sort(key=lambda provider: provider.priority())
        return handler_list

    def _create_on_error_handler(self, constraints: list, unhandled_obligations: Union[list, None] = None) -> \
            list[Callable[[Exception], None]]:
        if unhandled_obligations is None:
            unhandled_obligations = []
        handler_list = []
        for constraint in constraints:
            for handler in self._error_handler:
                self._add_responsible_handler(handler, constraint, handler_list, unhandled_obligations)
        handler_list.sort(key=lambda provider: provider.priority())
        return handler_list

    def _create_result_handler(self, constraints: list, unhandled_obligations: Union[list, None] = None) -> \
            list[Callable[[Any], Any]]:
        if unhandled_obligations is None:
            unhandled_obligations = []
        handler_list = []
        for constraint in constraints:
            for handler in self._result_handler:
                self._add_responsible_handler(handler, constraint, handler_list, unhandled_obligations)
        handler_list.sort(key=lambda provider: provider.priority())
        return handler_list

    def _create_function_argument_mapper(self, constraints: list, unhandled_obligations: Union[list, None] = None) -> \
            list[Callable[[dict], None]]:
        if unhandled_obligations is None:
            unhandled_obligations = []
        handler_list = []
        for constraint in constraints:
            for handler in self._function_arguments_mapper:
                self._add_responsible_handler(handler, constraint, handler_list, unhandled_obligations)
        handler_list.sort(key=lambda provider: provider.priority())
        return handler_list

    @staticmethod
    def _add_responsible_handler(handler: ConstraintHandlerProvider, constraint, handler_list: list,
                                 unhandled_obligations: list):
        if handler.is_responsible(constraint):
            handler_list.append(handler)
            try:
                unhandled_obligations.remove(constraint)
            except ValueError:
                pass

    @staticmethod
    def _get_obligations_and_advices(decision):
        obligations = []
        advices = []
        if hasattr(decision, "obligation"):
            obligation = getattr(decision, "obligation")
            for item in obligation:
                obligations.append(item)
        if hasattr(decision, "advices"):
            advice = getattr(decision, "advices")
            for item in advice:
                advices.append(item)
        return obligations, advices


constraint_handler_service = ConstraintHandlerService()
