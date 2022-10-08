from sapl_base.constraint_handling.constraint_handler_provider import OnDecisionConstraintHandlerProvider, \
    ErrorConstraintHandlerProvider, FunctionArgumentsConstraintHandlerProvider, ResultConstraintHandlerProvider


class ConstraintHandlerService:
    # TODO Search project for classes which inherit from ConstraintHandlerProvider and add them to the
    #  ConstraintHandlerService instead of registering all ConstraintHandler manually

    _on_decision_handler: list[OnDecisionConstraintHandlerProvider] = []
    _error_handler: list[ErrorConstraintHandlerProvider] = []
    _result_handler: list[ResultConstraintHandlerProvider] = []
    _function_arguments_mapper: list[FunctionArgumentsConstraintHandlerProvider] = []

    def __init__(self):
        pass

    def build_post_enforce_bundle(self):
        pass

    def build_pre_enforce_bundle(self):
        pass

    def _get_responsible_handler(self, constraints):
        pass


constraint_handler_service = ConstraintHandlerService()
