"""v0.1.0 stored the installation identity as ``installation_uuid`` and an
unused ``api_key`` secret. The wire name is ``installation_id`` and the
protocol has no API key: rename the value (never regenerate it) and drop the
key. The old site_config backup key is kept and still read as a fallback."""

import frappe
from frappe.installer import update_site_config
from frappe.utils.password import remove_encrypted_password

SETTINGS = "SpeakDo Settings"


def execute():
	old = frappe.db.sql(
		"select value from `tabSingles` where doctype=%s and field='installation_uuid'", (SETTINGS,)
	)
	current = frappe.db.sql(
		"select value from `tabSingles` where doctype=%s and field='installation_id'", (SETTINGS,)
	)
	if old and old[0][0] and not (current and current[0][0]):
		frappe.db.sql(
			"delete from `tabSingles` where doctype=%s and field='installation_id'", (SETTINGS,)
		)
		frappe.db.sql(
			"update `tabSingles` set field='installation_id' where doctype=%s and field='installation_uuid'",
			(SETTINGS,),
		)
	else:
		frappe.db.sql(
			"delete from `tabSingles` where doctype=%s and field='installation_uuid'", (SETTINGS,)
		)

	conf = frappe.get_site_config()
	if conf.get("speakdo_installation_uuid") and not conf.get("speakdo_installation_id"):
		update_site_config("speakdo_installation_id", conf.get("speakdo_installation_uuid"))

	remove_encrypted_password(SETTINGS, SETTINGS, "api_key")
	frappe.db.sql("delete from `tabSingles` where doctype=%s and field='api_key'", (SETTINGS,))
