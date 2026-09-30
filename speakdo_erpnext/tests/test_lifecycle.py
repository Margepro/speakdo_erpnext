from unittest.mock import patch

import frappe

from speakdo_erpnext.constants import TERMINAL_DOCTYPE, EnrollmentStatus, FeatureAvailability
from speakdo_erpnext.services import enrollment, enrollment_tokens, flows, lifecycle, store
from speakdo_erpnext.services import lifecycle as lifecycle_module
from speakdo_erpnext.services.errors import StateError
from speakdo_erpnext.tests.utils import ERP_URL, TENANT, SpeakDoTestCase, error

NEW_URL = "https://new.client.example"


class TestRelocation(SpeakDoTestCase):
	def setUp(self):
		super().setUp()
		self.secret = self.enroll()
		self.calls_after_enroll = len(self.mw.calls)

	def test_relocation_unavailable_for_erpnext(self):
		# The middleware refuses ERPNext relocation: refused locally, never attempted.
		enrollment.save_configuration(instance_url=NEW_URL)
		result = flows.run("relocate", lifecycle.relocate, protocol=self.protocol())
		self.assertEqual((result["ok"], result["error_code"]), (False, "feature_unavailable"))
		self.assertEqual(len(self.mw.calls), self.calls_after_enroll)
		self.assertEqual(store.get("relocation_availability"), FeatureAvailability.UNAVAILABLE)
		self.assertEqual(store.get("declared_instance_url"), ERP_URL)
		self.assertEqual(store.get_hmac_secret(), self.secret)

	def test_feature_gate_respected_when_enabled_locally(self):
		enrollment.save_configuration(instance_url=NEW_URL)
		with patch.object(lifecycle_module, "RELOCATION_SUPPORTED", True):
			result = flows.run("relocate", lifecycle.relocate, protocol=self.protocol())
		self.assertEqual((result["error_code"], result["http_status"]), ("feature_unavailable", 404))
		self.assertEqual(store.get("declared_instance_url"), ERP_URL)

	def test_prepared_relocation_flow(self):
		self.mw.relocation_enabled = True
		enrollment.save_configuration(instance_url=NEW_URL)
		with patch.object(lifecycle_module, "RELOCATION_SUPPORTED", True):
			lifecycle.relocate(protocol=self.protocol())
		start = next(c for c in self.mw.calls if c["path"] == "/api/v1/tenants/relocate/start")
		self.assertEqual(start["body"], {"installation_id": self.installation_id, "dolibarr_base_url": NEW_URL})
		self.assertEqual(self.mw.proof_fetches[-1]["body"]["new_base_url"], NEW_URL)
		self.assertEqual(store.get("declared_instance_url"), NEW_URL)
		self.assertEqual(store.get_hmac_secret(), self.secret)
		self.assertEqual(store.get("tenant_uuid"), TENANT)


class TestReset(SpeakDoTestCase):
	def setUp(self):
		super().setUp()
		self.secret = self.enroll()
		self.user = self.make_user("speakdo.reset@example.com")
		enrollment_tokens.issue(self.user)
		doc = frappe.new_doc(TERMINAL_DOCTYPE)
		doc.name = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
		doc.erp_user = self.user
		doc.status = "active"
		doc.db_insert()

	def test_feature_gate_respected(self):
		result = flows.run("reset", lifecycle.reset, protocol=self.protocol())
		self.assertEqual((result["ok"], result["error_code"]), (False, "feature_unavailable"))
		self.assertEqual(store.get("reset_availability"), FeatureAvailability.UNAVAILABLE)
		# nothing erased: 404 is NOT treated as a terminal status
		self.assertEqual(store.get_hmac_secret(), self.secret)
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.ENROLLED)
		self.assertEqual(frappe.db.get_single_value("SpeakDo Settings", "installation_id"), self.installation_id)

	def test_reset_is_hmac_signed_and_clears_local_attachment(self):
		self.mw.reset_enabled = True
		lifecycle.reset(protocol=self.protocol())
		call = self.mw.calls[-1]
		self.assertEqual(call["path"], "/api/v1/tenants/installation/reset")
		self.assertEqual(call["body"], {"installation_id": self.installation_id, "reason": "admin_factory_reset"})
		self.assertEqual(call["headers"]["X-SpeakDo-Tenant"], TENANT)
		self.assertFalse(store.has_hmac_secret())
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.REPAIR_REQUIRED)
		self.assertEqual(store.get("tenant_uuid"), TENANT)
		self.assertEqual(frappe.db.get_single_value("SpeakDo Settings", "installation_id"), self.installation_id)
		self.assertEqual(frappe.db.get_value(TERMINAL_DOCTYPE, {}, "status"), "revoked")
		self.assertEqual(frappe.db.count("SpeakDo Enrollment Token", {"status": "issued"}), 0)

	def test_reset_refused_signature_keeps_credentials(self):
		self.mw.reset_enabled = True
		self.mw.tenants[self.installation_id]["secret"] = "rotated-elsewhere-" * 3
		result = flows.run("reset", lifecycle.reset, protocol=self.protocol())
		self.assertEqual(result["error_code"], "invalid_tenant_signature")
		self.assertEqual(store.get_hmac_secret(), self.secret)

	def test_repair_after_reset(self):
		from speakdo_erpnext.services import repair

		self.mw.reset_enabled = True
		lifecycle.reset(protocol=self.protocol())
		repair.repair(protocol=self.protocol())
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.ENROLLED)
		self.assertEqual(frappe.db.get_single_value("SpeakDo Settings", "installation_id"), self.installation_id)

	def test_reset_requires_enrollment(self):
		store.clear_hmac_secret()
		with self.assertRaises(StateError):
			lifecycle.reset(protocol=self.protocol())

	def test_feature_unavailable_is_distinct_from_business_404(self):
		self.mw.reset_enabled = True
		self.mw.fail["POST /api/v1/tenants/installation/reset"] = error(404, "installation_not_found")
		result = flows.run("reset", lifecycle.reset, protocol=self.protocol())
		self.assertEqual(result["error_code"], "installation_not_found")
		self.assertNotEqual(store.get("reset_availability"), FeatureAvailability.UNAVAILABLE)
		self.assertEqual(store.get_hmac_secret(), self.secret)
