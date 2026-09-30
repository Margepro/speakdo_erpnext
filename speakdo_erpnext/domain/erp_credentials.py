"""ERPNext user credential handed to the middleware (``erpnext_api_token``).

The middleware calls ERPNext on behalf of the enrolled user with
``Authorization: token <api_key>:<api_secret>``: Frappe's native per-user API
key pair (``User.api_key`` + ``User.api_secret``, the secret stored encrypted
in ``__Auth``). Frappe only authenticates it for an ENABLED user, and every
request then runs with that user's own permissions: no shared account, no
privilege beyond the user's.

Lifecycle (decision of 30/09/2026):

- no API key on the user: SpeakDo creates the pair at enrollment and records,
  in ``SpeakDo ERP Credential``, that it owns its lifecycle (SHA-256 of the
  key, never the secret);
- API key present but not provably SpeakDo's (no active ownership record whose
  hash matches the current key): CONFLICT. The key is never reused, replaced
  nor regenerated; the enrollment is refused;
- several terminals of a user share the pair; revoking a terminal keeps it
  while another active terminal of the user depends on it;
- revoking the last terminal clears the SpeakDo-owned pair (key and secret);
  no new pair is created until a future enrollment;
- rotation = revoke every terminal of the user + clear the pair: all
  terminals must re-enroll.

Nothing here logs; the secret only leaves through ``ErpCredential``, whose
``repr`` hides it.
"""

import hashlib
import hmac
from dataclasses import dataclass, field

import frappe
from frappe.utils import now_datetime
from frappe.utils.password import get_decrypted_password, remove_encrypted_password, set_encrypted_password

from speakdo_erpnext.constants import CREDENTIAL_DOCTYPE

CREDENTIAL_TYPE = "erpnext_api_token"

OWNERSHIP_NONE = "none"
OWNERSHIP_SPEAKDO = "speakdo"
OWNERSHIP_FOREIGN = "foreign"

ACTIVE = "active"
REVOKED = "revoked"


class CredentialConflict(Exception):
	"""The user already has an API key whose lifecycle SpeakDo does not own."""

	reason = "erp_credential_conflict"


@dataclass(frozen=True)
class ErpCredential:
	credential_type: str
	api_key: str = field(repr=False)
	api_secret: str = field(repr=False)


def _key_hash(api_key):
	return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _current_key(erp_user_id):
	return frappe.db.get_value("User", erp_user_id, "api_key") or None


def _active_record(erp_user_id):
	return frappe.db.get_value(
		CREDENTIAL_DOCTYPE, {"name": erp_user_id, "status": ACTIVE}, ["name", "api_key_hash"], as_dict=True
	)


def ownership(erp_user_id):
	"""Who owns the user's current API key: none / speakdo / foreign."""
	api_key = _current_key(erp_user_id)
	if not api_key:
		return OWNERSHIP_NONE
	record = _active_record(erp_user_id)
	if record and record.api_key_hash and hmac.compare_digest(record.api_key_hash, _key_hash(api_key)):
		return OWNERSHIP_SPEAKDO
	return OWNERSHIP_FOREIGN


def ensure_issuable(erp_user_id):
	"""Raise CredentialConflict when a credential cannot be issued for the user."""
	if ownership(erp_user_id) == OWNERSHIP_FOREIGN:
		raise CredentialConflict()


def _record_ownership(erp_user_id, api_key):
	values = {
		"erp_user": erp_user_id,
		"credential_type": CREDENTIAL_TYPE,
		"status": ACTIVE,
		"api_key_hash": _key_hash(api_key),
		"issued_at": now_datetime(),
		"revoked_at": None,
		"revocation_reason": None,
	}
	if frappe.db.exists(CREDENTIAL_DOCTYPE, erp_user_id):
		frappe.db.set_value(CREDENTIAL_DOCTYPE, erp_user_id, values)
	else:
		doc = frappe.new_doc(CREDENTIAL_DOCTYPE)
		doc.name = erp_user_id
		doc.update(values)
		doc.db_insert()


def issue_for_terminal(erp_user_id):
	"""Credential for a terminal being enrolled for ``erp_user_id``.

	Creates the pair when the user has none, reuses the SpeakDo-owned pair
	otherwise. Raises CredentialConflict for a foreign key (nothing modified).
	"""
	state = ownership(erp_user_id)
	if state == OWNERSHIP_FOREIGN:
		raise CredentialConflict()

	if state == OWNERSHIP_SPEAKDO:
		api_key = _current_key(erp_user_id)
		api_secret = get_decrypted_password("User", erp_user_id, "api_secret", raise_exception=False)
		if api_secret:
			return ErpCredential(CREDENTIAL_TYPE, api_key, api_secret)
		# SpeakDo-owned key whose secret disappeared: the pair is already
		# unusable for every terminal, re-issue a secret for the same key.
	else:
		# Same generator and lengths as frappe.core.doctype.user.user.generate_keys.
		api_key = frappe.generate_hash(length=15)
		frappe.db.set_value("User", erp_user_id, "api_key", api_key, update_modified=False)
		_record_ownership(erp_user_id, api_key)

	api_secret = frappe.generate_hash(length=15)
	set_encrypted_password("User", erp_user_id, api_secret, "api_secret")
	return ErpCredential(CREDENTIAL_TYPE, api_key, api_secret)


def revoke(erp_user_id, reason):
	"""Invalidate the SpeakDo-owned pair of the user. A key SpeakDo does not own
	(replaced meanwhile) is never touched. Returns True if a pair was cleared."""
	record = _active_record(erp_user_id)
	if not record:
		return False
	cleared = False
	if ownership(erp_user_id) == OWNERSHIP_SPEAKDO:
		frappe.db.set_value("User", erp_user_id, "api_key", None, update_modified=False)
		remove_encrypted_password("User", erp_user_id, "api_secret")
		cleared = True
	frappe.db.set_value(
		CREDENTIAL_DOCTYPE,
		erp_user_id,
		{"status": REVOKED, "revoked_at": now_datetime(), "revocation_reason": (reason or "")[:140]},
	)
	return cleared


CREDENTIAL_STATE_ABSENT = "absent"
CREDENTIAL_STATE_MANAGED = "managed"
CREDENTIAL_STATE_CONFLICT = "conflict"
CREDENTIAL_STATE_REVOKED = "revoked"


def state(erp_user_id):
	"""Display state of the user's ERP credential. Never exposes key nor secret."""
	current = ownership(erp_user_id)
	if current == OWNERSHIP_SPEAKDO:
		return CREDENTIAL_STATE_MANAGED
	if current == OWNERSHIP_FOREIGN:
		return CREDENTIAL_STATE_CONFLICT
	if frappe.db.get_value(CREDENTIAL_DOCTYPE, erp_user_id, "status") == REVOKED:
		return CREDENTIAL_STATE_REVOKED
	return CREDENTIAL_STATE_ABSENT


def active_owned_users():
	return frappe.get_all(CREDENTIAL_DOCTYPE, filters={"status": ACTIVE}, pluck="name")
