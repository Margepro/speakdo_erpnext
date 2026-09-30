"""Single source of version and publication files (docs/RELEASE.md)."""

import os
import re

import frappe
import tomllib
from frappe.tests.utils import FrappeTestCase

import speakdo_erpnext
from speakdo_erpnext import __version__
from speakdo_erpnext.constants import COMPANION_VERSION, USER_AGENT

PACKAGE_DIR = os.path.dirname(os.path.abspath(speakdo_erpnext.__file__))
REPO_ROOT = os.path.dirname(PACKAGE_DIR)
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def read(*parts):
	with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as f:
		return f.read()


class TestVersion(FrappeTestCase):
	def test_canonical_version_is_semver(self):
		self.assertRegex(__version__, SEMVER)

	def test_pyproject_reads_the_version_from_the_package(self):
		project = tomllib.loads(read("pyproject.toml"))["project"]
		self.assertIn("version", project.get("dynamic", []))
		self.assertNotIn("version", project)  # no second, static version

	def test_no_other_file_declares_a_version(self):
		for name in ("setup.py", "setup.cfg", "package.json"):
			self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, name)), name)
		hooks = read("speakdo_erpnext", "hooks.py")
		self.assertNotRegex(hooks, r"(?m)^\s*app_version\s*=")
		literal = re.compile(r"""__version__\s*=\s*["']""")
		declaring = []
		for root, _dirs, files in os.walk(PACKAGE_DIR):
			if "__pycache__" in root:
				continue
			for name in files:
				if name.endswith(".py"):
					with open(os.path.join(root, name), encoding="utf-8") as f:
						if literal.search(f.read()):
							declaring.append(os.path.relpath(os.path.join(root, name), REPO_ROOT))
		self.assertEqual(declaring, ["speakdo_erpnext/__init__.py"])

	def test_every_surface_derives_from_the_source(self):
		from speakdo_erpnext.adapters.middleware_legacy import proof_body
		from speakdo_erpnext.constants import FlowType
		from speakdo_erpnext.services import diagnostics
		from speakdo_erpnext.services.enrollment import get_versions

		self.assertIs(COMPANION_VERSION, __version__)
		self.assertTrue(USER_AGENT.endswith("/" + __version__))
		self.assertEqual(get_versions()["companion"], __version__)
		self.assertEqual(diagnostics.get_status()["companion_version"], __version__)
		proof = proof_body(FlowType.BOOTSTRAP, {"flow_id": "x", "installation_id": "y", "challenge": "z"})
		self.assertEqual(proof["companion_version"], __version__)
		# stored copy is rewritten on install/migrate from the same source
		from speakdo_erpnext.install import after_install

		after_install()
		self.assertEqual(frappe.db.get_single_value("SpeakDo Settings", "companion_version"), __version__)

	def test_admin_page_does_not_hardcode_the_version(self):
		script = read("speakdo_erpnext", "speakdo", "page", "speakdo_admin", "speakdo_admin.js")
		self.assertIn("s.companion_version", script)
		self.assertNotIn(__version__, script)

	def test_changelog_documents_the_current_version(self):
		changelog = read("CHANGELOG.md")
		first = re.search(r"(?m)^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", changelog)
		self.assertIsNotNone(first)
		self.assertEqual(first.group(1), __version__)


class TestPublicationFiles(FrappeTestCase):
	def test_repository_files(self):
		for name in ("README.md", "CHANGELOG.md", "LICENSE", "pyproject.toml", ".gitignore", "docs/RELEASE.md"):
			self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, name)), name)

	def test_pyproject_metadata_points_to_existing_files(self):
		project = tomllib.loads(read("pyproject.toml"))["project"]
		self.assertEqual(project["name"], "speakdo_erpnext")
		self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, project["readme"])))
		for license_file in project["license-files"]:
			self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, license_file)), license_file)

	def test_license_is_gpl3_or_later_everywhere(self):
		spdx = "GPL-3.0-or-later"
		license_text = read("LICENSE")
		self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
		self.assertIn("Version 3, 29 June 2007", license_text)
		self.assertEqual(tomllib.loads(read("pyproject.toml"))["project"]["license"], spdx)
		hooks = read("speakdo_erpnext", "hooks.py")
		self.assertEqual(re.search(r'app_license\s*=\s*"([^"]+)"', hooks).group(1), spdx)
		for doc in ("README.md", "CHANGELOG.md"):
			self.assertIn(spdx, read(doc), doc)
		self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, "license.txt")))

	def test_no_mit_license_left(self):
		pattern = re.compile(r"\bMIT\b|app_license\s*=\s*\"mit\"", re.IGNORECASE)
		this_file = os.path.abspath(__file__)
		offenders = []
		for root, dirs, files in os.walk(REPO_ROOT):
			dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
			for name in files:
				path = os.path.join(root, name)
				if name == "LICENSE" or os.path.abspath(path) == this_file:
					continue
				if name.endswith((".py", ".js", ".json", ".md", ".txt", ".toml", ".css")):
					with open(path, encoding="utf-8", errors="ignore") as f:
						if pattern.search(f.read()):
							offenders.append(os.path.relpath(path, REPO_ROOT))
		self.assertEqual(offenders, [])

	def test_internal_prompt_is_not_published(self):
		self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, "docs", "MIDDLEWARE_GENERALIZATION_PROMPT.md")))
		for root, dirs, files in os.walk(REPO_ROOT):
			dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
			for name in files:
				if name.endswith((".md", ".py", ".toml", ".json", ".js")) and name != os.path.basename(__file__):
					with open(os.path.join(root, name), encoding="utf-8", errors="ignore") as f:
						self.assertNotIn("MIDDLEWARE_GENERALIZATION_PROMPT", f.read(), name)

	def test_readme_is_bilingual_and_honest(self):
		readme = read("README.md")
		self.assertIn("# 🇫🇷 Français", readme)
		self.assertIn("# 🇬🇧 English", readme)
		self.assertNotIn("full ERPNext support", readme)
		for private in ("labs.margepro", "92.222.", "erpnext-credentials"):
			self.assertNotIn(private, readme)

	def test_gitignore_keeps_frappe_files(self):
		ignored = [line.strip() for line in read(".gitignore").splitlines() if line.strip() and not line.startswith("#")]
		for needed in ("*.json", "*.js", "*.css", "patches.txt", "modules.txt", "hooks.py"):
			self.assertNotIn(needed, ignored)

	def test_no_private_lab_data_in_published_files(self):
		pattern = re.compile(r"labs\.margepro-sasu|92\.222\.234\.|open-techno\.fr")
		offenders = []
		for root, dirs, files in os.walk(REPO_ROOT):
			dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
			for name in files:
				if name.endswith((".py", ".js", ".json", ".md", ".txt", ".toml", ".css")):
					path = os.path.join(root, name)
					with open(path, encoding="utf-8", errors="ignore") as f:
						if pattern.search(f.read()):
							offenders.append(os.path.relpath(path, REPO_ROOT))
		self.assertEqual(offenders, [])
