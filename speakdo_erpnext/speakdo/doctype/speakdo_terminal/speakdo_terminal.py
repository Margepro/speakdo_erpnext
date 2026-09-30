from frappe.model.document import Document


class SpeakDoTerminal(Document):
	"""Enrolled terminal (name = middleware terminal_id). Written by services.terminals only."""

	def on_trash(self):
		# A deleted terminal is a revoked one: release the shared ERP credential
		# if no other live terminal of the user depends on it.
		from speakdo_erpnext.services.terminals import release_credential_if_unused

		release_credential_if_unused(self.erp_user, exclude=self.name, reason="terminal_deleted")
