import frappe

from speakdo_erpnext import __version__
from speakdo_erpnext.constants import FLOW_CHALLENGE_DOCTYPE, SETTINGS_DOCTYPE, EnrollmentStatus
from speakdo_erpnext.services import diagnostics, enrollment, flows, store
from speakdo_erpnext.services.errors import MiddlewareRefused, StateError
from speakdo_erpnext.tests.utils import (
	COMPANION_BASE_URL,
	ERP_URL,
	TENANT,
	SpeakDoTestCase,
	call_surface,
	error,
)


class TestBootstrap(SpeakDoTestCase):
	def test_start_payload(self):
		self.enroll()
		start = self.mw.calls[0]
		self.assertEqual((start["method"], start["path"]), ("POST", "/api/v1/tenants/bootstrap/start"))
		self.assertEqual(
			start["body"],
			{
				"installation_id": self.installation_id,
				"erp_type": "erpnext",
				"dolibarr_base_url": ERP_URL,  # the real ERPNext root, no prefix
				"companion_base_url": "https://erp.client.example/api/method/speakdo_erpnext.api.companion",
			},
		)
		self.assertNotIn("X-SpeakDo-Signature", start["headers"])

	def test_finalize_has_empty_body(self):
		self.enroll()
		finalize = self.mw.calls[1]
		self.assertRegex(finalize["path"], r"^/api/v1/tenants/bootstrap/[0-9a-f-]{36}/finalize$")
		self.assertEqual(finalize["raw"], b"")

	def test_proof_published_with_exact_fields(self):
		self.enroll()
		fetch = self.mw.proof_fetches[0]
		flow_id = self.mw.calls[1]["path"].split("/")[5]
		self.assertEqual((fetch["function"], fetch["args"], fetch["status"]), ("bootstrap_proof", {"id": flow_id}, 200))
		self.assertEqual(
			fetch["body"],
			{
				"bootstrap_id": flow_id,
				"installation_id": self.installation_id,
				"challenge": self.mw.flows[flow_id]["challenge"],
				"companion_version": __version__,
				"protocol_version": 1,
			},
		)

	def test_challenge_discarded_after_finalize(self):
		self.enroll()
		flow_id = self.mw.calls[1]["path"].split("/")[5]
		self.assertFalse(frappe.db.exists(FLOW_CHALLENGE_DOCTYPE, flow_id))
		self.assertEqual(call_surface("bootstrap_proof", args={"id": flow_id})[0], 404)

	def test_finalize_stores_tenant_and_secret(self):
		secret = self.enroll()
		self.assertEqual(store.get("tenant_uuid"), TENANT)
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.ENROLLED)
		self.assertEqual(store.get("bootstrap_mode"), "new_installation")
		self.assertIsNotNone(store.get("last_successful_contact"))
		self.assertFalse(store.get("last_error_code"))
		self.assertEqual(store.get_hmac_secret(), secret)

	def test_secret_stored_encrypted_and_never_exposed(self):
		secret = self.enroll()
		raw = frappe.db.sql(
			"select password from `__Auth` where doctype=%s and fieldname='hmac_secret'", (SETTINGS_DOCTYPE,)
		)
		self.assertTrue(raw and raw[0][0])
		self.assertNotEqual(raw[0][0], secret)
		self.assertNotIn(secret, str(frappe.db.sql("select * from `tabSingles` where doctype=%s", (SETTINGS_DOCTYPE,))))
		self.assertNotIn(secret, frappe.as_json(diagnostics.get_status()))
		self.assertNotIn(secret, frappe.as_json(frappe.get_doc(SETTINGS_DOCTYPE).as_dict()))

	def test_urls_are_distinct_and_unprefixed(self):
		self.enroll()
		status = diagnostics.get_status()
		self.assertEqual((status["erp_type"], status["instance_url"]), ("erpnext", ERP_URL))
		self.assertEqual(status["companion_base_url"], COMPANION_BASE_URL)
		self.assertEqual(store.get("declared_instance_url"), ERP_URL)

	def test_erp_base_url_must_be_a_root(self):
		result = flows.run("save_configuration", enrollment.save_configuration, instance_url="https://erp.example/speakdo")
		self.assertEqual(result["error_code"], "erp_base_url_has_path")
		enrollment.save_configuration(instance_url="https://erp.example:8443/")
		self.assertEqual(store.get("instance_url"), "https://erp.example:8443")

	def test_result_returned_to_admin_has_no_secret(self):
		result = flows.run("bootstrap", enrollment.bootstrap, protocol=self.protocol())
		self.assertTrue(result["ok"])
		self.assertNotIn(self.mw.tenants[self.installation_id]["secret"], frappe.as_json(result))
		self.assertEqual(result["tenant_uuid"], TENANT)

	def test_already_enrolled_refused_locally(self):
		self.enroll()
		with self.assertRaises(StateError) as ctx:
			enrollment.bootstrap(protocol=self.protocol())
		self.assertEqual(ctx.exception.error_code, "already_enrolled")

	def test_start_errors(self):
		cases = [
			(error(409, "tenant_already_enrolled"), "tenant_already_enrolled"),
			(error(409, "installation_url_mismatch", dolibarr_base_url="https://old.example"), "installation_url_mismatch"),
			(error(409, "legacy_candidate_conflict"), "legacy_candidate_conflict"),
			(error(422, "invalid_installation_id"), "invalid_installation_id"),
			(error(422, "invalid_dolibarr_url"), "invalid_erp_url"),
		]
		for answer, code in cases:
			with self.subTest(code=code):
				self.mw.fail["POST /api/v1/tenants/bootstrap/start"] = answer
				result = flows.run("bootstrap", enrollment.bootstrap, protocol=self.protocol())
				self.assertFalse(result["ok"])
				self.assertEqual((result["error_code"], result["http_status"]), (code, answer.status_code))
				self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.NOT_ENROLLED)
				self.assertFalse(store.has_hmac_secret())
				self.assertEqual(store.get("last_error_code"), code)
				if code == "installation_url_mismatch":
					self.assertEqual(result["details"]["registered_erp_url"], "https://old.example")

	def test_finalize_errors_discard_challenge(self):
		for status, code in (
			(404, "bootstrap_not_found"),
			(410, "bootstrap_expired"),
			(409, "tenant_conflict"),
			(422, "bootstrap_verification_failed"),
		):
			with self.subTest(code=code):
				original = self.mw.bootstrap_finalize
				self.mw.bootstrap_finalize = lambda *a, s=status, c=code: error(s, c)
				try:
					with self.assertRaises(MiddlewareRefused) as ctx:
						enrollment.bootstrap(protocol=self.protocol())
				finally:
					self.mw.bootstrap_finalize = original
				self.assertEqual(ctx.exception.error_code, code)
				self.assertEqual(frappe.db.count(FLOW_CHALLENGE_DOCTYPE), 0)

	def test_legacy_migration_without_local_secret_requires_repair(self):
		self.mw.legacy_url = ERP_URL
		result = enrollment.bootstrap(protocol=self.protocol())
		self.assertEqual(result["mode"], "legacy_migration")
		self.assertEqual(store.get("tenant_uuid"), TENANT)
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.REPAIR_REQUIRED)
		self.assertEqual(store.get("last_error_code"), "legacy_migration_requires_repair")
		self.assertFalse(store.has_hmac_secret())

	def test_legacy_migration_keeps_existing_secret(self):
		store.store_hmac_secret("previously-configured-secret-000000000000")
		self.mw.legacy_url = ERP_URL
		enrollment.bootstrap(protocol=self.protocol())
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.ENROLLED)
		self.assertEqual(store.get_hmac_secret(), "previously-configured-secret-000000000000")

	def test_installation_id_is_uuid_v4_and_stable(self):
		before = self.installation_id
		self.assertRegex(before, r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
		self.enroll()
		self.assertEqual(frappe.db.get_single_value(SETTINGS_DOCTYPE, "installation_id"), before)
