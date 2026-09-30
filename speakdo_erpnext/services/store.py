"""Access to the `SpeakDo Settings` single and to the tenant HMAC secret.

The secret is stored encrypted through Frappe's `__Auth` table (Password
field, encrypted with the site ``encryption_key``). It is never returned by
any whitelisted method, never logged, and a rotation overwrites it (the
previous value is not kept).
"""

import frappe
from frappe.utils import now_datetime
from frappe.utils.password import (
	get_decrypted_password,
	remove_encrypted_password,
	set_encrypted_password,
)

from speakdo_erpnext.constants import SETTINGS_DOCTYPE

HMAC_SECRET_FIELD = "hmac_secret"

# Fields any service may update. installation_id is intentionally absent:
# only domain.identity may write it.
_WRITABLE_FIELDS = {
	"middleware_url",
	"app_url",
	"instance_url",
	"declared_instance_url",
	"tenant_uuid",
	"enrollment_status",
	"bootstrap_mode",
	"billing_status",
	"eligible_until",
	"protocol_version",
	"companion_version",
	"relocation_availability",
	"reset_availability",
	"features_checked_at",
	"last_successful_contact",
	"last_error_code",
	"last_error_message",
	"last_error_at",
}


def get(fieldname):
	value = frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname)
	# Frappe casts an empty Datetime single value to year 1.
	if str(value).startswith("0001-01-01"):
		return None
	return value


def get_all():
	fields = [*sorted(_WRITABLE_FIELDS), "installation_id", "erp_type"]
	return {f: get(f) for f in fields}


def update(**values):
	unknown = set(values) - _WRITABLE_FIELDS
	if unknown:
		raise ValueError(f"Non writable SpeakDo settings field(s): {sorted(unknown)}")
	if values:
		frappe.db.set_single_value(SETTINGS_DOCTYPE, values)


def mark_contact():
	update(last_successful_contact=now_datetime())


def record_error(error_code, message):
	update(
		last_error_code=(error_code or "")[:140],
		last_error_message=(message or "")[:500],
		last_error_at=now_datetime(),
	)


def clear_error():
	update(last_error_code=None, last_error_message=None, last_error_at=None)


# -- tenant HMAC secret -------------------------------------------------------


def get_hmac_secret():
	return get_decrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, HMAC_SECRET_FIELD, raise_exception=False)


def store_hmac_secret(secret):
	"""Store (rotate) the tenant secret. The previous value is overwritten."""
	if not isinstance(secret, str) or not secret:
		raise ValueError("empty secret")
	set_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, secret, HMAC_SECRET_FIELD)


def clear_hmac_secret():
	remove_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, HMAC_SECRET_FIELD)


def has_hmac_secret():
	return bool(get_hmac_secret())
