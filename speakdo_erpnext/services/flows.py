"""Common machinery of the proof based flows (bootstrap, repair, relocation).

start -> store the challenge -> COMMIT (the middleware fetches the proof
through another HTTP request, served by another worker) -> finalize ->
discard the challenge, whatever the outcome.
"""

import frappe

from speakdo_erpnext.services import challenges, messages, store
from speakdo_erpnext.services.errors import SpeakDoError
from speakdo_erpnext.services.log import log_event


def commit_publication():
	"""Make the stored challenge visible to the worker that will serve the proof."""
	frappe.db.commit()


def run_proof_flow(flow_type, started, installation_id, erp_base_url, finalize):
	"""Publish ``started`` (FlowStart) then call ``finalize(flow_id)``."""
	challenges.store(
		flow_type,
		started.flow_id,
		started.challenge,
		installation_id,
		erp_base_url,
		started.expires_in_seconds,
	)
	commit_publication()
	try:
		return finalize(started.flow_id)
	finally:
		challenges.discard(started.flow_id)


def run(operation, func, *args, **kwargs):
	"""Run an admin operation and convert SpeakDo errors to a result dict.

	Errors are returned (not raised) so that the request commits and
	last_error_* is kept. Messages come from the companion, never from the
	middleware payload.
	"""
	try:
		result = func(*args, **kwargs)
	except SpeakDoError as exc:
		exc.message = messages.message_for(exc.error_code, exc.message)
		store.record_error(exc.error_code, exc.message)
		log_event(operation, "result", "error", exc.error_code, exc.http_status)
		return exc.as_dict()
	log_event(operation, "result", "ok")
	return {"ok": True, **(result or {})}
