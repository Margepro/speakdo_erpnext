app_name = "speakdo_erpnext"
app_title = "SpeakDo"
app_publisher = "SpeakDo"
app_description = "SpeakDo companion for ERPNext (attachment, enrolment, capabilities, profiles, credentials, terminals)"
app_email = "contact@speakdo.fr"
app_license = "GPL-3.0-or-later"
app_logo_url = "/assets/speakdo_erpnext/images/speakdo.svg"

# Apps screen (/apps) entry
add_to_apps_screen = [
	{
		"name": "speakdo_erpnext",
		"logo": "/assets/speakdo_erpnext/images/speakdo.svg",
		"title": "SpeakDo",
		"route": "/app/speakdo",
		"has_permission": "speakdo_erpnext.permissions.has_app_permission",
	}
]

before_install = "speakdo_erpnext.install.before_install"
after_install = "speakdo_erpnext.install.after_install"
after_migrate = "speakdo_erpnext.install.after_migrate"

# The surface called by the SpeakDo middleware is made of whitelisted methods:
# speakdo_erpnext.api.companion (companion_base_url = /api/method/speakdo_erpnext.api.companion).

scheduler_events = {
	"hourly": ["speakdo_erpnext.services.maintenance.purge_expired"],
}

# This companion deliberately exposes no business endpoint and no document
# event hooks: SpeakDo actions and ERPNext mappings live in the middleware.
