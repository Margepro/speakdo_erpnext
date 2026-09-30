import os
import re

from speakdo_erpnext.adapters import middleware_legacy as wire
from speakdo_erpnext.domain import erp_instance
from speakdo_erpnext.domain.erp_users import get_erp_user
from speakdo_erpnext.services import enrollment
from speakdo_erpnext.services.errors import MiddlewareHTTPError, StateError
from speakdo_erpnext.tests.utils import ERP_URL, SpeakDoTestCase

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADAPTER = os.path.join(APP_ROOT, "adapters", "middleware_legacy.py")


class TestWireAdapter(SpeakDoTestCase):
	def test_bootstrap_body_translation(self):
		body = wire.bootstrap_start_body(self.installation_id, "erpnext", ERP_URL, erp_instance.companion_base_url(ERP_URL))
		self.assertEqual(
			body,
			{
				"installation_id": self.installation_id,
				"erp_type": "erpnext",
				"dolibarr_base_url": "https://erp.client.example",
				"companion_base_url": "https://erp.client.example/api/method/speakdo_erpnext.api.companion",
			},
		)
		self.assertEqual(wire.flow_start_body(self.installation_id, ERP_URL), {"installation_id": self.installation_id, "dolibarr_base_url": ERP_URL})

	def test_companion_base_url_constraints(self):
		for erp in ("https://erp.client.example", "http://92.0.2.10:8080"):
			companion = erp_instance.companion_base_url(erp)
			self.assertTrue(companion.startswith(erp + "/api/method/"))
		self.assertEqual(
			erp_instance.surface_path("terminal_status"), "/api/method/speakdo_erpnext.api.companion.terminal_status"
		)

	def test_secret_name_translation(self):
		parsed = wire.parse_bootstrap_finalize({"tenant_id": "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e", "dolibarr_hmac_secret": "s" * 64})
		self.assertEqual(parsed["hmac_secret"], "s" * 64)
		parsed = wire.parse_bootstrap_finalize({"tenant_uuid": "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e", "erp_hmac_secret": "g" * 64})
		self.assertEqual(parsed["hmac_secret"], "g" * 64)

	def test_middleware_locked_once_attached(self):
		self.enroll()
		with self.assertRaises(StateError):
			enrollment.save_configuration(middleware_url="https://other-mw.test")

	def test_error_code_translation(self):
		exc = MiddlewareHTTPError(error_code="invalid_dolibarr_url", http_status=422, server_error_code="invalid_dolibarr_url", body={})
		self.assertEqual(wire.translate_error(exc).error_code, "invalid_erp_url")
		gate = MiddlewareHTTPError(error_code="not_found", http_status=404, server_error_code="not_found", body={})
		self.assertEqual(wire.translate_error(gate, feature_gated=True).error_code, "feature_unavailable")
		self.assertEqual(wire.translate_error(gate).error_code, "not_found")

	def test_no_dolibarr_naming_outside_the_adapter(self):
		offenders = []
		pattern = re.compile(r"dolibarr|DOLAPIKEY|api/index\.php", re.IGNORECASE)
		for root, _dirs, files in os.walk(APP_ROOT):
			if "__pycache__" in root or os.path.join(APP_ROOT, "tests") in root:
				continue
			for name in files:
				if not name.endswith((".py", ".js", ".json", ".txt", ".css")):
					continue
				path = os.path.join(root, name)
				if path == ADAPTER:
					continue
				with open(path, encoding="utf-8") as f:
					for number, line in enumerate(f, 1):
						if pattern.search(line):
							offenders.append(f"{os.path.relpath(path, APP_ROOT)}:{number}")
		self.assertEqual(offenders, [])

	def test_user_name_is_the_wire_user_id_and_credential_format(self):
		from speakdo_erpnext.domain.erp_credentials import ErpCredential

		user = self.make_user("jane@example.fr")
		result = {
			"valid": True,
			"user": get_erp_user(user),
			"terminal_status": "active",
			"capabilities": [],
			"channel": "pwa",
			"permissions_version": "v",
			"erp_credential": None,
		}
		body = wire.verify_response(result)
		self.assertEqual(body["user"], {"id": "jane@example.fr", "active": True, "display_name": "Jean Dupont"})
		self.assertEqual(
			set(body), {"valid", "user", "terminal_status", "capabilities", "channel", "permissions_version", "allowed_profiles"}
		)
		self.assertEqual(body["allowed_profiles"], [])
		self.assertEqual(wire.verify_response({**result, "allowed_profiles": ["generic", "commercial", "generic"]})["allowed_profiles"], ["commercial", "generic"])
		credential = ErpCredential("erpnext_api_token", "k1", "s1")
		body = wire.verify_response({**result, "erp_credential": credential})
		self.assertEqual((body["credential_type"], body["erp_credential"]), ("erpnext_api_token", "k1:s1"))
		self.assertNotIn("dolibarr_apikey", body)
		self.assertNotIn("s1", repr(credential))
