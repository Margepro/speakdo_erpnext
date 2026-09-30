"""Wire protocol of the current SpeakDo middleware (still partly Dolibarr-named).

COMPATIBILITY LAYER. This module is the only place of the companion that
knows:

- the historical wire field names still used by the middleware for every ERP
  (``dolibarr_base_url`` carries the real ERP root URL, ``dolibarr_hmac_secret``
  the tenant secret, ``tenant_id`` vs ``tenant_uuid``) and the legacy error
  codes (``*dolibarr*``);
- the middleware endpoint paths;
- the JSON documents served by the companion surface (proofs, verify, status,
  capabilities).

The middleware generalised for ``erp_type = erpnext`` reaches this companion
through ``companion_base_url`` (declared at bootstrap), no longer through a
Dolibarr path layout. When the middleware drops the ``dolibarr_*`` names, only
this module changes.

Sources: SPEAKDO_COMPANION_PROTOCOL.md (29/09/2026) + ERPNext mandate
(bootstrap fields ``installation_id``, ``erp_type``, ``dolibarr_base_url``,
``companion_base_url``).
"""

import re
from dataclasses import dataclass

from speakdo_erpnext.constants import COMPANION_PROTOCOL_VERSION, COMPANION_VERSION, FlowType
from speakdo_erpnext.domain import identity
from speakdo_erpnext.services.errors import (
	FeatureUnavailable,
	MiddlewareHTTPError,
	MiddlewareInvalidResponse,
	MiddlewareRefused,
	safe_code,
)

# -- outgoing endpoints ----------------------------------------------------------

BOOTSTRAP_START = "/api/v1/tenants/bootstrap/start"
BOOTSTRAP_FINALIZE = "/api/v1/tenants/bootstrap/{flow_id}/finalize"
REPAIR_START = "/api/v1/tenants/repair/start"
REPAIR_FINALIZE = "/api/v1/tenants/repair/{flow_id}/finalize"
RELOCATION_START = "/api/v1/tenants/relocate/start"
RELOCATION_FINALIZE = "/api/v1/tenants/relocate/{flow_id}/finalize"
INSTALLATION_RESET = "/api/v1/tenants/installation/reset"
# Profile catalogue of the middleware (tenant HMAC). The middleware is the
# authority of the catalogue; the companion stores the ALLOWED profiles of a user.
PROFILES = "/profiles"

# -- wire field names --------------------------------------------------------------

WIRE_BASE_URL = "dolibarr_base_url"  # value: the real ERP root URL (erp_base_url)
WIRE_HMAC_SECRET = "dolibarr_hmac_secret"
GENERIC_HMAC_SECRET = "erp_hmac_secret"  # read as a fallback only

# Legacy error codes -> companion (generic) codes. Unlisted codes are kept.
_ERROR_CODES = {
	"invalid_dolibarr_url": "invalid_erp_url",
	"dolibarr_unavailable": "erp_unavailable",
	"dolibarr_url_rejected": "erp_url_rejected",
	"dolibarr_host_changed": "erp_host_changed",
	"dolibarr_invalid_response": "erp_invalid_response",
	"dolibarr_rejected": "erp_rejected",
}

_FLOW_ID = re.compile(r"^[0-9a-f-]{36}$")
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{16,512}$")


@dataclass(frozen=True)
class FlowStart:
	flow_id: str
	challenge: str
	expires_in_seconds: int | None


# -- outgoing request bodies ---------------------------------------------------------


def bootstrap_start_body(installation_id, erp_type, erp_base_url, companion_base_url):
	return {
		"installation_id": installation_id,
		"erp_type": erp_type,
		WIRE_BASE_URL: erp_base_url,
		"companion_base_url": companion_base_url,
	}


def flow_start_body(installation_id, erp_base_url):
	"""repair/start and relocate/start (SPEAKDO_COMPANION_PROTOCOL §8.2, §9.1)."""
	return {"installation_id": installation_id, WIRE_BASE_URL: erp_base_url}


def reset_body(installation_id, reason):
	return {"installation_id": installation_id, "reason": (reason or "")[:120]}


def finalize_path(template, flow_id):
	if not isinstance(flow_id, str) or not _FLOW_ID.match(flow_id):
		raise MiddlewareInvalidResponse("Identifiant de flux invalide.", error_code="flow_id_invalid")
	return template.format(flow_id=flow_id)


# -- response parsing ----------------------------------------------------------------


def _translate_code(code):
	return _ERROR_CODES.get(code, code)


def translate_error(exc, feature_gated=False):
	"""Convert a MiddlewareHTTPError into a companion error (generic names only)."""
	if not isinstance(exc, MiddlewareHTTPError):
		return exc
	body = exc.body or {}
	code = exc.server_error_code
	if feature_gated and exc.http_status == 404 and code == "not_found":
		return FeatureUnavailable(http_status=404, server_error_code=code)
	details = {}
	registered = body.get(WIRE_BASE_URL) or body.get("erp_base_url")
	if isinstance(registered, str) and registered:
		details["registered_erp_url"] = registered
	generic = _translate_code(code) if code else MiddlewareHTTPError.error_code
	return MiddlewareRefused(error_code=generic, http_status=exc.http_status, server_error_code=code, details=details)


def _required_str(data, key, pattern=None):
	value = data.get(key)
	if not isinstance(value, str) or not value or (pattern and not pattern.match(value)):
		raise MiddlewareInvalidResponse(error_code="middleware_invalid_response")
	return value


def parse_flow_start(data, id_field):
	"""201 of bootstrap/repair/relocate start -> FlowStart."""
	expires = data.get("expires_in_seconds")
	return FlowStart(
		flow_id=_required_str(data, id_field, _FLOW_ID),
		challenge=_required_str(data, "challenge", _CHALLENGE),
		expires_in_seconds=int(expires) if isinstance(expires, int) and expires > 0 else None,
	)


def _tenant_uuid(data, *keys):
	for key in keys:
		value = identity.normalize_tenant_uuid(data.get(key))
		if value:
			return value
	raise MiddlewareInvalidResponse("Identifiant tenant absent ou invalide.", error_code="tenant_invalid")


def _secret(data):
	for key in (WIRE_HMAC_SECRET, GENERIC_HMAC_SECRET):
		value = data.get(key)
		if isinstance(value, str) and value:
			return value
	return None


def parse_bootstrap_finalize(data):
	"""201 of bootstrap finalize (new_installation or legacy_migration)."""
	secret = _secret(data)
	retained = data.get("hmac_secret_retained") is True
	mode = data.get("bootstrap_mode") or ("legacy_migration" if retained else "new_installation")
	if not retained and not secret:
		raise MiddlewareInvalidResponse("Aucun secret HMAC restitué.", error_code="hmac_secret_missing")
	eligible_until = data.get("eligible_until")
	free_trial = data.get("free_trial_granted")
	return {
		"tenant_uuid": _tenant_uuid(data, "tenant_uuid", "tenant_id"),
		"hmac_secret": None if retained else secret,
		"mode": mode if mode in ("new_installation", "legacy_migration") else "new_installation",
		"billing_status": safe_code(data.get("billing_status")),
		"eligible_until": eligible_until if isinstance(eligible_until, str) else None,
		"free_trial_granted": free_trial if isinstance(free_trial, int) else None,
	}


def parse_repair_finalize(data):
	"""200 of repair finalize."""
	secret = _secret(data)
	if not secret or data.get("repair_completed") is not True:
		raise MiddlewareInvalidResponse("Réparation incomplète.", error_code="hmac_secret_missing")
	installation_id = data.get("installation_id")
	return {
		"tenant_uuid": _tenant_uuid(data, "tenant_uuid", "tenant_id"),
		"installation_id": installation_id if isinstance(installation_id, str) else None,
		"hmac_secret": secret,
	}


def parse_relocation_start(data):
	"""201 -> FlowStart ; 200 installation_url_unchanged -> None."""
	error = data.get("error")
	if data.get("ok") is False and isinstance(error, dict):
		if error.get("code") == "installation_url_unchanged":
			return None
		raise MiddlewareRefused(error_code=_translate_code(safe_code(error.get("code")) or "middleware_refused"))
	return parse_flow_start(data, "relocation_id")


def parse_relocation_finalize(data):
	if data.get("relocation_completed") is not True:
		raise MiddlewareInvalidResponse("Relocation non confirmée.", error_code="relocation_not_confirmed")
	return {"tenant_uuid": _tenant_uuid(data, "tenant_uuid")}


def parse_reset(data):
	if data.get("ok") is not True:
		raise MiddlewareInvalidResponse("Réinitialisation non confirmée.", error_code="reset_not_confirmed")
	return {}


# -- companion surface documents -------------------------------------------------------


def proof_body(flow_type, proof):
	"""Public proof document (§5.2, §8.3, §9.2)."""
	if flow_type == FlowType.BOOTSTRAP:
		return {
			"bootstrap_id": proof["flow_id"],
			"installation_id": proof["installation_id"],
			"challenge": proof["challenge"],
			"companion_version": COMPANION_VERSION,
			"protocol_version": COMPANION_PROTOCOL_VERSION,
		}
	if flow_type == FlowType.REPAIR:
		return {
			"repair_id": proof["flow_id"],
			"installation_id": proof["installation_id"],
			"challenge": proof["challenge"],
		}
	return {
		"relocation_id": proof["flow_id"],
		"installation_id": proof["installation_id"],
		"new_base_url": proof["erp_base_url"],
		"challenge": proof["challenge"],
	}


def parse_verify_request(data):
	"""Body of enrollment_verify -> generic dict (validated by the service)."""
	terminal = data.get("terminal") if isinstance(data.get("terminal"), dict) else {}
	return {
		"consume": data.get("consume") is True,
		"terminal": {
			"terminal_id": terminal.get("terminal_id"),
			"label": terminal.get("label"),
			"public_key_pem": terminal.get("public_key_pem"),
			"public_key_fingerprint": terminal.get("public_key_fingerprint"),
		},
	}


def verify_response(result):
	"""Generic verify result -> wire answer.

	ERP credential on the wire (decision of 30/09/2026):
	``credential_type`` + ``erp_credential`` = "<api_key>:<api_secret>", opaque
	for the companion <-> middleware protocol (only the middleware ERPNext
	adapter turns it into ``Authorization: token …``). Emitted only when a
	credential was issued. Never logged; never a Dolibarr API key.
	"""
	if not result.get("valid"):
		return {"valid": False, "error": {"code": result.get("reason") or "enrollment_rejected"}}
	user = result["user"]
	return {
		"valid": True,
		"user": {"id": user.erp_user_id, "active": user.active, "display_name": user.display_name},
		"terminal_status": result["terminal_status"],
		"capabilities": list(result.get("capabilities") or []),
		"channel": result["channel"],
		"permissions_version": result["permissions_version"],
		**_allowed_profiles_field(result),
		**_credential_fields(result.get("erp_credential")),
	}


def _credential_fields(credential):
	if not credential:
		return {}
	return {
		"credential_type": credential.credential_type,
		"erp_credential": f"{credential.api_key}:{credential.api_secret}",
	}


# Profiles on the wire (decision 30/09/2026): ``allowed_profiles`` = the SET of
# profiles the administrator authorizes for the user: canonical catalogue ids,
# sorted, unique; ``[]`` = no profile assigned (never "generic"). Always emitted
# in enrollment_verify and user_capabilities (same canonical list in both).
# The historical single ``profile_id`` is NOT emitted by the ERPNext companion:
# it would fabricate an active/main profile. The ACTIVE profile belongs to the
# middleware/session (profile.switch). See MIDDLEWARE CONTRACT REQUIRED in
# docs/SPEAKDO_ERPNEXT_USER_MODEL.md.


def _allowed_profiles_field(result):
	return {"allowed_profiles": sorted(set(result.get("allowed_profiles") or []))}


def parse_profiles(data):
	"""GET /profiles -> ({profile_id: {version, label, short_label, doc_url}}, {alias: profile_id})."""
	profiles = {}
	for item in data.get("profiles") or []:
		if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
			profiles[item["id"]] = {
				"id": item["id"],
				"version": item.get("version"),
				"label": item.get("label") if isinstance(item.get("label"), str) else item["id"],
				"short_label": item.get("short_label") if isinstance(item.get("short_label"), str) else None,
				"doc_url": item.get("doc_url") if isinstance(item.get("doc_url"), str) else None,
			}
	aliases = {
		a["id"]: a["alias_of"]
		for a in data.get("aliases") or []
		if isinstance(a, dict) and isinstance(a.get("id"), str) and a.get("alias_of") in profiles
	}
	if data.get("ok") is False or not profiles:
		raise MiddlewareInvalidResponse("Catalogue de profils vide ou invalide.", error_code="profiles_unavailable")
	return profiles, aliases


def terminal_status_response(result):
	return {"status": result["status"], "permissions_version": result["permissions_version"]}


def user_capabilities_response(result):
	return {
		"active": result["active"],
		"capabilities": list(result.get("capabilities") or []),
		"permissions_version": result["permissions_version"],
		**_allowed_profiles_field(result),
	}


def error_body(code, message=None):
	"""Error envelope of the middleware (§11.1): it relays ``error.code``."""
	return {"ok": False, "error": {"code": code, "message": message or code}}


# -- high level client -------------------------------------------------------------------


class LegacyMiddlewareProtocol:
	"""Middleware operations. Takes and returns generic (ERP-neutral) values and
	raises companion errors (MiddlewareRefused, FeatureUnavailable, ...)."""

	def __init__(self, client):
		self.client = client

	def _call(self, operation, method, path, payload=None, signer=None, feature_gated=False):
		try:
			return self.client.request(operation, method, path, payload, signer=signer)
		except MiddlewareHTTPError as exc:
			raise translate_error(exc, feature_gated=feature_gated)

	def bootstrap_start(self, installation_id, erp_type, erp_base_url, companion_base_url):
		_, data = self._call(
			"bootstrap_start", "POST", BOOTSTRAP_START,
			bootstrap_start_body(installation_id, erp_type, erp_base_url, companion_base_url),
		)  # fmt: skip
		return parse_flow_start(data, "bootstrap_id")

	def bootstrap_finalize(self, flow_id):
		_, data = self._call("bootstrap_finalize", "POST", finalize_path(BOOTSTRAP_FINALIZE, flow_id))
		return parse_bootstrap_finalize(data)

	def repair_start(self, installation_id, erp_base_url):
		_, data = self._call("repair_start", "POST", REPAIR_START, flow_start_body(installation_id, erp_base_url))
		return parse_flow_start(data, "repair_id")

	def repair_finalize(self, flow_id):
		_, data = self._call("repair_finalize", "POST", finalize_path(REPAIR_FINALIZE, flow_id))
		return parse_repair_finalize(data)

	def relocation_start(self, installation_id, new_erp_base_url):
		_, data = self._call(
			"relocation_start", "POST", RELOCATION_START,
			flow_start_body(installation_id, new_erp_base_url), feature_gated=True,
		)  # fmt: skip
		return parse_relocation_start(data)

	def relocation_finalize(self, flow_id):
		_, data = self._call(
			"relocation_finalize", "POST", finalize_path(RELOCATION_FINALIZE, flow_id), feature_gated=True
		)
		return parse_relocation_finalize(data)

	def list_profiles(self, tenant_uuid, secret):
		_, data = self._call("profiles_read", "GET", PROFILES, signer=(tenant_uuid, secret))
		return parse_profiles(data)

	def installation_reset(self, tenant_uuid, secret, installation_id, reason):
		_, data = self._call(
			"installation_reset", "POST", INSTALLATION_RESET,
			reset_body(installation_id, reason), signer=(tenant_uuid, secret), feature_gated=True,
		)  # fmt: skip
		return parse_reset(data)
