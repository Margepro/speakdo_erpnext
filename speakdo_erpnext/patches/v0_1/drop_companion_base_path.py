"""The /speakdo prefix surface was replaced by whitelisted methods
(companion_base_url = {erp_base_url}/api/method/speakdo_erpnext.api.companion):
drop the orphan companion_base_path value."""

import frappe


def execute():
	frappe.db.sql("delete from `tabSingles` where doctype='SpeakDo Settings' and field='companion_base_path'")
