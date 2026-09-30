import frappe
from frappe.utils import get_url

from speakdo_erpnext.constants import (
	COMPANION_VERSION,
	DEFAULT_APP_URL,
	DEFAULT_MIDDLEWARE_URL,
	ERP_TYPE,
	SETTINGS_DOCTYPE,
	EnrollmentStatus,
)
from speakdo_erpnext.domain import identity

APP_NAME = "speakdo_erpnext"


def before_install():
	# `install_app` syncs DocTypes/Pages/Workspaces from `frappe.local.app_modules`,
	# built once at `frappe.init` from the site's Redis key "app_modules". If that
	# key was cached before this app was added to sites/apps.txt, it lacks this app
	# and `sync_for` silently imports nothing (the `clear_cache()` done by
	# `install_app` empties Redis but not `frappe.local`). Rebuild the map from
	# apps.txt / modules.txt so the standard sync discovers our documents.
	if frappe.local.app_modules.get(APP_NAME):
		return
	frappe.cache.delete_value(["app_modules", "installed_app_modules"])
	frappe.setup_module_map()
	if not frappe.local.app_modules.get(APP_NAME):
		frappe.throw(
			f"{APP_NAME} is not listed by Frappe's module map (check sites/apps.txt and modules.txt)."
		)


def after_install():
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		# Never create it here: the DocType must come from Frappe's standard sync.
		frappe.throw(
			f"DocType {SETTINGS_DOCTYPE} was not synced by Frappe during install. "
			"Run `bench --site <site> clear-cache` and retry the installation."
		)
	identity.ensure_installation_id()
	values = {"companion_version": COMPANION_VERSION, "erp_type": ERP_TYPE}

	def fill_if_empty(fieldname, value):
		if not frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname):
			values[fieldname] = value

	# Defaults only: existing (possibly LAB / dev) values are never overwritten.
	fill_if_empty("enrollment_status", EnrollmentStatus.NOT_ENROLLED)
	fill_if_empty("middleware_url", DEFAULT_MIDDLEWARE_URL)
	fill_if_empty("app_url", DEFAULT_APP_URL)
	fill_if_empty("instance_url", get_url())
	frappe.db.set_single_value(SETTINGS_DOCTYPE, values)


def after_migrate():
	# Runs after `bench migrate` and app updates: identity is only created if
	# missing, never regenerated; URLs are only filled if empty.
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return
	after_install()
