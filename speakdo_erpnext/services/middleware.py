"""HTTP transport to the SpeakDo middleware.

This module is the ONLY place of the companion that performs network calls to
SpeakDo. It knows neither the middleware paths nor the wire field names: those
belong to the protocol adapter (``adapters.middleware_legacy``), which calls
``MiddlewareClient.request``.

Base URLs are never hardcoded: they always come from SpeakDo Settings.
"""

import json
import time
from urllib.parse import urlsplit

import requests

from speakdo_erpnext.constants import ERP_TYPE, USER_AGENT
from speakdo_erpnext.domain.erp_instance import normalize_base_url
from speakdo_erpnext.services import hmac, store
from speakdo_erpnext.services.errors import (
	MiddlewareHTTPError,
	MiddlewareInvalidResponse,
	MiddlewareTimeout,
	MiddlewareTLSError,
	MiddlewareUnreachable,
	safe_code,
)
from speakdo_erpnext.services.log import log_event

# (connect, read) timeouts in seconds. The read timeout covers a finalize
# during which the middleware fetches the proof (its own timeout is 12 s).
DEFAULT_TIMEOUT = (5, 30)
PROBE_TIMEOUT = (3, 5)


def get_middleware_url():
	return normalize_base_url(store.get("middleware_url"), "URL du middleware SpeakDo")


def get_app_url():
	return normalize_base_url(store.get("app_url"), "URL de l'application SpeakDo")


def encode_json(payload):
	"""Exact bytes sent on the wire (they are also the signed bytes)."""
	if payload is None:
		return b""
	return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class MiddlewareClient:
	def __init__(self, base_url=None, timeout=DEFAULT_TIMEOUT, session=None):
		self.base_url = normalize_base_url(base_url, "URL du middleware SpeakDo") if base_url else get_middleware_url()
		self.timeout = timeout
		self.session = session or requests.Session()

	def request(self, operation, method, path, payload=None, signer=None, timeout=None):
		"""Perform one JSON call and return ``(http_status, decoded_json_object)`` for a 2xx.

		``signer`` is a ``(tenant_uuid, secret)`` tuple for tenant HMAC routes.
		The signed path is the full path seen by the middleware (base path of
		middleware_url + endpoint path). Never logs the payload, the headers or
		the raw response. Non 2xx answers raise MiddlewareHTTPError.
		"""
		url = f"{self.base_url}{path}"
		body = encode_json(payload)
		headers = {
			"User-Agent": USER_AGENT,
			"Accept": "application/json",
			"X-SpeakDo-ERP-Type": ERP_TYPE,
		}
		if payload is not None:
			headers["Content-Type"] = "application/json"
		if signer:
			tenant_uuid, secret = signer
			headers.update(hmac.signed_headers(tenant_uuid, secret, method, urlsplit(url).path, body))

		started = time.monotonic()

		def elapsed():
			return (time.monotonic() - started) * 1000

		try:
			response = self.session.request(
				method,
				url,
				data=body,
				headers=headers,
				timeout=timeout or self.timeout,
				verify=True,
				allow_redirects=False,
			)
		except requests.exceptions.Timeout:
			log_event(operation, "http", "error", MiddlewareTimeout.error_code, None, elapsed())
			raise MiddlewareTimeout()
		except requests.exceptions.SSLError:
			log_event(operation, "http", "error", MiddlewareTLSError.error_code, None, elapsed())
			raise MiddlewareTLSError()
		except requests.exceptions.RequestException:
			log_event(operation, "http", "error", MiddlewareUnreachable.error_code, None, elapsed())
			raise MiddlewareUnreachable()

		http_status = response.status_code
		try:
			data = response.json()
		except ValueError:
			data = None

		if not 200 <= http_status < 300:
			server_code = None
			if isinstance(data, dict):
				error = data.get("error")
				if isinstance(error, dict):
					server_code = safe_code(error.get("code"))
				server_code = server_code or safe_code(data.get("error_code"))
			log_event(operation, "http", "error", server_code or MiddlewareHTTPError.error_code, http_status, elapsed())
			raise MiddlewareHTTPError(
				error_code=server_code or MiddlewareHTTPError.error_code,
				http_status=http_status,
				server_error_code=server_code,
				body=data if isinstance(data, dict) else None,
			)

		if not isinstance(data, dict):
			log_event(operation, "decode", "error", MiddlewareInvalidResponse.error_code, http_status, elapsed())
			raise MiddlewareInvalidResponse(http_status=http_status)

		log_event(operation, "http", "ok", None, http_status, elapsed())
		return http_status, data

	def probe(self):
		"""Side-effect free reachability check: GET on the middleware base URL.

		Any HTTP answer (even 404) means reachable. No credential is sent and
		no body is read.
		"""
		started = time.monotonic()
		try:
			response = self.session.get(
				self.base_url,
				headers={"User-Agent": USER_AGENT},
				timeout=PROBE_TIMEOUT,
				verify=True,
				allow_redirects=False,
			)
		except requests.exceptions.Timeout:
			code = MiddlewareTimeout.error_code
		except requests.exceptions.SSLError:
			code = MiddlewareTLSError.error_code
		except requests.exceptions.RequestException:
			code = MiddlewareUnreachable.error_code
		else:
			latency = int((time.monotonic() - started) * 1000)
			log_event("probe", "http", "ok", None, response.status_code, latency)
			return {"reachable": True, "http_status": response.status_code, "latency_ms": latency, "error_code": None}
		latency = int((time.monotonic() - started) * 1000)
		log_event("probe", "http", "error", code, None, latency)
		return {"reachable": False, "http_status": None, "latency_ms": latency, "error_code": code}
