from frappe.model.document import Document


class SpeakDoEnrollmentToken(Document):
	"""One-shot enrollment token (name = SHA-256 of the token). Written by services.enrollment_tokens only."""
