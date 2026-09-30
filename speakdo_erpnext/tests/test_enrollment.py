import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import frappe
from frappe.utils import now_datetime

from speakdo_erpnext.constants import ENROLLMENT_TOKEN_DOCTYPE, TERMINAL_DOCTYPE
from speakdo_erpnext.domain.erp_capabilities import capabilities_for, permissions_version
from speakdo_erpnext.services import enrollment_tokens, qr
from speakdo_erpnext.services.errors import StateError
from speakdo_erpnext.tests.utils import SECRET, TENANT, SpeakDoTestCase, call_surface, signed_call

TERMINAL_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
PEM = "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\n-----END PUBLIC KEY-----"


def verify_body(consume=True, terminal_id=TERMINAL_ID):
	return json.dumps(
		{
			"consume": consume,
			"terminal": {
				"terminal_id": terminal_id,
				"label": "Téléphone chantier",
				"public_key_pem": PEM,
				"public_key_fingerprint": "sha256:abcdef0123456789",
			},
		}
	).encode()


class TestEnrollmentTokens(SpeakDoTestCase):
	def setUp(self):
		super().setUp()
		self.set_enrolled()
		self.user = self.make_user("jane@example.fr")

	def generate(self, user=None):
		captured = {}
		with patch.object(qr, "render_png_data_uri", side_effect=lambda url: captured.setdefault("url", url) and "data:x"):
			result = qr.generate_enrollment_qr(user or self.user)
		return result, captured["url"]

	def test_qr_generation(self):
		result, url = self.generate()
		parts = urlsplit(url)
		query = parse_qs(parts.query)
		self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", "https://app.test/enroll")
		self.assertEqual(query["tenant_id"], [TENANT])
		self.assertEqual(query["channel"], ["pwa"])
		token = query["token"][0]
		self.assertRegex(token, r"^[A-Za-z0-9._~-]{24,512}$")
		self.assertNotIn("token", result)
		# only the SHA-256 is stored
		self.assertFalse(frappe.db.exists(ENROLLMENT_TOKEN_DOCTYPE, token))
		row = frappe.get_doc(ENROLLMENT_TOKEN_DOCTYPE, enrollment_tokens.token_hash(token))
		self.assertEqual((row.erp_user, row.status, row.channel), (self.user, "issued", "pwa"))
		self.assertNotIn(token, frappe.as_json(row.as_dict()))

	def test_qr_requires_enrolled_instance_and_enrollable_user(self):
		disabled = self.make_user("speakdo.disabled@example.com", enabled=0)
		with self.assertRaises(StateError) as ctx:
			qr.generate_enrollment_qr(disabled)
		self.assertEqual(ctx.exception.error_code, "user_not_enrollable")
		frappe.db.set_single_value("SpeakDo Settings", "enrollment_status", "repair_required")
		with self.assertRaises(StateError) as ctx:
			qr.generate_enrollment_qr(self.user)
		self.assertEqual(ctx.exception.error_code, "not_enrolled")

	def test_one_shot_consumption(self):
		token, _ = enrollment_tokens.issue(self.user)
		enrollment_tokens.consume(token)
		with self.assertRaises(enrollment_tokens.TokenRejected) as ctx:
			enrollment_tokens.consume(token)
		self.assertEqual(ctx.exception.reason, "enrollment_token_consumed")

	def test_expired_token(self):
		token, _ = enrollment_tokens.issue(self.user)
		frappe.db.set_value(
			ENROLLMENT_TOKEN_DOCTYPE, enrollment_tokens.token_hash(token), "expires_at", now_datetime() - timedelta(seconds=1)
		)
		with self.assertRaises(enrollment_tokens.TokenRejected) as ctx:
			enrollment_tokens.consume(token)
		self.assertEqual(ctx.exception.reason, "enrollment_token_expired")

	def test_unknown_or_malformed_token(self):
		for token in ("x" * 43, "short", "bad token with spaces and more", "é" * 30):
			with self.assertRaises(enrollment_tokens.TokenRejected) as ctx:
				enrollment_tokens.consume(token)
			self.assertEqual(ctx.exception.reason, "enrollment_token_invalid")

	def test_verify_enrollment(self):
		_, url = self.generate()
		token = parse_qs(urlsplit(url).query)["token"][0]
		status, body = signed_call("enrollment_verify", "POST", {"token": token}, verify_body())
		self.assertEqual(status, 200)
		# ERP credential of the user (decision 30/09/2026): opaque "<api_key>:<api_secret>"
		self.assertEqual(body.pop("credential_type"), "erpnext_api_token")
		api_key, api_secret = body.pop("erp_credential").split(":")
		self.assertEqual(api_key, frappe.db.get_value("User", self.user, "api_key"))
		self.assertEqual(api_secret, frappe.utils.password.get_decrypted_password("User", self.user, "api_secret"))
		self.assertEqual(
			body,
			{
				"valid": True,
				"user": {"id": self.user, "active": True, "display_name": "Jean Dupont"},
				"terminal_status": "active",
				"capabilities": capabilities_for(self.user),
				"channel": "pwa",
				"permissions_version": permissions_version(capabilities_for(self.user)),
				"allowed_profiles": [],
			},
		)
		# User.name, a string: no artificial numeric id
		self.assertIsInstance(body["user"]["id"], str)
		terminal = frappe.get_doc(TERMINAL_DOCTYPE, TERMINAL_ID)
		self.assertEqual((terminal.erp_user, terminal.status, terminal.label), (self.user, "active", "Téléphone chantier"))
		token_row = frappe.get_doc(ENROLLMENT_TOKEN_DOCTYPE, enrollment_tokens.token_hash(token))
		self.assertEqual((token_row.status, token_row.terminal_id), ("consumed", TERMINAL_ID))

		# one shot through the surface as well
		status, body = signed_call("enrollment_verify", "POST", {"token": token}, verify_body(terminal_id="1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e")
		)
		self.assertEqual((status, body["valid"], body["error"]["code"]), (200, False, "enrollment_token_consumed"))

	def test_verify_without_consume_does_not_consume(self):
		token, _ = enrollment_tokens.issue(self.user)
		_, body = signed_call("enrollment_verify", "POST", {"token": token}, verify_body(consume=False))
		self.assertTrue(body["valid"])
		self.assertEqual(frappe.db.get_value(ENROLLMENT_TOKEN_DOCTYPE, enrollment_tokens.token_hash(token), "status"), "issued")
		self.assertFalse(frappe.db.exists(TERMINAL_DOCTYPE, TERMINAL_ID))

	def test_verify_expired_token(self):
		token, _ = enrollment_tokens.issue(self.user, ttl_seconds=-1)
		status, body = signed_call("enrollment_verify", "POST", {"token": token}, verify_body())
		self.assertEqual((status, body["valid"], body["error"]["code"]), (200, False, "enrollment_token_expired"))

	def test_verify_inactive_user(self):
		token, _ = enrollment_tokens.issue(self.user)
		frappe.db.set_value("User", self.user, "enabled", 0)
		_, body = signed_call("enrollment_verify", "POST", {"token": token}, verify_body())
		self.assertEqual((body["valid"], body["user"]["active"]), (True, False))
		self.assertFalse(frappe.db.exists(TERMINAL_DOCTYPE, TERMINAL_ID))

	def test_verify_requires_hmac(self):
		token, _ = enrollment_tokens.issue(self.user)
		status, body = call_surface("enrollment_verify", "POST", {"token": token}, body=verify_body())
		self.assertEqual((status, body["error"]["code"]), (401, "tenant_signature_missing"))
		status, _ = signed_call("enrollment_verify", "POST", {"token": token}, verify_body(), secret="wrong-" * 8)
		self.assertEqual(status, 401)
		self.assertEqual(frappe.db.get_value(ENROLLMENT_TOKEN_DOCTYPE, enrollment_tokens.token_hash(token), "status"), "issued")

	def test_verify_malformed_requests_do_not_consume(self):
		token, _ = enrollment_tokens.issue(self.user)
		args = {"token": token}
		self.assertEqual(signed_call("enrollment_verify", "POST", args, b"not json")[0], 400)
		self.assertEqual(signed_call("enrollment_verify", "POST", args, verify_body(terminal_id="not-a-uuid"))[0], 422)
		self.assertEqual(frappe.db.get_value(ENROLLMENT_TOKEN_DOCTYPE, enrollment_tokens.token_hash(token), "status"), "issued")

	def test_no_fake_dolibarr_api_key(self):
		token, _ = enrollment_tokens.issue(self.user)
		_, body = signed_call("enrollment_verify", "POST", {"token": token}, verify_body())
		self.assertTrue(body["valid"])
		self.assertNotIn("dolibarr_apikey", body)
		# only the generic, opaque credential fields
		self.assertEqual({k for k in body if "credential" in k or "key" in k or "secret" in k}, {"credential_type", "erp_credential"})
		self.assertEqual(body["credential_type"], "erpnext_api_token")

	def test_secret_of_signed_call_matches_tenant(self):
		self.assertEqual(SECRET, frappe.utils.password.get_decrypted_password("SpeakDo Settings", "SpeakDo Settings", "hmac_secret"))
