imported_addon = None

try:
    from sapl_django import *
    imported_addon = 'sapl_django'
except ImportError:
    pass

#try:
  #  from sapl_flask import *
  #  if not imported_addon:
   #     imported_addon = 'sapl_flask'
   # else:
     #   sys.exit("%s is already imported, only one sapl_package can be installed" % imported_addon)
#except ImportError:
    #pass

#try:
    #from sapl_tornado import basic
    #if not imported_addon:
    #    imported_addon = 'sapl_tornado'
    #else:
    #    sys.exit("%s is already imported, only one sapl_package can be installed" % imported_addon)
#except ImportError:
    #pass

del imported_addon
