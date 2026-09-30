"""Static technical constants of the SpeakDo companion.

Nothing here describes SpeakDo business concepts: actions, mappings, sources
and capabilities live in the SpeakDo middleware only. Wire (network) names of
the current middleware protocol are NOT defined here: they are confined to
``speakdo_erpnext.adapters.middleware_legacy``.
"""

from speakdo_erpnext import __version__

COMPANION_VERSION = __version__
ERP_TYPE = "erpnext"
USER_AGENT = f"SpeakDo-ERPNext/{COMPANION_VERSION}"

# Companion protocol version announced in the proofs. The middleware fixes it
# server side (value 1) and only records the announced value for diagnostics.
COMPANION_PROTOCOL_VERSION = 1

SETTINGS_DOCTYPE = "SpeakDo Settings"
FLOW_CHALLENGE_DOCTYPE = "SpeakDo Flow Challenge"
ENROLLMENT_TOKEN_DOCTYPE = "SpeakDo Enrollment Token"
TERMINAL_DOCTYPE = "SpeakDo Terminal"
NONCE_DOCTYPE = "SpeakDo Nonce"
CREDENTIAL_DOCTYPE = "SpeakDo ERP Credential"
ALLOWED_PROFILE_DOCTYPE = "SpeakDo Allowed Profile"
# Single-profile DocType of the previous model, removed by patch v0_1.migrate_allowed_profiles.
LEGACY_PROFILE_DOCTYPE = "SpeakDo User Profile"

# Roles allowed to administrate the companion (System Manager only).
MANAGER_ROLES = ("System Manager",)

# Stable identity backup, kept in site_config.json so that the installation
# identity survives an app uninstall / reinstall.
SITE_CONFIG_INSTALLATION_KEY = "speakdo_installation_id"
# Key written by v0.1.0 before the installation_uuid -> installation_id rename.
# Still read as a fallback, never written.
LEGACY_SITE_CONFIG_INSTALLATION_KEY = "speakdo_installation_uuid"

# DEFAULT values only. They pre-fill SpeakDo Settings at creation time and
# are used by "restore defaults". Runtime logic must always read
# SpeakDo Settings.middleware_url / SpeakDo Settings.app_url instead.
DEFAULT_MIDDLEWARE_URL = "https://api.speakdo.fr"
DEFAULT_APP_URL = "https://app.speakdo.fr"

# Python module whose whitelisted functions form the companion surface called
# by the middleware. Frappe exposes them as
# {erp_base_url}/api/method/<module>.<function>, hence
# companion_base_url = {erp_base_url}/api/method/<module>.
COMPANION_SURFACE_MODULE = "speakdo_erpnext.api.companion"

# The middleware explicitly refuses relocation for erp_type=erpnext: the flow
# is kept ready but never called while this is False.
RELOCATION_SUPPORTED = False

# PWA enrollment route on app_url: {app_url}/enroll?tenant_id=..&token=..&channel=pwa
PWA_ENROLL_PATH = "/enroll"
PWA_CHANNEL = "pwa"

ENROLLMENT_TOKEN_TTL_SECONDS = 600
# Local lifetime cap of a proof challenge (the middleware TTL is 300 s).
FLOW_CHALLENGE_MAX_TTL_SECONDS = 900

# Incoming HMAC: same values as the middleware (TERMINAL_CLOCK_SKEW_SECONDS,
# REPLAY_NONCE_TTL_SECONDS).
HMAC_CLOCK_SKEW_SECONDS = 300
HMAC_NONCE_TTL_SECONDS = 600

# Capabilities and permissions_version: see domain.erp_capabilities.


class EnrollmentStatus:
	NOT_ENROLLED = "not_enrolled"
	ENROLLED = "enrolled"
	REPAIR_REQUIRED = "repair_required"
	ERROR = "error"

	ALL = (NOT_ENROLLED, ENROLLED, REPAIR_REQUIRED, ERROR)


class TerminalStatus:
	ACTIVE = "active"
	PENDING_APPROVAL = "pending_approval"
	REVOKED = "revoked"

	ALL = (ACTIVE, PENDING_APPROVAL, REVOKED)


class FlowType:
	BOOTSTRAP = "bootstrap"
	REPAIR = "repair"
	RELOCATION = "relocation"

	ALL = (BOOTSTRAP, REPAIR, RELOCATION)


class FeatureAvailability:
	"""Middleware feature gates observed by the companion (relocation, reset)."""

	UNKNOWN = "unknown"
	AVAILABLE = "available"
	UNAVAILABLE = "unavailable"
