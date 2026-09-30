"""ERPNext user credential (erpnext_api_token): issuance, SpeakDo ownership,
foreign-key conflict and lifecycle (decision of 30/09/2026)."""

import json

import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from speakdo_erpnext.constants import CREDENTIAL_DOCTYPE, ENROLLMENT_TOKEN_DOCTYPE, TERMINAL_DOCTYPE
from speakdo_erpnext.domain import erp_credentials
from speakdo_erpnext.services import enrollment_tokens, lifecycle, qr, terminals
from speakdo_erpnext.services.errors import StateError
from speakdo_erpnext.tests.utils import SpeakDoTestCase, signed_call

T1 = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
T2 = "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e"
T3 = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"


def verify(user, terminal_id, consume=True):
	token, _ = enrollment_tokens.issue(user)
	body = json.dumps(
		{"consume": consume, "terminal": {"terminal_id": terminal_id, "label": "t", "public_key_pem": "PEM", "public_key_fingerprint": "fp"}}
	).encode()
	status, response = signed_call("enrollment_verify", "POST", {"token": token}, body)
	return token, status, response


def user_key(user):
	return frappe.db.get_value("User", user, "api_key"), get_decrypted_password("User", user, "api_secret", raise_exception=False)


class TestErpCredential(SpeakDoTestCase):
	def setUp(self):
		super().setUp()
		self.set_enrolled()
		self.user = self.make_user("cred.tech@example.com")

	# -- issuance -------------------------------------------------------------

	def test_first_enrollment_creates_a_speakdo_owned_pair(self):
		self.assertEqual(user_key(self.user), (None, None))
		_, status, body = verify(self.user, T1)
		self.assertEqual((status, body["valid"], body["credential_type"]), (200, True, "erpnext_api_token"))
		api_key, api_secret = user_key(self.user)
		self.assertEqual(body["erp_credential"], f"{api_key}:{api_secret}")
		record = frappe.get_doc(CREDENTIAL_DOCTYPE, self.user)
		self.assertEqual((record.status, record.credential_type), ("active", "erpnext_api_token"))
		self.assertEqual(erp_credentials.ownership(self.user), erp_credentials.OWNERSHIP_SPEAKDO)
		# only a hash of the key is recorded, never the secret
		self.assertNotIn(api_secret, frappe.as_json(record.as_dict()))
		self.assertNotIn(api_key, frappe.as_json(record.as_dict()))

	def test_credential_authenticates_as_that_user_only(self):
		_, _, body = verify(self.user, T1)
		api_key, api_secret = body["erp_credential"].split(":")
		previous = frappe.session.user
		previous_manager = getattr(frappe.local, "login_manager", None)
		try:
			frappe.set_user("Guest")
			frappe.local.login_manager = frappe._dict(user="Guest")
			frappe.auth.validate_api_key_secret(api_key, api_secret)
			self.assertEqual(frappe.session.user, self.user)
		finally:
			frappe.local.login_manager = previous_manager
			frappe.set_user(previous)
		with self.assertRaises(frappe.AuthenticationError):
			frappe.auth.validate_api_key_secret(api_key, "wrong-secret")

	def test_disabled_user_credential_is_refused_by_frappe(self):
		_, _, body = verify(self.user, T1)
		api_key, api_secret = body["erp_credential"].split(":")
		frappe.db.set_value("User", self.user, "enabled", 0)
		with self.assertRaises(frappe.AuthenticationError):
			frappe.auth.validate_api_key_secret(api_key, api_secret)

	def test_several_terminals_share_the_pair(self):
		_, _, first = verify(self.user, T1)
		_, _, second = verify(self.user, T2)
		self.assertEqual(first["erp_credential"], second["erp_credential"])

	def test_no_credential_without_consumption_or_for_inactive_user(self):
		_, _, body = verify(self.user, T1, consume=False)
		self.assertTrue(body["valid"])
		self.assertNotIn("erp_credential", body)
		self.assertEqual(user_key(self.user), (None, None))
		frappe.db.set_value("User", self.user, "enabled", 0)
		_, _, body = verify(self.user, T2)
		self.assertEqual((body["valid"], body["user"]["active"]), (True, False))
		self.assertNotIn("erp_credential", body)
		self.assertEqual(user_key(self.user), (None, None))

	def test_shared_administrator_account_is_never_enrolled(self):
		token, _, body = verify("Administrator", T1)
		self.assertEqual((body["valid"], body["error"]["code"]), (False, "user_not_enrollable"))
		self.assertEqual(frappe.db.get_value(ENROLLMENT_TOKEN_DOCTYPE, enrollment_tokens.token_hash(token), "status"), "issued")
		self.assertFalse(frappe.db.exists(CREDENTIAL_DOCTYPE, "Administrator"))
		with self.assertRaises(StateError):
			qr.check_qr_preconditions("Administrator")

	# -- foreign key ---------------------------------------------------------

	def set_foreign_key(self):
		frappe.db.set_value("User", self.user, "api_key", "foreignkey12345", update_modified=False)
		set_encrypted_password("User", self.user, "foreignsecret99", "api_secret")

	def test_foreign_key_refuses_enrollment_and_is_never_touched(self):
		self.set_foreign_key()
		token, status, body = verify(self.user, T1)
		self.assertEqual((status, body["valid"], body["error"]["code"]), (200, False, "erp_credential_conflict"))
		self.assertEqual(user_key(self.user), ("foreignkey12345", "foreignsecret99"))
		self.assertFalse(frappe.db.exists(TERMINAL_DOCTYPE, T1))
		self.assertFalse(frappe.db.exists(CREDENTIAL_DOCTYPE, self.user))
		# the token is not consumed: the same QR works once the conflict is resolved
		self.assertEqual(frappe.db.get_value(ENROLLMENT_TOKEN_DOCTYPE, enrollment_tokens.token_hash(token), "status"), "issued")

	def test_foreign_key_refuses_qr_generation(self):
		self.set_foreign_key()
		with self.assertRaises(StateError) as ctx:
			qr.check_qr_preconditions(self.user)
		self.assertEqual(ctx.exception.error_code, "erp_credential_conflict")

	def test_key_replaced_after_issuance_becomes_foreign(self):
		verify(self.user, T1)
		self.set_foreign_key()
		self.assertEqual(erp_credentials.ownership(self.user), erp_credentials.OWNERSHIP_FOREIGN)
		# revoking must not touch a key SpeakDo cannot prove it owns
		terminals.revoke(T1)
		self.assertEqual(user_key(self.user), ("foreignkey12345", "foreignsecret99"))
		self.assertEqual(frappe.db.get_value(CREDENTIAL_DOCTYPE, self.user, "status"), "revoked")

	# -- lifecycle ------------------------------------------------------------

	def test_revoking_one_of_two_terminals_keeps_the_credential(self):
		_, _, body = verify(self.user, T1)
		verify(self.user, T2)
		terminals.revoke(T1)
		self.assertEqual(f"{user_key(self.user)[0]}:{user_key(self.user)[1]}", body["erp_credential"])
		self.assertEqual(frappe.db.get_value(CREDENTIAL_DOCTYPE, self.user, "status"), "active")

	def test_revoking_the_last_terminal_clears_the_pair_without_creating_a_new_one(self):
		_, _, body = verify(self.user, T1)
		verify(self.user, T2)
		terminals.revoke(T1)
		terminals.revoke(T2)
		self.assertEqual(user_key(self.user), (None, None))
		record = frappe.get_doc(CREDENTIAL_DOCTYPE, self.user)
		self.assertEqual((record.status, record.revocation_reason), ("revoked", "last_terminal_revoked"))
		api_key, api_secret = body["erp_credential"].split(":")
		with self.assertRaises(frappe.AuthenticationError):
			frappe.auth.validate_api_key_secret(api_key, api_secret)
		# a future enrollment issues a NEW pair
		_, _, again = verify(self.user, T3)
		self.assertTrue(again["valid"])
		self.assertNotEqual(again["erp_credential"], body["erp_credential"])
		self.assertEqual(frappe.db.get_value(CREDENTIAL_DOCTYPE, self.user, "status"), "active")

	def test_deleted_terminal_releases_the_credential(self):
		verify(self.user, T1)
		frappe.delete_doc(TERMINAL_DOCTYPE, T1, ignore_permissions=True, force=True)
		self.assertEqual(user_key(self.user), (None, None))
		self.assertEqual(frappe.db.get_value(CREDENTIAL_DOCTYPE, self.user, "revocation_reason"), "terminal_deleted")

	def test_rotation_revokes_every_terminal_and_the_pair(self):
		verify(self.user, T1)
		verify(self.user, T2)
		self.assertTrue(terminals.rotate_credential(self.user))
		self.assertEqual(user_key(self.user), (None, None))
		self.assertEqual(
			set(frappe.get_all(TERMINAL_DOCTYPE, filters={"erp_user": self.user}, pluck="status")), {"revoked"}
		)
		self.assertEqual(frappe.db.get_value(CREDENTIAL_DOCTYPE, self.user, "revocation_reason"), "rotation")

	def test_installation_reset_revokes_speakdo_credentials_only(self):
		verify(self.user, T1)
		other = self.make_user("cred.foreign@example.com")
		frappe.db.set_value("User", other, "api_key", "otherforeignkey", update_modified=False)
		self.mw.reset_enabled = True
		lifecycle.reset(protocol=self.protocol())
		self.assertEqual(user_key(self.user), (None, None))
		self.assertEqual(frappe.db.get_value("User", other, "api_key"), "otherforeignkey")

	def test_missing_secret_of_owned_key_is_reissued(self):
		_, _, first = verify(self.user, T1)
		frappe.db.delete("__Auth", {"doctype": "User", "name": self.user, "fieldname": "api_secret"})
		_, _, second = verify(self.user, T2)
		self.assertEqual(first["erp_credential"].split(":")[0], second["erp_credential"].split(":")[0])
		self.assertNotEqual(first["erp_credential"], second["erp_credential"])
