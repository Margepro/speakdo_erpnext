import frappe

from speakdo_erpnext.constants import MANAGER_ROLES


def is_manager(user=None):
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	return bool(set(MANAGER_ROLES) & set(frappe.get_roles(user)))


def require_manager():
	"""Raise frappe.PermissionError unless the session user may administrate SpeakDo.

	Explicit role check rather than frappe.only_for(), which is bypassed when
	frappe.flags.in_test is set and would make the permission tests vacuous.
	Guest never holds a manager role, so anonymous calls are always refused.
	"""
	if not is_manager():
		raise frappe.PermissionError


def has_app_permission():
	"""`add_to_apps_screen` permission hook."""
	return is_manager()
