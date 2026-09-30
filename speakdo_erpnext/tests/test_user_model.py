"""Multi-user model: users, profiles, capabilities, credentials and terminals are
isolated per ERPNext user; the admin view is global, the personal view is scoped
server side (no IDOR)."""

import json
import unittest
from unittest.mock import patch

import frappe

from speakdo_erpnext.api import admin, me
from speakdo_erpnext.domain.erp_capabilities import capabilities_for, permissions_version
from speakdo_erpnext.services import enrollment_tokens, profiles, terminals, users
from speakdo_erpnext.services.errors import StateError
from speakdo_erpnext.tests.utils import SpeakDoTestCase, as_user, signed_call

A1 = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
A2 = "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e"
B1 = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"
CAPS_A = ["thirdparty.read"]
CAPS_B = ["task.create"]


class UserModelCase(SpeakDoTestCase):
	def setUp(self):
		super().setUp()
		if not all(frappe.db.exists("DocType", dt) for dt in ("Customer", "Project", "Task")):
			raise unittest.SkipTest("ERPNext is not installed on the test site")
		self.set_enrolled()
		self.a = self.exact_roles(self.make_user("user.a@example.com", roles=("Sales User",)), "Sales User")
		self.b = self.exact_roles(self.make_user("user.b@example.com", roles=("Projects User",)), "Projects User")
		self._protocol_patch = patch.object(profiles, "get_middleware_protocol", side_effect=lambda: self.protocol())
		self._protocol_patch.start()

	@staticmethod
	def exact_roles(user, *roles):
		"""Users are reused between tests: reset their roles to exactly ``roles``."""
		doc = frappe.get_doc("User", user)
		extra = [r.role for r in doc.roles if r.role not in roles]
		if extra:
			doc.remove_roles(*extra)
		doc.add_roles(*roles)
		frappe.clear_cache(user=user)
		return user

	def tearDown(self):
		self._protocol_patch.stop()
		super().tearDown()

	def enroll(self, user, terminal_id):
		token, _ = enrollment_tokens.issue(user)
		payload = {"consume": True, "terminal": {"terminal_id": terminal_id, "label": terminal_id[:4], "public_key_pem": "PEM", "public_key_fingerprint": "fp-" + terminal_id[:4]}}
		status, body = signed_call("enrollment_verify", "POST", {"token": token}, json.dumps(payload).encode())
		self.assertEqual((status, body["valid"]), (200, True), body)
		return body


class TestTwoUsers(UserModelCase):
	def test_enrolling_a_never_marks_b(self):
		self.enroll(self.a, A1)
		state_b = users.user_state(self.b)
		self.assertEqual((state_b["enrolled"], state_b["active_terminal_count"], state_b["terminals"]), (False, 0, []))
		self.assertEqual(state_b["credential_state"], "absent")
		# B enrolls normally despite A's terminal
		body_b = self.enroll(self.b, B1)
		self.assertTrue(body_b["valid"])
		self.assertEqual([t.terminal_id for t in users.user_state(self.a)["terminals"]], [A1])
		self.assertEqual([t.terminal_id for t in users.user_state(self.b)["terminals"]], [B1])

	def test_capabilities_and_profiles_do_not_contaminate(self):
		profiles.set_allowed_profiles(self.a, ["generic", "commercial"], "Administrator")
		profiles.set_allowed_profiles(self.b, ["receptionist"], "Administrator")
		body_a = self.enroll(self.a, A1)
		body_b = self.enroll(self.b, B1)
		self.assertEqual(body_a["capabilities"], CAPS_A)
		self.assertEqual(body_b["capabilities"], CAPS_B)
		self.assertNotEqual(body_a["permissions_version"], body_b["permissions_version"])
		self.assertEqual(users.user_state(self.a)["allowed_profiles"], ["commercial", "generic"])
		self.assertEqual(users.user_state(self.b)["allowed_profiles"], ["receptionist"])
		for user, caps in ((self.a, CAPS_A), (self.b, CAPS_B)):
			_, body = signed_call("user_capabilities", args={"user": user})
			self.assertEqual(body["capabilities"], caps)

	def test_credentials_are_distinct_and_revocation_is_isolated(self):
		cred_a = self.enroll(self.a, A1)["erp_credential"]
		cred_b = self.enroll(self.b, B1)["erp_credential"]
		self.assertNotEqual(cred_a.split(":")[0], cred_b.split(":")[0])
		terminals.revoke(A1)
		self.assertEqual(users.user_state(self.a)["credential_state"], "revoked")
		self.assertEqual(users.user_state(self.b)["credential_state"], "managed")
		self.assertEqual(f"{frappe.db.get_value('User', self.b, 'api_key')}", cred_b.split(":")[0])
		_, status = signed_call("terminal_status", args={"terminal_uuid": B1})
		self.assertEqual(status["status"], "active")


class TestMultiTerminal(UserModelCase):
	def test_two_terminals_of_one_user(self):
		profiles.set_allowed_profiles(self.a, ["generic", "commercial"], "Administrator")
		first = self.enroll(self.a, A1)
		second = self.enroll(self.a, A2)
		self.assertEqual(first["user"]["id"], second["user"]["id"])
		self.assertEqual(first["capabilities"], second["capabilities"])
		self.assertEqual(first["permissions_version"], second["permissions_version"])
		self.assertEqual(first["erp_credential"], second["erp_credential"])
		# the allowed set belongs to the user: both terminals see the same one
		statuses = {t: signed_call("terminal_status", args={"terminal_uuid": t})[1] for t in (A1, A2)}
		self.assertEqual(statuses[A1]["permissions_version"], statuses[A2]["permissions_version"])
		self.assertEqual(sorted(t.terminal_id for t in users.user_state(self.a)["terminals"]), sorted([A1, A2]))
		terminals.revoke(A1)
		self.assertEqual(signed_call("terminal_status", args={"terminal_uuid": A2})[1]["status"], "active")
		self.assertEqual(users.user_state(self.a)["credential_state"], "managed")
		terminals.revoke(A2)
		self.assertEqual(users.user_state(self.a)["credential_state"], "revoked")
		self.assertIsNone(frappe.db.get_value("User", self.a, "api_key"))


class TestProfiles(UserModelCase):
	def test_catalogue_comes_from_the_middleware(self):
		catalogue = profiles.get_catalogue(refresh=True)
		self.assertEqual(sorted(catalogue["profiles"]), ["commercial", "field.it_technician", "generic", "receptionist"])
		self.assertEqual(catalogue["aliases"], {"field.it_support": "field.it_technician"})
		self.assertTrue(any(c["path"] == "/profiles" and "X-SpeakDo-Signature" in c["headers"] for c in self.mw.calls))

	def test_several_allowed_profiles(self):
		result = profiles.set_allowed_profiles(self.a, ["generic", "field.it_technician", "commercial"], "Administrator")
		self.assertEqual(result, ["commercial", "field.it_technician", "generic"])
		self.assertEqual(profiles.get_allowed_profiles(self.a), ["commercial", "field.it_technician", "generic"])
		self.assertEqual(frappe.db.count("SpeakDo Allowed Profile", {"erp_user": self.a}), 3)

	def test_duplicate_is_idempotent_and_unique_per_user(self):
		self.assertEqual(profiles.set_allowed_profiles(self.a, ["commercial", "commercial"], "Administrator"), ["commercial"])
		profiles.set_allowed_profiles(self.a, ["commercial"], "Administrator")
		self.assertEqual(frappe.db.count("SpeakDo Allowed Profile", {"erp_user": self.a}), 1)
		# the primary key forbids a second row for the same (user, profile)
		with self.assertRaises(frappe.DuplicateEntryError):
			profiles._insert(self.a, "commercial", "Administrator")

	def test_unknown_profile_refuses_the_whole_change(self):
		profiles.set_allowed_profiles(self.a, ["generic"], "Administrator")
		with self.assertRaises(StateError) as ctx:
			profiles.set_allowed_profiles(self.a, ["commercial", "unknown.profile"], "Administrator")
		self.assertEqual(ctx.exception.error_code, "profile_unknown")
		self.assertEqual(profiles.get_allowed_profiles(self.a), ["generic"])

	def test_alias_is_resolved(self):
		self.assertEqual(profiles.set_allowed_profiles(self.a, ["field.it_support"], "Administrator"), ["field.it_technician"])
		self.assertEqual(
			profiles.set_allowed_profiles(self.a, ["field.it_support", "field.it_technician"], "Administrator"),
			["field.it_technician"],
		)

	def test_no_profile_stays_empty(self):
		self.assertEqual(profiles.get_allowed_profiles(self.a), [])
		profiles.set_allowed_profiles(self.a, ["generic"], "Administrator")
		self.assertEqual(profiles.set_allowed_profiles(self.a, [], "Administrator"), [])
		state = users.user_state(self.a)
		self.assertEqual(state["allowed_profiles"], [])  # never silently "generic"
		self.assertNotIn("active_profile", state)

	def test_change_of_allowed_set_changes_permissions_version(self):
		profiles.set_allowed_profiles(self.a, ["generic", "commercial"], "Administrator")
		self.enroll(self.a, A1)
		before = signed_call("terminal_status", args={"terminal_uuid": A1})[1]["permissions_version"]
		profiles.set_allowed_profiles(self.a, ["generic", "field.it_technician"], "Administrator")
		after = signed_call("terminal_status", args={"terminal_uuid": A1})[1]["permissions_version"]
		self.assertNotEqual(before, after)
		self.assertEqual(signed_call("user_capabilities", args={"user": self.a})[1]["permissions_version"], after)

	def test_order_does_not_change_permissions_version(self):
		caps = capabilities_for(self.a)
		self.assertEqual(
			permissions_version(caps, ["generic", "commercial"]), permissions_version(caps, ["commercial", "generic"])
		)
		self.assertEqual(permissions_version(caps, ["generic", "generic"]), permissions_version(caps, ["generic"]))
		profiles.set_allowed_profiles(self.a, ["generic", "commercial"], "Administrator")
		first = users.user_state(self.a)["permissions_version"]
		profiles.set_allowed_profiles(self.a, ["commercial", "generic"], "Administrator")
		self.assertEqual(users.user_state(self.a)["permissions_version"], first)

	def test_profiles_never_touch_credential_nor_capabilities(self):
		body = self.enroll(self.a, A1)
		caps = capabilities_for(self.a)
		for allowed in (["generic"], ["commercial", "field.it_technician"], []):
			profiles.set_allowed_profiles(self.a, allowed, "Administrator")
			self.assertEqual(capabilities_for(self.a), caps)
			api_key = frappe.db.get_value("User", self.a, "api_key")
			api_secret = frappe.utils.password.get_decrypted_password("User", self.a, "api_secret")
			self.assertEqual(f"{api_key}:{api_secret}", body["erp_credential"])

	def test_allowed_profiles_contract_on_the_wire(self):
		profiles.set_allowed_profiles(self.a, ["generic", "commercial"], "Administrator")
		body = self.enroll(self.a, A1)
		_, caps = signed_call("user_capabilities", args={"user": self.a})
		# same canonical set in both answers; never a single/active profile
		self.assertEqual(body["allowed_profiles"], ["commercial", "generic"])
		self.assertEqual(caps["allowed_profiles"], body["allowed_profiles"])
		for payload in (body, caps):
			for field in ("profile_id", "active_profile", "profile_missing_modules", "dolibarr_apikey"):
				self.assertNotIn(field, payload)
		self.assertEqual(body["permissions_version"], caps["permissions_version"])
		self.assertEqual(body["permissions_version"], permissions_version(capabilities_for(self.a), ["commercial", "generic"]))

	def test_empty_allowed_profiles_on_the_wire(self):
		body = self.enroll(self.a, A1)
		self.assertEqual(body["allowed_profiles"], [])
		self.assertEqual(signed_call("user_capabilities", args={"user": self.a})[1]["allowed_profiles"], [])

	def test_removing_the_active_profile_is_visible_at_revalidation(self):
		profiles.set_allowed_profiles(self.a, ["generic", "commercial"], "Administrator")
		self.enroll(self.a, A1)
		before = signed_call("user_capabilities", args={"user": self.a})[1]
		profiles.set_allowed_profiles(self.a, ["generic"], "Administrator")  # e.g. "commercial" was active
		after = signed_call("user_capabilities", args={"user": self.a})[1]
		self.assertEqual(after["allowed_profiles"], ["generic"])
		self.assertNotEqual(after["permissions_version"], before["permissions_version"])
		self.assertEqual(signed_call("terminal_status", args={"terminal_uuid": A1})[1]["permissions_version"], after["permissions_version"])

	def test_two_terminals_receive_the_same_allowed_profiles(self):
		profiles.set_allowed_profiles(self.a, ["field.it_technician", "commercial"], "Administrator")
		first = self.enroll(self.a, A1)
		second = self.enroll(self.a, A2)
		self.assertEqual(first["allowed_profiles"], ["commercial", "field.it_technician"])
		self.assertEqual(second["allowed_profiles"], first["allowed_profiles"])

	def test_migration_from_single_profile(self):
		from speakdo_erpnext.patches.v0_1.migrate_allowed_profiles import migrate_rows

		rows = [(self.a, "commercial", "Administrator", None), (self.b, "receptionist", "Administrator", None), (self.b, None, None, None)]
		self.assertEqual(migrate_rows(rows), 2)
		self.assertEqual(profiles.get_allowed_profiles(self.a), ["commercial"])
		self.assertEqual(profiles.get_allowed_profiles(self.b), ["receptionist"])
		self.assertEqual(migrate_rows(rows), 0)  # idempotent, nothing added
		self.assertFalse(frappe.db.table_exists("SpeakDo User Profile"))


class TestViewsAndIdor(UserModelCase):
	def test_personal_view_is_scoped_to_the_session_user(self):
		self.enroll(self.a, A1)
		self.enroll(self.b, B1)
		with as_user(self.a):
			mine = me.get_my_speakdo()
		self.assertEqual(mine["erp_user_id"], self.a)
		self.assertEqual([t.terminal_id for t in mine["terminals"]], [A1])
		self.assertEqual(mine["capabilities"], CAPS_A)
		self.assertNotIn(self.b, frappe.as_json(mine))
		for forbidden in ("erp_credential", "api_secret", "api_key", "Authorization"):
			self.assertNotIn(forbidden, frappe.as_json(mine))

	def test_user_cannot_revoke_another_users_terminal(self):
		self.enroll(self.a, A1)
		self.enroll(self.b, B1)
		with as_user(self.a):
			result = me.revoke_my_terminal(terminal_id=B1)
		self.assertEqual((result["ok"], result["error_code"]), (False, "terminal_not_found"))
		self.assertEqual(frappe.db.get_value("SpeakDo Terminal", B1, "status"), "active")
		with as_user(self.a):
			self.assertTrue(me.revoke_my_terminal(terminal_id=A1)["ok"])
		self.assertEqual(frappe.db.get_value("SpeakDo Terminal", A1, "status"), "revoked")

	def test_personal_api_takes_no_user_parameter(self):
		import inspect

		for name in ("get_my_speakdo", "generate_my_qr"):
			self.assertEqual(list(inspect.signature(getattr(me, name)).parameters), [], name)
		self.assertEqual(list(inspect.signature(me.revoke_my_terminal).parameters), ["terminal_id"])

	def test_personal_qr_is_bound_to_the_session_user(self):
		with as_user(self.b), patch("speakdo_erpnext.services.qr.render_png_data_uri", return_value="data:x"):
			result = me.generate_my_qr()
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["erp_user"], self.b)
		self.assertEqual(frappe.get_all("SpeakDo Enrollment Token", filters={"status": "issued"}, pluck="erp_user"), [self.b])

	def test_admin_view_is_global_and_secret_free(self):
		profiles.set_allowed_profiles(self.b, ["field.it_technician", "receptionist"], "Administrator")
		self.enroll(self.a, A1)
		self.enroll(self.b, B1)
		listed = {u["erp_user_id"]: u for u in admin.list_users()}
		self.assertEqual(set(listed), {self.a, self.b})
		self.assertEqual((listed[self.a]["capabilities"], listed[self.a]["allowed_profiles"]), (CAPS_A, []))
		self.assertEqual(
			(listed[self.b]["capabilities"], listed[self.b]["allowed_profiles"]), (CAPS_B, ["field.it_technician", "receptionist"])
		)
		self.assertEqual(listed[self.a]["credential_state"], "managed")
		dumped = frappe.as_json(listed)
		for forbidden in ("erp_credential", "api_secret", "api_key", frappe.db.get_value("User", self.a, "api_key")):
			self.assertNotIn(forbidden, dumped)
		# a user without any SpeakDo state can be displayed on demand
		other = self.make_user("user.c@example.com", roles=("Employee",))
		self.assertIn(other, {u["erp_user_id"] for u in admin.list_users(include_user=other)})

	def test_admin_sets_several_profiles_through_the_api(self):
		result = admin.set_allowed_profiles(erp_user=self.a, profile_ids='["generic", "commercial", "generic"]')
		self.assertEqual((result["ok"], result["allowed_profiles"]), (True, ["commercial", "generic"]))
		self.assertEqual(admin.set_allowed_profiles(erp_user=self.a, profile_ids="[]")["allowed_profiles"], [])
		self.assertEqual(admin.set_allowed_profiles(erp_user=self.a, profile_ids='"generic"')["error_code"], "invalid_profiles")

	def test_admin_user_methods_require_system_manager(self):
		for method, kwargs in (
			(admin.list_users, {}),
			(admin.get_profiles, {}),
			(admin.set_allowed_profiles, {"erp_user": self.b, "profile_ids": '["generic"]'}),
		):
			with self.subTest(method=method.__name__), as_user(self.a), self.assertRaises(frappe.PermissionError):
				method(**kwargs)
		self.assertEqual(profiles.get_allowed_profiles(self.b), [])

	def test_personal_view_shows_own_profiles_only(self):
		profiles.set_allowed_profiles(self.a, ["generic", "commercial"], "Administrator")
		profiles.set_allowed_profiles(self.b, ["receptionist"], "Administrator")
		with as_user(self.a):
			mine = me.get_my_speakdo()
		self.assertEqual(mine["allowed_profiles"], ["commercial", "generic"])
		self.assertNotIn("receptionist", frappe.as_json(mine))
		self.assertNotIn("active_profile", mine)
		# the personal surface has no way to write profiles
		self.assertFalse([n for n in dir(me) if "profile" in n.lower()])

	def test_capabilities_reflect_current_permissions_not_a_cache(self):
		self.assertEqual(users.user_state(self.a)["capabilities"], CAPS_A)
		frappe.get_doc("User", self.a).add_roles("Projects User")
		frappe.clear_cache(user=self.a)
		self.assertEqual(users.user_state(self.a)["capabilities"], sorted(CAPS_A + CAPS_B))

	def test_personal_page_calls_only_the_personal_api(self):
		from frappe.desk.desk_page import get as get_page

		script = get_page("speakdo-me").script
		self.assertIn('"speakdo_erpnext.api.me."', script)
		self.assertNotIn("speakdo_erpnext.api.admin", script)
		self.assertNotIn("speakdo_erpnext.api.companion", script)
		self.assertEqual([r.role for r in frappe.get_doc("Page", "speakdo-me").roles], ["Desk User"])
