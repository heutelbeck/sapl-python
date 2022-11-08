import asyncio

from sapl_base.authorization_subscription_factory import client_request


class SAPLMiddleware:
    async_capable = True
    sync_capable = True

    def __init__(self, get_response):
        if get_response is None:
            raise ValueError("get_response must be provided.")
        self.get_response = get_response
        self._async_check()
        super().__init__()

    def __repr__(self):
        return "<%s get_response=%s>" % (
            self.__class__.__qualname__,
            getattr(
                self.get_response,
                "__qualname__",
                self.get_response.__class__.__name__,
            ),
        )

    def _async_check(self):
        """
        If get_response is a coroutine function, turns us into async mode so
        a thread is not consumed during a whole request.
        """
        if asyncio.iscoroutinefunction(self.get_response):
            # Mark the class as async-capable, but do the actual switch
            # inside __call__ to avoid swapping out dunder methods
            self._is_coroutine = asyncio.coroutines._is_coroutine
        else:
            self._is_coroutine = None

    def __call__(self, request):
        return self.process_request(request)

    def process_request(self, request):
        client_request.set(request)
        return self.get_response(request)
