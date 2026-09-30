"""Error types of the companion.

Every error carries a stable, machine readable ``error_code`` and a user facing
message written by the companion itself. Raw middleware payloads are never
copied into an error: only the few sanitized ``details`` extracted by the
protocol adapter (e.g. a registered URL) are kept.
"""

import re

_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")


def safe_code(value, default=None):
	"""Return ``value`` only if it looks like a technical error code."""
	if isinstance(value, str) and _SAFE_CODE.match(value.strip().lower()):
		return value.strip().lower()
	return default


class SpeakDoError(Exception):
	error_code = "speakdo_error"
	default_message = "Erreur SpeakDo."

	def __init__(self, message=None, error_code=None, http_status=None, server_error_code=None, details=None):
		if error_code:
			self.error_code = error_code
		self.message = message or self.default_message
		self.http_status = http_status
		self.server_error_code = server_error_code
		self.details = details or {}
		super().__init__(self.message)

	def as_dict(self):
		return {
			"ok": False,
			"error_code": self.error_code,
			"message": self.message,
			"http_status": self.http_status,
			"details": dict(self.details),
		}


class ConfigurationError(SpeakDoError):
	error_code = "configuration_error"


class StateError(SpeakDoError):
	"""The operation is not allowed in the current local state."""

	error_code = "invalid_state"


class MiddlewareError(SpeakDoError):
	error_code = "middleware_error"


class MiddlewareTimeout(MiddlewareError):
	error_code = "middleware_timeout"
	default_message = "Le middleware SpeakDo n'a pas répondu dans le délai imparti."


class MiddlewareUnreachable(MiddlewareError):
	error_code = "middleware_unreachable"
	default_message = "Le middleware SpeakDo est injoignable."


class MiddlewareTLSError(MiddlewareError):
	error_code = "middleware_tls_error"
	default_message = "La vérification TLS du middleware SpeakDo a échoué."


class MiddlewareInvalidResponse(MiddlewareError):
	error_code = "middleware_invalid_response"
	default_message = "Réponse invalide du middleware SpeakDo."


class MiddlewareHTTPError(MiddlewareError):
	"""Non 2xx answer. The decoded body is kept privately for the protocol adapter only."""

	error_code = "middleware_http_error"
	default_message = "Le middleware SpeakDo a refusé la requête."

	def __init__(self, *args, body=None, **kwargs):
		super().__init__(*args, **kwargs)
		self._body = body

	@property
	def body(self):
		return self._body


class MiddlewareRefused(MiddlewareError):
	"""A middleware refusal translated to a companion (generic) error code."""

	error_code = "middleware_refused"
	default_message = "Le middleware SpeakDo a refusé la requête."


class FeatureUnavailable(MiddlewareError):
	"""The middleware surface is closed by a feature gate (404 not_found)."""

	error_code = "feature_unavailable"
	default_message = "Cette fonction est désactivée sur le middleware SpeakDo."


class HmacRejected(SpeakDoError):
	"""Incoming request refused by the tenant HMAC verification."""

	error_code = "invalid_tenant_signature"
	default_message = "Signature refusée."

	def __init__(self, error_code):
		super().__init__(error_code=error_code, http_status=401)


class InboundRequestError(SpeakDoError):
	"""Malformed request received on the companion surface."""

	error_code = "invalid_request"
	default_message = "Requête invalide."
