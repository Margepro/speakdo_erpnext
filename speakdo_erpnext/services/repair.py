"""Repair (SPEAKDO_COMPANION_PROTOCOL §8).

For an installation that lost its tenant secret (or its tenant uuid) but still
has its installation_id. The proof is fetched on the URL registered by the
middleware; the secret is replaced (the previous one is refused at once and is
not kept locally). installation_id and instance_url are never modified.
"""

from speakdo_erpnext.adapters import get_middleware_protocol
from speakdo_erpnext.constants import EnrollmentStatus, FlowType
from speakdo_erpnext.domain import erp_instance, identity
from speakdo_erpnext.services import flows, store
from speakdo_erpnext.services.errors import StateError


def repair(protocol=None):
	installation_id = identity.require_installation_id()
	erp_base_url = erp_instance.erp_base_url()
	protocol = protocol or get_middleware_protocol()

	started = protocol.repair_start(installation_id, erp_base_url)
	result = flows.run_proof_flow(FlowType.REPAIR, started, installation_id, erp_base_url, protocol.repair_finalize)

	if result["installation_id"] and result["installation_id"].lower() != installation_id.lower():
		raise StateError("Le middleware a réparé une autre installation.", error_code="installation_mismatch")

	store.store_hmac_secret(result["hmac_secret"])  # overwrites: the old secret is gone
	store.update(tenant_uuid=result["tenant_uuid"], enrollment_status=EnrollmentStatus.ENROLLED)
	if not store.get("declared_instance_url"):
		store.update(declared_instance_url=erp_base_url)
	store.mark_contact()
	store.clear_error()
	return {"tenant_uuid": result["tenant_uuid"]}
