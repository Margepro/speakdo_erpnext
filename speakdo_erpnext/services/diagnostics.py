"""Read-only status and diagnostics. No function here writes to the database."""

from speakdo_erpnext.constants import (
	COMPANION_PROTOCOL_VERSION,
	COMPANION_VERSION,
	RELOCATION_SUPPORTED,
	EnrollmentStatus,
	FeatureAvailability,
)
from speakdo_erpnext.domain import erp_instance, identity
from speakdo_erpnext.services import store
from speakdo_erpnext.services.enrollment import get_versions
from speakdo_erpnext.services.errors import SpeakDoError
from speakdo_erpnext.services.middleware import MiddlewareClient


def _safe(func):
	try:
		return func()
	except SpeakDoError:
		return None


def get_status():
	"""Public (browser-safe) state. Never contains a secret."""
	settings = store.get_all()
	status = settings.get("enrollment_status") or EnrollmentStatus.NOT_ENROLLED
	has_secret = store.has_hmac_secret()
	if status == EnrollmentStatus.ENROLLED and not has_secret:
		status = EnrollmentStatus.REPAIR_REQUIRED
	erp_base_url = _safe(erp_instance.erp_base_url)
	return {
		"enrollment_status": status,
		"erp_type": erp_instance.erp_type(),
		"tenant_uuid": settings.get("tenant_uuid"),
		"installation_id": settings.get("installation_id"),
		"middleware_url": settings.get("middleware_url"),
		"app_url": settings.get("app_url"),
		"instance_url": erp_base_url,
		"companion_base_url": erp_instance.companion_base_url(erp_base_url) if erp_base_url else None,
		"declared_instance_url": settings.get("declared_instance_url"),
		"relocation_pending": bool(erp_base_url) and erp_instance.relocation_pending(),
		"has_credentials": has_secret,
		"bootstrap_mode": settings.get("bootstrap_mode"),
		"billing_status": settings.get("billing_status"),
		"eligible_until": settings.get("eligible_until"),
		"relocation_availability": settings.get("relocation_availability")
		or (FeatureAvailability.UNKNOWN if RELOCATION_SUPPORTED else FeatureAvailability.UNAVAILABLE),
		"reset_availability": settings.get("reset_availability") or FeatureAvailability.UNKNOWN,
		"protocol_version": settings.get("protocol_version") or str(COMPANION_PROTOCOL_VERSION),
		"companion_version": COMPANION_VERSION,
		"versions": get_versions(),
		"last_successful_contact": settings.get("last_successful_contact"),
		"last_error_code": settings.get("last_error_code"),
		"last_error_message": settings.get("last_error_message"),
		"last_error_at": settings.get("last_error_at"),
		"actions": _available_actions(status, settings, has_secret, erp_base_url),
	}


def _available_actions(status, settings, has_secret, erp_base_url):
	"""Admin actions that make sense in the current local state (UI hints only:
	every service re-checks its own preconditions)."""
	enrolled = status == EnrollmentStatus.ENROLLED and has_secret
	attached = identity.is_valid_uuid(settings.get("tenant_uuid"))
	reset_gate = settings.get("reset_availability") != FeatureAvailability.UNAVAILABLE
	return {
		"bootstrap": not enrolled and bool(erp_base_url),
		"repair": identity.is_uuid_v4(settings.get("installation_id")) and bool(erp_base_url),
		"generate_qr": enrolled and attached,
		"reset": enrolled and reset_gate,
		"relocation": bool(RELOCATION_SUPPORTED and attached and erp_base_url and erp_instance.relocation_pending()),
	}


def run_diagnostics(probe=True, client=None):
	status = get_status()
	middleware = {"reachable": None, "http_status": None, "latency_ms": None, "error_code": None}
	if probe:
		try:
			client = client or MiddlewareClient()
			middleware = client.probe()
		except SpeakDoError as exc:
			middleware = {"reachable": False, "http_status": None, "latency_ms": None, "error_code": exc.error_code}

	return {
		"middleware_reachable": middleware["reachable"],
		"middleware_probe": middleware,
		"tenant_present": identity.is_valid_uuid(status["tenant_uuid"]),
		"installation_id_present": identity.is_uuid_v4(status["installation_id"]),
		"credentials_present": status["has_credentials"],
		"enrollment_status": status["enrollment_status"],
		"relocation_pending": status["relocation_pending"],
		"companion_base_url": status["companion_base_url"],
		"relocation_availability": status["relocation_availability"],
		"reset_availability": status["reset_availability"],
		"versions": status["versions"],
		"protocol_version": status["protocol_version"],
		"last_error_code": status["last_error_code"],
		"last_successful_contact": status["last_successful_contact"],
	}
