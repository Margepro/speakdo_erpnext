from urllib.parse import quote

import frappe

from speakdo_erpnext.api import companion
from speakdo_erpnext.constants import FlowType
from speakdo_erpnext.domain.erp_capabilities import capabilities_for, permissions_version
from speakdo_erpnext.services import challenges, store, terminals
from speakdo_erpnext.tests.utils import (
	ERP_URL,
	SECRET,
	SURFACE,
	SpeakDoTestCase,
	call_surface,
	reference_headers,
	signed_call,
)

TERMINAL_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
FLOW_ID = "3f0b6c1e-8a51-4f7e-9b0d-2a7c5e9d1f44"
CHALLENGE = "C" * 43


class TestSurface(SpeakDoTestCase):
	def setUp(self):
		super().setUp()
		self.set_enrolled()
		self.user = self.make_user("speakdo.field@example.com")

	def add_terminal(self, status="active"):
		doc = frappe.new_doc("SpeakDo Terminal")
		doc.name = TERMINAL_ID
		doc.erp_user = self.user
		doc.status = status
		doc.label = "t"
		doc.db_insert()

	# -- Frappe exposure -----------------------------------------------------

	def test_whitelisting(self):
		expected = {
			"bootstrap_proof": {"GET"},
			"repair_proof": {"GET"},
			"relocation_proof": {"GET"},
			"enrollment_verify": {"POST"},
			"terminal_status": {"GET"},
			"user_capabilities": {"GET"},
			"action": {"POST"},
		}
		for name, methods in expected.items():
			fn = getattr(companion, name)
			self.assertIn(fn, frappe.guest_methods, name)
			self.assertIn(fn, frappe.xss_safe_methods, name)
			self.assertEqual(set(frappe.allowed_http_methods_for_whitelisted_func[fn]), methods, name)

	# -- proofs (public) -------------------------------------------------------

	def test_proof_endpoints_are_public(self):
		for flow_type, function, expected_keys in (
			(FlowType.BOOTSTRAP, "bootstrap_proof", {"bootstrap_id", "installation_id", "challenge", "companion_version", "protocol_version"}),
			(FlowType.REPAIR, "repair_proof", {"repair_id", "installation_id", "challenge"}),
			(FlowType.RELOCATION, "relocation_proof", {"relocation_id", "installation_id", "new_base_url", "challenge"}),
		):
			with self.subTest(flow=flow_type):
				challenges.store(flow_type, FLOW_ID, CHALLENGE, self.installation_id, ERP_URL)
				status, body = call_surface(function, args={"id": FLOW_ID})  # no session, no HMAC
				self.assertEqual(status, 200)
				self.assertEqual(set(body), expected_keys)
				self.assertEqual(body["challenge"], CHALLENGE)
				if flow_type == FlowType.RELOCATION:
					self.assertEqual(body["new_base_url"], ERP_URL)
				challenges.discard(FLOW_ID)

	def test_proof_only_for_valid_temporary_ids(self):
		challenges.store(FlowType.REPAIR, FLOW_ID, CHALLENGE, self.installation_id, ERP_URL)
		self.assertEqual(call_surface("bootstrap_proof", args={"id": FLOW_ID})[0], 404)  # other flow
		self.assertEqual(call_surface("repair_proof", args={"id": FLOW_ID[:-1] + "0"})[0], 404)
		self.assertEqual(call_surface("repair_proof", args={"id": "../../x"})[0], 404)
		self.assertEqual(call_surface("repair_proof")[0], 404)
		frappe.db.set_value("SpeakDo Flow Challenge", FLOW_ID, "expires_at", frappe.utils.add_to_date(None, seconds=-1))
		self.assertEqual(call_surface("repair_proof", args={"id": FLOW_ID})[0], 404)

	def test_proof_contains_no_permanent_secret(self):
		challenges.store(FlowType.BOOTSTRAP, FLOW_ID, CHALLENGE, self.installation_id, ERP_URL)
		_, body = call_surface("bootstrap_proof", args={"id": FLOW_ID})
		self.assertNotIn(SECRET, frappe.as_json(body))

	# -- terminal status ---------------------------------------------------------

	def test_terminal_status(self):
		self.add_terminal()
		args = {"terminal_uuid": TERMINAL_ID}
		version = permissions_version(capabilities_for(self.user))
		self.assertEqual(signed_call("terminal_status", args=args), (200, {"status": "active", "permissions_version": version}))
		frappe.db.set_value("SpeakDo Terminal", TERMINAL_ID, "status", "pending_approval")
		self.assertEqual(signed_call("terminal_status", args=args)[1]["status"], "pending_approval")
		terminals.revoke(TERMINAL_ID)
		self.assertEqual(signed_call("terminal_status", args=args)[1]["status"], "revoked")

	def test_terminal_status_unknown_or_user_disabled_is_revoked(self):
		self.assertEqual(signed_call("terminal_status", args={"terminal_uuid": "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e"})[1]["status"], "revoked")
		self.assertEqual(signed_call("terminal_status")[1]["status"], "revoked")
		self.add_terminal()
		frappe.db.set_value("User", self.user, "enabled", 0)
		self.assertEqual(signed_call("terminal_status", args={"terminal_uuid": TERMINAL_ID})[1]["status"], "revoked")

	# -- user capabilities ---------------------------------------------------------

	def test_user_capabilities(self):
		status, body = signed_call("user_capabilities", args={"user": self.user})
		caps = capabilities_for(self.user)
		self.assertEqual(
			(status, body),
			(200, {"active": True, "capabilities": caps, "permissions_version": permissions_version(caps), "allowed_profiles": []}),
		)
		frappe.db.set_value("User", self.user, "enabled", 0)
		self.assertFalse(signed_call("user_capabilities", args={"user": self.user})[1]["active"])
		self.assertFalse(signed_call("user_capabilities", args={"user": "nobody@example.com"})[1]["active"])

	# -- REQUEST_TARGET = path + raw query ----------------------------------------------

	def _raw(self, function, raw_query, sign_target=None, method="GET"):
		"""Call with a verbatim query; sign ``sign_target`` (default: the real target)."""
		real = f"{SURFACE}.{function}?{raw_query}"
		headers = reference_headers(SECRET, method, sign_target or real)
		return call_surface(function, method, headers=headers, raw_query=raw_query)

	def test_request_without_query(self):
		# terminal_status without parameter: REQUEST_TARGET is the bare path
		status, body = signed_call("terminal_status")
		self.assertEqual((status, body["status"]), (200, "revoked"))

	def test_simple_and_multiple_parameters_order_encoding_empty(self):
		user_q = quote(self.user, safe="")
		for raw_query in (
			f"user={user_q}",  # simple, percent-encoded value
			f"user={user_q}&extra=1&z=",  # several parameters, empty value
			f"z=&extra=1&user={user_q}",  # other order, signed as sent
			f"user={user_q}&user=ignored%40x.fr",  # repeated parameter (first one used)
			f"USER=x&user={user_q}",  # case kept
		):
			with self.subTest(query=raw_query):
				status, body = self._raw("user_capabilities", raw_query)
				self.assertEqual((status, body["active"]), (200, True))

	def test_path_only_signature_refused(self):
		status, body = self._raw("user_capabilities", f"user={quote(self.user, safe='')}", sign_target=f"{SURFACE}.user_capabilities")
		self.assertEqual((status, body["error"]["code"]), (401, "invalid_tenant_signature"))

	def test_query_tampering_refused(self):
		user_q = quote(self.user, safe="")
		signed = f"{SURFACE}.user_capabilities?user={user_q}&a=1"
		for sent in (
			"user=other%40example.fr&a=1",  # parameter modified
			f"user={user_q}",  # parameter removed
			f"user={user_q}&a=1&b=2",  # parameter added
			f"a=1&user={user_q}",  # reordered
			f"user={self.user}&a=1",  # same value, other encoding (@ vs %40)
		):
			with self.subTest(sent=sent):
				status, body = self._raw("user_capabilities", sent, sign_target=signed)
				self.assertEqual((status, body["error"]["code"]), (401, "invalid_tenant_signature"))

	def test_same_body_other_query_refused(self):
		token_a, token_b = "a" * 43, "b" * 43
		body = b'{"consume":true,"terminal":{}}'
		headers = reference_headers(SECRET, "POST", f"{SURFACE}.enrollment_verify?token={token_a}", body)
		status, resp = call_surface("enrollment_verify", "POST", headers=headers, body=body, raw_query=f"token={token_b}")
		self.assertEqual((status, resp["error"]["code"]), (401, "invalid_tenant_signature"))

	def test_real_erpnext_routes_signed_with_query(self):
		self.add_terminal()
		cases = (
			("enrollment_verify", "POST", f"token={'t' * 43}", b'{"consume":false,"terminal":{"terminal_id":"x"}}', 422),
			("terminal_status", "GET", f"terminal_uuid={TERMINAL_ID}", b"", 200),
			("user_capabilities", "GET", f"user={quote(self.user, safe='')}", b"", 200),
			("action", "POST", "action_id=task.create", b"{}", 424),
		)
		for function, method, raw_query, body, expected in cases:
			with self.subTest(function=function):
				target = f"{SURFACE}.{function}?{raw_query}"
				ok = call_surface(function, method, headers=reference_headers(SECRET, method, target, body), body=body, raw_query=raw_query)
				self.assertEqual(ok[0], expected, ok[1])
				bare = reference_headers(SECRET, method, f"{SURFACE}.{function}", body)
				refused = call_surface(function, method, headers=bare, body=body, raw_query=raw_query)
				self.assertEqual((refused[0], refused[1]["error"]["code"]), (401, "invalid_tenant_signature"))

	def test_absolute_form_target(self):
		raw_query = f"user={quote(self.user, safe='')}"
		target = f"http://erp.example:8080{SURFACE}.user_capabilities?{raw_query}"
		headers = reference_headers(SECRET, "GET", f"{SURFACE}.user_capabilities?{raw_query}")
		status, _ = call_surface("user_capabilities", headers=headers, raw_query=raw_query, target=target)
		self.assertEqual(status, 200)

	# -- action ----------------------------------------------------------------------

	def test_action_never_executes_business(self):
		status, body = signed_call("action", "POST", args={"action_id": "task.create"}, body=b'{"title":"x"}')
		self.assertEqual((status, body["error"]["code"]), (424, "erp_connector_unavailable"))
		self.assertEqual(call_surface("action", "POST", args={"action_id": "task.create"})[0], 401)

	# -- HMAC mandatory ---------------------------------------------------------------

	def test_hmac_routes_refused_without_signature(self):
		for function, method, args in (
			("terminal_status", "GET", {"terminal_uuid": TERMINAL_ID}),
			("user_capabilities", "GET", {"user": self.user}),
			("enrollment_verify", "POST", {"token": "t" * 43}),
			("action", "POST", {"action_id": "x"}),
		):
			with self.subTest(function=function):
				status, body = call_surface(function, method, args)
				self.assertEqual((status, body["error"]["code"]), (401, "tenant_signature_missing"))

	def test_hmac_bad_signature_and_expired_timestamp(self):
		self.assertEqual(signed_call("user_capabilities", args={"user": self.user}, secret="wrong-" * 8)[1]["error"]["code"], "invalid_tenant_signature")
		old = int(frappe.utils.now_datetime().timestamp()) - 1000
		self.assertEqual(signed_call("user_capabilities", args={"user": self.user}, timestamp=old)[1]["error"]["code"], "tenant_timestamp_expired")

	def test_replayed_request_refused(self):
		headers = reference_headers(SECRET, "GET", f"{SURFACE}.user_capabilities?user={quote(self.user, safe='')}")
		self.assertEqual(call_surface("user_capabilities", args={"user": self.user}, headers=headers)[0], 200)
		status, body = call_surface("user_capabilities", args={"user": self.user}, headers=headers)
		self.assertEqual((status, body["error"]["code"]), (401, "tenant_replay_detected"))

	def test_signature_for_another_function_refused(self):
		headers = reference_headers(SECRET, "GET", f"{SURFACE}.terminal_status?user={quote(self.user, safe='')}")
		status, body = call_surface("user_capabilities", args={"user": self.user}, headers=headers)
		self.assertEqual((status, body["error"]["code"]), (401, "invalid_tenant_signature"))

	def test_not_enrolled_instance_refuses_signed_calls(self):
		store.clear_hmac_secret()
		status, body = signed_call("user_capabilities", args={"user": self.user})
		self.assertEqual((status, body["error"]["code"]), (401, "invalid_tenant_signature"))
