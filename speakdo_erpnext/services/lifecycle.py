"""Relocation and installation reset (SPEAKDO_COMPANION_PROTOCOL §9, §10).

Both surfaces are closed by a middleware feature gate in PROD
(``TENANT_RELOCATION_HTTP_ENABLED``): they then answer ``404 not_found``. The
companion records the feature as unavailable and changes nothing locally; the
gate is never worked around. installation_id is never erased.
"""

from frappe.utils import now_datetime

from speakdo_erpnext.adapters import get_middleware_protocol
from speakdo_erpnext.constants import RELOCATION_SUPPORTED, EnrollmentStatus, FeatureAvailability, FlowType
from speakdo_erpnext.domain import erp_instance, identity
from speakdo_erpnext.services import enrollment_tokens, flows, store, terminals
from speakdo_erpnext.services.errors import FeatureUnavailable, StateError

RESET_REASON = "admin_factory_reset"


def _record_availability(field, available):
	store.update(
		**{field: FeatureAvailability.AVAILABLE if available else FeatureAvailability.UNAVAILABLE},
		features_checked_at=now_datetime(),
	)


def relocate(protocol=None):
	"""Declare the new ERP base URL (same tenant, same installation, same secret).

	The middleware refuses relocation for erp_type=erpnext: while
	RELOCATION_SUPPORTED is False the flow is refused locally, without calling
	the middleware (the refusal is never worked around).
	"""
	if not RELOCATION_SUPPORTED:
		_record_availability("relocation_availability", False)
		raise FeatureUnavailable("La relocation n'est pas encore prise en charge par le middleware pour ERPNext.")
	if not erp_instance.relocation_pending():
		raise StateError(error_code="no_relocation_pending")
	installation_id = identity.require_installation_id()
	new_erp_base_url = erp_instance.erp_base_url()
	protocol = protocol or get_middleware_protocol()

	try:
		started = protocol.relocation_start(installation_id, new_erp_base_url)
		_record_availability("relocation_availability", True)
		if started is None:
			# installation_url_unchanged: the middleware already has this URL
			# (also the recovery path after a lost finalize answer).
			result = {"unchanged": True}
		else:
			flows.run_proof_flow(
				FlowType.RELOCATION, started, installation_id, new_erp_base_url, protocol.relocation_finalize
			)
			result = {"unchanged": False}
	except FeatureUnavailable:
		_record_availability("relocation_availability", False)
		raise

	store.update(declared_instance_url=new_erp_base_url)
	store.mark_contact()
	store.clear_error()
	return {"instance_url": new_erp_base_url, **result}


def reset(protocol=None, reason=RESET_REASON):
	"""Ask the middleware to deregister this installation (signed call).

	Only a confirmed ``200 {"ok": true}`` clears the local secret and revokes
	local terminals / tokens. tenant_uuid and installation_id are kept: after a
	reset the middleware still knows the installation, and only a repair can
	re-attach it (§10.4).
	"""
	tenant_uuid = identity.normalize_tenant_uuid(store.get("tenant_uuid"))
	secret = store.get_hmac_secret()
	if not tenant_uuid or not secret:
		raise StateError(error_code="not_enrolled")
	installation_id = identity.require_installation_id()
	protocol = protocol or get_middleware_protocol()

	try:
		protocol.installation_reset(tenant_uuid, secret, installation_id, reason)
	except FeatureUnavailable:
		_record_availability("reset_availability", False)
		raise
	_record_availability("reset_availability", True)

	store.clear_hmac_secret()
	terminals.revoke_all()
	enrollment_tokens.revoke_all()
	store.update(enrollment_status=EnrollmentStatus.REPAIR_REQUIRED)
	store.mark_contact()
	store.clear_error()
	return {"tenant_uuid": tenant_uuid}
