// SpeakDo companion administration page.
// Talks only to speakdo_erpnext.api.admin; never receives any secret.

const SPEAKDO_API = "speakdo_erpnext.api.admin.";

frappe.pages["speakdo-admin"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("SpeakDo"),
		single_column: true,
	});
	wrapper.speakdo_admin = new SpeakDoAdmin(page);
};

frappe.pages["speakdo-admin"].on_page_show = function (wrapper) {
	wrapper.speakdo_admin && wrapper.speakdo_admin.refresh();
};

const FEATURE_LABELS = {
	unknown: __("non vérifiée"),
	available: __("disponible"),
	unavailable: __("désactivée sur le middleware"),
};

const STATUS_LABELS = {
	enrolled: { label: __("Connecté"), color: "green" },
	not_enrolled: { label: __("Non enrôlé"), color: "gray" },
	repair_required: { label: __("Réparation nécessaire"), color: "orange" },
	error: { label: __("Erreur"), color: "red" },
};

class SpeakDoAdmin {
	constructor(page) {
		this.page = page;
		this.status = null;
		this.$body = $(`<div class="speakdo-admin"></div>`).appendTo(page.main);
		this.page.set_secondary_action(__("Actualiser"), () => this.refresh(), "refresh");
		this.refresh();
	}

	call(method, args, type) {
		return frappe
			.call({ method: SPEAKDO_API + method, args: args || {}, type: type || "POST", freeze: true })
			.then((r) => r.message);
	}

	refresh() {
		return this.call("get_status", {}, "GET").then((status) => {
			this.status = status;
			this.render();
		});
	}

	render() {
		const s = this.status;
		const esc = frappe.utils.escape_html;
		const st = STATUS_LABELS[s.enrollment_status] || STATUS_LABELS.error;
		const shown_error = s.last_error_code && s.enrollment_status !== "enrolled";
		const indicator = shown_error && s.enrollment_status === "not_enrolled" ? STATUS_LABELS.error : st;
		this.page.set_indicator(indicator.label, indicator.color);

		const row = (label, value) =>
			`<div class="sd-label">${esc(label)}</div><div class="sd-value">${
				value ? esc(String(value)) : `<span class="sd-muted">—</span>`
			}</div>`;
		const when = (v) => (v ? frappe.datetime.str_to_user(v) : null);

		this.$body.html(`
			<div class="sd-card">
				<h4>${__("Rattachement de l'instance")}</h4>
				<p class="sd-muted">${__("État de cette instance ERPNext auprès du middleware SpeakDo (commun à tous les utilisateurs). L'état de chaque utilisateur est détaillé plus bas.")}</p>
				<div class="sd-grid">
					${row(__("État"), indicator.label)}
					${row(__("Tenant UUID"), s.tenant_uuid)}
					${row(__("Installation ID"), s.installation_id)}
					${row(__("Middleware"), s.middleware_url)}
					${row(__("URL ERPNext"), s.instance_url)}
					${row(__("Surface compagnon (companion_base_url)"), s.companion_base_url)}
					${row(__("Relocation (middleware)"), FEATURE_LABELS[s.relocation_availability])}
					${row(__("Reset (middleware)"), FEATURE_LABELS[s.reset_availability])}
					${row(__("Version ERPNext"), s.versions.erpnext)}
					${row(__("Version Frappe"), s.versions.frappe)}
					${row(__("Version compagnon"), s.companion_version)}
					${row(__("Version protocole"), s.protocol_version)}
					${row(__("Dernier contact réussi"), when(s.last_successful_contact))}
					${s.last_error_code ? row(__("Dernière erreur"), `${s.last_error_code} — ${s.last_error_message || ""}`) : ""}
				</div>
				${
					s.relocation_pending
						? `<div class="alert alert-warning mt-3 mb-0">${__(
								"L'URL de cette instance a changé depuis la dernière déclaration au middleware ({0}).",
								[esc(s.declared_instance_url || "")]
						  )} ${
								s.relocation_availability === "unavailable"
									? `<br>${__("La relocation n'est pas disponible sur le middleware pour ERPNext : l'intégration SpeakDo utilise toujours l'ancienne URL.")}`
									: `<button class="btn btn-xs btn-default sd-relocate">${__("Déclarer la nouvelle URL")}</button>`
						  }</div>`
						: ""
				}
			</div>

			<div class="sd-card">
				<h4>${__("Configuration")}</h4>
				<div class="sd-form"></div>
				<div class="sd-actions mt-2">
					<button class="btn btn-sm btn-primary sd-save-config">${__("Enregistrer la configuration")}</button>
					<button class="btn btn-sm btn-default sd-restore-urls">${__("Restaurer les URLs SpeakDo par défaut")}</button>
				</div>
			</div>

			<div class="sd-card">
				<h4>${__("Actions")}</h4>
				<div class="sd-actions">
					<button class="btn btn-sm btn-primary sd-enroll">${__("Enrôler cette instance")}</button>
					<button class="btn btn-sm btn-default sd-qr-btn">${__("Régénérer le QR d'enrôlement")}</button>
					<button class="btn btn-sm btn-default sd-repair">${__("Réparer")}</button>
					<button class="btn btn-sm btn-danger sd-reset">${__("Réinitialiser")}</button>
				</div>
			</div>

			<div class="sd-card">
				<h4>${__("QR d'enrôlement PWA")}</h4>
				<div class="sd-qr"><span class="sd-muted">${__(
					"Cliquez sur « Régénérer le QR d'enrôlement » pour obtenir un QR temporaire à usage unique."
				)}</span></div>
			</div>

			<div class="sd-card">
				<h4>${__("Utilisateurs SpeakDo")}</h4>
				<p class="sd-muted">${__("Par utilisateur : profils SpeakDo autorisés (catalogue du middleware, 0 à N), capabilities issues de ses permissions ERPNext, état du credential et terminaux. Les profils autorisés s'appliquent à tous les terminaux de l'utilisateur ; le profil actif est choisi dans SpeakDo (session).")}</p>
				<div class="sd-add-user"></div>
				<div class="sd-users"><span class="sd-muted">—</span></div>
			</div>

			<div class="sd-card">
				<h4>${__("Diagnostics")}</h4>
				<div class="sd-diagnostics"><span class="sd-muted">${__("Aucun diagnostic lancé.")}</span></div>
				<div class="sd-actions mt-2">
					<button class="btn btn-sm btn-default sd-diag">${__("Lancer le diagnostic")}</button>
				</div>
			</div>
			<p class="sd-muted sd-version text-right">SpeakDo ERPNext — ${__("version")} ${esc(s.companion_version || "")}</p>
		`);

		this.make_config_form();
		this.bind();
		this.apply_available_actions();
		this.load_users();
	}

	apply_available_actions() {
		const actions = this.status.actions || {};
		const buttons = { bootstrap: ".sd-enroll", generate_qr: ".sd-qr-btn", repair: ".sd-repair", reset: ".sd-reset" };
		Object.entries(buttons).forEach(([action, selector]) => {
			this.$body.find(selector).prop("disabled", actions[action] === false);
		});
	}

	make_config_form() {
		const s = this.status;
		const attached = !!s.tenant_uuid;
		this.config_form = new frappe.ui.FieldGroup({
			parent: this.$body.find(".sd-form"),
			fields: [
				{
					fieldname: "middleware_url",
					fieldtype: "Data",
					label: __("Middleware SpeakDo"),
					default: s.middleware_url,
					read_only: attached ? 1 : 0,
					description: attached ? __("Non modifiable tant que l'instance est rattachée.") : "",
				},
				{ fieldname: "app_url", fieldtype: "Data", label: __("Application SpeakDo"), default: s.app_url },
				{
					fieldname: "instance_url",
					fieldtype: "Data",
					label: __("URL de cette instance ERPNext"),
					default: s.instance_url,
					description: __(
						"Racine réelle de cet ERPNext (sans chemin), joignable depuis le middleware. La surface compagnon en est dérivée."
					),
				},

			],
		});
		this.config_form.make();
	}

	bind() {
		const $b = this.$body;
		$b.find(".sd-save-config").on("click", () => this.save_config());
		$b.find(".sd-restore-urls").on("click", () => this.restore_urls());
		$b.find(".sd-enroll").on("click", () => this.enroll());
		$b.find(".sd-qr-btn").on("click", () => this.generate_qr());
		$b.find(".sd-repair").on("click", () => this.repair());
		$b.find(".sd-reset").on("click", () => this.reset());
		$b.find(".sd-diag").on("click", () => this.diagnostics());
		$b.find(".sd-relocate").on("click", () => this.run_action("relocate", {}, __("Nouvelle URL déclarée.")));
	}

	show_result(result, success_message) {
		if (result && result.ok) {
			frappe.show_alert({ message: success_message, indicator: "green" });
		} else {
			const esc = frappe.utils.escape_html;
			const details = (result && result.details) || {};
			const registered = details.registered_erp_url
				? `<br>${__("URL enregistrée par le middleware")} : <code>${esc(details.registered_erp_url)}</code>`
				: "";
			frappe.msgprint({
				title: __("SpeakDo"),
				indicator: result && result.error_code === "feature_unavailable" ? "orange" : "red",
				message: `${esc((result && result.message) || __("Erreur inconnue."))}${registered}
					<br><small class="text-muted">${esc((result && result.error_code) || "")}</small>`,
			});
		}
		return result;
	}

	run_action(method, args, success_message) {
		return this.call(method, args).then((result) => {
			this.show_result(result, success_message);
			return this.refresh().then(() => result);
		});
	}

	save_config() {
		const values = this.config_form.get_values();
		const args = { app_url: values.app_url || "", instance_url: values.instance_url || "" };
		if (!this.status.tenant_uuid) args.middleware_url = values.middleware_url || "";
		this.run_action("save_configuration", args, __("Configuration enregistrée."));
	}

	restore_urls() {
		frappe.confirm(
			__(
				"Remettre le middleware et l'application SpeakDo sur leurs URLs par défaut ? L'identité, l'URL d'instance et les identifiants ne sont pas modifiés."
			),
			() => this.run_action("restore_default_urls", {}, __("URLs SpeakDo par défaut restaurées."))
		);
	}

	enroll() {
		const esc = frappe.utils.escape_html;
		frappe.confirm(
			`${__("Enrôler cette instance auprès du middleware")} <code>${esc(this.status.middleware_url || "")}</code> ?<br>
			<small class="text-muted">${__(
				"Le middleware viendra chercher une preuve temporaire via"
			)} <code>${esc(this.status.companion_base_url || "")}.bootstrap_proof</code>. ${__(
				"Cette URL doit être joignable depuis Internet."
			)}</small>`,
			() => this.run_action("bootstrap", {}, __("Instance enrôlée."))
		);
	}

	generate_qr() {
		const $qr = this.$body.find(".sd-qr");
		this.call("generate_qr").then((result) => {
			if (!result || !result.ok) {
				$qr.html(
					`<div class="alert alert-warning mb-0">${frappe.utils.escape_html(
						(result && result.message) || __("QR indisponible.")
					)}</div>`
				);
				return;
			}
			const expires = result.expires_at
				? `<span class="sd-muted">${__("Expire")} : ${frappe.utils.escape_html(result.expires_at)}</span>`
				: "";
			$qr.html(`
				<img alt="${__("QR d'enrôlement SpeakDo")}" src="${result.qr_image}">
				<span class="sd-muted">${__("QR temporaire à usage unique, lié à votre utilisateur ERPNext. À scanner depuis l'application SpeakDo.")}</span>
				${expires}
			`);
		});
	}

	repair() {
		frappe.confirm(
			__(
				"Réparer la liaison SpeakDo ? Le middleware vérifie une preuve publiée sur l'URL qu'il a enregistrée, puis remplace le secret technique (l'ancien est immédiatement refusé). L'identité d'installation et l'URL ne changent pas."
			),
			() => this.run_action("repair", {}, __("Connexion réparée."))
		);
	}

	reset() {
		if (this.status.reset_availability === "unavailable") {
			frappe.msgprint(__("La réinitialisation est actuellement désactivée sur le middleware SpeakDo."));
		}
		const d = new frappe.ui.Dialog({
			title: __("Réinitialiser le rattachement SpeakDo"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<div class="alert alert-danger">${__(
						"Le middleware révoque le secret, les terminaux et les sessions. Localement, le secret est supprimé et les terminaux révoqués. Le tenant et l'identité d'installation sont conservés : une réparation sera nécessaire pour se rattacher de nouveau. Si le middleware refuse (fonction désactivée), rien n'est modifié."
					)}</div>`,
				},
				{ fieldname: "confirmation", fieldtype: "Data", label: __("Tapez RESET pour confirmer"), reqd: 1 },
			],
			primary_action_label: __("Réinitialiser"),
			primary_action: (values) => {
				if (values.confirmation !== "RESET") {
					frappe.msgprint(__("Tapez RESET pour confirmer."));
					return;
				}
				d.hide();
				this.run_action("reset", { confirmation: values.confirmation }, __("Rattachement réinitialisé."));
			},
		});
		d.show();
	}

	load_users(include_user) {
		const $u = this.$body.find(".sd-users");
		const esc = frappe.utils.escape_html;
		const credential_labels = {
			absent: __("Absent"),
			managed: __("Géré par SpeakDo"),
			conflict: __("Conflit avec une clé existante"),
			revoked: __("Révoqué"),
		};
		this.make_add_user_field();
		Promise.all([
			frappe.call({ method: SPEAKDO_API + "list_users", args: { include_user: include_user || "" }, type: "GET" }),
			frappe.call({ method: SPEAKDO_API + "get_profiles", type: "GET" }),
		]).then(([users_r, profiles_r]) => {
			const users = users_r.message || [];
			const catalogue = (profiles_r.message && profiles_r.message.ok && profiles_r.message.profiles) || null;
			if (!users.length) {
				$u.html(`<span class="sd-muted">${__("Aucun utilisateur SpeakDo pour l'instant.")}</span>`);
				return;
			}
			const profile_checkboxes = (u) =>
				catalogue
					.map(
						(p) => `<label class="sd-profile-choice" style="display:block;margin:0">
							<input type="checkbox" class="sd-profile" data-user="${esc(u.erp_user_id)}" value="${esc(p.id)}" ${
							(u.allowed_profiles || []).includes(p.id) ? "checked" : ""
						}> ${esc(p.label)} <small class="sd-muted">${esc(p.id)}</small></label>`
					)
					.join("") +
				`<button class="btn btn-xs btn-default mt-1 sd-save-profiles" data-user="${esc(u.erp_user_id)}">${__("Enregistrer les profils")}</button>`;
			$u.html(
				users
					.map((u) => {
						const caps = u.capabilities.length
							? u.capabilities.map((c) => `<code>${esc(c)}</code>`).join(" ")
							: `<span class="sd-muted">${__("Aucune")}</span>`;
						const terminals = u.terminals.length
							? u.terminals
									.map(
										(t) => `<div>${esc(t.label || t.terminal_id)} — ${esc(t.status)}${
											t.status !== "revoked"
												? ` <button class="btn btn-xs btn-default sd-revoke" data-id="${esc(t.terminal_id)}">${__("Révoquer")}</button>`
												: ""
										}</div>`
									)
									.join("")
							: `<span class="sd-muted">${__("Aucun")}</span>`;
						const allowed = u.allowed_profiles || [];
						const profile = catalogue
							? profile_checkboxes(u)
							: `${allowed.length ? allowed.map((p) => `<code>${esc(p)}</code>`).join(" ") : `<span class="sd-muted">${__("Aucun profil affecté")}</span>`} <small class="sd-muted">${__("(catalogue indisponible)")}</small>`;
						return `<div class="sd-card sd-user">
							<h5>${esc(u.display_name)} <small class="sd-muted">${esc(u.erp_user_id)}</small>${u.active ? "" : ` <span class="indicator-pill red">${__("désactivé")}</span>`}</h5>
							<div class="sd-grid">
								<div class="sd-label">${__("Profils SpeakDo autorisés")}</div><div>${profile}</div>
								<div class="sd-label">${__("Capabilities")}</div><div>${caps}</div>
								<div class="sd-label">${__("Credential")}</div><div>${esc(credential_labels[u.credential_state] || u.credential_state)}</div>
								<div class="sd-label">${__("Terminaux actifs")}</div><div>${esc(String(u.active_terminal_count))}</div>
								<div class="sd-label">${__("Terminaux")}</div><div>${terminals}</div>
							</div>
						</div>`;
					})
					.join("")
			);
			$u.find(".sd-save-profiles").on("click", (e) => {
				const user = $(e.currentTarget).attr("data-user");
				const ids = $u
					.find(".sd-profile:checked")
					.filter((_, el) => $(el).attr("data-user") === user)
					.map((_, el) => el.value)
					.get();
				this.call("set_allowed_profiles", { erp_user: user, profile_ids: JSON.stringify(ids) }).then((result) => {
					this.show_result(result, __("Profils autorisés enregistrés."));
					this.load_users(user);
				});
			});
			$u.find(".sd-revoke").on("click", (e) => {
				const id = $(e.currentTarget).attr("data-id");
				frappe.confirm(__("Révoquer ce terminal ?"), () =>
					this.run_action("revoke_terminal", { terminal_id: id }, __("Terminal révoqué."))
				);
			});
		});
	}

	make_add_user_field() {
		const $slot = this.$body.find(".sd-add-user");
		if ($slot.children().length) return;
		const field = frappe.ui.form.make_control({
			parent: $slot,
			df: {
				fieldtype: "Link",
				options: "User",
				fieldname: "sd_user",
				label: __("Afficher / configurer un utilisateur"),
				filters: { user_type: "System User", enabled: 1 },
				change: () => {
					const user = field.get_value();
					if (user) this.load_users(user);
				},
			},
			render_input: true,
		});
	}

	diagnostics() {
		const $d = this.$body.find(".sd-diagnostics");
		this.call("run_diagnostics", {}, "GET").then((r) => {
			const esc = frappe.utils.escape_html;
			const yn = (v) =>
				v === null || v === undefined
					? `<span class="sd-muted">—</span>`
					: v
					? `<span class="indicator-pill green">${__("oui")}</span>`
					: `<span class="indicator-pill red">${__("non")}</span>`;
			const row = (label, html) => `<div class="sd-label">${esc(label)}</div><div>${html}</div>`;
			const txt = (v) => (v ? esc(String(v)) : `<span class="sd-muted">—</span>`);
			$d.html(`<div class="sd-grid">
				${row(__("Middleware joignable"), yn(r.middleware_reachable) + (r.middleware_probe.error_code ? ` <small class="sd-muted">${esc(r.middleware_probe.error_code)}</small>` : ""))}
				${row(__("Tenant présent"), yn(r.tenant_present))}
				${row(__("installation_id (UUID v4) présent"), yn(r.installation_id_present))}
				${row(__("Identifiants techniques présents"), yn(r.credentials_present))}
				${row(__("État d'enrôlement"), txt((STATUS_LABELS[r.enrollment_status] || {}).label || r.enrollment_status))}
				${row(__("Versions"), txt(`Frappe ${r.versions.frappe} · ERPNext ${r.versions.erpnext || "—"} · SpeakDo ${r.versions.companion} · protocole ${r.protocol_version}`))}
				${row(__("Dernier code erreur"), txt(r.last_error_code))}
				${row(__("Dernier contact réussi"), txt(r.last_successful_contact && frappe.datetime.str_to_user(r.last_successful_contact)))}
				${row(__("Surface compagnon"), txt(r.companion_base_url))}
				${row(__("Relocation (middleware)"), txt(FEATURE_LABELS[r.relocation_availability]))}
				${row(__("Reset (middleware)"), txt(FEATURE_LABELS[r.reset_availability]))}
			</div>`);
		});
	}
}
