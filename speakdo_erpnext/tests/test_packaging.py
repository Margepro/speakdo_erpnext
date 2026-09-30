"""Packaging invariants: every declarative document of the app must be found by
Frappe's standard sync (`frappe.model.sync.sync_for`) and be installed by it."""

import json
import os
from unittest.mock import patch

import frappe
from frappe.model.sync import get_doc_files, sync_for
from frappe.tests.utils import FrappeTestCase

from speakdo_erpnext import install
from speakdo_erpnext.constants import SETTINGS_DOCTYPE

APP = "speakdo_erpnext"

# (doctype, name) of every declarative document shipped by the app.
EXPECTED_DOCUMENTS = {
	("DocType", SETTINGS_DOCTYPE),
	("DocType", "SpeakDo Flow Challenge"),
	("DocType", "SpeakDo Enrollment Token"),
	("DocType", "SpeakDo Terminal"),
	("DocType", "SpeakDo Nonce"),
	("DocType", "SpeakDo ERP Credential"),
	("DocType", "SpeakDo Allowed Profile"),
	("Page", "speakdo-me"),
	("Page", "speakdo-admin"),
	("Workspace", "SpeakDo"),
}


def discovered_files(app_modules):
	"""Same discovery loop as `sync_for` for a non-frappe app."""
	files = []
	for module_name in app_modules.get(APP) or []:
		folder = os.path.dirname(frappe.get_module(f"{APP}.{module_name}").__file__)
		files = get_doc_files(files=files, start_path=folder)
	return files


class TestPackaging(FrappeTestCase):
	def test_modules_txt_matches_python_packages(self):
		modules = frappe.get_module_list(APP)
		self.assertEqual(modules, ["SpeakDo"])
		for module in modules:
			self.assertTrue(frappe.get_module(f"{APP}.{frappe.scrub(module)}"))

	def test_module_map_lists_app(self):
		self.assertEqual(frappe.local.app_modules.get(APP), ["speakdo"])
		self.assertEqual(frappe.local.module_app.get("speakdo"), APP)

	def test_sync_discovers_every_declarative_document(self):
		modules = frappe.get_module_list(APP)
		found = set()
		for path in discovered_files(frappe.local.app_modules):
			with open(path) as f:
				doc = json.load(f)
			self.assertIn(doc["module"], modules, path)
			# Frappe expects <module>/<doctype folder>/<scrub(name)>/<scrub(name)>.json
			self.assertEqual(os.path.basename(path), frappe.scrub(doc["name"]) + ".json", path)
			found.add((doc["doctype"], doc["name"]))
		self.assertEqual(found, EXPECTED_DOCUMENTS)

	def test_documents_installed_by_standard_sync(self):
		for doctype, name in EXPECTED_DOCUMENTS:
			self.assertTrue(frappe.db.exists(doctype, name), f"{doctype} {name}")
			self.assertEqual(frappe.db.get_value(doctype, name, "module"), "SpeakDo")
		self.assertEqual(frappe.db.get_value("Module Def", "SpeakDo", "app_name"), APP)

	def test_sync_for_imports_settings_doctype(self):
		imported = []
		with patch("frappe.model.sync.import_file_by_path", side_effect=lambda p, **kw: imported.append(p)):
			sync_for(APP)
		self.assertIn(
			"speakdo_settings.json", {os.path.basename(p) for p in imported}, "sync_for found nothing"
		)

	def test_before_install_repairs_stale_module_map(self):
		# Reproduces a site whose "app_modules" cache predates the app in apps.txt.
		stale = {app: mods for app, mods in frappe.local.app_modules.items() if app != APP}
		frappe.local.app_modules = stale
		frappe.cache.set_value("app_modules", stale)
		self.assertEqual(discovered_files(frappe.local.app_modules), [])
		try:
			install.before_install()
			self.assertEqual(frappe.local.app_modules.get(APP), ["speakdo"])
			self.assertTrue(discovered_files(frappe.local.app_modules))
		finally:
			frappe.cache.delete_value("app_modules")
			frappe.setup_module_map()
