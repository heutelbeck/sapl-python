from flask import current_app, request

from sapl_base.authorization_subscription_factory import AuthorizationSubscriptionFactory


class FlaskAuthorizationSubscriptionFactory(AuthorizationSubscriptionFactory):

    def create_authorization_subscription(self, values: dict, subject, action, resource, environment, scope,
                                          enforcement_type):
        """
        Create an AuthorizationSubscription with the given dictionary and arguments

        :param enforcement_type: the type of enforcement, with which the function is decorated
        :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
        :param values: Dictionary which contains data related to the decorated function (class if present, function and dict with named args )
        :param subject: subject with which the function was decorated. None if not specified
        :param action:  action with which the function was decorated. None if not specified
        :param resource: resource with which the function was decorated. None if not specified
        :param environment: environment with which the function was decorated. None if not specified
        :return: An authorization_subscription which can be sent to a pdp to get an authorization_decision
        """
        authz = self._create_subscription(values, subject, action, resource, environment)
        return authz

    def _default_subject_function(self, values: dict) -> dict:
        """
        Default function returns an empty dict.
        The subject is composed of functions, which need to be provided by the developer of the flask application.

        :param values: Dict which contains
        the decorated function itself as  'function', the class of the decorated method as 'class' and the args and kwargs
        zipped in a dict as 'args'.

        :return: empty dict
        """
        return {}

    def _default_action_function(self, values: dict) -> dict:
        """
        The default function, which creates the action of an AuthorizationSubscription

        :param values: Dict which contains
        the decorated function itself as  'function', the class of the decorated method as 'class' and the args and kwargs
        zipped in a dict as 'args'.

        :return: A dict containing key-value pairs, which are set as action of the AuthorizationSubscription
        """
        action = {}
        function_para = {}
        if request.endpoint in current_app.view_functions:
            try:
                classname = current_app.view_functions.get(request.endpoint).view_class
                function_para.update({'class': classname.__name__})
            except Exception:
                pass
        function_para.update({'function_name': values['function'].__name__})
        request_para = {}
        request_para.update({'path': request.path})
        request_para.update({'method': request.method})
        request_para.update({'endpoint': request.endpoint})
        request_para.update({'route': request.root_url})
        request_para.update({'blueprint': request.blueprint})
        action.update({'request': request_para})
        action.update({'function': function_para})
        return action

    def _default_resource_function(self, values: dict) -> dict:
        """
        The default function, which creates the resource of an AuthorizationSubscription

        :param values: Dict which contains
        the decorated function itself as  'function', the class of the decorated method as 'class' and the args and
        kwargs zipped in a dict as 'args'.
        :return: A dict containing key-value pairs, which are set as resource of the AuthorizationSubscription
        """
        resource = {}
        request_method = request.method
        request_resources = {}
        function_resources = {}
        if request_method == 'GET':
            request_resources.update({'GET': request.args})
        if request_method == 'POST':
            if request.is_json:
                request_resources.update({'POST': request.json})
            elif request.form:
                request_resources.update({'POST': request.form})

        if 'return_value' in values:
            return_value = values['return_value']
            resource.update({'return_value': return_value})
        args_copy: dict = values.get('args').copy()
        if 'self' in args_copy:
            args_copy.pop('self')

        function_resources.update({'kwargs': args_copy})
        resource.update({
            'request': request_resources,
            'function': function_resources})

        return resource
