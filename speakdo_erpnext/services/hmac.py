"""Tenant HMAC, both directions (companion -> middleware and middleware -> companion).

Canonical string (5 lines joined by "\\n", no trailing newline)::

    METHOD            upper case
    REQUEST_TARGET    path + raw query string exactly as sent on the wire
                      (order, percent-encoding, repeated and empty parameters kept)
    TIMESTAMP         Unix seconds
    NONCE             ^[A-Za-z0-9_-]{16,190}$
    SHA256_HEX(BODY)  lower case hex of the raw body (empty body -> sha256(""))

Signature: base64 (standard, padded) of HMAC-SHA256(secret, canonical).

Nothing in this module logs: secrets, signatures and nonces never leave it
except in the returned headers.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time

from speakdo_erpnext.constants import HMAC_CLOCK_SKEW_SECONDS
from speakdo_erpnext.services.errors import HmacRejected

HEADER_TENANT = "X-SpeakDo-Tenant"
HEADER_TIMESTAMP = "X-SpeakDo-Timestamp"
HEADER_NONCE = "X-SpeakDo-Nonce"
HEADER_SIGNATURE = "X-SpeakDo-Signature"
SIGNED_HEADERS = (HEADER_TENANT, HEADER_TIMESTAMP, HEADER_NONCE, HEADER_SIGNATURE)

NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,190}$")
_TIMESTAMP_PATTERN = re.compile(r"^[0-9]{1,12}$")

# Same refusal codes as the middleware (TenantHmacMiddleware).
SIGNATURE_MISSING = "tenant_signature_missing"
INVALID_TIMESTAMP = "invalid_tenant_timestamp"
TIMESTAMP_EXPIRED = "tenant_timestamp_expired"
INVALID_NONCE = "invalid_tenant_nonce"
INVALID_SIGNATURE = "invalid_tenant_signature"
REPLAY_DETECTED = "tenant_replay_detected"


def _as_bytes(body):
	if body is None:
		return b""
	if isinstance(body, str):
		return body.encode("utf-8")
	return bytes(body)


def body_sha256_hex(body):
	return hashlib.sha256(_as_bytes(body)).hexdigest()


def canonical_string(method, path, timestamp, nonce, body):
	return "\n".join((method.upper(), path, str(timestamp), nonce, body_sha256_hex(body)))


def sign(secret, method, path, timestamp, nonce, body):
	digest = hmac.new(
		secret.encode("utf-8"), canonical_string(method, path, timestamp, nonce, body).encode("utf-8"), hashlib.sha256
	).digest()
	return base64.b64encode(digest).decode("ascii")


def new_nonce():
	# 18 random bytes -> 24 url-safe characters, within NONCE_PATTERN.
	return secrets.token_urlsafe(18)


def signed_headers(tenant_uuid, secret, method, path, body, now=None):
	"""Headers authenticating an outgoing request to the middleware."""
	timestamp = str(int(now if now is not None else time.time()))
	nonce = new_nonce()
	return {
		HEADER_TENANT: tenant_uuid,
		HEADER_TIMESTAMP: timestamp,
		HEADER_NONCE: nonce,
		HEADER_SIGNATURE: sign(secret, method, path, timestamp, nonce, body),
	}


def verify_request(
	*, method, request_target, headers, body, tenant_uuid, secret, consume_nonce, now=None, skew=HMAC_CLOCK_SKEW_SECONDS
):
	"""Verify an incoming signed request; raise HmacRejected on any failure.

	``request_target`` is the raw request target received (path + query string
	exactly as sent, never rebuilt nor normalised). It is the only accepted
	signed form: a signature over the path alone is refused when a query is
	present. A missing target is refused.
	``consume_nonce(nonce)`` must atomically record the nonce and return False
	if it was already seen. It is called only after a valid signature, like the
	middleware does. Checks run in the middleware order.
	"""
	values = {name: (headers.get(name) or "").strip() for name in SIGNED_HEADERS}
	if not all(values.values()):
		raise HmacRejected(SIGNATURE_MISSING)

	timestamp = values[HEADER_TIMESTAMP]
	if not _TIMESTAMP_PATTERN.match(timestamp):
		raise HmacRejected(INVALID_TIMESTAMP)
	current = int(now if now is not None else time.time())
	if abs(current - int(timestamp)) > skew:
		raise HmacRejected(TIMESTAMP_EXPIRED)

	nonce = values[HEADER_NONCE]
	if not NONCE_PATTERN.match(nonce):
		raise HmacRejected(INVALID_NONCE)

	# Unknown tenant / no local secret: indistinguishable from a bad signature.
	if not secret or not tenant_uuid or not hmac.compare_digest(
		values[HEADER_TENANT].lower().encode("utf-8"), tenant_uuid.lower().encode("utf-8")
	):
		raise HmacRejected(INVALID_SIGNATURE)

	if not request_target:
		raise HmacRejected(INVALID_SIGNATURE)
	expected = sign(secret, method, request_target, timestamp, nonce, body).encode("ascii")
	if not hmac.compare_digest(expected, values[HEADER_SIGNATURE].encode("utf-8")):
		raise HmacRejected(INVALID_SIGNATURE)

	if not consume_nonce(nonce):
		raise HmacRejected(REPLAY_DETECTED)
	return True
