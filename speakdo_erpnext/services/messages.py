"""User facing messages for companion (generic) error codes."""

MESSAGES = {
	# bootstrap
	"tenant_already_enrolled": "Cette installation est déjà enrôlée auprès du middleware. Utilisez « Réparer » pour obtenir un nouveau secret.",
	"installation_url_mismatch": "Le middleware connaît cette installation à une autre URL. Une relocation est nécessaire.",
	"legacy_candidate_conflict": "Une autre installation est déjà enregistrée pour cette URL : intervention SpeakDo nécessaire.",
	"invalid_installation_id": "Identifiant d'installation refusé par le middleware.",
	"invalid_erp_url": "URL de l'instance refusée par le middleware (localhost, IP privée, DNS, schéma…).",
	"bootstrap_not_found": "Défi d'enrôlement inconnu ou déjà utilisé.",
	"bootstrap_expired": "Défi d'enrôlement expiré : relancez l'enrôlement.",
	"bootstrap_verification_failed": "Le middleware n'a pas pu vérifier la preuve publiée par cette instance (URL injoignable depuis le middleware, préfixe compagnon, proxy…).",
	"legacy_migration_failed": "Échec technique du rattachement à l'enregistrement existant.",
	"tenant_conflict": "Conflit à la création du tenant côté middleware.",
	"legacy_migration_requires_repair": "Instance rattachée à un enregistrement existant sans nouveau secret : lancez « Réparer ».",
	# repair
	"repair_not_found": "Installation inconnue du middleware : un enrôlement est nécessaire, pas une réparation.",
	"repair_rate_limited": "Trop de réparations récentes (5 par heure) : réessayez plus tard.",
	"repair_conflict": "Réparation refusée par le middleware (suspension ou conflit).",
	"repair_target_unavailable": "Le middleware n'a pas d'URL enregistrée pour cette installation.",
	"repair_expired": "Défi de réparation expiré : relancez la réparation.",
	"repair_already_consumed": "Défi de réparation déjà utilisé : relancez la réparation.",
	"repair_verification_failed": "Le middleware n'a pas pu vérifier la preuve de réparation publiée par cette instance.",
	# relocation / reset
	"feature_unavailable": "Fonction désactivée sur le middleware SpeakDo (feature gate).",
	"relocation_rate_limited": "Trop de relocations récentes : réessayez plus tard.",
	"installation_not_found": "Installation inconnue du middleware.",
	"relocation_not_found": "Relocation inconnue.",
	"relocation_already_finalized": "Relocation déjà finalisée.",
	"relocation_expired": "Défi de relocation expiré.",
	"relocation_not_pending": "Relocation non en attente.",
	"relocation_proof_failed": "Le middleware n'a pas pu vérifier la preuve publiée sur la nouvelle URL.",
	"relocation_conflict": "L'URL enregistrée a changé pendant la relocation.",
	"installation_mismatch": "L'installation ne correspond pas au tenant signataire.",
	"invalid_tenant_signature": "Signature HMAC refusée par le middleware : le secret local n'est plus valide (réparation nécessaire).",
	# local
	"already_enrolled": "Cette instance est déjà enrôlée.",
	"not_enrolled": "Instance non enrôlée.",
	"tenant_missing": "Aucun tenant SpeakDo local.",
	"no_relocation_pending": "L'URL de l'instance n'a pas changé depuis la dernière déclaration.",
	"installation_id_invalid": "Identifiant d'installation local invalide.",
	"middleware_change_forbidden": "Impossible de changer de middleware sur une instance enrôlée.",
	"base_path_locked": "Le chemin de la surface compagnon ne peut pas changer sur une instance rattachée.",
	"erp_credential_conflict": "Cet utilisateur ERPNext possède déjà une clé API que SpeakDo n'a pas créée : SpeakDo ne la réutilise ni ne la remplace. Supprimez-la (ou utilisez un autre utilisateur) avant d'enrôler un terminal.",
	"profile_unknown": "Ce profil n'existe pas dans le catalogue du middleware SpeakDo.",
	"profiles_unavailable": "Catalogue des profils indisponible sur le middleware SpeakDo.",
	"user_not_found": "Utilisateur ERPNext inconnu.",
	"user_not_enrollable": "Cet utilisateur ERPNext ne peut pas enrôler de terminal (utilisateur désactivé ou non « System User »).",
}


def message_for(error_code, default=None):
	return MESSAGES.get(error_code) or default or "Le middleware SpeakDo a refusé la requête."
