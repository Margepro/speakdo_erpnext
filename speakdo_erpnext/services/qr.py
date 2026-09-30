"""Temporary PWA enrollment QR code.

The middleware does not generate enrollment tokens: the companion does
(``services.enrollment_tokens``) and verifies / consumes them when the
middleware calls ``…/v1/enrollments/{token}/verify``.

URL format (accepted by the PWA, ``enroll.js::parseEnrollmentPayload``)::

    {app_url}/enroll?tenant_id={tenant_uuid}&token={token}&channel=pwa

The token only exists in clear inside the QR image returned to the admin who
asked for it; only its SHA-256 is stored and it is never logged.
"""

import base64
import io
from urllib.parse import urlencode

import pyqrcode

from speakdo_erpnext.constants import PWA_CHANNEL, PWA_ENROLL_PATH, EnrollmentStatus
from speakdo_erpnext.domain import erp_credentials, erp_instance, erp_users, identity
from speakdo_erpnext.services import enrollment_tokens, store
from speakdo_erpnext.services.errors import StateError
from speakdo_erpnext.services.middleware import get_app_url


def build_enroll_url(app_url, tenant_uuid, token):
	base = erp_instance.normalize_base_url(app_url, "URL de l'application SpeakDo")
	query = urlencode([("tenant_id", tenant_uuid), ("token", token), ("channel", PWA_CHANNEL)])
	return f"{base}{PWA_ENROLL_PATH}?{query}"


def render_png_data_uri(content, scale=6):
	buffer = io.BytesIO()
	pyqrcode.create(content, error="M").png(buffer, scale=scale, quiet_zone=4)
	return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def check_qr_preconditions(erp_user_id):
	"""Raise StateError if a QR cannot be generated. No network, no write."""
	tenant_uuid = identity.normalize_tenant_uuid(store.get("tenant_uuid"))
	if not tenant_uuid:
		raise StateError(error_code="tenant_missing")
	if store.get("enrollment_status") != EnrollmentStatus.ENROLLED or not store.has_hmac_secret():
		# Without a valid secret the middleware's verify call could not be authenticated.
		raise StateError(error_code="not_enrolled")
	if not erp_users.can_enroll(erp_user_id):
		raise StateError(error_code="user_not_enrollable")
	try:
		# Fail early: the enrollment would be refused anyway.
		erp_credentials.ensure_issuable(erp_user_id)
	except erp_credentials.CredentialConflict as exc:
		raise StateError(error_code=exc.reason)
	get_app_url()  # validates app_url
	return tenant_uuid


def generate_enrollment_qr(erp_user_id):
	"""QR for ``erp_user_id`` (v1: the ERPNext user who asks for it)."""
	tenant_uuid = check_qr_preconditions(erp_user_id)
	token, expires_at = enrollment_tokens.issue(erp_user_id)
	image = render_png_data_uri(build_enroll_url(get_app_url(), tenant_uuid, token))
	return {"qr_image": image, "expires_at": str(expires_at), "channel": PWA_CHANNEL, "erp_user": erp_user_id}
