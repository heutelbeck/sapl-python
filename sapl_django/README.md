# SAPL Integration library for Django

This library provides decorators to enforce methods, functions, asyncGenerator and AsyncWebsocketConsumer with SAPL functionality, allowing you to implement attribute streaming based access control (ABAC) in a Django application.

If you're not familiar with ABAC, it's recommended that you first read the SAPL [documentation](https://sapl.io/documentation) to gain a better understanding of the underlying concepts.

## What is SAPL

SAPL is an evolution of ABAC that uses a publish/subscribe model instead of a request-response model. When a 
client sends an Authorization Subscription to the Policy Decision Point (PDP), it receives a stream of Decisions that 
can update the decision for the given Subscription for the client. The SAPL_Django library handles the functionality of 
updating and enforcing newly received Decisions in the background, allowing developers to focus on writing policies. A 
comprehensive SAPL documentation can be found on https://sapl.io, including a playground for writing policies.


## Demo Application

A public demo project is available, which shows how SAPL and the SAPL Django integration library is used in a Django Application

The demo project can be found on GitHub [here](https://github.com/heutelbeck/sapl-python-demos/tree/main/djangoDemo)


## how to install

The SAPL Django integration library is available on PyPI and can be installed using `pip`.
To install SAPL_Django run `pip install sapl_django`. 

## initialize the library

To use SAPL_Django, you need to install it as an application in your Django project by adding it to the `INSTALLED_APPS` 
list in your project's settings file, as shown in the example below. It's recommended to add it at the end of the list 
to ensure that other packages are already initialized.
```
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'sapl_django',
]
```
SAPL_Django requires access to the Request object that the server receives. To make this Request available to the 
library, you need to install a middleware that saves the Request in a `ContextVar`. You should add this middleware to the 
`MIDDLEWARE` list in your project's settings file. It's important to add it at the end to ensure that it has access to all 
the previous middleware. An example of how to add the SAPL_Django middleware to the `MIDDLEWARE` list is shown below.
```
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'sapl_django.sapl_request_middleware.SAPLMiddleware',
]
```

## How to configure SAPL_Django

The configuration is used to determine, how to connect to the PDP.
This PDP should be a SAPL server, for which a documented open source version is available on 
[GitHub](https://github.com/heutelbeck/sapl-policy-engine/tree/master/sapl-server-lt).

The configuration can be made by adding a `"POLICY_DECISION_POINT"` key to the settings of the project.
The default configuration looks like this:
```
POLICY_DECISION_POINT = {
    "dummy" : False,
    "debug": False,
    "base_url": "http://localhost:8080/api/pdp/",
    "key": "YJidgyT2mfdkbmL",
    "secret": "Fa4zvYQdiwHZVXh",
    "verify": False,
    "backoff_const_max_time": 3,
    "backoff_expo_max_value": 50
}

```
- dummy: Enables a dummy PDP, which is used instead of a remote PDP. This PDP always grants access and should never be used in production.
- debug: Enables debugging , which adds logging.
- base_url: The URL, where your PDP Server is located. This has to include the path `'/api/pdp/'` of the PDP Server. 
- key: Access to the API of the SAPL PDP Server requires "Basic Auth". The client key (username) can be set with this parameter.
  The default is the default implemented credentials of a [SAPL-Server-lt](https://github.com/heutelbeck/sapl-policy-engine/tree/master/sapl-server-lt)
- secret: The password which is used to get access to the API.
- verify:
- backoff_const_max_time: When an error occurs, while requesting a single Decision from the PDP, SAPL_Django does a retry. 
  This parameter determines, how many seconds the library should retry to connect, before it aborts and denies the access.
- backoff_expo_max_value: When an error occurs, while requesting a stream of Decision from the PDP, SAPL_Django does a retry with increasing intervalls between each retry.
  This parameter determines, how much seconds is the maximum time in seconds between each retry.
  

# How to use it

To secure a Django project with SAPL, developers can decorate the functions, methods, asyncGenerator and AsyncWebsocketConsumer that they want to 
enforce with SAPL decorators. The SAPL Django integration library is designed to be compatible with both ASGI and WSGI 
servers, and can recognize both synchronous and asynchronous functions automatically.

The library provides decorators for functions, methods, AsyncWebsocketConsumer and templates, which are explained in their 
respective chapters in the documentation. The decorators can be customized with arguments for the Subject, Action, 
Resource, and Environment parameters. If no arguments are provided, the library uses default implementations to 
determine these values and create an AuthorizationSubscription, which is sent as a JSON to the PDP to request a decision.

An AuthorizationSubscription as JSON with default implementation for a method or function will look like this:
```json
{
  "subject": {
    "user_id": "id of the requesting user",
    "username": "name of the requesting user",
    "first_name": "first name",
    "last_name":  "last name",
    "is_active": "is the user still active",
    "is_superuser": "is the requesting user a superuser",
    "permissions": "list of permissions this user has",
    "groups": "list of groups to which the user belongs",
    "last_login": "time, when the user logged in the last time",
    "is_authenticated": "has the user been authenticated",
    "authorization": "JWT token, which was used for the request"
  },
  "action": {
    "function": {
      "function_name": "name of the function",
      "class": "name of the class, to which the decorated method belongs",
      "type": "type of the class in which the method is decorated"
    },
    "request": {
      "path": "request.path",
      "method": "request.method",
      "view_name": "resolver.view_name",
      "route": "resolver.route",
      "url_name": "resolver.urlname"
    }
  },
  "resources": {
    "function": {
      "url_kwargs": "arguments which were provided in the request",
      "kwargs": "arguments with which the decorated function was called"
    },
    "request": {
      "GET" : "Arguments of the GET Request",
      "POST" : "Arguments of the POST Request"
    },
    "return_value": "Return value of the decorated function"
  }
}
```
To determine access control in a system, policies must be defined. SAPL provides a policy language that allows you to 
write policies that can be evaluated by the SAPL Server. The policies specify who should have access to what resources 
and under what conditions.

When a policy is evaluated, it produces a decision, which is either "PERMIT" or "DENY". A decision can also contain 
obligations or advices. Obligations are things that must be done if access is granted, while advices are suggestions for 
things that could be done if access is granted.

The [SAPL documentation](https://sapl.io/documentation) provides more information on how to write policies and how the SAPL Server evaluates 
Authorization Subscriptions. Additionally, there is a section on [Obligations and Advices](#obligations-and-advices) that provides more information 
on how they work.

## Decorators for functions and methods

Functions and methods can be decorated with one 3 possible Decorators, which are:
- `pre_enforce` when a function shall be enforced, before it is called.
- `post_enforce` when the function is already executed and the return_value is needed to determine if the requesting client has access to these data.
- `pre_and_post_enforce` when the function is enforced before and after it is called. This decorator can be used,
when the return value of the function is needed to finally decide if access can be granted, but the execution of the 
function is expensive and there are certain parameters of a request, which can already be used to deny access before the 
return value is known.

an example for a pre_enforced function would be:
```Python
from sapl_base.decorators import pre_enforce

@pre_enforce
def pre_enforced_function(*args,**kwargs):
    return_value = "Do something"
    return return_value
```

The AuthorizationSubscription which could be sent to the PDP to request a Decision could be:

```json
{
  "subject":{
    "user_id":4,"username":"alina","first_name":"Alina","last_name":"Aurich","is_active":true,"is_superuser":false,
    "permissions":["medical.add_patient","medical.change_patient","medical.view_patient"],
    "groups":["Head Nurse","Nurse"],"last_login":"2023-06-12 10:15:51.149613+00:00","is_authenticated":true
  },
  "action":{
    "request":{
      "path":"/patients/5/update_patient_data/","method":"GET","view_name":"medical:update_patient",
      "route":"patients/<int:pk>/update_patient_data/","url_name":"update_patient"
    },
    "function":{
      "class":"PatientManager","function_name":"find_patient_by_pk","type":"Manager"
    }
  },
  "resource":{
    "return_value":{
      "id":5,"name":"hello","icd11_code":"5","diagnosis_text":"data",
      "attending_doctor":"doctor","room_number":20,"is_related_to_staff":false
    },"function":{
      "url_kwargs":{
        "pk":5
      },"kwargs":{
        "patient_pk":5
      }
    }
  }
}

```
Instead of using the default implementation to determine Subject,Action,Resources and Environment it is possible to provide Arguments for these parameter.
An explanation on how to provide Arguments for decorators is explained in the chapter [Providing arguments to a decorator](##providing_arguments_to_a_decorator)

## Decorators for AsyncGenerator and AsyncWebsockets

Django provides a class AsyncWebsocketConsumer, which can be enforced with SAPL.
There are 3 possible decorators which can be used to enforce AsyncGenerator and AsyncWebsocketConsumer:

- `enforce_till_denied`
- `enforce_drop_while_denied`
- `enforce_recoverable_if_denied`

When an AsyncWebsocketConsumer is decorated, these decorators will check for Permission, whenever data should be sent and 
can prevent the sending of data.
Using Obligations and Advices it is also possible to restrict the usage of certain methods within the class.
The Decorator also add methods to send an error message on a Recoverable_if_denied, or it can close the Connection on a pre_enforce decorator
Decorating doesn't prohibit the usage of sapl decorators for methods in the class.

When an AsyncGenerator is decorated, the decorator will enforce each yield of the AsyncGenerator.
The AsyncGenerator can be closed when the Permission is denied, or it can just drop a value, which should be yielded.
Additionally, any value can be handled with Constrainthandlers before yielding it.


## Decorators for templates

To use SAPL in a template, there are three available tags provided by the SAPL Django integration library:

- `enforce`: Begins a node that will be enforced with SAPL. This tag can accept arguments.
- `endenforce`: Ends the node, that will be enforced with SAPL.
- `deny`: Begins a node inside an Enforce node that will be displayed when the permission is denied.

Each node in a template that is enclosed by an enforce and endenforce Tag creates an AuthorizationSubscription and 
requests a Decision from the PDP 

If the decision of a node is PERMIT, the content until a 'deny' or 'endenforce' Tag will be displayed, while the parts after a 
'deny' Tag won't be displayed. If the received decision is 'DENY' only the content after a 'deny' Tag will be displayed.


## Providing arguments to a decorator

The decorators provided by the SAPL Django integration library allow for customization with arguments for the four 
parameters: Subject, Action, Resource, and Environment. These arguments replace the default implementation for 
determining the value of the parameter.

While the first three parameters have default implementations, the Environment parameter can only be set, when an 
argument to determine its value is provided.

Arguments for the decorators can be any value that can be converted to JSON, or a function that returns a 
JSON-serializable value. If a function is provided, it will be called when an AuthorizationSubscription is created, and 
the return value of the function will be used as the value for the corresponding parameter in the AuthorizationSubscription.

An example for a pre_enforce Decorator with a string as action and a function as Environment would be:

# TODO: EXAMPLE

# Obligations and Advices

After receiving a decision from the PDP (Policy Decision Point), constraints may be attached to it, which can be 
categorized as either obligations or advices. Obligations must be fulfilled; otherwise, the permission will be denied. 
Advices, on the other hand, are recommended to be fulfilled, but they won't affect the decision even if they're not.

To handle these constraints, the library provides an abstract class called `ConstraintHandlerProvider`, which can manage 
them. Developers must create classes to handle the constraints and register them with the library to ensure that the 
library can check if the given constraints can be managed.

## How to create ConstraintHandlerProvider

In order to create ConstraintHandlerProvider, 4 abstract ConstraintHandlerProvider are available to inherit from. These
abstract classes are: 

- `ErrorConstraintHandlerProvider`
- `OnDecisionConstraintHandlerProvider`
- `FunctionArgumentsConstraintHandlerProvider`
- `ResultConstraintHandlerProvider`

All of these classes inherit from the `ConstraintHandlerProvider` base class, which defines the methods that must be 
implemented in order to handle constraints.

The Baseclass is defined like this:
```python
from abc import abstractmethod, ABC

class ConstraintHandlerProvider(ABC):
  
    @abstractmethod
    def priority(self) -> int:
        """
        ConstraintHandlerProvider are sorted by the value of the priority, when the ConstraintHandlerBundle is created

        :return: value by which ConstraintHandlerProvider are sorted
        """
        return 0

    @abstractmethod
    def is_responsible(self, constraint) -> bool:
        """
        Determine if this ConstraintHandler is responsible for the provided constraint

        :param constraint: A constraint, which can be an Obligation or an Advice, for which the
        ConstraintHandlerProvider checks if it is responsible to handle it.
        :return: Is this ConstraintHandlerProvider responsible to handle the provided constraint
        """
        pass

    @abstractmethod
    def handle(self, argument):
        """
        Abstractmethod, which needs to be implemented by a ConstraintHandlerProvider
        :param argument: The argument, which is provided to the ConstraintHandler, when it is called. This argument can 
        be an Exception, function, decision, or the result of the executed function.
        """
```

When a decision contains a constraint, the library checks all registered `ConstraintHandlerProviders` to see if their 
`is_responsible` method evaluates to `True` for the given constraint. The responsible `ConstraintHandlerProvider` are 
gathered and sorted based on the value returned by their `priority` method. Finally, the `handle` methods of the sorted list 
of `ConstraintHandlerProviders` that are responsible for the given constraint are executed in the order of the list.

An example for a `ConstraintHandlerProvider`, which logs the received decision when it contains a constraint which 
equals "log decision" would be:
```python
from sapl_base.decision import Decision
from sapl_base.constraint_handling.constraint_handler_provider import OnDecisionConstraintHandlerProvider
import logging

class LogNewDecisionConstraintHandler(OnDecisionConstraintHandlerProvider):

    def handle(self, decision: Decision) -> None:
        logging.info(str(decision))

    def priority(self) -> int:
        return 0

    def is_responsible(self, constraint) -> bool:
        return True if constraint == "log decision" else False
```

## How to register ConstraintHandlerProvider

The `ConstraintHandlerService` class manages constraints and includes a `singleton` (i.e., `constraint_handler_service`) 
that's created upon file loading. All registered `ConstraintHandlerProviders` are taken into account by the `singleton` when 
checking if decision constraints can be handled.

The `ConstraintHandlerService` class provides methods to register a single `ConstraintHandlerProvider` or a list of 
`ConstraintHandlerProviders` for each of the four types of `ConstraintHandlerProvider`.

A recommended way to register a `ConstraintHandlerProvider` is to create a package that contains all the necessary 
`ConstraintHandlerProviders` and to register them in the `__init__` file of the package. For example, you can create a file 
that contains all `OnDecisionConstraintHandlerProviders` and add the `ConstraintHandlerProvider` created in the previous chapter. 
Then, in the `__init__` file of the package, you can register the `LogNewDecisionConstraintHandler` at the `OnDecisionConstraintHandler`:
```Python
from sapl_base.constraint_handling.constraint_handler_service import constraint_handler_service

from . import on_decision_constraint_handler_provider as on_decisions

constraint_handler_service.register_on_decision_constraint_handler_provider(on_decisions.LogNewDecisionConstraintHandler())
```

You can install the created package in the settings of your Django project to register all `ConstraintHandlerProviders` 
when the app starts. If you can't install the package in the settings due to an `AppRegistryNotReady` exception, you can 
initialize and register the `ConstraintHandlerProvider` when the app is ready.


The [Demo Project](https://github.com/heutelbeck/sapl-python-demos/tree/main/djangoDemo) for SAPL_Django initializes the 
`ConstraintHandlerService` when the app is ready. The following code of the demo project imports the package of the 
`ConstraintHandler` when the app is ready:
```Python
from django.apps import AppConfig

class ChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'medical'

    def ready(self):
        """
        The method ready configure if the application or DB first time runs.
        It initializes the DB and add the demoData and register the constraintService
        """

        if "runserver" not in sys.argv:
            return True
        # import here to avoid AppRegistryNotReady exception
        from medical.demo_data import initialize_database
        initialize_database()
        import djangoDemo.medical.constraint_handler_provider
```
## How to migrate

To integrate SAPL with an existing Django project, you can follow these steps: install, initialize, and configure SAPL 
in the existing project as if it were a new project.
