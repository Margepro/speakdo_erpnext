"""Protocol adapters. Only this package knows the wire names of the middleware.

Services obtain the middleware protocol through ``get_middleware_protocol()``
and only see generic (ERP-neutral) values.
"""


def get_middleware_protocol(client=None):
	from speakdo_erpnext.adapters.middleware_legacy import LegacyMiddlewareProtocol
	from speakdo_erpnext.services.middleware import MiddlewareClient

	return LegacyMiddlewareProtocol(client or MiddlewareClient())
