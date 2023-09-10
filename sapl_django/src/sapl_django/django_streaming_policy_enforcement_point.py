import asyncio
import json
import asgiref.sync
from channels.generic.websocket import AsyncWebsocketConsumer

from sapl_base.policy_enforcement_points.streaming_policy_enforcement_point import StreamingPolicyEnforcementPoint
from sapl_base.authorization_subscription_factory import consumer_scope


class DjangoStreamingPolicyEnforcementPoint(StreamingPolicyEnforcementPoint):

    instance: AsyncWebsocketConsumer

    def __init__(self, cl, *args, instance, type_of_enforcement, **kwargs):
        super().__init__(cl, *args, instance=instance, type_of_enforcement=type_of_enforcement, **kwargs)
        self.decorated_class = cl
        self.instance = self.values_dict.get("self")
        if self.instance is None or not isinstance(self.instance, AsyncWebsocketConsumer):
            raise Exception
        self.stream_task = asyncio.current_task()

    async def _cancel_stream(self):
        """
        Cancels the Websocket and any open Streams to the PDP
        """

        try:
            await self.instance.close()
        except Exception:
            pass
        self._decision_task.cancel()

    async def _handle_deny_on_recoverable(self):
        """
        Send a JSON to the client with an errormessage, that the Connection can be recovered
        """
        await self.send(text_data=json.dumps({"error": "can be recovered"}))


    async def websocket_disconnect(self, message):
        """
        Cancels the Stream to a PDP before calling the method websocket_disconnect
        :param message:
        """
        self._decision_task.cancel()
        await self.instance.original_websocket_disconnect(message)



    async def send(self, text_data=None, bytes_data=None, close=False):
        """
        Ensure that permission is granted before executing the ResultConstraintHandler and invoking the original send
        method of the AsyncWebsocketConsumer.

        If any exceptions occur within the ResultConstraintHandler, they will be handled by the pre-existing
        ErrorConstraintHandler within the ConstraintHandlerBundle before being raised as an exception.
        """
        if self._current_decision.decision != "PERMIT":
            return
        try:
            if text_data is not None:
                result = self.constraint_handler_bundle.execute_result_handler(text_data)
                await self.instance.original_send(text_data=result, bytes_data=bytes_data, close=close)
            elif bytes_data is not None:
                result = self.constraint_handler_bundle.execute_result_handler(bytes_data)
                await self.instance.original_send(text_data=result, bytes_data=result, close=close)
            else:
                raise ValueError("You must pass one of bytes_data or text_data")
        except Exception as e:
            self._fail_with_bundle(e)
        if close:
            await self.instance.close(close)

    def replace_methods(self):
        """
        Assign the original methods to separate variables and substitute the original methods of the decorated
        AsyncWebsocketConsumer with those belonging to the StreamingPolicyEnforcementPoint.
        """
        self.instance.original_send = self.instance.send
        self.instance.send = self.send
        self.instance.original_websocket_disconnect = self.instance.websocket_disconnect
        self.instance.websocket_disconnect = self.websocket_disconnect

    async def start_stream_and_connection(self, subscription):
        """
        Open a Connection to a PDP to receive Decisions for the provided Subscription and call the connect method of the
        decorated WebsocketConsumer
        :param subscription: The Authorization Subscription which is send to a PDP and for which Decisions are requested
        """
        decision_stream = await self.request_decision(subscription)
        self._decision_task = asyncio.create_task(decision_stream)
        await self.instance.original_connect()



    def enforce_till_denied(self, subject, action, resource, environment, scope):
        """
        All Data send from the decorated AsyncWebsocketConsumer will be sent as long as permission is granted and the constraints can be
        handled. However, if either the permission is revoked or the constraints can't be handled, the AsyncWebsocketConsumer will
        be closed, concluding its operation.

        :param subject: subject of an authorization_subscription or a function to create the subject
        :param action: action of an authorization_subscription or a function to create the action
        :param resource: resource of an authorization_subscription or a function to create the resource
        :param environment: environment of an authorization_subscription or a function to create the environment
        :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
        """

        async def connect():
            consumer_scope.set(self.instance.scope)
            subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource,
                                                  environment,
                                                  scope, self.type_of_enforcement)
            await self.start_stream_and_connection(subscription)

        self.instance.original_connect = self.instance.connect
        self.instance.connect = connect
        self.replace_methods()



    def drop_while_denied(self, subject, action, resource, environment, scope):
        """
        Once permission is granted, the obligations and advices outlined in the current decision will be applied to every
        data sent by the decorated AsyncWebsocketConsumer, before they are sent to the client. However, if access is
        denied, all data won't be sent until permission is reinstated. Once permission is granted again,
        the AsyncWebsocketConsumer can send data again.

        :param subject: subject of an authorization_subscription or a function to create the subject
        :param action: action of an authorization_subscription or a function to create the action
        :param resource: resource of an authorization_subscription or a function to create the resource
        :param environment: environment of an authorization_subscription or a function to create the environment
        :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
        """



        async def connect():
            consumer_scope.set(self.instance.scope)
            subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource,
                                                  environment,
                                                  scope, self.type_of_enforcement)
            await self.start_stream_and_connection(subscription)

        self.instance.original_connect = self.instance.connect
        self.instance.connect = connect

        self.replace_methods()

    def recoverable_if_denied(self, subject, action, resource, environment, scope,
                              handle_recoverable_deny_function):
        """
        Once permission is granted, the obligations and advices outlined in the current decision will be applied to every
        data sent by the decorated AsyncWebsocketConsumer, before they are sent to the client. However, if access is
        denied, any generated values will be discarded until permission is reinstated and the method
        _handle_deny_on_recoverable is called. Once permission is granted again, the AsyncWebsocketConsumer can send
        data again.

        :param subject: subject of an authorization_subscription or a function to create the subject
        :param action: action of an authorization_subscription or a function to create the action
        :param resource: resource of an authorization_subscription or a function to create the resource
        :param environment: environment of an authorization_subscription or a function to create the environment
        :param scope: Argument which creates a AuthorizationSubscription according to the given scope instead of evaluating the scope based on other parameter
        :param handle_recoverable_deny_function: Method which replaces the default method _handle_deny_on_recoverable and is called, when permission is revoked.
        """
        if handle_recoverable_deny_function is not None:
            self._handle_deny_on_recoverable = handle_recoverable_deny_function

        async def connect():
            consumer_scope.set(self.instance.scope)
            subscription = await asgiref.sync.sync_to_async(self._get_subscription)(subject, action, resource,
                                                  environment,
                                                  scope, self.type_of_enforcement)

            decision_stream = await self.request_decision(subscription)
            await self.instance.original_connect()
            if self._current_decision.decision != "PERMIT":
                await self._handle_deny_on_recoverable()

            self._decision_task = asyncio.create_task(decision_stream)


        self.instance.original_connect = self.instance.connect
        self.instance.connect = connect

        self.replace_methods()