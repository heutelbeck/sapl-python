from sapl_base.sapl_util import configuration

framework = configuration.get("framework", None)
if framework is not None:
    match framework:
        case 'django':
            from sapl_django import *
        case 'tornado':
            from sapl_tornado import *
        case 'flask':
            from sapl_flask import *








