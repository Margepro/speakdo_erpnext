"""Companion surface called by the SpeakDo middleware.

companion_base_url = {erp_base_url}/api/method/speakdo_erpnext.api.companion

Every function below is exposed by Frappe as
``{companion_base_url}.<function>`` (``/api/method/<dotted path>``). They are
``allow_guest`` because the middleware has no Frappe session; access control
is done by ``adapters.companion_http``:

- ``bootstrap_proof`` / ``repair_proof`` / ``relocation_proof``: public, only a
  pending, unexpired challenge of that flow is served;
- ``enrollment_verify`` / ``terminal_status`` / ``user_capabilities`` /
  ``action``: tenant HMAC mandatory, nothing is read before it is verified.

Parameters come from the query string only. ``xss_safe``: Frappe must not
rewrite guest inputs (they are strictly validated and never rendered as HTML).
Admin (System Manager) methods live in ``speakdo_erpnext.api.admin``.
"""

import frappe

from speakdo_erpnext.adapters import companion_http as surface


@frappe.whitelist(allow_guest=True, methods=["GET"], xss_safe=True)
def bootstrap_proof(**_ignored):
	return surface.respond(surface.BOOTSTRAP_PROOF, "id")


@frappe.whitelist(allow_guest=True, methods=["GET"], xss_safe=True)
def repair_proof(**_ignored):
	return surface.respond(surface.REPAIR_PROOF, "id")


@frappe.whitelist(allow_guest=True, methods=["GET"], xss_safe=True)
def relocation_proof(**_ignored):
	return surface.respond(surface.RELOCATION_PROOF, "id")


@frappe.whitelist(allow_guest=True, methods=["POST"], xss_safe=True)
def enrollment_verify(**_ignored):
	return surface.respond(surface.ENROLLMENT_VERIFY, "token")


@frappe.whitelist(allow_guest=True, methods=["GET"], xss_safe=True)
def terminal_status(**_ignored):
	return surface.respond(surface.TERMINAL_STATUS, "terminal_uuid")


@frappe.whitelist(allow_guest=True, methods=["GET"], xss_safe=True)
def user_capabilities(**_ignored):
	return surface.respond(surface.USER_CAPABILITIES, "user")


@frappe.whitelist(allow_guest=True, methods=["POST"], xss_safe=True)
def action(**_ignored):
	"""No business action is ever executed by the companion: HMAC checked, then
	``424 erp_connector_unavailable``."""
	return surface.respond(surface.ACTION, "action_id")
