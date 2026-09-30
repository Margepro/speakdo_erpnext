frappe.ui.form.on("SpeakDo Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Ouvrir l'administration SpeakDo"), () => {
			frappe.set_route("speakdo-admin");
		});
		const attached = !!frm.doc.tenant_uuid;
		frm.set_df_property("middleware_url", "read_only", attached ? 1 : 0);
	},
});
