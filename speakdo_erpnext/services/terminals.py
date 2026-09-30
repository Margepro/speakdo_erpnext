"""Terminal enrollment verification and identity revalidation.

Called by the companion surface once the tenant HMAC has been verified.
Capabilities are derived from the user's real ERPNext permissions
(``domain.erp_capabilities``); ``permissions_version`` fingerprints them.
"""

import frappe
from frappe.utils import now_datetime

from speakdo_erpnext.constants import TERMINAL_DOCTYPE, TerminalStatus
from speakdo_erpnext.domain import erp_capabilities, erp_credentials, erp_users, identity
from speakdo_erpnext.services import enrollment_tokens, profiles
from speakdo_erpnext.services.errors import InboundRequestError

MAX_LABEL = 190
MAX_PUBLIC_KEY = 4096
MAX_FINGERPRINT = 190


def _validate_terminal(terminal):
	terminal_id = terminal.get("terminal_id")
	label = terminal.get("label")
	pem = terminal.get("public_key_pem")
	fingerprint = terminal.get("public_key_fingerprint")
	if not identity.is_valid_uuid(terminal_id):
		raise InboundRequestError(error_code="invalid_terminal_id", http_status=422)
	if label is not None and (not isinstance(label, str) or len(label) > MAX_LABEL):
		raise InboundRequestError(error_code="invalid_terminal_label", http_status=422)
	if not isinstance(pem, str) or not pem or len(pem) > MAX_PUBLIC_KEY:
		raise InboundRequestError(error_code="invalid_terminal_key", http_status=422)
	if not isinstance(fingerprint, str) or not fingerprint or len(fingerprint) > MAX_FINGERPRINT:
		raise InboundRequestError(error_code="invalid_terminal_key", http_status=422)
	return {
		"terminal_id": identity.normalize_uuid(terminal_id),
		"label": label or "",
		"public_key_pem": pem,
		"public_key_fingerprint": fingerprint,
	}


def _rejected(reason):
	return {"valid": False, "reason": reason}


def verify_enrollment(token, consume, terminal):
	"""Verify (and consume) an enrollment token for a terminal being enrolled."""
	terminal = _validate_terminal(terminal or {})
	if consume and frappe.db.exists(TERMINAL_DOCTYPE, terminal["terminal_id"]):
		return _rejected("terminal_already_enrolled")
	try:
		# Validates and locks the token row (SELECT … FOR UPDATE) without consuming it.
		row = enrollment_tokens.peek(token)
	except enrollment_tokens.TokenRejected as exc:
		return _rejected(exc.reason)

	user = erp_users.get_erp_user(row.erp_user)
	if not user:
		return _rejected("user_not_found")

	credential = None
	if consume and user.active and not erp_users.can_enroll(user.erp_user_id):
		return _rejected("user_not_enrollable")
	if consume and user.active:
		# A credential conflict refuses the enrollment BEFORE the token is
		# consumed: the admin can resolve it and the same QR stays usable.
		try:
			erp_credentials.ensure_issuable(user.erp_user_id)
		except erp_credentials.CredentialConflict as exc:
			return _rejected(exc.reason)
	if consume:
		enrollment_tokens.consume(token, terminal["terminal_id"])

	# An inactive user is reported as such (the middleware answers 403
	# user_inactive): no terminal and no credential for it.
	if consume and user.active:
		credential = erp_credentials.issue_for_terminal(user.erp_user_id)
		doc = frappe.new_doc(TERMINAL_DOCTYPE)
		doc.name = terminal["terminal_id"]
		doc.erp_user = user.erp_user_id
		doc.label = terminal["label"]
		doc.public_key_fingerprint = terminal["public_key_fingerprint"]
		doc.public_key_pem = terminal["public_key_pem"]
		doc.channel = row.channel
		doc.status = TerminalStatus.ACTIVE
		doc.enrolled_at = now_datetime()
		doc.db_insert()

	capabilities = erp_capabilities.capabilities_for(user.erp_user_id)
	allowed_profiles = profiles.get_allowed_profiles(user.erp_user_id)
	return {
		"valid": True,
		"user": user,
		"terminal_status": TerminalStatus.ACTIVE,
		"capabilities": capabilities,
		"allowed_profiles": allowed_profiles,
		"channel": row.channel,
		"permissions_version": erp_capabilities.permissions_version(capabilities, allowed_profiles),
		"erp_credential": credential,
	}


def terminal_status(terminal_id):
	"""Unknown terminal, revoked terminal or inactive user -> revoked."""
	status = TerminalStatus.REVOKED
	capabilities = []
	allowed_profiles = []
	if identity.is_valid_uuid(terminal_id):
		row = frappe.db.get_value(
			TERMINAL_DOCTYPE, identity.normalize_uuid(terminal_id), ["status", "erp_user"], as_dict=True
		)
		if row and row.status in TerminalStatus.ALL:
			user = erp_users.get_erp_user(row.erp_user)
			status = row.status if user and user.active else TerminalStatus.REVOKED
			if status != TerminalStatus.REVOKED:
				capabilities = erp_capabilities.capabilities_for(row.erp_user)
				allowed_profiles = profiles.get_allowed_profiles(row.erp_user)
	return {"status": status, "permissions_version": erp_capabilities.permissions_version(capabilities, allowed_profiles)}


def user_capabilities(erp_user_id):
	user = erp_users.get_erp_user(erp_user_id)
	capabilities = erp_capabilities.capabilities_for(erp_user_id) if user else []
	allowed_profiles = profiles.get_allowed_profiles(erp_user_id) if user else []
	return {
		"active": bool(user and user.active),
		"capabilities": capabilities,
		"allowed_profiles": allowed_profiles,
		"permissions_version": erp_capabilities.permissions_version(capabilities, allowed_profiles),
	}


_TERMINAL_FIELDS = ["name as terminal_id", "erp_user", "label", "channel", "status", "enrolled_at"]


def list_terminals(erp_user_id=None):
	"""Terminals, optionally scoped to ONE user (always scope for non-admin callers)."""
	filters = {"erp_user": erp_user_id} if erp_user_id else {}
	return frappe.get_all(
		TERMINAL_DOCTYPE, filters=filters, fields=_TERMINAL_FIELDS, order_by="enrolled_at desc", limit_page_length=500
	)


def terminal_owner(terminal_id):
	if not identity.is_valid_uuid(terminal_id):
		return None
	return frappe.db.get_value(TERMINAL_DOCTYPE, terminal_id, "erp_user")


def _has_other_live_terminal(erp_user_id, exclude=None):
	filters = {"erp_user": erp_user_id, "status": ("!=", TerminalStatus.REVOKED)}
	if exclude:
		filters["name"] = ("!=", exclude)
	return bool(frappe.db.exists(TERMINAL_DOCTYPE, filters))


def release_credential_if_unused(erp_user_id, exclude=None, reason="last_terminal_revoked"):
	"""Clear the user's SpeakDo-owned ERP credential once no live terminal depends on it."""
	if erp_user_id and not _has_other_live_terminal(erp_user_id, exclude):
		erp_credentials.revoke(erp_user_id, reason)


def revoke(terminal_id):
	if not identity.is_valid_uuid(terminal_id) or not frappe.db.exists(TERMINAL_DOCTYPE, terminal_id):
		return False
	frappe.db.set_value(TERMINAL_DOCTYPE, terminal_id, "status", TerminalStatus.REVOKED)
	release_credential_if_unused(frappe.db.get_value(TERMINAL_DOCTYPE, terminal_id, "erp_user"))
	return True


def rotate_credential(erp_user_id):
	"""Voluntary rotation: invalidates the shared pair, so every terminal of the
	user is revoked and must re-enroll (a new pair is issued at that time)."""
	frappe.db.set_value(
		TERMINAL_DOCTYPE, {"erp_user": erp_user_id, "status": ("!=", TerminalStatus.REVOKED)}, "status", TerminalStatus.REVOKED
	)
	return erp_credentials.revoke(erp_user_id, "rotation")


def revoke_all():
	frappe.db.set_value(TERMINAL_DOCTYPE, {"status": ("!=", TerminalStatus.REVOKED)}, "status", TerminalStatus.REVOKED)
	for erp_user_id in erp_credentials.active_owned_users():
		erp_credentials.revoke(erp_user_id, "installation_reset")
