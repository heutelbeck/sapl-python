from sapl_base.constraint_handling.constraint_handler_bundle import ConstraintHandlerBundle
from sapl_base.constraint_handling.constraint_handler_provider import OnDecisionConstraintHandlerProvider, \
    ErrorConstraintHandlerProvider, FunctionArgumentsConstraintHandlerProvider, ResultConstraintHandlerProvider, \
    ConstraintHandlerProvider
from sapl_base.decision import Decision
from sapl_base.policy_enforcement_points.policy_enforcement_point import permission_denied_exception


class ConstraintHandlerService:
    """
    Class, which contains all available ConstraintHandlerProvider and creates ConstraintHandlerBundle with
    responsible ConstraintHandlerProvider to handle the Obligations and Advices of a Decision
    """


    def __init__(self):
        self.on_decision_handler : list[OnDecisionConstraintHandlerProvider]= []
        self.error_handler : list[ErrorConstraintHandlerProvider]= []
        self.result_handler : list[ResultConstraintHandlerProvider]= []
        self.function_arguments_mapper : list[FunctionArgumentsConstraintHandlerProvider]= []

    def register_decision_constraint_handler_provider(self, providers:
    list[OnDecisionConstraintHandlerProvider] | OnDecisionConstraintHandlerProvider):
        try:
            for provider in providers:
                self.on_decision_handler.append(provider)
        except TypeError:
            self.on_decision_handler.append(providers)

    def register_error_constraint_handler_provider(self, providers: list[ErrorConstraintHandlerProvider] | ErrorConstraintHandlerProvider):
        try:
            for provider in providers:
                self.error_handler.append(provider)
        except TypeError:
            self.error_handler.append(providers)

    def register_result_constraint_handler_provider(self, providers: list[ResultConstraintHandlerProvider] | ResultConstraintHandlerProvider):
        try:
            for provider in providers:
                self.result_handler.append(provider)
        except TypeError:
            self.result_handler.append(providers)

    def register_function_arguments_constraint_handler_provider(self, providers: list[
        FunctionArgumentsConstraintHandlerProvider] | FunctionArgumentsConstraintHandlerProvider):
        try:
            for provider in providers:
                self.function_arguments_mapper.append(provider)
        except TypeError:
            self.function_arguments_mapper.append(providers)

    def build_post_enforce_bundle(self, decision: Decision) -> ConstraintHandlerBundle:
        """
        Create a ConstraintHandlerBundle for a function, which was decorated with @post_enforce, or
        @pre_and_post_enforce to handle the obligations and advices of the decision

        :param decision: decision from the PolicyDecisionPoint
        :raise PermissionDenied Exception, when at least one obligation can't be handled:
        :return: A ConstraintHandlerBundle, containing all ConstraintHandlerProvider, which are responsible for the
        obligations and advices of the decision

        """

        unhandled_obligations = []
        for obligation in decision.obligations:
            unhandled_obligations.append(obligation)
        on_decision_handler, error_handler, result_handler = self._build_basic_bundle(decision.obligations,
                                                                                      decision.advice,
                                                                                      unhandled_obligations)
        if unhandled_obligations:
            raise permission_denied_exception
        return ConstraintHandlerBundle(on_decision_handler, error_handler, result_handler)

    def build_pre_enforce_bundle(self, decision: Decision) -> ConstraintHandlerBundle:
        """
        Create a ConstraintHandlerBundle for a function, which was decorated with @pre_enforce, or
        @pre_and_post_enforce to handle the obligations and advices of the decision

        :param decision: decision from the PolicyDecisionPoint
        :raise PermissionDenied Exception, when at least one obligation can't be handled:
        :return: A ConstraintHandlerBundle, containing all ConstraintHandlerProvider, which are responsible for the
        obligations and advices of the decision
        """

        unhandled_obligations = []
        for obligation in decision.obligations:
            unhandled_obligations.append(obligation)
        on_decision_handler, error_handler, result_handler = self._build_basic_bundle(decision.obligations,
                                                                                      decision.advice,
                                                                                      unhandled_obligations)

        function_arguments_mapper = self._create_function_argument_mapper(decision.obligations, unhandled_obligations)
        function_arguments_mapper.extend(self._create_function_argument_mapper(decision.advice, []))
        if unhandled_obligations:
            raise permission_denied_exception
        return ConstraintHandlerBundle(on_decision_handler, error_handler, result_handler, function_arguments_mapper)

    def _build_basic_bundle(self, obligations: list, advices: list, unhandled_obligations: list) \
            -> tuple[list[OnDecisionConstraintHandlerProvider], list[ErrorConstraintHandlerProvider],
            list[ResultConstraintHandlerProvider]]:
        """
        Create lists of ConstraintHandlerProvider which are responsible for the given obligations and advices

        :param obligations: a constraint, which must be handled by a ConstraintHandlerProvider
        :param advices: a constraint which should be handled by a ConstraintHandlerProvider
        :param unhandled_obligations: list of all obligations, for which no responsible ConstraintHandlerProvider has been found
        :return: Tuple of three lists with ConstraintHandlerProvider
        """
        on_decision_handler = self._create_on_decision_handler(obligations, unhandled_obligations)
        on_decision_handler.extend(self._create_on_decision_handler(advices, []))

        error_handler = self._create_on_error_handler(obligations, unhandled_obligations)
        error_handler.extend(self._create_on_error_handler(advices, []))

        result_handler = self._create_result_handler(obligations, unhandled_obligations)
        result_handler.extend(self._create_result_handler(advices, []))

        return on_decision_handler, error_handler, result_handler

    def _create_on_decision_handler(self, constraints: list, unhandled_obligations: list) -> \
            list[OnDecisionConstraintHandlerProvider]:
        """
        Creates a list with OnDecisionConstraintHandlerProvider, which are responsible for the given constraints

        :param constraints: Constraints to handle
        :param unhandled_obligations: list of all obligations, for which no responsible ConstraintHandlerProvider has been found
        :return: A list of OnDecisionConstraintHandlerProvider sorted by their priority, which are responsible for the given constraints
        """

        handler_list = []
        for constraint in constraints:
            for handler in self.on_decision_handler:
                self._add_responsible_handler(handler, constraint, handler_list, unhandled_obligations)
        handler_list.sort(key=lambda provider: provider.priority())
        return handler_list

    def _create_on_error_handler(self, constraints: list, unhandled_obligations: list) -> \
            list[ErrorConstraintHandlerProvider]:
        """
        Creates a list with ErrorConstraintHandlerProvider, which are responsible for the given constraints

        :param constraints: Constraints to handle
        :param unhandled_obligations: list of all obligations, for which no responsible ConstraintHandlerProvider has been found
        :return: A list of ErrorConstraintHandlerProvider sorted by their priority, which are responsible for the given constraints
        """

        handler_list = []

        for constraint in constraints:
            for handler in self.error_handler:
                self._add_responsible_handler(handler, constraint, handler_list, unhandled_obligations)
        handler_list.sort(key=lambda provider: provider.priority())
        return handler_list

    def _create_result_handler(self, constraints: list, unhandled_obligations: list) -> \
            list[ResultConstraintHandlerProvider]:
        """
        Creates a list with ResultConstraintHandlerProvider, which are responsible for the given constraints

        :param constraints: Constraints to handle
        :param unhandled_obligations: list of all obligations, for which no responsible ConstraintHandlerProvider has been found
        :return: A list of ResultConstraintHandlerProvider sorted by their priority, which are responsible for the given constraints
        """

        handler_list = []
        for constraint in constraints:
            for handler in self.result_handler:
                self._add_responsible_handler(handler, constraint, handler_list, unhandled_obligations)
        handler_list.sort(key=lambda provider: provider.priority())
        return handler_list

    def _create_function_argument_mapper(self, constraints: list, unhandled_obligations: list) -> \
            list[FunctionArgumentsConstraintHandlerProvider]:
        """
        Creates a list with FunctionArgumentsConstraintHandlerProvider, which are responsible for the given constraints

        :param constraints: Constraints to handle
        :param unhandled_obligations: list of all obligations, for which no responsible ConstraintHandlerProvider has been found
        :return: A list of FunctionArgumentsConstraintHandlerProvider sorted by their priority, which are responsible for the given constraints
        """

        handler_list = []
        for constraint in constraints:
            for handler in self.function_arguments_mapper:
                self._add_responsible_handler(handler, constraint, handler_list, unhandled_obligations)
        handler_list.sort(key=lambda provider: provider.priority())
        return handler_list

    @staticmethod
    def _add_responsible_handler(handler: ConstraintHandlerProvider, constraint, handler_list: list,
                                 unhandled_obligations: list) -> None:
        """
        Checks if the given ConstraintHandlerProvider is responsible to handle the given constraint. When the
        ConstraintHandlerProvider is responsible, it is added to a list of ConstraintHandlerProvider, which are used to
        create a ConstraintHandlerBundle. The constraint is removed from the list of obligations, which need to be
        handled

        :param handler: ConstraintHandlerProvider to check if it is responsible for the given constraint

        :param constraint: A constraint for the ConstraintHandlerProvider to check if it is responsible for it

        :param handler_list: A List containing all ConstraintHandlerProvider, which are responsible for given constraints

        :param unhandled_obligations: List of obligations, for which no responsible ConstraintHandlerProvider has been found so far
        """
        if handler.is_responsible(constraint):
            handler_list.append(handler)
            try:
                unhandled_obligations.remove(constraint)
            except ValueError:
                pass


constraint_handler_service = ConstraintHandlerService()
framework_permission_denied: ErrorConstraintHandlerProvider | None = None
