import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import frappe

from speakdo_erpnext.api import admin
from speakdo_erpnext.constants import SETTINGS_DOCTYPE
from speakdo_erpnext.services import qr, repair
from speakdo_erpnext.tests.utils import SURFACE, SpeakDoTestCase, as_user, call_surface, reference_headers

ADMIN_METHODS = {
	"get_status": {},
	"run_diagnostics": {},
	"save_configuration": {"app_url": "https://x.test"},
	"restore_default_urls": {},
	"bootstrap": {},
	"generate_qr": {},
	"repair": {},
	"relocate": {},
	"reset": {"confirmation": "RESET"},
	"list_terminals": {},
	"revoke_terminal": {"terminal_id": "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"},
}


class TestAdminPermissions(SpeakDoTestCase):
	def test_admin_role_required(self):
		plain = self.make_user("speakdo.plain@example.com", roles=("Blogger",))
		for user in ("Guest", plain):
			for method, kwargs in ADMIN_METHODS.items():
				with self.subTest(user=user, method=method), as_user(user):
					with self.assertRaises(frappe.PermissionError):
						getattr(admin, method)(**kwargs)

	def test_admin_methods_are_not_guest_whitelisted(self):
		for method in ADMIN_METHODS:
			fn = getattr(admin, method)
			self.assertIn(fn, frappe.whitelisted)
			self.assertNotIn(fn, frappe.guest_methods)

	def test_manager_can_read_status_without_secret(self):
		secret = self.enroll()
		status = admin.get_status()
		self.assertEqual(status["tenant_uuid"], self.mw.tenants[self.installation_id]["tenant_uuid"])
		self.assertNotIn(secret, json.dumps(status, default=str))
		self.assertTrue(status["has_credentials"])

	def test_settings_form_cannot_change_identity(self):
		self.enroll()
		doc = frappe.get_doc(SETTINGS_DOCTYPE)
		doc.installation_id = "3f0b6c1e-8a51-4f7e-9b0d-2a7c5e9d1f44"
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestNoSecretsInLogs(SpeakDoTestCase):
	def test_no_secret_in_logs(self):
		error_logs_before = frappe.db.count("Error Log")
		secret = self.enroll()
		user = self.make_user("speakdo.logs@example.com")

		captured = {}
		with patch.object(qr, "render_png_data_uri", side_effect=lambda url: captured.setdefault("url", url)):
			qr.generate_enrollment_qr(user)
		token = parse_qs(urlsplit(captured["url"]).query)["token"][0]

		body = json.dumps(
			{"consume": True, "terminal": {"terminal_id": "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d", "label": "t", "public_key_pem": "PEM", "public_key_fingerprint": "fp"}}
		).encode()
		headers = reference_headers(secret, "POST", f"{SURFACE}.enrollment_verify?token={token}", body)
		status, verified = call_surface("enrollment_verify", "POST", {"token": token}, headers, body)
		self.assertEqual(status, 200)
		erp_credential = verified["erp_credential"]

		repair.repair(protocol=self.protocol())
		new_secret = self.mw.tenants[self.installation_id]["secret"]

		sensitive = [secret, new_secret, token, headers["X-SpeakDo-Signature"], headers["X-SpeakDo-Nonce"]]
		sensitive += [erp_credential, erp_credential.split(":")[1]]  # ERP credential and its api_secret
		sensitive += [flow["challenge"] for flow in self.mw.flows.values()]
		log = "\n".join(self.logger.lines)
		self.assertTrue(self.logger.lines, "the flows must have produced log lines")
		for value in sensitive:
			self.assertNotIn(value, log)
		self.assertEqual(frappe.db.count("Error Log"), error_logs_before)
		# log records only carry whitelisted technical fields
		for line in self.logger.lines:
			self.assertEqual(
				set(json.loads(line)), {"operation", "stage", "status", "error_code", "http_status", "latency_ms", "timestamp"}
			)
