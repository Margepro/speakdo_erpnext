"""Test helpers: an in-process fake of the SpeakDo middleware that follows
SPEAKDO_COMPANION_PROTOCOL.md (it fetches the proofs through the real companion
surface), and an independent reference implementation of the tenant HMAC."""

import base64
import hashlib
import hmac as std_hmac
import json
import secrets
import time
import uuid
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urlsplit

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.datastructures import Headers, MultiDict

from speakdo_erpnext.adapters import companion_http, get_middleware_protocol
from speakdo_erpnext.constants import (
	ALLOWED_PROFILE_DOCTYPE,
	CREDENTIAL_DOCTYPE,
	ENROLLMENT_TOKEN_DOCTYPE,
	FLOW_CHALLENGE_DOCTYPE,
	NONCE_DOCTYPE,
	SETTINGS_DOCTYPE,
	TERMINAL_DOCTYPE,
	EnrollmentStatus,
)
from speakdo_erpnext.domain import identity
from speakdo_erpnext.services import flows, store
from speakdo_erpnext.services.middleware import MiddlewareClient

MW_URL = "https://mw.test"
ERP_URL = "https://erp.client.example"
SURFACE = "/api/method/speakdo_erpnext.api.companion"
COMPANION_BASE_URL = ERP_URL + SURFACE
TENANT = "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e"
SECRET = "Tenant_HMAC_secret_" + "k" * 45


# -- reference HMAC (written from the contract, independent of services.hmac) --


def reference_sign(secret, method, path, timestamp, nonce, body=b""):
	canonical = "\n".join([method.upper(), path, str(timestamp), nonce, hashlib.sha256(body).hexdigest()])
	return base64.b64encode(std_hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).digest()).decode()


def reference_headers(secret, method, path, body=b"", tenant=TENANT, timestamp=None, nonce=None):
	timestamp = str(int(time.time()) if timestamp is None else timestamp)
	nonce = nonce or secrets.token_urlsafe(18)
	return {
		"X-SpeakDo-Tenant": tenant,
		"X-SpeakDo-Timestamp": timestamp,
		"X-SpeakDo-Nonce": nonce,
		"X-SpeakDo-Signature": reference_sign(secret, method, path, timestamp, nonce, body),
		"X-SpeakDo-Protocol": "1",
	}


# -- companion surface calls ---------------------------------------------------


def raw_target(path, args=None, raw_query=None):
	"""Request target as a client puts it on the wire: path + query (``raw_query``
	is used verbatim when given, otherwise ``args`` is url-encoded in order)."""
	query = raw_query if raw_query is not None else urlencode(list((args or {}).items()))
	return f"{path}?{query}" if query or raw_query is not None else path


class FakeRequest:
	def __init__(self, method, path, args=None, headers=None, body=b"", raw_query=None, target=None):
		self.method = method
		self.path = path
		query = raw_query if raw_query is not None else urlencode(list((args or {}).items()))
		self.args = MultiDict(parse_qsl(query, keep_blank_values=True))
		self.headers = Headers(headers or {})
		self._body = body
		# What gunicorn exposes: the request-line target, byte for byte.
		self.environ = {"RAW_URI": target if target is not None else raw_target(path, args, raw_query)}

	def get_data(self, cache=True):
		return self._body


@contextmanager
def as_user(user):
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous)


def call_surface(function, method="GET", args=None, headers=None, body=b"", raw_query=None, target=None):
	"""Anonymous call of a surface function (as the middleware does), through the
	real whitelisted function. Returns (status, decoded json)."""
	from speakdo_erpnext.api import companion

	request = FakeRequest(method, f"{SURFACE}.{function}", args, headers, body, raw_query, target)
	previous = getattr(frappe.local, "request", None)
	frappe.local.request = request
	try:
		with as_user("Guest"):
			response = getattr(companion, function)()
	finally:
		frappe.local.request = previous
	return response.status_code, json.loads(response.get_data())


def signed_call(function, method="GET", args=None, body=b"", secret=SECRET, tenant=TENANT, raw_query=None, **kwargs):
	"""Signed as the middleware does: REQUEST_TARGET = path + raw query as sent."""
	target = raw_target(f"{SURFACE}.{function}", args, raw_query)
	headers = reference_headers(secret, method, target, body, tenant=tenant, **kwargs)
	return call_surface(function, method, args, headers, body, raw_query)


# -- fake middleware -------------------------------------------------------------


class FakeResponse:
	def __init__(self, status_code, payload=None):
		self.status_code = status_code
		self._payload = payload

	def json(self):
		if self._payload is None:
			raise ValueError("no json")
		return self._payload


def error(status, code, **root):
	return FakeResponse(status, {"ok": False, "error": {"code": code, "message": code, "details": {}}, **root})


class FakeMiddleware:
	"""requests.Session look-alike implementing the middleware side of the contract."""

	def __init__(self):
		self.calls = []
		self.flows = {}
		self.tenants = {}  # installation_id -> {"tenant_uuid", "secret", "url"}
		self.legacy_url = None  # URL of a legacy tenant (no installation_id)
		self.legacy_secret_known = False
		self.relocation_enabled = False
		self.reset_enabled = False
		self.fail = {}  # "METHOD path" -> FakeResponse (forced answer)
		self.proof_fetches = []
		self.companion_base_urls = {}  # installation_id -> declared companion_base_url

	# transport entry point
	def request(self, method, url, data=b"", headers=None, **kwargs):
		path = urlsplit(url).path
		body = json.loads(data) if data else None
		self.calls.append({"method": method, "path": path, "body": body, "raw": data, "headers": dict(headers or {})})
		forced = self.fail.get(f"{method} {path}")
		if forced:
			return forced
		for prefix, handler in (
			("/api/v1/tenants/bootstrap/start", self.bootstrap_start),
			("/api/v1/tenants/bootstrap/", self.bootstrap_finalize),
			("/api/v1/tenants/repair/start", self.repair_start),
			("/api/v1/tenants/repair/", self.repair_finalize),
			("/api/v1/tenants/relocate/start", self.relocate_start),
			("/api/v1/tenants/relocate/", self.relocate_finalize),
			("/api/v1/tenants/installation/reset", self.reset),
			("/profiles", self.profiles),
		):
			if path.startswith(prefix):
				return handler(path, body, headers or {}, data)
		return error(404, "not_found")

	def get(self, url, **kwargs):
		return FakeResponse(404, None)

	# helpers
	def _new_flow(self, kind, installation_id, url):
		flow_id = str(uuid.uuid4())
		challenge = secrets.token_urlsafe(32)
		self.flows[flow_id] = {"kind": kind, "installation_id": installation_id, "url": url, "challenge": challenge, "status": "pending"}
		return flow_id, challenge

	def _fetch_proof(self, function, flow_id):
		"""GET {companion_base_url}.{function}?id={flow_id} (provisional middleware template)."""
		status, body = call_surface(function, "GET", {"id": flow_id})
		self.proof_fetches.append({"function": function, "args": {"id": flow_id}, "status": status, "body": body})
		return status, body

	@staticmethod
	def _identity(url):
		parts = urlsplit(url)
		return parts.netloc + parts.path.rstrip("/")

	# bootstrap
	def bootstrap_start(self, path, body, headers, raw):
		assert set(body) == {"installation_id", "erp_type", "dolibarr_base_url", "companion_base_url"}, body
		installation_id, url = body["installation_id"], body["dolibarr_base_url"]
		if not identity.is_uuid_v4(installation_id):
			return error(422, "invalid_installation_id")
		companion, erp = urlsplit(body["companion_base_url"]), urlsplit(url)
		# constraints stated by the middleware: same host, same port, /api/method/ prefix
		if body["erp_type"] != "erpnext" or companion.netloc != erp.netloc or not companion.path.startswith("/api/method/"):
			return error(422, "invalid_companion_base_url")
		self.companion_base_urls[installation_id] = body["companion_base_url"]
		known = self.tenants.get(installation_id)
		if known and self._identity(known["url"]) != self._identity(url):
			return error(409, "installation_url_mismatch", dolibarr_base_url=known["url"])
		if known:
			return error(409, "tenant_already_enrolled")
		flow_id, challenge = self._new_flow("bootstrap", installation_id, url)
		return FakeResponse(201, {
			"bootstrap_id": flow_id, "challenge": challenge, "expires_at": "2026-09-29 14:05:00.000000",
			"expires_in_seconds": 300, "proof_url": f"{self.companion_base_urls[installation_id]}.bootstrap_proof?id={flow_id}",
		})  # fmt: skip

	def bootstrap_finalize(self, path, body, headers, raw):
		flow_id = path.split("/")[5]
		flow = self.flows.get(flow_id)
		if not flow or flow["kind"] != "bootstrap" or flow["status"] != "pending":
			return error(404, "bootstrap_not_found")
		flow["status"] = "verifying"
		status, proof = self._fetch_proof("bootstrap_proof", flow_id)
		if status != 200 or proof.get("bootstrap_id") != flow_id or proof.get("installation_id") != flow["installation_id"] or proof.get("challenge") != flow["challenge"]:
			return error(422, "bootstrap_verification_failed")
		flow["status"] = "completed"
		if self.legacy_url and self._identity(self.legacy_url) == self._identity(flow["url"]):
			self.tenants[flow["installation_id"]] = {"tenant_uuid": TENANT, "secret": SECRET, "url": flow["url"]}
			return FakeResponse(201, {
				"tenant_id": TENANT, "hmac_secret_retained": True, "bootstrap_mode": "legacy_migration",
				"warning": "…", "billing_status": "active", "eligible_until": "2026-12-31 00:00:00.000000",
			})  # fmt: skip
		secret = secrets.token_urlsafe(48)
		self.tenants[flow["installation_id"]] = {"tenant_uuid": TENANT, "secret": secret, "url": flow["url"]}
		return FakeResponse(201, {
			"tenant_id": TENANT, "dolibarr_hmac_secret": secret, "warning": "Ne le journalisez pas.",
			"billing_status": "trialing", "eligible_until": "2026-10-29 14:00:12.345678", "free_trial_granted": 1500000,
		})  # fmt: skip

	# repair
	def repair_start(self, path, body, headers, raw):
		installation_id = body.get("installation_id")
		if not identity.is_uuid_v4(installation_id or ""):
			return error(422, "invalid_installation_id")
		known = self.tenants.get(installation_id)
		if not known:
			return error(404, "repair_not_found")
		if body.get("dolibarr_base_url") and self._identity(known["url"]) != self._identity(body["dolibarr_base_url"]):
			return error(409, "installation_url_mismatch", dolibarr_base_url=known["url"])
		flow_id, challenge = self._new_flow("repair", installation_id, known["url"])
		return FakeResponse(201, {
			"repair_id": flow_id, "challenge": challenge, "expires_at": "2026-09-29 14:05:00.000000",
			"expires_in_seconds": 300, "proof_url": f"{self.companion_base_urls.get(installation_id, known['url'] + '/api/method/speakdo_erpnext.api.companion')}.repair_proof?id={flow_id}",
		})  # fmt: skip

	def repair_finalize(self, path, body, headers, raw):
		flow_id = path.split("/")[5]
		flow = self.flows.get(flow_id)
		if not flow or flow["kind"] != "repair":
			return error(404, "repair_not_found")
		if flow["status"] != "pending":
			return error(409, "repair_already_consumed")
		flow["status"] = "verifying"
		status, proof = self._fetch_proof("repair_proof", flow_id)
		if status != 200 or proof != {"repair_id": flow_id, "installation_id": flow["installation_id"], "challenge": flow["challenge"]}:
			return error(422, "repair_verification_failed")
		flow["status"] = "completed"
		tenant = self.tenants[flow["installation_id"]]
		tenant["secret"] = secrets.token_urlsafe(48)
		return FakeResponse(200, {
			"tenant_uuid": tenant["tenant_uuid"], "installation_id": flow["installation_id"],
			"dolibarr_hmac_secret": tenant["secret"], "repair_completed": True, "warning": "…",
		})  # fmt: skip

	# relocation
	def relocate_start(self, path, body, headers, raw):
		if not self.relocation_enabled:
			return error(404, "not_found")
		known = self.tenants.get(body["installation_id"])
		if not known:
			return error(404, "installation_not_found")
		if self._identity(known["url"]) == self._identity(body["dolibarr_base_url"]):
			return FakeResponse(200, {
				"ok": False, "error": {"code": "installation_url_unchanged", "message": "…"},
				"dolibarr_base_url": known["url"],
			})  # fmt: skip
		flow_id, challenge = self._new_flow("relocation", body["installation_id"], body["dolibarr_base_url"])
		return FakeResponse(201, {"relocation_id": flow_id, "challenge": challenge, "expires_in_seconds": 300})

	def relocate_finalize(self, path, body, headers, raw):
		if not self.relocation_enabled:
			return error(404, "not_found")
		flow_id = path.split("/")[5]
		flow = self.flows.get(flow_id)
		if not flow or flow["kind"] != "relocation":
			return error(404, "relocation_not_found")
		status, proof = self._fetch_proof("relocation_proof", flow_id)
		expected = {"relocation_id": flow_id, "installation_id": flow["installation_id"], "new_base_url": flow["url"], "challenge": flow["challenge"]}
		if status != 200 or proof != expected:
			return error(422, "relocation_proof_failed")
		tenant = self.tenants[flow["installation_id"]]
		tenant["url"] = flow["url"]
		return FakeResponse(200, {"tenant_uuid": tenant["tenant_uuid"], "relocation_completed": True})

	# profile catalogue (HMAC) - same structure as the LAB middleware (30/09/2026)
	PROFILES = {
		"ok": True,
		"profiles": [
			{"id": "commercial", "version": 1, "label": "Commercial — suivi client", "short_label": "Commercial", "labels": {}, "doc_url": "https://docs.speakdo.fr/profils/commercial", "requires": {"required": {"all_of": ["societe"], "any_of": []}}, "enhanced_by": []},
			{"id": "field.it_technician", "version": 1, "label": "Technicien informatique — terrain", "short_label": "Technicien IT", "labels": {}, "doc_url": "https://docs.speakdo.fr/profils/technicien-informatique", "requires": {"required": {"all_of": ["societe"], "any_of": ["ticket", "ficheinter"]}}, "enhanced_by": []},
			{"id": "generic", "version": 1, "label": "Générique", "short_label": "Générique", "labels": {}, "doc_url": "https://docs.speakdo.fr/profils/generique", "requires": {"required": {"all_of": [], "any_of": []}}, "enhanced_by": []},
			{"id": "receptionist", "version": 1, "label": "Réceptionniste", "short_label": "Réceptionniste", "labels": {}, "doc_url": "https://docs.speakdo.fr/profils/receptionniste", "requires": {"required": {"all_of": ["societe", "ticket"], "any_of": []}}, "enhanced_by": []},
		],
		"aliases": [{"id": "field.it_support", "alias_of": "field.it_technician", "label": "ancien profil"}],
	}

	def profiles(self, path, body, headers, raw):
		tenant = next((t for t in self.tenants.values() if t["tenant_uuid"] == headers.get("X-SpeakDo-Tenant")), None)
		expected = tenant and reference_sign(
			tenant["secret"], "GET", path, headers["X-SpeakDo-Timestamp"], headers["X-SpeakDo-Nonce"], raw or b""
		)
		if not tenant or expected != headers.get("X-SpeakDo-Signature"):
			return error(401, "invalid_tenant_signature")
		return FakeResponse(200, self.PROFILES)

	# reset (HMAC)
	def reset(self, path, body, headers, raw):
		if not self.reset_enabled:
			return error(404, "not_found")
		tenant = next((t for t in self.tenants.values() if t["tenant_uuid"] == headers.get("X-SpeakDo-Tenant")), None)
		expected = tenant and reference_sign(
			tenant["secret"], "POST", path, headers["X-SpeakDo-Timestamp"], headers["X-SpeakDo-Nonce"], raw
		)
		if not tenant or expected != headers.get("X-SpeakDo-Signature"):
			return error(401, "invalid_tenant_signature")
		if self.tenants.get(body["installation_id"]) is not tenant:
			return error(403, "installation_mismatch")
		tenant["secret"] = secrets.token_urlsafe(48)  # unknown to everyone
		return FakeResponse(200, {"ok": True})


class CapturingLogger:
	def __init__(self):
		self.lines = []

	def info(self, msg, *args, **kwargs):
		self.lines.append(str(msg))

	warning = error = debug = exception = info


class SpeakDoTestCase(FrappeTestCase):
	"""Clean companion state for every test; no commit, no site_config write."""

	def setUp(self):
		frappe.set_user("Administrator")
		self._backup = {"value": None}
		self.logger = CapturingLogger()
		self._patches = [
			patch.object(identity, "_read_backup", side_effect=lambda: self._backup["value"]),
			patch.object(identity, "_write_backup", side_effect=lambda v: self._backup.__setitem__("value", v)),
			patch.object(flows, "commit_publication", lambda: None),
			patch.object(companion_http, "_commit", lambda: None),
			patch("speakdo_erpnext.services.log.get_logger", return_value=self.logger),
		]
		for p in self._patches:
			p.start()
		for doctype in (FLOW_CHALLENGE_DOCTYPE, ENROLLMENT_TOKEN_DOCTYPE, TERMINAL_DOCTYPE, NONCE_DOCTYPE):
			frappe.db.delete(doctype)
		frappe.db.delete(CREDENTIAL_DOCTYPE)
		frappe.db.delete(ALLOWED_PROFILE_DOCTYPE)
		frappe.cache.delete_value("speakdo_profile_catalogue")
		# API keys of the test users only (never a real account of the site).
		for name in frappe.get_all("User", filters={"name": ("like", "%@example.%")}, pluck="name"):
			frappe.db.set_value("User", name, "api_key", None, update_modified=False)
			frappe.db.delete("__Auth", {"doctype": "User", "name": name, "fieldname": "api_secret"})
		frappe.db.delete("__Auth", {"doctype": FLOW_CHALLENGE_DOCTYPE})
		store.clear_hmac_secret()
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "installation_id", None)
		store.update(
			middleware_url=MW_URL,
			app_url="https://app.test",
			instance_url=ERP_URL,
			declared_instance_url=None,
			tenant_uuid=None,
			enrollment_status=EnrollmentStatus.NOT_ENROLLED,
			bootstrap_mode=None,
			relocation_availability=None,
			reset_availability=None,
			last_error_code=None,
			last_error_message=None,
		)
		self.installation_id = identity.ensure_installation_id()
		self.mw = FakeMiddleware()

	def tearDown(self):
		for p in reversed(self._patches):
			p.stop()
		frappe.set_user("Administrator")

	def protocol(self):
		return get_middleware_protocol(MiddlewareClient(base_url=MW_URL, session=self.mw))

	def enroll(self):
		"""Put the companion in the enrolled state through a real bootstrap."""
		from speakdo_erpnext.services import enrollment

		enrollment.bootstrap(protocol=self.protocol())
		return self.mw.tenants[self.installation_id]["secret"]

	def set_enrolled(self, secret=SECRET):
		store.store_hmac_secret(secret)
		store.update(tenant_uuid=TENANT, enrollment_status=EnrollmentStatus.ENROLLED, declared_instance_url=ERP_URL)
		self.mw.tenants[self.installation_id] = {"tenant_uuid": TENANT, "secret": secret, "url": ERP_URL}

	def make_user(self, email, enabled=1, roles=("System Manager",)):
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Jean", "last_name": "Dupont", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles(*roles)
		frappe.db.set_value("User", email, "enabled", enabled)
		return email
