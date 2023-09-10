import contextvars
from typing import Dict

from channels.consumer import AsyncConsumer
from django.db.models import QuerySet, Manager, Model
from django.forms import model_to_dict
from django.urls import ResolverMatch
from django.views import View

from sapl_base.authorization_subscription_factory import AuthorizationSubscriptionFactory, client_request, consumer_scope
from sapl_base.authorization_subscriptions import AuthorizationSubscription


def identify_type(values: Dict) -> str:
    """
    Identifies the type of the decorated function

    :param values: dict containing all values needed to create the AuthorizationSubscription
    :return: The name of the type of the decorated function
    """
    if 'self' in values:
        try:
            classes_names = values['self']
            if isinstance(classes_names, View):
                return 'View'
            if isinstance(classes_names, QuerySet):
                return 'Queryset'
            if isinstance(classes_names, Manager):
                return 'Manager'
            if isinstance(classes_names, AsyncConsumer):
                return 'Consumer'
        except Exception:
            pass
    return 'View'


def get_authorization(request):
    if request.headers.get("Authorization") is not None:
        authorization = request.headers.get("Authorization")
        if authorization.find('Bearer ') == 0:
            return authorization[7:]
        else:
            return None


class DjangoAuthorizationSubscriptionFactory(AuthorizationSubscriptionFactory):
    """
    AuthorizationSubscriptionFactory for Django projects
    Creates AuthorizationSubscription, when SAPL is used in a Django project.
    """

    STREAMING_ENFORCEMENTS = ('enforce_till_denied', 'enforce_drop_while_denied','enforce_recoverable_if_denied')
    POST_ENFORCE_CLASSES = ('Manager', 'Queryset')

    def _default_action_function(self, values: Dict) -> Dict:
        """
        Create a dict which is used as action to create an AuthorizationSubscription
        :param values: dict containing all values needed to create an AuthorizationSubscription
        :param fn_type: Type of the decorated function
        :return: A dictionary which will be provided as action, when an AuthorizationSubscription is created
        """
        action = {}
        function_para = {}

        if 'self' in values:
            function_para.update({'class': values['self'].__class__.__name__})
        try:
            function_para.update({'function_name': values['function'].__name__})
        except Exception:
            pass
        function_para.update({'type': values['type']})
        request_para = {}
        if values.get('request') is not None:
            request = values['request']
            resolver: ResolverMatch = request.resolver_match
            request_para.update({'path': request.path})
            request_para.update({'method': request.method})
            request_para.update({'view_name': resolver.view_name})
            request_para.update({'route': resolver.route})
            request_para.update({'url_name': resolver.url_name})
        elif values.get('scope') is not None:
            request = values['scope']
            request_para.update({'path': request["path"]})
            request_para.update({'type': request["type"]})


        action.update({'request': request_para})
        action.update({'function': function_para})
        return action

    def _default_resource_function(self, values: Dict) -> Dict:
        """
        Create a dict which is used as resource to create an AuthorizationSubscription
        :param values: dict containing all values needed to create an AuthorizationSubscription
        :return: A dictionary which will be provided as resource, when an AuthorizationSubscription is created
        """
        resource = {}
        request_resources = {}
        function_resources = {}

        if values.get('request') is not None:
            request = values['request']
            resolver: ResolverMatch = request.resolver_match
            request_method = request.method
            if request_method == 'GET':
                request_resources.update({'GET': request.GET.dict()})
            if request_method == 'POST':
                request_resources.update({'POST': request.POST.dict()})
            function_resources.update({'url_kwargs': resolver.kwargs})

        elif values.get('scope') is not None:
            request = values['scope']
            function_resources.update({'url_kwargs': request["url_route"]["kwargs"]})
            function_resources.update({'cookies': request["cookies"]})
            function_resources.update({'asgi': request["asgi"]})


        args_copy: dict = values.get('args').copy()
        if 'self' in args_copy:
            args_copy.pop('self')
        function_resources.update({'kwargs': self._map_model_to_dict(args_copy)})
        if 'return_value' in values:
            return_value = values['return_value']
            if isinstance(return_value, Model):
                resource.update({'return_value': model_to_dict(return_value)})
            else:
                resource.update({'return_value': return_value})

        resource.update({
            'request': request_resources,
            'function': function_resources})

        return resource

    @staticmethod
    def _map_model_to_dict(kwargs: Dict) -> Dict:
        """
        Creates a dict from a Model object to make it serializable
        :param kwargs: dict which can contain object of Model class
        :return: dict with objects of Model class mapped to dict
        """
        for k, v in kwargs.items():
            if isinstance(v, Model):
                kwargs.update({k: model_to_dict(v)})
        return kwargs

    def _default_subject_function(self, values: Dict):
        """
        Create a dict which is used as subject to create an AuthorizationSubscription
        :param values: dict containing all values needed to create an AuthorizationSubscription
        :return: A dictionary which will be provided as subject, when an AuthorizationSubscription is created
        """
        request = values.get('request')
        if request is None:
            request = values.get('scope')
            user = request["user"]
        else:
            user = request.user
        try:
            if user.is_anonymous:
                if request.headers.get("Authorization") is not None:
                    return {"authorization": get_authorization(request)}
                return 'anonymous'
        except Exception:
            return 'anonymous'
        subj = {}
        subj.update({'user_id': user.id,
                     'username': user.username,
                     'first_name': user.first_name,
                     'last_name': user.last_name,
                     'is_active': user.is_active,
                     'is_superuser': user.is_superuser,
                     'permissions': list(user.get_all_permissions()),
                     'groups': [group.name for group in list(user.groups.all())],
                     'last_login': user.last_login,
                     'is_authenticated': user.is_authenticated,
                     })
        try:
            subj.update({'authorization': get_authorization(request)})
        except Exception:
            pass
        return subj

    def create_authorization_subscription(self, values: Dict, subject, action, resource,
                                          environment, scope, enforcement_type)-> AuthorizationSubscription:
        """
        Create an AuthorizationSubscription with the given dictionary and arguments

        The returned AuthorizationSubscription is dependent of the framework and the decorated function

        :param enforcement_type: the type of enforcement, with which the function is decorated
        :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
        :param values: Dictionary which contains data related to the decorated function (class if present, function and dict with named args )
        :param subject: subject with which the function was decorated. None if not specified
        :param action:  action with which the function was decorated. None if not specified
        :param resource: resource with which the function was decorated. None if not specified
        :param environment: environment with which the function was decorated. None if not specified
        :return: An authorization_subscription which can be sent to a pdp to get an authorization_decision
        """
        fn_type: str
        self._add_contextvar_to_values(values)
        if scope == "automatic":
            fn_type = identify_type(values)
        else:
            fn_type = scope

        self._valid_combination(fn_type, enforcement_type)
        values.update({'type': fn_type})

        authz = self._create_subscription(values, subject, action, resource, environment)
        return authz

    def _valid_combination(self, fn_type: str, enforcement_type: str) -> None:
        """
        Checks if the combination of the type of the decorated function and the type of enforcement is valid

        :param fn_type: Type of decorated function
        :param enforcement_type: Type of enforcement with which the function is decorated
        """
        if fn_type == 'View' and enforcement_type == 'pre_enforce':
            return
        if fn_type == 'Consumer' and enforcement_type in self.STREAMING_ENFORCEMENTS:
            return
        if fn_type in self.POST_ENFORCE_CLASSES and enforcement_type in ('post_enforce', 'pre_enforce'):
            return
        if fn_type == 'Template' and enforcement_type == 'pre_enforce':
            return
        raise

    def _add_contextvar_to_values(self, values: Dict) -> None:
        """
        Adds the request made to the dict which is used to create the AuthorizationSubscription
        :param values: A dict object containing all values needed to create an AuthorizationSubscription
        """
        if client_request.get('request') != 'request':
            values.update({'request': client_request.get('request')})
        if consumer_scope.get('scope') != 'scope':
            values.update({'scope': consumer_scope.get()})