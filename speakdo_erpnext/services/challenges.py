"""Temporary proof challenges of the bootstrap / repair / relocation flows.

A challenge is a bearer secret for the duration of its flow: it is stored
encrypted (Password field), served only by the public proof route of its flow
until it expires, and deleted as soon as the flow is finalized (success or
failure). The database (not a process cache) is used so that any gunicorn
worker can serve the proof while another one waits for finalize.
"""

import re
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime
from frappe.utils.password import (
	get_decrypted_password,
	remove_encrypted_password,
	set_encrypted_password,
)

from speakdo_erpnext.constants import FLOW_CHALLENGE_DOCTYPE, FLOW_CHALLENGE_MAX_TTL_SECONDS, FlowType

DEFAULT_TTL_SECONDS = 300
_FLOW_ID = re.compile(r"^[0-9a-f-]{36}$")


def store(flow_type, flow_id, challenge, installation_id, erp_base_url, expires_in_seconds=None):
	if flow_type not in FlowType.ALL or not _FLOW_ID.match(flow_id or ""):
		raise ValueError("invalid flow")
	ttl = min(expires_in_seconds or DEFAULT_TTL_SECONDS, FLOW_CHALLENGE_MAX_TTL_SECONDS)
	doc = frappe.new_doc(FLOW_CHALLENGE_DOCTYPE)
	doc.name = flow_id
	doc.flow_type = flow_type
	doc.installation_id = installation_id
	doc.erp_base_url = erp_base_url
	doc.expires_at = now_datetime() + timedelta(seconds=ttl)
	doc.db_insert()
	set_encrypted_password(FLOW_CHALLENGE_DOCTYPE, flow_id, challenge, "challenge")


def get_published_proof(flow_type, flow_id):
	"""Proof content for a pending, unexpired challenge of ``flow_type``; else None."""
	if not isinstance(flow_id, str) or not _FLOW_ID.match(flow_id):
		return None
	row = frappe.db.get_value(
		FLOW_CHALLENGE_DOCTYPE,
		{"name": flow_id, "flow_type": flow_type},
		["name", "installation_id", "erp_base_url", "expires_at"],
		as_dict=True,
	)
	if not row or get_datetime(row.expires_at) <= now_datetime():
		return None
	challenge = get_decrypted_password(FLOW_CHALLENGE_DOCTYPE, flow_id, "challenge", raise_exception=False)
	if not challenge:
		return None
	return {
		"flow_id": row.name,
		"installation_id": row.installation_id,
		"erp_base_url": row.erp_base_url,
		"challenge": challenge,
	}


def discard(flow_id):
	remove_encrypted_password(FLOW_CHALLENGE_DOCTYPE, flow_id, "challenge")
	frappe.db.delete(FLOW_CHALLENGE_DOCTYPE, {"name": flow_id})


def purge_expired():
	for name in frappe.get_all(FLOW_CHALLENGE_DOCTYPE, filters={"expires_at": ("<", now_datetime())}, pluck="name"):
		discard(name)
