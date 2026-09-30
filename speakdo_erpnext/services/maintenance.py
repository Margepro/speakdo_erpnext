"""Scheduled housekeeping (hooks.scheduler_events)."""

import frappe

from speakdo_erpnext.services import challenges, enrollment_tokens, replay


def purge_expired():
	replay.purge_expired()
	challenges.purge_expired()
	enrollment_tokens.purge_expired()
	frappe.db.commit()
