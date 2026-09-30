from frappe.model.document import Document


class SpeakDoAllowedProfile(Document):
	"""One allowed (user, profile) pair. Written by services.profiles only."""
