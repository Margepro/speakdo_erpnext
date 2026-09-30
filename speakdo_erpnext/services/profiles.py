"""SpeakDo profiles of ERPNext users: ALLOWED profiles (0..N per user).

Two distinct notions:

- ALLOWED profiles: the working modes an administrator authorizes for a user.
  A property of the USER (common to all their terminals), stored here in
  ``SpeakDo Allowed Profile`` (one row per user x profile).
- ACTIVE profile: the working mode currently in use. It belongs to the
  middleware (semantic action ``profile.switch``, observed on the LAB
  30/09/2026: "le profil demandé doit appartenir aux profils autorisés pour
  cet utilisateur … refusé par le serveur"). The companion never stores nor
  fabricates an active profile.

Catalogue: owned by the middleware (``GET /profiles``, tenant HMAC), cached
briefly, never hardcoded. Aliases are resolved against it; unknown ids are
refused.

Wire: ``allowed_profiles`` (sorted canonical ids) in enrollment_verify and
user_capabilities; the historical single ``profile_id`` is not emitted (see
docs/SPEAKDO_ERPNEXT_USER_MODEL.md, MIDDLEWARE CONTRACT REQUIRED). An empty
set stays empty: it is never turned into "generic".
"""

import hashlib

import frappe
from frappe.utils import now_datetime

from speakdo_erpnext.adapters import get_middleware_protocol
from speakdo_erpnext.constants import ALLOWED_PROFILE_DOCTYPE
from speakdo_erpnext.domain import erp_users, identity
from speakdo_erpnext.services import store
from speakdo_erpnext.services.errors import SpeakDoError, StateError

CATALOGUE_TTL_SECONDS = 300
_CACHE_KEY = "speakdo_profile_catalogue"


def get_catalogue(protocol=None, refresh=False):
	"""{"profiles": {id: {...}}, "aliases": {alias: id}} from the middleware."""
	if not refresh:
		cached = frappe.cache.get_value(_CACHE_KEY)
		if cached:
			return cached
	tenant_uuid = identity.normalize_tenant_uuid(store.get("tenant_uuid"))
	secret = store.get_hmac_secret()
	if not tenant_uuid or not secret:
		raise StateError(error_code="not_enrolled")
	protocol = protocol or get_middleware_protocol()
	profiles, aliases = protocol.list_profiles(tenant_uuid, secret)
	catalogue = {"profiles": profiles, "aliases": aliases}
	frappe.cache.set_value(_CACHE_KEY, catalogue, expires_in_sec=CATALOGUE_TTL_SECONDS)
	return catalogue


def canonical_profile_id(profile_id, catalogue):
	"""Catalogue id for ``profile_id`` (aliases resolved), or None if unknown."""
	if profile_id in catalogue["profiles"]:
		return profile_id
	return catalogue["aliases"].get(profile_id)


def assignment_name(erp_user_id, profile_id):
	"""Deterministic row name: the primary key makes a (user, profile) pair unique."""
	return hashlib.sha256(f"{erp_user_id}\n{profile_id}".encode()).hexdigest()[:32]


def get_allowed_profiles(erp_user_id):
	"""Sorted canonical ids of the profiles allowed to the user ([] if none)."""
	if not erp_user_id:
		return []
	return sorted(frappe.get_all(ALLOWED_PROFILE_DOCTYPE, filters={"erp_user": erp_user_id}, pluck="profile_id"))


def _insert(erp_user_id, profile_id, assigned_by):
	doc = frappe.new_doc(ALLOWED_PROFILE_DOCTYPE)
	doc.name = assignment_name(erp_user_id, profile_id)
	doc.erp_user = erp_user_id
	doc.profile_id = profile_id
	doc.assigned_by = assigned_by
	doc.assigned_at = now_datetime()
	doc.db_insert()


def set_allowed_profiles(erp_user_id, profile_ids, assigned_by, protocol=None):
	"""Replace the set of allowed profiles of a user (idempotent).

	Every id must exist in the middleware catalogue (aliases canonicalized):
	one unknown id refuses the whole change, nothing is modified. Duplicates
	collapse. Returns the resulting sorted set.
	"""
	if not erp_users.get_erp_user(erp_user_id):
		raise StateError(error_code="user_not_found")
	requested = [p for p in (profile_ids or []) if p]
	wanted = set()
	if requested:
		catalogue = get_catalogue(protocol=protocol, refresh=True)
		for profile_id in requested:
			canonical = canonical_profile_id(profile_id, catalogue)
			if not canonical:
				raise StateError(error_code="profile_unknown")
			wanted.add(canonical)
	current = set(get_allowed_profiles(erp_user_id))
	for profile_id in current - wanted:
		frappe.db.delete(ALLOWED_PROFILE_DOCTYPE, {"name": assignment_name(erp_user_id, profile_id)})
	for profile_id in sorted(wanted - current):
		_insert(erp_user_id, profile_id, assigned_by)
	return sorted(wanted)


def profile_labels(profile_ids):
	"""Best-effort display labels from the cached catalogue (ids if unavailable)."""
	try:
		catalogue = get_catalogue()
	except SpeakDoError:
		catalogue = None
	labels = {}
	for profile_id in profile_ids:
		entry = catalogue["profiles"].get(profile_id) if catalogue else None
		labels[profile_id] = entry["label"] if entry else profile_id
	return labels
