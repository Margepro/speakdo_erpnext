"""Single profile per user (SpeakDo User Profile.profile_id) -> set of ALLOWED
profiles (SpeakDo Allowed Profile, one row per user x profile).

Every existing assignment becomes an allowed set containing exactly that
profile: nothing is lost, nothing is added. The old DocType is then removed."""

import frappe
from frappe.utils import now_datetime

from speakdo_erpnext.constants import ALLOWED_PROFILE_DOCTYPE, LEGACY_PROFILE_DOCTYPE


def migrate_rows(rows):
	"""rows: iterable of (erp_user, profile_id, assigned_by, assigned_at). Idempotent."""
	from speakdo_erpnext.services.profiles import assignment_name

	migrated = 0
	for erp_user, profile_id, assigned_by, assigned_at in rows:
		if not erp_user or not profile_id:
			continue
		name = assignment_name(erp_user, profile_id)
		if frappe.db.exists(ALLOWED_PROFILE_DOCTYPE, name):
			continue
		doc = frappe.new_doc(ALLOWED_PROFILE_DOCTYPE)
		doc.name = name
		doc.erp_user = erp_user
		doc.profile_id = profile_id
		doc.assigned_by = assigned_by
		doc.assigned_at = assigned_at or now_datetime()
		doc.db_insert()
		migrated += 1
	return migrated


def execute():
	frappe.reload_doc("speakdo", "doctype", "speakdo_allowed_profile")
	if frappe.db.table_exists(LEGACY_PROFILE_DOCTYPE):
		rows = frappe.db.sql(
			f"select erp_user, profile_id, assigned_by, assigned_at from `tab{LEGACY_PROFILE_DOCTYPE}`"
		)
		migrate_rows(rows)
	if frappe.db.exists("DocType", LEGACY_PROFILE_DOCTYPE):
		frappe.delete_doc("DocType", LEGACY_PROFILE_DOCTYPE, force=True, ignore_missing=True)
	frappe.db.sql_ddl(f"drop table if exists `tab{LEGACY_PROFILE_DOCTYPE}`")
