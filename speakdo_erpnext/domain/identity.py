"""Stable technical identity of this ERPNext installation.

- ``installation_id`` (UUID v4) is generated locally exactly once and never
  rotated by bootstrap / repair / reset / relocation / migrate / app update.
  It does not depend on any URL nor on the Docker hostname.
- ``tenant_uuid`` is *only* ever received from the middleware; it is never
  generated locally.
- The ERP base URL is never used as an identity (see relocation).

v0.1.0 named the installation identity ``installation_uuid``; the field was
renamed ``installation_id`` (patch ``v0_1.rename_installation_uuid``). The old
site_config backup key is still read as a fallback, never written.
"""

import re
import uuid

import frappe
from frappe.installer import update_site_config

from speakdo_erpnext.constants import (
	LEGACY_SITE_CONFIG_INSTALLATION_KEY,
	SETTINGS_DOCTYPE,
	SITE_CONFIG_INSTALLATION_KEY,
)
from speakdo_erpnext.services.errors import StateError

_UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)


def is_valid_uuid(value):
	if not isinstance(value, str) or not value.strip():
		return False
	try:
		uuid.UUID(value.strip())
	except (ValueError, AttributeError, TypeError):
		return False
	return True


def is_uuid_v4(value):
	return isinstance(value, str) and bool(_UUID_V4.match(value.strip()))


def normalize_uuid(value):
	return str(uuid.UUID(value.strip()))


def _read_backup():
	conf = frappe.get_site_config()
	return conf.get(SITE_CONFIG_INSTALLATION_KEY) or conf.get(LEGACY_SITE_CONFIG_INSTALLATION_KEY)


def _write_backup(value):
	update_site_config(SITE_CONFIG_INSTALLATION_KEY, value)


def get_installation_id():
	return frappe.db.get_single_value(SETTINGS_DOCTYPE, "installation_id")


def ensure_installation_id():
	"""Return the installation id, creating it only if none exists anywhere.

	Priority: value in SpeakDo Settings, then the site_config backup
	(survives app reinstall), then a freshly generated uuid4.
	"""
	current = get_installation_id()
	backup = _read_backup()

	if is_valid_uuid(current):
		current = normalize_uuid(current)
		if not (is_valid_uuid(backup) and normalize_uuid(backup) == current):
			_write_backup(current)
		return current

	if is_valid_uuid(backup):
		value = normalize_uuid(backup)
	else:
		value = str(uuid.uuid4())
	_write_backup(value)
	frappe.db.set_single_value(SETTINGS_DOCTYPE, "installation_id", value)
	return value


def require_installation_id():
	"""Installation id usable on the wire (strict UUID v4), or StateError.

	A non v4 value is never silently replaced: changing the identity must stay
	an explicit operator decision.
	"""
	value = ensure_installation_id()
	if not is_uuid_v4(value):
		raise StateError(
			"L'identifiant d'installation local n'est pas un UUID v4 : intervention manuelle requise.",
			error_code="installation_id_invalid",
		)
	return value


def normalize_tenant_uuid(value):
	"""Validate a tenant uuid received from the middleware (never generated here)."""
	if not isinstance(value, str) or not is_valid_uuid(value):
		return None
	return normalize_uuid(value)
