"""Personal SpeakDo API of the logged-in ERPNext user ("Mon SpeakDo" page).

Scoping is enforced server side: every method works on ``frappe.session.user``
only and takes no user parameter, so a forged request cannot reach another
user's profile, capabilities, credential state or terminals. Nothing returned
contains a secret. Admin (all users) methods live in ``speakdo_erpnext.api.admin``.
"""

import frappe

from speakdo_erpnext.services import flows, qr, terminals, users


def _me():
	user = frappe.session.user
	if not user or user == "Guest":
		raise frappe.PermissionError
	return user


@frappe.whitelist(methods=["GET"])
def get_my_speakdo():
	user = _me()
	state = users.user_state(user)
	if not state:
		raise frappe.PermissionError
	return state


@frappe.whitelist(methods=["POST"])
def generate_my_qr():
	"""Enrollment QR for the session user (token bound to that user)."""
	return flows.run("generate_my_qr", qr.generate_enrollment_qr, _me())


@frappe.whitelist(methods=["POST"])
def revoke_my_terminal(terminal_id=None):
	"""Revoke one of the session user's own terminals. Another user's terminal is
	answered exactly like an unknown one (no existence oracle)."""
	user = _me()
	if terminals.terminal_owner(terminal_id) != user:
		return {"ok": False, "error_code": "terminal_not_found", "message": "Terminal inconnu."}
	terminals.revoke(terminal_id)
	return {"ok": True}
