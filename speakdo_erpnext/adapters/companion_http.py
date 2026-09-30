"""Central handler of the companion surface called by the middleware.

The surface functions (``speakdo_erpnext.api.companion``) are thin Frappe
whitelisted methods; all of them delegate here:

- proof routes: public (no session, no HMAC); they only reveal a pending,
  unexpired challenge of the requested flow;
- every other route: tenant HMAC mandatory (timestamp ±300 s, nonce
  anti-replay in the database, constant time comparison) before anything
  else is read. The signed REQUEST_TARGET is the raw request target received
  (``/api/method/speakdo_erpnext.api.companion.<function>?<raw query>``),
  so the query parameters are covered by the signature. It is taken from the
  WSGI environ as sent (nginx proxies it unchanged), never rebuilt.

No route depends on a Frappe browser session. Answers are raw JSON (a
werkzeug Response bypasses Frappe's ``{"message": …}`` envelope) with
``Cache-Control: no-store``. Only the route name, the status and the error
code are logged.
"""

import json

import frappe
from werkzeug.wrappers import Response

from speakdo_erpnext.adapters import middleware_legacy as wire
from speakdo_erpnext.constants import FlowType
from speakdo_erpnext.domain import identity
from speakdo_erpnext.services import challenges, hmac, replay, store, terminals
from speakdo_erpnext.services.errors import HmacRejected, InboundRequestError
from speakdo_erpnext.services.log import log_event

MAX_BODY_BYTES = 64 * 1024
_SAVEPOINT = "speakdo_surface"

BOOTSTRAP_PROOF = "bootstrap_proof"
REPAIR_PROOF = "repair_proof"
RELOCATION_PROOF = "relocation_proof"
ENROLLMENT_VERIFY = "enrollment_verify"
TERMINAL_STATUS = "terminal_status"
USER_CAPABILITIES = "user_capabilities"
ACTION = "action"

PROOF_ROUTES = {
	BOOTSTRAP_PROOF: FlowType.BOOTSTRAP,
	REPAIR_PROOF: FlowType.REPAIR,
	RELOCATION_PROOF: FlowType.RELOCATION,
}

# Business actions are executed by the middleware ERPNext connector, never by
# this companion.
ERP_CONNECTOR_UNAVAILABLE = "erp_connector_unavailable"


def _commit():
	frappe.db.commit()


def _rollback():
	"""Undo the writes of the current surface request only."""
	frappe.db.rollback(save_point=_SAVEPOINT)


def json_response(status, body):
	return Response(
		json.dumps(body, separators=(",", ":"), ensure_ascii=False),
		status=status,
		mimetype="application/json",
		headers={"Cache-Control": "no-store"},
	)


def raw_request_target(request):
	"""Request target exactly as received (path + query, byte for byte), or None.

	RAW_URI (gunicorn) / REQUEST_URI hold the request-line target unchanged:
	parameter order, percent-encoding, repeated and empty parameters are kept.
	An absolute-form target is reduced to its origin-form without re-encoding.
	"""
	environ = getattr(request, "environ", None) or {}
	raw = environ.get("RAW_URI") or environ.get("REQUEST_URI")
	if not raw:
		return None
	if "://" in raw:
		start = raw.find("/", raw.index("://") + 3)
		return raw[start:] if start != -1 else None
	return raw


def _authenticate(request, body):
	tenant_uuid = identity.normalize_tenant_uuid(store.get("tenant_uuid"))
	hmac.verify_request(
		method=request.method,
		request_target=raw_request_target(request),
		headers=request.headers,
		body=body,
		tenant_uuid=tenant_uuid,
		secret=store.get_hmac_secret(),
		consume_nonce=lambda nonce: replay.consume_nonce(f"tenant:{tenant_uuid}", nonce),
	)
	# Frappe only commits POST/PUT/DELETE requests: the consumed nonce must
	# persist for GET routes too, and even if the handler fails afterwards.
	_commit()
	frappe.db.savepoint(_SAVEPOINT)


def _read_json(body):
	try:
		data = json.loads(body.decode("utf-8")) if body else None
	except (ValueError, UnicodeDecodeError):
		data = None
	if not isinstance(data, dict):
		raise InboundRequestError(error_code="invalid_json", http_status=400)
	return data


def _dispatch(route, request, params):
	if route in PROOF_ROUTES:
		flow_type = PROOF_ROUTES[route]
		proof = challenges.get_published_proof(flow_type, params.get("id"))
		if not proof:
			return 404, wire.error_body("not_found")
		return 200, wire.proof_body(flow_type, proof)

	body = request.get_data(cache=True) or b""
	if len(body) > MAX_BODY_BYTES:
		raise InboundRequestError(error_code="payload_too_large", http_status=413)
	_authenticate(request, body)

	if route == ENROLLMENT_VERIFY:
		data = wire.parse_verify_request(_read_json(body))
		result = terminals.verify_enrollment(params.get("token"), data["consume"], data["terminal"])
		return 200, wire.verify_response(result)
	if route == TERMINAL_STATUS:
		return 200, wire.terminal_status_response(terminals.terminal_status(params.get("terminal_uuid")))
	if route == USER_CAPABILITIES:
		return 200, wire.user_capabilities_response(terminals.user_capabilities(params.get("user")))
	if route == ACTION:
		return 424, wire.error_body(ERP_CONNECTOR_UNAVAILABLE, "Aucune action métier n'est exécutée par le compagnon.")
	return 404, wire.error_body("not_found")


def handle(route, request, params):
	"""Serve one surface request. Returns (http_status, json_body)."""
	frappe.db.savepoint(_SAVEPOINT)
	try:
		status, body = _dispatch(route, request, params)
	except HmacRejected as exc:
		_rollback()
		status, body = 401, wire.error_body(exc.error_code)
	except InboundRequestError as exc:
		_rollback()
		status, body = exc.http_status or 400, wire.error_body(exc.error_code)
	except Exception:
		_rollback()
		log_event(f"surface.{route}", "result", "error", "internal_error", 500)
		return 500, wire.error_body("internal_error")

	_commit()
	error = body.get("error", {}).get("code") if isinstance(body.get("error"), dict) else None
	log_event(f"surface.{route}", "result", "error" if status >= 400 else "ok", error, status)
	return status, body


def respond(route, *param_names):
	"""Entry point of the whitelisted surface functions.

	Parameters are read from the query string only (``request.args``): Frappe
	merges JSON body keys into ``form_dict``, and a body key must never
	override a query parameter.
	"""
	request = frappe.local.request
	params = {name: request.args.get(name) for name in param_names}
	status, body = handle(route, request, params)
	return json_response(status, body)
