// "Mon SpeakDo": personal view of the logged-in ERPNext user.
// Talks only to speakdo_erpnext.api.me (scoped to the session user server side);
// never receives any secret.

const SPEAKDO_ME_API = "speakdo_erpnext.api.me.";

frappe.pages["speakdo-me"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Mon SpeakDo"), single_column: true });
	wrapper.speakdo_me = new SpeakDoMe(page);
};

frappe.pages["speakdo-me"].on_page_show = function (wrapper) {
	wrapper.speakdo_me && wrapper.speakdo_me.refresh();
};

const SPEAKDO_CREDENTIAL_LABELS = {
	absent: __("Absent (créé au premier enrôlement)"),
	managed: __("Géré par SpeakDo"),
	conflict: __("Conflit avec une clé API existante"),
	revoked: __("Révoqué"),
};

class SpeakDoMe {
	constructor(page) {
		this.page = page;
		this.$body = $(`<div class="speakdo-me"></div>`).appendTo(page.main);
		this.page.set_secondary_action(__("Actualiser"), () => this.refresh(), "refresh");
		this.refresh();
	}

	call(method, args, type) {
		return frappe
			.call({ method: SPEAKDO_ME_API + method, args: args || {}, type: type || "POST", freeze: true })
			.then((r) => r.message);
	}

	refresh() {
		return this.call("get_my_speakdo", {}, "GET").then((state) => {
			this.state = state;
			this.render();
		});
	}

	render() {
		const s = this.state;
		const esc = frappe.utils.escape_html;
		const row = (label, html) => `<div class="sd-label">${esc(label)}</div><div class="sd-value">${html}</div>`;
		const txt = (v) => (v ? esc(String(v)) : `<span class="sd-muted">—</span>`);
		this.page.set_indicator(
			s.enrolled ? __("Terminal enrôlé") : __("Aucun terminal"),
			s.enrolled ? "green" : "gray"
		);
		const caps = s.capabilities.length
			? s.capabilities.map((c) => `<code>${esc(c)}</code>`).join(" ")
			: `<span class="sd-muted">${__("Aucune")}</span>`;
		const terminals = s.terminals.length
			? `<table class="table table-sm"><thead><tr><th>${__("Libellé")}</th><th>${__("Statut")}</th><th>${__(
					"Enrôlé le"
			  )}</th><th></th></tr></thead><tbody>${s.terminals
					.map(
						(t) => `<tr><td>${esc(t.label || "")}</td><td>${esc(t.status)}</td>
						<td>${esc(t.enrolled_at ? frappe.datetime.str_to_user(t.enrolled_at) : "")}</td>
						<td>${
							t.status !== "revoked"
								? `<button class="btn btn-xs btn-default sd-revoke" data-id="${esc(t.terminal_id)}">${__("Révoquer")}</button>`
								: ""
						}</td></tr>`
					)
					.join("")}</tbody></table>`
			: `<span class="sd-muted">${__("Aucun terminal.")}</span>`;

		this.$body.html(`
			<div class="sd-card">
				<h4>${esc(s.display_name)} <small class="sd-muted">${esc(s.erp_user_id)}</small></h4>
				<div class="sd-grid">
					${row(
						__("Mes profils SpeakDo"),
						s.allowed_profiles.length
							? s.allowed_profiles.map((p) => `<div>• ${esc(s.allowed_profile_labels[p] || p)} <small class="sd-muted">${esc(p)}</small></div>`).join("")
							: `<span class="sd-muted">${__("Aucun profil affecté")}</span>`
					)}
					${row(__("Profil actif"), `<span class="sd-muted">${__("géré par la session SpeakDo")}</span>`)}
					${row(__("Capabilities"), caps)}
					${row(__("Credential ERPNext"), txt(SPEAKDO_CREDENTIAL_LABELS[s.credential_state] || s.credential_state))}
					${row(__("Terminaux actifs"), txt(String(s.active_terminal_count)))}
				</div>
			</div>
			<div class="sd-card">
				<h4>${__("Mes terminaux")}</h4>
				<div class="sd-terminals">${terminals}</div>
				<div class="sd-actions mt-2">
					<button class="btn btn-sm btn-primary sd-qr-btn" ${s.can_enroll ? "" : "disabled"}>${__(
						"Générer mon QR d'enrôlement"
					)}</button>
				</div>
				<div class="sd-qr mt-2"></div>
			</div>
		`);
		this.$body.find(".sd-qr-btn").on("click", () => this.generate_qr());
		this.$body.find(".sd-revoke").on("click", (e) => {
			const id = $(e.currentTarget).attr("data-id");
			frappe.confirm(__("Révoquer ce terminal ?"), () =>
				this.call("revoke_my_terminal", { terminal_id: id }).then(() => this.refresh())
			);
		});
	}

	generate_qr() {
		const $qr = this.$body.find(".sd-qr");
		const esc = frappe.utils.escape_html;
		this.call("generate_my_qr").then((result) => {
			if (!result || !result.ok) {
				$qr.html(`<div class="alert alert-warning mb-0">${esc((result && result.message) || __("QR indisponible."))}</div>`);
				return;
			}
			$qr.html(`
				<img alt="${__("QR d'enrôlement SpeakDo")}" src="${result.qr_image}">
				<span class="sd-muted">${__("QR temporaire à usage unique, lié à votre utilisateur. À scanner depuis l'application SpeakDo.")}</span>
				<span class="sd-muted">${__("Expire")} : ${esc(result.expires_at || "")}</span>
			`);
		});
	}
}
