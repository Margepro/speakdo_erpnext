"""Instance configuration and bootstrap v2 (instance enrollment).

Flow (SPEAKDO_COMPANION_PROTOCOL §5, generalised for erp_type=erpnext):
start {installation_id, erp_type, ERP root URL, companion_base_url} ->
publish {bootstrap_id, installation_id, challenge} on the bootstrap_proof
surface function -> finalize (the middleware fetches the proof) -> tenant_uuid +
HMAC secret (returned once, new_installation) or tenant_uuid only
(legacy_migration: the existing secret must be kept).
"""

import frappe

from speakdo_erpnext.adapters import get_middleware_protocol
from speakdo_erpnext.constants import (
	COMPANION_PROTOCOL_VERSION,
	COMPANION_VERSION,
	DEFAULT_APP_URL,
	DEFAULT_MIDDLEWARE_URL,
	EnrollmentStatus,
	FlowType,
)
from speakdo_erpnext.domain import erp_instance, identity
from speakdo_erpnext.services import flows, store
from speakdo_erpnext.services.errors import StateError
from speakdo_erpnext.services.log import log_event


def get_versions():
	versions = {"frappe": frappe.__version__, "erpnext": None, "companion": COMPANION_VERSION}
	if "erpnext" in frappe.get_installed_apps():
		try:
			import erpnext

			versions["erpnext"] = erpnext.__version__
		except Exception:
			versions["erpnext"] = None
	return versions


def is_attached():
	"""A tenant exists for this installation (enrolled or awaiting repair)."""
	return identity.normalize_tenant_uuid(store.get("tenant_uuid")) is not None


# -- configuration -----------------------------------------------------------


def save_configuration(middleware_url=None, app_url=None, instance_url=None):
	values = {}
	attached = is_attached()

	if middleware_url is not None:
		normalized = erp_instance.normalize_base_url(middleware_url, "URL du middleware SpeakDo")
		if attached and normalized != store.get("middleware_url"):
			raise StateError(error_code="middleware_change_forbidden")
		values["middleware_url"] = normalized
	if app_url is not None:
		values["app_url"] = erp_instance.normalize_base_url(app_url, "URL de l'application SpeakDo")
	if instance_url is not None:
		# Changing instance_url never changes the identity; the middleware is
		# informed through the relocation flow.
		values["instance_url"] = erp_instance.normalize_erp_base_url(instance_url)

	store.update(**values)
	return {"saved": sorted(values)}


def restore_default_urls():
	"""Reset middleware_url and app_url only (identity, instance_url, secrets untouched)."""
	if is_attached() and store.get("middleware_url") != DEFAULT_MIDDLEWARE_URL:
		raise StateError(error_code="middleware_change_forbidden")
	store.update(middleware_url=DEFAULT_MIDDLEWARE_URL, app_url=DEFAULT_APP_URL)
	return {"middleware_url": DEFAULT_MIDDLEWARE_URL, "app_url": DEFAULT_APP_URL}


# -- bootstrap v2 --------------------------------------------------------------


def bootstrap(protocol=None):
	if store.get("enrollment_status") == EnrollmentStatus.ENROLLED and store.has_hmac_secret():
		raise StateError(error_code="already_enrolled")

	installation_id = identity.require_installation_id()
	erp_base_url = erp_instance.erp_base_url()
	protocol = protocol or get_middleware_protocol()

	started = protocol.bootstrap_start(
		installation_id, erp_instance.erp_type(), erp_base_url, erp_instance.companion_base_url(erp_base_url)
	)
	result = flows.run_proof_flow(
		FlowType.BOOTSTRAP, started, installation_id, erp_base_url, protocol.bootstrap_finalize
	)

	if result["hmac_secret"]:
		store.store_hmac_secret(result["hmac_secret"])
	has_secret = bool(result["hmac_secret"]) or store.has_hmac_secret()
	status = EnrollmentStatus.ENROLLED if has_secret else EnrollmentStatus.REPAIR_REQUIRED

	store.update(
		tenant_uuid=result["tenant_uuid"],
		enrollment_status=status,
		bootstrap_mode=result["mode"],
		billing_status=result["billing_status"],
		eligible_until=result["eligible_until"],
		protocol_version=str(COMPANION_PROTOCOL_VERSION),
		companion_version=COMPANION_VERSION,
		declared_instance_url=erp_base_url,
	)
	store.mark_contact()
	if has_secret:
		store.clear_error()
	else:
		# legacy_migration without any local secret: the chained repair (§6)
		# is the only way to obtain one.
		store.record_error("legacy_migration_requires_repair", "Réparation nécessaire.")
		log_event("bootstrap", "result", "error", "legacy_migration_requires_repair")

	return {
		"tenant_uuid": result["tenant_uuid"],
		"mode": result["mode"],
		"enrollment_status": status,
		"billing_status": result["billing_status"],
		"eligible_until": result["eligible_until"],
		"free_trial_granted": result["free_trial_granted"],
	}
