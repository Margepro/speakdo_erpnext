"""Anti-replay store for incoming HMAC nonces.

Backed by the `SpeakDo Nonce` table (shared by every gunicorn worker): the row
name is SHA-256(scope:nonce), so recording a nonce twice fails on the primary
key, atomically, whatever the number of workers.
"""

import hashlib
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from speakdo_erpnext.constants import HMAC_NONCE_TTL_SECONDS, NONCE_DOCTYPE


def _key(scope, nonce):
	return hashlib.sha256(f"{scope}:{nonce}".encode()).hexdigest()


def consume_nonce(scope, nonce, ttl_seconds=HMAC_NONCE_TTL_SECONDS):
	"""Record ``nonce`` for ``scope``. Return False if it was already recorded."""
	doc = frappe.new_doc(NONCE_DOCTYPE)
	doc.name = _key(scope, nonce)
	doc.expires_at = now_datetime() + timedelta(seconds=ttl_seconds)
	try:
		doc.db_insert()
	except frappe.DuplicateEntryError:
		return False
	return True


def purge_expired():
	frappe.db.delete(NONCE_DOCTYPE, {"expires_at": ("<", now_datetime())})
