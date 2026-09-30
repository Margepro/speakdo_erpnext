"""User-centric SpeakDo state (the model is multi-user):

    ERPNext User
      ├── allowed SpeakDo profiles [0..N] (stored by the companion, catalogue = middleware)
      ├── ERP permissions → capabilities (computed live, never cached)
      ├── ERP credential        (state only, never the key nor the secret)
      └── terminals             (SpeakDo Terminal.erp_user)

The ACTIVE profile is a middleware/session concern (profile.switch): it is not
known nor fabricated here. The instance attachment (tenant,
SpeakDo Settings.enrollment_status) is a different, instance-level state.
"""

import frappe

from speakdo_erpnext.constants import (
	ALLOWED_PROFILE_DOCTYPE,
	CREDENTIAL_DOCTYPE,
	TERMINAL_DOCTYPE,
	TerminalStatus,
)
from speakdo_erpnext.domain import erp_capabilities, erp_credentials, erp_users
from speakdo_erpnext.services import profiles, terminals


def user_state(erp_user_id):
	"""Full SpeakDo state of ONE user. Callers must have checked they may see it."""
	user = erp_users.get_erp_user(erp_user_id)
	if not user:
		return None
	capabilities = erp_capabilities.capabilities_for(erp_user_id)
	allowed_profiles = profiles.get_allowed_profiles(erp_user_id)
	user_terminals = terminals.list_terminals(erp_user_id)
	active = [t for t in user_terminals if t.status != TerminalStatus.REVOKED]
	return {
		"erp_user_id": user.erp_user_id,
		"display_name": user.display_name,
		"active": user.active,
		"can_enroll": erp_users.can_enroll(erp_user_id),
		"allowed_profiles": allowed_profiles,
		"allowed_profile_labels": profiles.profile_labels(allowed_profiles),
		"capabilities": capabilities,
		"permissions_version": erp_capabilities.permissions_version(capabilities, allowed_profiles),
		"credential_state": erp_credentials.state(erp_user_id),
		"enrolled": bool(active),
		"active_terminal_count": len(active),
		"terminals": user_terminals,
	}


def speakdo_users(extra_user=None):
	"""Users having any SpeakDo state (terminal, credential record, profile)."""
	names = set(frappe.get_all(TERMINAL_DOCTYPE, pluck="erp_user", distinct=True))
	names |= set(frappe.get_all(CREDENTIAL_DOCTYPE, pluck="name"))
	names |= set(frappe.get_all(ALLOWED_PROFILE_DOCTYPE, pluck="erp_user", distinct=True))
	if extra_user:
		names.add(extra_user)
	states = [user_state(name) for name in sorted(n for n in names if n)]
	return [s for s in states if s]
