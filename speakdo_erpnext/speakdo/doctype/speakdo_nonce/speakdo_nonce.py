from frappe.model.document import Document


class SpeakDoNonce(Document):
	"""HMAC anti-replay record. Written by services.replay only."""
