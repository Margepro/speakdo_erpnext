import uuid

import frappe

from speakdo_erpnext.constants import SETTINGS_DOCTYPE
from speakdo_erpnext.domain import identity
from speakdo_erpnext.patches.v0_1 import rename_installation_uuid
from speakdo_erpnext.services.errors import StateError
from speakdo_erpnext.tests.utils import SpeakDoTestCase


class TestIdentity(SpeakDoTestCase):
	def test_generated_once(self):
		first = identity.ensure_installation_id()
		self.assertTrue(identity.is_uuid_v4(first))
		self.assertEqual(identity.ensure_installation_id(), first)
		self.assertEqual(self._backup["value"], first)

	def test_restored_from_backup_after_reinstall(self):
		first = identity.ensure_installation_id()
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "installation_id", None)
		self.assertEqual(identity.ensure_installation_id(), first)

	def test_independent_of_urls(self):
		first = identity.ensure_installation_id()
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "instance_url", "https://moved.example")
		self.assertEqual(identity.ensure_installation_id(), first)

	def test_non_v4_value_is_never_replaced_silently(self):
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "installation_id", str(uuid.uuid1()))
		with self.assertRaises(StateError):
			identity.require_installation_id()

	def test_patch_renames_installation_uuid(self):
		legacy_value = str(uuid.uuid4())
		frappe.db.sql("delete from `tabSingles` where doctype=%s and field in ('installation_id','installation_uuid')", (SETTINGS_DOCTYPE,))
		frappe.db.sql(
			"insert into `tabSingles` (doctype, field, value) values (%s, 'installation_uuid', %s)", (SETTINGS_DOCTYPE, legacy_value)
		)
		frappe.clear_cache(doctype=SETTINGS_DOCTYPE)
		rename_installation_uuid.execute()
		self.assertEqual(
			frappe.db.sql("select value from `tabSingles` where doctype=%s and field='installation_id'", (SETTINGS_DOCTYPE,))[0][0],
			legacy_value,
		)
		self.assertFalse(
			frappe.db.sql("select 1 from `tabSingles` where doctype=%s and field='installation_uuid'", (SETTINGS_DOCTYPE,))
		)
