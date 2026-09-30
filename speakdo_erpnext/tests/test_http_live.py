"""End-to-end HTTP checks through the real Frappe stack (gunicorn, /api/method
dispatcher, whitelisting, guest access), against the site under test. Skipped
when the local web server is not reachable. Data is committed (another process
serves it) and removed."""

import os
import unittest

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from speakdo_erpnext import __version__
from speakdo_erpnext.constants import FlowType
from speakdo_erpnext.domain import identity
from speakdo_erpnext.domain.erp_capabilities import capabilities_for, permissions_version
from speakdo_erpnext.services import challenges, store
from speakdo_erpnext.tests.utils import reference_headers

SERVER = os.environ.get("SPEAKDO_TEST_SERVER", "http://127.0.0.1:8000")
SURFACE = "/api/method/speakdo_erpnext.api.companion"
FLOW_ID = "9a8b7c6d-5e4f-4a3b-9c2d-1e0f9a8b7c6d"


class TestLiveSurface(FrappeTestCase):
	def setUp(self):
		try:
			requests.get(SERVER, timeout=2)
		except requests.RequestException:
			raise unittest.SkipTest("local web server not reachable")
		self.headers = {"Host": frappe.local.site, "X-Frappe-Site-Name": frappe.local.site}

	def call(self, method, path, headers=None, **kwargs):
		return requests.request(
			method, SERVER + path, headers=headers or self.headers, timeout=10, allow_redirects=False, **kwargs
		)

	def test_public_proof_reachable_without_login(self):
		installation_id = identity.ensure_installation_id()
		challenges.store(FlowType.BOOTSTRAP, FLOW_ID, "L" * 43, installation_id, "https://erp.test")
		frappe.db.commit()
		try:
			response = self.call("GET", f"{SURFACE}.bootstrap_proof?id={FLOW_ID}")
			self.assertEqual(response.status_code, 200, response.text[:200])
			self.assertTrue(response.headers["Content-Type"].startswith("application/json"))
			self.assertIn("no-store", response.headers.get("Cache-Control", ""))
			# raw document, no Frappe {"message": …} envelope
			self.assertEqual(
				response.json(),
				{
					"bootstrap_id": FLOW_ID,
					"installation_id": installation_id,
					"challenge": "L" * 43,
					"companion_version": __version__,
					"protocol_version": 1,
				},
			)
		finally:
			challenges.discard(FLOW_ID)
			frappe.db.commit()
		self.assertEqual(self.call("GET", f"{SURFACE}.bootstrap_proof?id={FLOW_ID}").status_code, 404)

	def test_hmac_routes_refused_without_signature(self):
		for method, path in (
			("GET", f"{SURFACE}.terminal_status?terminal_uuid=0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"),
			("GET", f"{SURFACE}.user_capabilities?user=Administrator"),
			("POST", f"{SURFACE}.enrollment_verify?token={'t' * 43}"),
			("POST", f"{SURFACE}.action?action_id=task.create"),
		):
			with self.subTest(path=path):
				response = self.call(method, path, json={"consume": True})
				self.assertEqual(response.status_code, 401, response.text[:200])
				self.assertEqual(response.json()["error"]["code"], "tenant_signature_missing")

	def test_http_method_enforced(self):
		self.assertEqual(self.call("POST", f"{SURFACE}.bootstrap_proof?id={FLOW_ID}").status_code, 403)
		self.assertEqual(self.call("GET", f"{SURFACE}.enrollment_verify?token=x").status_code, 403)

	def test_admin_api_refused_to_guest(self):
		for name in ("get_status", "bootstrap", "generate_qr", "repair"):
			with self.subTest(name=name):
				response = self.call("POST" if name != "get_status" else "GET", f"/api/method/speakdo_erpnext.api.admin.{name}")
				self.assertEqual(response.status_code, 403, response.text[:200])

	def test_signed_raw_target_through_gunicorn(self):
		"""The real stack hands the request target over byte for byte (order,
		percent-encoding, empty and repeated parameters): signing it verbatim
		passes, signing the path alone is refused."""
		tenant, secret = "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e", "live-test-secret-" + "x" * 40
		previous = {"tenant_uuid": store.get("tenant_uuid"), "secret": store.get_hmac_secret()}
		store.update(tenant_uuid=tenant)
		store.store_hmac_secret(secret)
		frappe.db.commit()
		try:
			path = f"{SURFACE}.user_capabilities"
			target = f"{path}?z=&user=Administrator&a=%40b&user=ignored"
			ok = self.call("GET", target, headers={**self.headers, **reference_headers(secret, "GET", target, tenant=tenant)})
			self.assertEqual(ok.status_code, 200, ok.text[:200])
			self.assertEqual(ok.json()["capabilities"], capabilities_for("Administrator"))
			self.assertEqual(ok.json()["permissions_version"], permissions_version(capabilities_for("Administrator")))
			bare = self.call("GET", target, headers={**self.headers, **reference_headers(secret, "GET", path, tenant=tenant)})
			self.assertEqual((bare.status_code, bare.json()["error"]["code"]), (401, "invalid_tenant_signature"))
		finally:
			store.update(tenant_uuid=previous["tenant_uuid"])
			if previous["secret"]:
				store.store_hmac_secret(previous["secret"])
			else:
				store.clear_hmac_secret()
			frappe.db.commit()


class TestLiveAdminApi(FrappeTestCase):
	"""Admin API through the real stack, as the logged-in admin page calls it."""

	USER = "speakdo.live.admin@example.com"

	def setUp(self):
		try:
			requests.get(SERVER, timeout=2)
		except requests.RequestException:
			raise unittest.SkipTest("local web server not reachable")
		import secrets as _secrets

		from frappe.utils.password import update_password

		if not frappe.db.exists("User", self.USER):
			user = frappe.get_doc({"doctype": "User", "email": self.USER, "first_name": "Live", "send_welcome_email": 0})
			user.insert(ignore_permissions=True)
			user.add_roles("System Manager")
		# Browser-like session login: no API key on this user (an API key not
		# created by SpeakDo would rightly be a credential conflict).
		password = _secrets.token_urlsafe(24)
		update_password(self.USER, password)
		frappe.db.commit()
		site = {"Host": frappe.local.site, "X-Frappe-Site-Name": frappe.local.site}
		login = requests.post(SERVER + "/api/method/login", json={"usr": self.USER, "pwd": password}, headers=site, timeout=15)
		self.assertEqual(login.status_code, 200, login.text[:200])
		self.headers = {**site, "Cookie": f"sid={login.cookies.get('sid')}"}

	def tearDown(self):
		frappe.db.delete("SpeakDo Enrollment Token", {"erp_user": self.USER})
		frappe.delete_doc("User", self.USER, force=True, ignore_permissions=True)
		frappe.db.commit()

	def call(self, method, path, **kwargs):
		return requests.request(method, SERVER + path, headers=self.headers, timeout=15, **kwargs)

	def test_old_page_call_fails_and_admin_call_succeeds(self):
		old = self.call("GET", "/api/method/speakdo_erpnext.api.companion.get_status")
		self.assertEqual(old.status_code, 417)  # the reported bug: no such attribute on the machine surface
		new = self.call("GET", "/api/method/speakdo_erpnext.api.admin.get_status")
		self.assertEqual(new.status_code, 200, new.text[:200])
		status = new.json()["message"]
		self.assertEqual(status["erp_type"], "erpnext")
		self.assertIn("actions", status)
		self.assertNotIn("hmac_secret", new.text)

	def test_generate_qr_through_admin_api(self):
		tenant, secret = "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e", "live-qr-secret-" + "q" * 40
		previous = {f: store.get(f) for f in ("tenant_uuid", "enrollment_status", "app_url")}
		had_secret = store.get_hmac_secret()
		store.update(tenant_uuid=tenant, enrollment_status="enrolled", app_url="https://app.test")
		store.store_hmac_secret(secret)
		frappe.db.commit()
		try:
			response = self.call("POST", "/api/method/speakdo_erpnext.api.admin.generate_qr")
			self.assertEqual(response.status_code, 200, response.text[:200])
			result = response.json()["message"]
			self.assertTrue(result["ok"], result)
			self.assertTrue(result["qr_image"].startswith("data:image/png;base64,"))
			self.assertEqual(result["erp_user"], self.USER)
			self.assertNotIn(secret, response.text)
		finally:
			store.update(**previous)
			if had_secret:
				store.store_hmac_secret(had_secret)
			else:
				store.clear_hmac_secret()
			frappe.db.commit()

	def test_admin_api_refused_without_login(self):
		response = requests.get(
			SERVER + "/api/method/speakdo_erpnext.api.admin.get_status",
			headers={"Host": frappe.local.site, "X-Frappe-Site-Name": frappe.local.site},
			timeout=10,
		)
		self.assertEqual(response.status_code, 403)


class TestLiveErpCredential(FrappeTestCase):
	"""The issued erpnext_api_token authenticates, through the real stack, as the
	enrolled user only, and stops working once revoked."""

	USER = "speakdo.live.tech@example.com"

	def setUp(self):
		try:
			requests.get(SERVER, timeout=2)
		except requests.RequestException:
			raise unittest.SkipTest("local web server not reachable")
		if not frappe.db.exists("User", self.USER):
			user = frappe.get_doc({"doctype": "User", "email": self.USER, "first_name": "Tech", "send_welcome_email": 0})
			user.insert(ignore_permissions=True)
			user.add_roles("Projects User")
		frappe.db.set_value("User", self.USER, "api_key", None, update_modified=False)
		frappe.db.delete("__Auth", {"doctype": "User", "name": self.USER, "fieldname": "api_secret"})
		frappe.db.delete("SpeakDo ERP Credential", {"name": self.USER})
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete("SpeakDo ERP Credential", {"name": self.USER})
		frappe.delete_doc("User", self.USER, force=True, ignore_permissions=True)
		frappe.db.commit()

	def whoami(self, credential):
		return requests.get(
			SERVER + "/api/method/frappe.auth.get_logged_user",
			headers={"Host": frappe.local.site, "X-Frappe-Site-Name": frappe.local.site, "Authorization": f"token {credential}"},
			timeout=15,
		)

	def test_issued_credential_is_the_user_and_is_revocable(self):
		from speakdo_erpnext.domain import erp_credentials

		credential = erp_credentials.issue_for_terminal(self.USER)
		frappe.db.commit()
		token = f"{credential.api_key}:{credential.api_secret}"
		response = self.whoami(token)
		self.assertEqual((response.status_code, response.json()["message"]), (200, self.USER))
		self.assertNotEqual(self.whoami(f"{credential.api_key}:wrong").status_code, 200)
		# the user's own permissions apply: a Projects User cannot create a Customer
		created = requests.post(
			SERVER + "/api/resource/Customer",
			json={"customer_name": "SPEAKDO-TEST no privilege escalation"},
			headers={"Host": frappe.local.site, "X-Frappe-Site-Name": frappe.local.site, "Authorization": f"token {token}"},
			timeout=15,
		)
		self.assertEqual(created.status_code, 403, created.text[:200])
		self.assertFalse(frappe.db.exists("Customer", {"customer_name": "SPEAKDO-TEST no privilege escalation"}))
		erp_credentials.revoke(self.USER, "test")
		frappe.db.commit()
		self.assertNotEqual(self.whoami(token).status_code, 200)
