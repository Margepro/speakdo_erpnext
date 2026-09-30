"""ERPNext permissions -> SpeakDo capabilities: deterministic, fail closed.

Requires ERPNext on the test site (Customer / Project / Task DocTypes). The
expected sets below follow the STANDARD ERPNext v15 role permissions.
"""

import json
import unittest
import unittest.mock

import frappe

from speakdo_erpnext.domain import erp_capabilities
from speakdo_erpnext.domain.erp_capabilities import (
	CAPABILITY_REQUIREMENTS,
	capabilities_for,
	permissions_version,
)
from speakdo_erpnext.services import enrollment_tokens, terminals
from speakdo_erpnext.tests.utils import SpeakDoTestCase, signed_call

# Contract confirmed by the middleware (30/09/2026): only these two are required.
ALL = ["task.create", "thirdparty.read"]
TERMINAL_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


class TestCapabilities(SpeakDoTestCase):
	def setUp(self):
		super().setUp()
		if not all(frappe.db.exists("DocType", dt) for dt in ("Customer", "Project", "Task")):
			raise unittest.SkipTest("ERPNext is not installed on the test site")

	def user_with(self, email, *roles):
		self.make_user(email, roles=roles)
		frappe.clear_cache(user=email)
		return email

	def test_only_the_capabilities_required_by_the_middleware(self):
		self.assertEqual(sorted(CAPABILITY_REQUIREMENTS), ALL)
		for not_required in ("thirdparty.search", "project.search", "project.read", "task.update"):
			self.assertNotIn(not_required, CAPABILITY_REQUIREMENTS)
		self.assertEqual(CAPABILITY_REQUIREMENTS["thirdparty.read"], (("Customer", "read"),))
		self.assertEqual(CAPABILITY_REQUIREMENTS["task.create"], (("Task", "create"),))

	def test_standard_roles_translation(self):
		cases = {
			self.user_with("caps.sales@example.com", "Sales User"): ["thirdparty.read"],
			self.user_with("caps.projects@example.com", "Projects User"): ["task.create"],
			self.user_with("caps.both@example.com", "Sales User", "Projects User"): ALL,
			self.user_with("caps.employee@example.com", "Employee"): [],
			"Administrator": ALL,
		}
		for user, expected in cases.items():
			with self.subTest(user=user):
				self.assertEqual(capabilities_for(user), expected)

	def test_every_capability_is_backed_by_a_real_permission(self):
		for email, role in (("caps.sales@example.com", "Sales User"), ("caps.projects@example.com", "Projects User")):
			user = self.user_with(email, role)
			for capability in capabilities_for(user):
				for doctype, ptype in CAPABILITY_REQUIREMENTS[capability]:
					self.assertTrue(frappe.has_permission(doctype, ptype, user=user), (user, capability))

	def test_fail_closed(self):
		disabled = self.user_with("caps.disabled@example.com", "Sales User", "Projects User")
		frappe.db.set_value("User", disabled, "enabled", 0)
		self.assertEqual(capabilities_for(disabled), [])
		self.assertEqual(capabilities_for("nobody@example.com"), [])
		self.assertEqual(capabilities_for("Guest"), [])
		# a DocType missing from the site never yields a capability
		with unittest.mock.patch.dict(CAPABILITY_REQUIREMENTS, {"task.create": (("No Such DocType", "create"),)}):
			self.assertNotIn("task.create", capabilities_for("Administrator"))

	def test_deterministic_version_changes_with_permissions(self):
		user = self.user_with("caps.change@example.com", "Sales User")
		first = capabilities_for(user)
		self.assertEqual(first, capabilities_for(user))
		version = permissions_version(first)
		self.assertEqual(version, permissions_version(list(reversed(first))))
		frappe.get_doc("User", user).add_roles("Projects User")
		frappe.clear_cache(user=user)
		second = capabilities_for(user)
		self.assertEqual(second, ALL)
		self.assertNotEqual(permissions_version(second), version)

	def test_surface_reports_real_capabilities(self):
		self.set_enrolled()
		user = self.user_with("caps.surface@example.com", "Projects User")
		status, body = signed_call("user_capabilities", args={"user": user})
		expected = ["task.create"]
		self.assertEqual((status, body["capabilities"]), (200, expected))
		self.assertEqual(body["permissions_version"], permissions_version(expected))

		token, _ = enrollment_tokens.issue(user)
		payload = {"consume": True, "terminal": {"terminal_id": TERMINAL_ID, "label": "t", "public_key_pem": "PEM", "public_key_fingerprint": "fp"}}
		status, body = signed_call("enrollment_verify", "POST", {"token": token}, json.dumps(payload).encode())
		self.assertEqual((status, body["valid"], body["capabilities"]), (200, True, expected))

		status, body = signed_call("terminal_status", args={"terminal_uuid": TERMINAL_ID})
		self.assertEqual(body, {"status": "active", "permissions_version": permissions_version(expected)})
		terminals.revoke(TERMINAL_ID)
		status, body = signed_call("terminal_status", args={"terminal_uuid": TERMINAL_ID})
		self.assertEqual(body, {"status": "revoked", "permissions_version": permissions_version([])})

	def test_mapping_revision_is_part_of_the_version(self):
		before = permissions_version(ALL)
		with unittest.mock.patch.object(erp_capabilities, "MAPPING_REVISION", "erpnext-caps-test"):
			self.assertNotEqual(permissions_version(ALL), before)
