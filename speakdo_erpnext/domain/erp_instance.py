"""The ERP instance as seen by SpeakDo: type, base URL, companion surface URL.

- ``erp_base_url``: the real ERPNext root (SpeakDo Settings.instance_url),
  ``scheme://host[:port]`` with no path (Frappe is always served at the root).
- ``companion_base_url``: the HTTP surface of this companion, i.e. the Frappe
  RPC prefix of ``COMPANION_SURFACE_MODULE``:
  ``{erp_base_url}/api/method/speakdo_erpnext.api.companion``. It is derived,
  never configured, so it always shares host and port with ``erp_base_url``
  and starts with ``/api/method/`` (both required by the middleware).

Neither is an identity: see domain.identity.
"""

from urllib.parse import urlsplit, urlunsplit

from frappe.utils import get_url

from speakdo_erpnext.constants import COMPANION_SURFACE_MODULE, ERP_TYPE
from speakdo_erpnext.services import store
from speakdo_erpnext.services.errors import ConfigurationError

RPC_PREFIX = "/api/method/"


def erp_type():
	return ERP_TYPE


def normalize_base_url(url, label="URL"):
	"""Validate an http(s) base URL and strip the trailing slash / query / fragment."""
	if not isinstance(url, str) or not url.strip():
		raise ConfigurationError(f"{label} non configurée.", error_code="url_missing")
	parts = urlsplit(url.strip())
	if parts.scheme not in ("http", "https") or not parts.netloc:
		raise ConfigurationError(
			f"{label} invalide : seules les URLs http:// ou https:// sont acceptées.",
			error_code="url_invalid",
		)
	if parts.username or parts.password:
		raise ConfigurationError(f"{label} invalide : identifiants interdits dans l'URL.", error_code="url_invalid")
	return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def normalize_erp_base_url(url):
	"""ERPNext root: a base URL without any path."""
	normalized = normalize_base_url(url, "URL de cette instance ERPNext")
	if urlsplit(normalized).path:
		raise ConfigurationError(
			"L'URL ERPNext doit être la racine du site (sans chemin) : Frappe ne se sert pas sous un sous-chemin.",
			error_code="erp_base_url_has_path",
		)
	return normalized


def erp_base_url():
	"""The real URL of this ERPNext (not a SpeakDo URL, not an identity)."""
	return normalize_erp_base_url(store.get("instance_url") or get_url())


def companion_base_url(base_url=None):
	return f"{base_url or erp_base_url()}{RPC_PREFIX}{COMPANION_SURFACE_MODULE}"


def surface_path(function_name):
	"""HTTP path of one surface function (what the middleware signs)."""
	return f"{RPC_PREFIX}{COMPANION_SURFACE_MODULE}.{function_name}"


def declared_erp_base_url():
	"""ERP base URL last acknowledged by the middleware (bootstrap / relocation)."""
	return store.get("declared_instance_url") or None


def relocation_pending():
	"""True when the ERP base URL differs from the one last declared to the middleware."""
	declared = declared_erp_base_url()
	return bool(declared) and declared.rstrip("/") != erp_base_url().rstrip("/")
