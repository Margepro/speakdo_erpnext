"""The SpeakDo admin page must only call the admin API (speakdo_erpnext.api.admin).

Regression of 30/09/2026: browsers kept a cached copy of the page script written
before the admin methods moved out of speakdo_erpnext.api.companion (machine
surface of the middleware), and called
/api/method/speakdo_erpnext.api.companion.get_status -> HTTP 417 AttributeError.
"""

import importlib
import inspect
import re

import frappe
from frappe.desk.desk_page import get as get_page

from speakdo_erpnext.api import admin, companion
from speakdo_erpnext.constants import EnrollmentStatus
from speakdo_erpnext.services import diagnostics
from speakdo_erpnext.tests.utils import SECRET, SpeakDoTestCase

ADMIN_MODULE = "speakdo_erpnext.api.admin"
MACHINE_SURFACE = {
	"bootstrap_proof",
	"repair_proof",
	"relocation_proof",
	"enrollment_verify",
	"terminal_status",
	"user_capabilities",
	"action",
}
REQUIRED_STATUS_KEYS = {
	"installation_id",
	"tenant_uuid",
	"enrollment_status",
	"middleware_url",
	"app_url",
	"instance_url",
	"erp_type",
	"companion_base_url",
	"companion_version",
	"protocol_version",
	"last_successful_contact",
	"last_error_code",
	"last_error_message",
	"relocation_availability",
	"reset_availability",
	"actions",
}


def page_api_problems(script):
	"""Every server method the page script calls, checked against the real modules.
	Returns a list of problems (empty = valid)."""
	problems = []
	prefix = re.search(r'const SPEAKDO_API = "([^"]+)\.";', script)
	if not prefix:
		return ["SPEAKDO_API constant not found"]
	module_path = prefix.group(1)
	if module_path != ADMIN_MODULE:
		problems.append(f"page calls {module_path}, expected {ADMIN_MODULE}")
	names = set(re.findall(r'this\.call\(\s*"([a-z_]+)"', script))
	names |= set(re.findall(r'SPEAKDO_API \+ "([a-z_]+)"', script))
	names |= set(re.findall(r'run_action\(\s*"([a-z_]+)"', script))
	module = importlib.import_module(module_path)
	for name in sorted(names):
		fn = getattr(module, name, None)
		if fn is None:
			problems.append(f"{module_path}.{name} does not exist")
		elif fn not in frappe.whitelisted:
			problems.append(f"{module_path}.{name} is not whitelisted")
		elif fn in frappe.guest_methods:
			problems.append(f"{module_path}.{name} is allow_guest")
	if "speakdo_erpnext.api.companion." in script:
		problems.append("page references the machine surface speakdo_erpnext.api.companion")
	return problems


class TestAdminPage(SpeakDoTestCase):
	def served_script(self):
		# Exactly what the browser receives (frappe.desk.desk_page.getpage).
		return get_page("speakdo-admin").script

	def test_served_page_calls_only_the_admin_api(self):
		script = self.served_script()
		self.assertEqual(page_api_problems(script), [])
		self.assertIn('"get_status"', script)
		self.assertNotIn("speakdo_erpnext.api.companion.get_status", script)

	def test_pre_refactor_page_script_is_rejected(self):
		# The cached script that produced the 417: same page, old API prefix.
		stale = self.served_script().replace(f"{ADMIN_MODULE}.", "speakdo_erpnext.api.companion.")
		problems = page_api_problems(stale)
		self.assertIn("speakdo_erpnext.api.companion.get_status does not exist", problems)
		self.assertIn("page references the machine surface speakdo_erpnext.api.companion", problems)

	def test_machine_surface_exposes_no_admin_method(self):
		exposed = {
			name
			for name, fn in inspect.getmembers(companion, inspect.isfunction)
			if fn.__module__ == companion.__name__ and fn in frappe.whitelisted
		}
		self.assertEqual(exposed, MACHINE_SURFACE)
		self.assertFalse(hasattr(companion, "get_status"))
		self.assertTrue(all(getattr(companion, n) in frappe.guest_methods for n in MACHINE_SURFACE))

	def test_admin_methods_require_login(self):
		for name, fn in inspect.getmembers(admin, inspect.isfunction):
			if fn.__module__ == admin.__name__ and fn in frappe.whitelisted:
				self.assertNotIn(fn, frappe.guest_methods, name)

	def test_status_payload(self):
		status = admin.get_status()
		self.assertTrue(REQUIRED_STATUS_KEYS <= set(status), REQUIRED_STATUS_KEYS - set(status))
		self.assertEqual(status["erp_type"], "erpnext")
		self.assertEqual(status["companion_base_url"], status["instance_url"] + "/api/method/speakdo_erpnext.api.companion")
		self.assertEqual(
			status["actions"],
			{"bootstrap": True, "repair": True, "generate_qr": False, "reset": False, "relocation": False},
		)

	def test_status_when_enrolled_allows_qr_and_never_leaks_secret(self):
		self.set_enrolled()
		status = diagnostics.get_status()
		self.assertEqual(status["enrollment_status"], EnrollmentStatus.ENROLLED)
		self.assertTrue(status["actions"]["generate_qr"])
		self.assertFalse(status["actions"]["bootstrap"])
		dumped = frappe.as_json(status)
		self.assertNotIn(SECRET, dumped)
		for forbidden in ("hmac_secret", "api_secret", "signature", "token"):
			self.assertFalse(any(forbidden in key for key in status), forbidden)
