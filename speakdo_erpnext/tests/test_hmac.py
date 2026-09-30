import base64
import hashlib
import time

import frappe

from speakdo_erpnext.services import hmac, replay
from speakdo_erpnext.services.errors import HmacRejected
from speakdo_erpnext.tests.utils import SECRET, TENANT, SpeakDoTestCase, reference_headers, reference_sign

PATH = "/api/method/speakdo_erpnext.api.companion.terminal_status"


class TestHmacSignature(SpeakDoTestCase):
	def test_canonical_string_format(self):
		canonical = hmac.canonical_string("post", "/a/b", 1790683200, "n" * 24, b"")
		self.assertEqual(
			canonical,
			"POST\n/a/b\n1790683200\n" + "n" * 24 + "\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
		)

	def test_signature_matches_reference_implementation(self):
		body = b'{"consume":true}'
		ours = hmac.sign(SECRET, "POST", PATH, "1790683200", "abcdefghijklmnop", body)
		self.assertEqual(ours, reference_sign(SECRET, "POST", PATH, "1790683200", "abcdefghijklmnop", body))
		# standard base64 of a 32 byte digest, padded
		self.assertEqual(len(base64.b64decode(ours, validate=True)), 32)
		self.assertTrue(ours.endswith("="))

	def test_known_vector(self):
		# Independent computation from the contract text.
		canonical = "GET\n/p\n1\nABCDEFGHIJKLMNOP\n" + hashlib.sha256(b"").hexdigest()
		import hmac as std

		expected = base64.b64encode(std.new(b"k" * 32, canonical.encode(), hashlib.sha256).digest()).decode()
		self.assertEqual(hmac.sign("k" * 32, "GET", "/p", "1", "ABCDEFGHIJKLMNOP", b""), expected)

	def test_outgoing_headers(self):
		headers = hmac.signed_headers(TENANT, SECRET, "POST", "/api/v1/tenants/installation/reset", b"{}")
		self.assertEqual(set(headers), set(hmac.SIGNED_HEADERS))
		self.assertTrue(hmac.NONCE_PATTERN.match(headers["X-SpeakDo-Nonce"]))
		self.assertTrue(headers["X-SpeakDo-Timestamp"].isdigit())
		self.assertEqual(
			headers["X-SpeakDo-Signature"],
			reference_sign(SECRET, "POST", "/api/v1/tenants/installation/reset", headers["X-SpeakDo-Timestamp"], headers["X-SpeakDo-Nonce"], b"{}"),
		)


class TestHmacVerification(SpeakDoTestCase):
	def verify(self, headers, body=b"", method="GET", path=PATH, secret=SECRET, seen=None):
		seen = set() if seen is None else seen

		def consume(nonce):
			if nonce in seen:
				return False
			seen.add(nonce)
			return True

		return hmac.verify_request(
			method=method, request_target=path, headers=headers, body=body, tenant_uuid=TENANT, secret=secret, consume_nonce=consume
		)

	def assertRejected(self, code, headers, **kwargs):
		with self.assertRaises(HmacRejected) as ctx:
			self.verify(headers, **kwargs)
		self.assertEqual(ctx.exception.error_code, code)
		self.assertEqual(ctx.exception.http_status, 401)

	def test_valid_request_accepted(self):
		self.assertTrue(self.verify(reference_headers(SECRET, "GET", PATH)))

	def test_missing_headers(self):
		for name in hmac.SIGNED_HEADERS:
			headers = reference_headers(SECRET, "GET", PATH)
			headers.pop(name)
			self.assertRejected(hmac.SIGNATURE_MISSING, headers)
		self.assertRejected(hmac.SIGNATURE_MISSING, {})

	def test_timestamp_expired(self):
		now = int(time.time())
		self.assertRejected(hmac.TIMESTAMP_EXPIRED, reference_headers(SECRET, "GET", PATH, timestamp=now - 301))
		self.assertRejected(hmac.TIMESTAMP_EXPIRED, reference_headers(SECRET, "GET", PATH, timestamp=now + 301))
		self.assertTrue(self.verify(reference_headers(SECRET, "GET", PATH, timestamp=now - 290)))

	def test_invalid_timestamp(self):
		headers = reference_headers(SECRET, "GET", PATH)
		headers["X-SpeakDo-Timestamp"] = "12a"
		self.assertRejected(hmac.INVALID_TIMESTAMP, headers)

	def test_invalid_nonce(self):
		self.assertRejected(hmac.INVALID_NONCE, reference_headers(SECRET, "GET", PATH, nonce="short"))
		self.assertRejected(hmac.INVALID_NONCE, reference_headers(SECRET, "GET", PATH, nonce="with space in it!!"))

	def test_nonce_replayed(self):
		seen = set()
		headers = reference_headers(SECRET, "GET", PATH)
		self.assertTrue(self.verify(headers, seen=seen))
		self.assertRejected(hmac.REPLAY_DETECTED, headers, seen=seen)

	def test_nonce_store_is_shared_and_atomic(self):
		self.assertTrue(replay.consume_nonce("tenant:x", "n" * 20))
		self.assertFalse(replay.consume_nonce("tenant:x", "n" * 20))
		self.assertTrue(replay.consume_nonce("tenant:y", "n" * 20))
		# only a hash is stored
		self.assertFalse(frappe.db.exists("SpeakDo Nonce", "n" * 20))

	def test_nonce_not_consumed_when_signature_invalid(self):
		seen = set()
		headers = reference_headers("wrong-secret-" * 4, "GET", PATH)
		self.assertRejected(hmac.INVALID_SIGNATURE, headers, seen=seen)
		self.assertEqual(seen, set())

	def test_wrong_secret_tenant_body_method_path(self):
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers("other-secret-" * 4, "GET", PATH))
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers(SECRET, "GET", PATH, tenant="3f0b6c1e-8a51-4f7e-9b0d-2a7c5e9d1f44"))
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers(SECRET, "POST", PATH, b"{}"), body=b"{ }", method="POST")
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers(SECRET, "POST", PATH))
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers(SECRET, "GET", PATH + "x"))

	def test_no_local_secret_is_neutral_refusal(self):
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers(SECRET, "GET", PATH), secret=None)

	def test_request_target_is_the_only_signed_form(self):
		target = PATH + "?terminal_uuid=abc"
		self.assertTrue(self.verify(reference_headers(SECRET, "GET", target), path=target))
		# a "path only" signature is refused as soon as the request has a query
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers(SECRET, "GET", PATH), path=target)
		# and a request without query is signed on its bare path
		self.assertTrue(self.verify(reference_headers(SECRET, "GET", PATH), path=PATH))

	def test_missing_request_target_refused(self):
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers(SECRET, "GET", PATH), path=None)
		self.assertRejected(hmac.INVALID_SIGNATURE, reference_headers(SECRET, "GET", PATH), path="")

	def test_canonical_keeps_query_verbatim(self):
		canonical = hmac.canonical_string("GET", "/p?b=2&a=%40&a=&c", 1, "n" * 16, b"")
		self.assertEqual(canonical.splitlines()[1], "/p?b=2&a=%40&a=&c")
