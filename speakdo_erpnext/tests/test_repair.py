from unittest.mock import patch

import frappe

from speakdo_erpnext.constants import FLOW_CHALLENGE_DOCTYPE, EnrollmentStatus
from speakdo_erpnext.services import challenges, enrollment, flows, repair, store
from speakdo_erpnext.tests.utils import (
	ERP_URL,
	TENANT,
	SpeakDoTestCase,
	error,
	signed_call,
)


class TestRepair(SpeakDoTestCase):
	def setUp(self):
		super().setUp()
		self.old_secret = self.enroll()
		self.user = self.make_user("speakdo.repair@example.com")
		self.mw.calls.clear()
		self.mw.proof_fetches.clear()

	def test_repair_start_payload(self):
		repair.repair(protocol=self.protocol())
		start = self.mw.calls[0]
		self.assertEqual((start["method"], start["path"]), ("POST", "/api/v1/tenants/repair/start"))
		self.assertEqual(start["body"], {"installation_id": self.installation_id, "dolibarr_base_url": ERP_URL})
		self.assertNotIn("X-SpeakDo-Signature", start["headers"])

	def test_repair_proof(self):
		repair.repair(protocol=self.protocol())
		flow_id = self.mw.calls[1]["path"].split("/")[5]
		fetch = self.mw.proof_fetches[0]
		self.assertEqual((fetch["function"], fetch["args"]), ("repair_proof", {"id": flow_id}))
		self.assertEqual(
			fetch["body"],
			{"repair_id": flow_id, "installation_id": self.installation_id, "challenge": self.mw.flows[flow_id]["challenge"]},
		)
		self.assertEqual(self.mw.calls[1]["raw"], b"")
		self.assertFalse(frappe.db.exists(FLOW_CHALLENGE_DOCTYPE, flow_id))

	def test_repair_finalize_replaces_secret(self):
		result = repair.repair(protocol=self.protocol())
		new_secret = self.mw.tenants[self.installation_id]["secret"]
		self.assertNotEqual(new_secret, self.old_secret)
		self.assertEqual(store.get_hmac_secret(), new_secret)
		self.assertEqual(result, {"tenant_uuid": TENANT})
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.ENROLLED)

	def test_installation_id_and_instance_url_unchanged(self):
		repair.repair(protocol=self.protocol())
		self.assertEqual(frappe.db.get_single_value("SpeakDo Settings", "installation_id"), self.installation_id)
		self.assertEqual(store.get("instance_url"), ERP_URL)

	def test_old_secret_invalidated(self):
		args = {"user": self.user}
		self.assertEqual(signed_call("user_capabilities", args=args, secret=self.old_secret)[0], 200)
		repair.repair(protocol=self.protocol())
		status, body = signed_call("user_capabilities", args=args, secret=self.old_secret)
		self.assertEqual((status, body["error"]["code"]), (401, "invalid_tenant_signature"))
		self.assertEqual(signed_call("user_capabilities", args=args, secret=self.mw.tenants[self.installation_id]["secret"])[0], 200)

	def test_repair_restores_lost_secret(self):
		store.clear_hmac_secret()
		store.update(tenant_uuid=None, enrollment_status=EnrollmentStatus.NOT_ENROLLED)
		# bootstrap is refused by the middleware: the installation is known
		result = flows.run("bootstrap", enrollment.bootstrap, protocol=self.protocol())
		self.assertEqual(result["error_code"], "tenant_already_enrolled")
		repair.repair(protocol=self.protocol())
		self.assertEqual(store.get("tenant_uuid"), TENANT)
		self.assertTrue(store.has_hmac_secret())

	def test_repair_after_legacy_migration(self):
		# fresh instance, URL known as a legacy tenant -> legacy_migration, then chained repair
		self.mw.tenants.clear()
		store.clear_hmac_secret()
		store.update(tenant_uuid=None, enrollment_status=EnrollmentStatus.NOT_ENROLLED)
		self.mw.legacy_url = ERP_URL
		enrollment.bootstrap(protocol=self.protocol())
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.REPAIR_REQUIRED)
		repair.repair(protocol=self.protocol())
		self.assertEqual(store.get("enrollment_status"), EnrollmentStatus.ENROLLED)

	def test_repair_errors(self):
		start = "POST /api/v1/tenants/repair/start"
		cases = [
			(start, error(404, "repair_not_found")),
			(start, error(429, "repair_rate_limited")),
			(start, error(409, "installation_url_mismatch", dolibarr_base_url="https://old.example")),
			(start, error(409, "repair_conflict")),
			(start, error(409, "repair_target_unavailable")),
			("finalize", error(410, "repair_expired")),
			("finalize", error(409, "repair_already_consumed")),
			("finalize", error(422, "repair_verification_failed")),
		]
		for where, answer in cases:
			code = answer.json()["error"]["code"]
			with self.subTest(code=code):
				original = self.mw.repair_finalize
				if where == start:
					self.mw.fail[start] = answer
				else:
					self.mw.repair_finalize = lambda *a, r=answer: r
				try:
					result = flows.run("repair", repair.repair, protocol=self.protocol())
				finally:
					self.mw.fail.pop(start, None)
					self.mw.repair_finalize = original
				self.assertFalse(result["ok"])
				self.assertEqual(result["error_code"], code)
				self.assertEqual(result["http_status"], answer.status_code)
				self.assertEqual(store.get_hmac_secret(), self.old_secret)
				self.assertEqual(frappe.db.count(FLOW_CHALLENGE_DOCTYPE), 0)
				self.assertTrue(result["message"])
				if code == "installation_url_mismatch":
					self.assertEqual(result["details"]["registered_erp_url"], "https://old.example")

	def test_repair_proof_mismatch(self):
		# proof not served (e.g. unreachable instance): the middleware refuses, nothing changes
		with patch.object(challenges, "get_published_proof", return_value=None):
			result = flows.run("repair", repair.repair, protocol=self.protocol())
		self.assertEqual(result["error_code"], "repair_verification_failed")
		self.assertEqual(store.get_hmac_secret(), self.old_secret)
