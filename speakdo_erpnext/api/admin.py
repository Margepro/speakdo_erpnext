"""Whitelisted administration API of the SpeakDo companion.

Every method:
- requires an authenticated user holding a manager role (no allow_guest);
- never returns a permanent secret to the browser;
- delegates all logic to ``speakdo_erpnext.services``.

There is deliberately no business endpoint here (no task / event / customer /
invoice ...): SpeakDo actions and mappings live in the middleware. The routes
called BY the middleware are not here: see ``speakdo_erpnext.api.companion``.
"""

import frappe
from frappe.utils import cint

from speakdo_erpnext.permissions import require_manager
from speakdo_erpnext.services import diagnostics, enrollment, flows, lifecycle, profiles, qr, terminals, users
from speakdo_erpnext.services import repair as repair_service
from speakdo_erpnext.services.errors import SpeakDoError

RESET_CONFIRMATION = "RESET"


@frappe.whitelist(methods=["GET"])
def get_status():
	require_manager()
	return diagnostics.get_status()


@frappe.whitelist(methods=["GET"])
def run_diagnostics():
	require_manager()
	return diagnostics.run_diagnostics(probe=True)


@frappe.whitelist(methods=["POST"])
def save_configuration(middleware_url=None, app_url=None, instance_url=None):
	require_manager()
	return flows.run(
		"save_configuration",
		enrollment.save_configuration,
		middleware_url=middleware_url,
		app_url=app_url,
		instance_url=instance_url,
	)


@frappe.whitelist(methods=["POST"])
def restore_default_urls():
	require_manager()
	return flows.run("restore_default_urls", enrollment.restore_default_urls)


@frappe.whitelist(methods=["POST"])
def bootstrap():
	require_manager()
	return flows.run("bootstrap", enrollment.bootstrap)


@frappe.whitelist(methods=["POST"])
def generate_qr():
	require_manager()
	return flows.run("generate_qr", qr.generate_enrollment_qr, frappe.session.user)


@frappe.whitelist(methods=["POST"])
def repair():
	require_manager()
	return flows.run("repair", repair_service.repair)


@frappe.whitelist(methods=["POST"])
def relocate():
	require_manager()
	return flows.run("relocate", lifecycle.relocate)


@frappe.whitelist(methods=["POST"])
def reset(confirmation=None):
	require_manager()
	if confirmation != RESET_CONFIRMATION:
		return {"ok": False, "error_code": "confirmation_required", "message": "Confirmation manquante."}
	return flows.run("reset", lifecycle.reset)


@frappe.whitelist(methods=["GET"])
def list_terminals():
	require_manager()
	return terminals.list_terminals()


@frappe.whitelist(methods=["POST"])
def revoke_terminal(terminal_id=None):
	require_manager()
	if not terminals.revoke(terminal_id):
		return {"ok": False, "error_code": "terminal_not_found", "message": "Terminal inconnu."}
	return {"ok": True}


# -- users (the model is multi-user) -----------------------------------------------


@frappe.whitelist(methods=["GET"])
def list_users(include_user=None):
	"""Every user with SpeakDo state: profile, live capabilities, credential state, terminals."""
	require_manager()
	return users.speakdo_users(extra_user=include_user or None)


@frappe.whitelist(methods=["GET"])
def get_profiles(refresh=0):
	"""Profile catalogue as published by the middleware (never a local copy)."""
	require_manager()
	try:
		catalogue = profiles.get_catalogue(refresh=bool(cint(refresh)))
	except SpeakDoError as exc:
		return exc.as_dict()
	return {"ok": True, "profiles": list(catalogue["profiles"].values()), "aliases": catalogue["aliases"]}


@frappe.whitelist(methods=["POST"])
def set_allowed_profiles(erp_user=None, profile_ids=None):
	"""Replace the set of SpeakDo profiles ALLOWED to a user (0..N ids of the
	middleware catalogue; JSON list). Never sets an active profile."""
	require_manager()
	ids = frappe.parse_json(profile_ids) if isinstance(profile_ids, str) else profile_ids
	if ids is not None and not isinstance(ids, list):
		return {"ok": False, "error_code": "invalid_profiles", "message": "Liste de profils invalide."}
	return flows.run(
		"set_allowed_profiles",
		lambda: {"allowed_profiles": profiles.set_allowed_profiles(erp_user, ids or [], frappe.session.user)},
	)
