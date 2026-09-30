"""ERPNext users as seen by SpeakDo.

``erp_user_id`` is the native Frappe identifier ``User.name`` (usually the
e-mail address, or ``Administrator``). No artificial numeric id is created.
"""

from dataclasses import dataclass

import frappe

_NEVER_ENROLLABLE = ("Guest",)


@dataclass(frozen=True)
class ErpUser:
	erp_user_id: str
	active: bool
	display_name: str


def get_erp_user(erp_user_id):
	"""Return the ErpUser, or None when the user does not exist."""
	if not isinstance(erp_user_id, str) or not erp_user_id or erp_user_id in _NEVER_ENROLLABLE:
		return None
	row = frappe.db.get_value(
		"User", erp_user_id, ["name", "enabled", "full_name", "user_type"], as_dict=True
	)
	if not row:
		return None
	# Only desk (System) users can act on the ERP; website users never get a terminal.
	active = bool(row.enabled) and row.user_type == "System User"
	return ErpUser(erp_user_id=row.name, active=active, display_name=row.full_name or row.name)


# Built-in shared super-account: never used as a terminal identity (its API
# credential would be a shared administrator credential).
_SHARED_ACCOUNTS = ("Administrator",)


def can_enroll(erp_user_id):
	user = get_erp_user(erp_user_id)
	return bool(user and user.active and user.erp_user_id not in _SHARED_ACCOUNTS)
