"""SpeakDo capabilities of an ERPNext user, derived from real Frappe permissions.

Deterministic translation, never decided by an LLM:

    ERPNext permissions of the user  ->  SpeakDo capabilities

A capability is announced only if the user holds EVERY DocType-level
permission listed for it in ``CAPABILITY_REQUIREMENTS``, as evaluated by
``frappe.has_permission`` for that user (roles, including custom DocPerms of
the site). A missing DocType, a disabled user or a website user yields no
capability (fail closed).

A capability is a declaration, not a grant: every action still runs with the
user's own credential, so ERPNext keeps enforcing document-level rules
(User Permissions, sharing, ownership) at execution time. The companion never
widens what ERPNext allows.

Capability NAMES are the middleware vocabulary (permission-like), not action
names. Contract confirmed by the middleware audit (30/09/2026):

    action              capability required
    thirdparty.search   thirdparty.read
    project.search      none
    task.create         task.create
    task.update         none

Only the required capabilities are emitted; nothing is added to "unlock"
project.search / task.update. Those actions still run with the user's own
ERPNext credential, so ERPNext permissions keep applying at execution time.
The DocTypes must match the ErpNextAdapter bindings (thirdparty -> Customer,
task -> Task).
"""

import hashlib

import frappe

from speakdo_erpnext.domain import erp_users

# capability -> ((DocType, permission type), ...), all required.
CAPABILITY_REQUIREMENTS = {
	"thirdparty.read": (("Customer", "read"),),
	"task.create": (("Task", "create"),),
}

# Bump when CAPABILITY_REQUIREMENTS changes meaning (part of permissions_version).
MAPPING_REVISION = "erpnext-caps-3"


def _allowed(erp_user_id, doctype, ptype):
	if not frappe.db.exists("DocType", doctype):
		return False
	return bool(frappe.has_permission(doctype, ptype, user=erp_user_id))


def capabilities_for(erp_user_id):
	"""Sorted list of capabilities of ``erp_user_id`` (empty if not an active desk user)."""
	user = erp_users.get_erp_user(erp_user_id)
	if not user or not user.active:
		return []
	return sorted(
		capability
		for capability, requirements in CAPABILITY_REQUIREMENTS.items()
		if all(_allowed(user.erp_user_id, doctype, ptype) for doctype, ptype in requirements)
	)


def permissions_version(capabilities, allowed_profiles=()):
	"""Stable fingerprint of the user's AUTHORIZATIONS: ERP capabilities and the
	set of allowed SpeakDo profiles. Both are canonicalized (deduplicated,
	sorted), so storage order never changes it. The active profile of a session
	is not an authorization and is not part of it."""
	caps = ",".join(sorted(set(capabilities)))
	profiles = ",".join(sorted(set(allowed_profiles or ())))
	payload = f"{MAPPING_REVISION}|caps={caps}|allowed_profiles={profiles}"
	return hashlib.sha256(payload.encode()).hexdigest()[:16]
