import json

from django import template
from django.template import RequestContext
from django.template.base import Parser, Token, token_kwargs, NodeList

import sapl_base.authorization_subscription_factory as factory
import sapl_base.constraint_handling.constraint_handler_service as constraint_handler_service
import sapl_base.policy_decision_points as policy_decision_points
from sapl_base.constraint_handling.constraint_handler_bundle import ConstraintHandlerBundle
from sapl_base.decision import Decision

register = template.Library()


@register.tag
def enforce(parser: Parser, token: Token):
    """
    A Tag, which can be used in a template to use SAPL inside a template.
    Provided arguments will be used in a Node to create an AuthorizationSubscription
    """
    nodelist = parser.parse(('endenforce'))
    arguments = token.split_contents()[1:]
    kwargs = token_kwargs(arguments, parser)
    parser.delete_first_token()
    return EnforceNode(nodelist, kwargs)


def action_function(context: RequestContext):
    """
    Creates the action for the AuthorizationSubscription from the values of the request
    :param context: Context of the template which is rendered
    :return: Dictionary for the action of the AuthorizationSubscription
    """
    request = context.request
    resolver = request.resolver_match
    request_parameter = {
        'path': request.path,
        'method': request.method,
        'route': resolver.route,
        'url_name': resolver.url_name
    }
    return {'request': request_parameter, 'requested_type': 'template'}


def resource_function(context: RequestContext):
    """
    Creates the resource for the AuthorizationSubscription from the values of the request
    :param context: Context of the template which is rendered
    :return: Dictionary for the resource of the AuthorizationSubscription
    """
    request = context.request
    template_name = context.template_name
    request_resources = {}
    if request.method == 'GET':
        request_resources.update({'GET': request.GET.dict()})
    if request.method == 'POST':
        request_resources.update({'POST': request.POST.dict()})
    return {'request': request_resources, 'template_name': template_name}


def resolve_arguments(value, context: RequestContext):
    """
    Check if the provided argument is a function and resolve the value of the argument if it is not a function
    :param value: Argument, which is evaluated for its value
    :param context: Context in which this Tag is rendered
    :return: Resolved value of the provided argument
    """
    if callable(value):
        return value(context)
    try:
        argument = value.resolve(context)
    except Exception:
        return None
    try:
        json_dict = json.loads(argument)
        return json_dict
    except (TypeError, ValueError):
        return argument


class EnforceNode(template.Node):

    def __init__(self, nodelist, kwargs: dict):
        self.subject = kwargs.get('subject')
        self.action = kwargs.get('action') if kwargs.get('action') is not None else action_function
        self.resource = kwargs.get('resource') if kwargs.get('resource') is not None else resource_function
        self.environment = kwargs.get('environment')
        self.nodelist = nodelist
        self.denied_node_list = NodeList(nodelist.get_nodes_by_type(DeniedNode))

    def render(self, context: RequestContext):
        """
        Make a request to the PDP and render the Content based on the received Decision
        :param context: Context in which the template is rendered
        :return:
        """
        authorization_subscription = factory.auth_factory.create_authorization_subscription({},
                                                                                            resolve_arguments(self.subject, context),
                                                                                            resolve_arguments(self.action, context),
                                                                                            resolve_arguments(self.resource, context),
                                                                                            resolve_arguments(self.environment,context),
                                                                                            'Template',
                                                                                            'pre_enforce')

        decision = policy_decision_points.pdp.decide(authorization_subscription)
        if decision is None:
            decision = Decision.deny_decision()

        "Try to create a Constraint-handler Bundle and render the Content of the Deny Tag on error"
        constraint_handler_bundle: ConstraintHandlerBundle
        try:
            constraint_handler_bundle = constraint_handler_service.constraint_handler_service.build_pre_enforce_bundle(
                decision)
        except Exception:
            context.render_context['decision'] = Decision.deny_decision()
            return self.denied_node_list.render(context)

        "Try to execute the Constraint-handler Bundle and render the Content of the Deny Tag on error, or when permission is denied"
        try:
            constraint_handler_bundle.execute_on_decision_handler(decision)
        except Exception:
            decision = Decision.deny_decision()
        finally:
            context.render_context['decision'] = decision
            if decision.decision == 'DENY':
                return self.denied_node_list.render(context)
            return self.nodelist.render(context)


@register.tag
def deny(parser: Parser, token):
    """
    Tag, which can be placed between an 'enforce' and an 'endenforce' Tag.
    The Content after the Tag is only rendered, when the Permission is Denied.
    """
    nodelist = parser.parse(('endenforce'))
    return DeniedNode(nodelist)


class DeniedNode(template.Node):
    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        try:
            return '' if context.render_context['decision'].decision == "PERMIT" else self.nodelist.render(context)
        except Exception:
            return self.nodelist.render(context)
