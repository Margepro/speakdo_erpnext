import frappe
from frappe import _
from frappe.model.document import Document

from speakdo_erpnext.domain import erp_instance
from speakdo_erpnext.services.errors import SpeakDoError

# Identity fields cannot be edited through the form / REST save.
IMMUTABLE_FIELDS = ("installation_id", "tenant_uuid", "erp_type")
# Fields managed only by the companion services.
SERVICE_FIELDS = (
	"enrollment_status",
	"declared_instance_url",
	"bootstrap_mode",
	"billing_status",
	"eligible_until",
	"protocol_version",
	"companion_version",
	"relocation_availability",
	"reset_availability",
	"features_checked_at",
	"last_successful_contact",
	"last_error_code",
	"last_error_message",
	"last_error_at",
)
# Changing them would break an existing attachment with the middleware.
LOCKED_WHEN_ATTACHED = ("middleware_url",)


class SpeakDoSettings(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if before:
			for fieldname in IMMUTABLE_FIELDS + SERVICE_FIELDS:
				if self.get(fieldname) != before.get(fieldname):
					if fieldname in IMMUTABLE_FIELDS and before.get(fieldname):
						frappe.throw(_("{0} ne peut pas être modifié.").format(self.meta.get_label(fieldname)))
					self.set(fieldname, before.get(fieldname))

		self._normalize(before)

	def _normalize(self, before):
		labels = {
			"middleware_url": "URL du middleware SpeakDo",
			"app_url": "URL de l'application SpeakDo",
			"instance_url": "URL de cette instance ERPNext",
		}
		try:
			for fieldname, label in labels.items():
				if self.get(fieldname):
					self.set(fieldname, erp_instance.normalize_base_url(self.get(fieldname), label))
			if self.get("instance_url"):
				self.instance_url = erp_instance.normalize_erp_base_url(self.instance_url)
		except SpeakDoError as exc:
			frappe.throw(exc.message)

		if before and before.get("tenant_uuid"):
			for fieldname in LOCKED_WHEN_ATTACHED:
				if (before.get(fieldname) or "") != (self.get(fieldname) or ""):
					frappe.throw(
						_("{0} ne peut pas être modifié tant que l'instance est rattachée à SpeakDo.").format(
							self.meta.get_label(fieldname)
						)
					)
