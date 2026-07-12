"""
Marvin — Routage cloud/local partagé (v2.119-2.122).

Centralise les règles de routage Ollama Cloud utilisées à la fois par `agent.py`
(boucle de chat principale) ET `tools.py`/`skills.py` (appels LLM internes aux
outils : document_generate, email_*, text_summarize, upgrade_skill...). Vit dans
un module séparé pour éviter un import circulaire (`agent.py` importe déjà
`tools.py` pour TOOLS_REGISTRY/TOOLS_SPEC — `tools.py` ne peut donc pas importer
`agent.py` en retour).

Doctrine (v2.119-121, non-négociable sauf via `ultra_unrestricted`) :
- Les commandes catastrophiques restent bloquées par `security.py` dans TOUS les
  modes, sans exception — ce module n'y touche jamais.
- Une donnée sensible (email, SSH, mot de passe, facture...) ne part au cloud
  QUE si `ultra_unrestricted` est explicitement activé par l'utilisateur.
"""
import unicodedata

import database as db


def strip_accents(s: str) -> str:
    """« caractéristiques » → « caracteristiques » — le français tapé vite/sans
    clavier FR perd souvent les accents."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


SENSITIVE_KEYWORDS = (
    "email", "e-mail", "mail", "gmail", "outlook", "courriel",
    "ssh", "connexion ssh", "serveur distant",
    "mot de passe", "mots de passe", "password", "identifiant", "identifiants",
    "credential", "credentials", "cle api", "clé api", "api key",
    "cle privee", "clé privée", "private key", "token", "jeton", "secret",
    "facture", "devis", "client",
)
SENSITIVE_TOOL_PREFIXES = ("email_", "ssh_", "billing_", "credential_")

# v2.164 — outils "métadonnées uniquement" explicitement exemptés du repli local
# mid-boucle (agent.py) : leur nom commence par un préfixe sensible mais ils ne
# renvoient JAMAIS de contenu réel (mot de passe, corps d'email, sortie de commande
# distante...) — juste une liste de ce qui est configuré. Carve-out volontairement
# étroit et nommé outil par outil (jamais un préfixe entier) pour ne pas affaiblir
# la garde ailleurs. Signalé par l'utilisateur : "ssh_list" déclenchait le repli
# local ("🔒 Repli local (donnée sensible détectée)") sur une simple demande de
# script, dégradant la qualité de réponse sans aucune raison de confidentialité
# réelle (has_password/has_key restent des booléens, jamais la valeur).
SENSITIVE_TOOL_EXEMPTIONS = frozenset({
    "ssh_list",        # connexions enregistrées : host/port/username, has_password/has_key en booléen
    "email_accounts",  # comptes configurés : adresse seulement, jamais un contenu de message
})


def is_sensitive_text(text: str) -> bool:
    """True si le texte (prompt d'un appel LLM interne, message utilisateur...)
    contient un mot-clé de donnée sensible."""
    norm = strip_accents((text or "").lower())
    return any(strip_accents(k) in norm for k in SENSITIVE_KEYWORDS)


def is_sensitive_tool(name: str) -> bool:
    n = name or ""
    if n in SENSITIVE_TOOL_EXEMPTIONS:
        return False
    return any(n.startswith(p) for p in SENSITIVE_TOOL_PREFIXES)


def is_cloud_model(name: str) -> bool:
    # v2.141 — certains modèles cloud installés (ex. `qwen3-coder:480b-cloud`,
    # `gemma4:31b-cloud`) suffixent le TAG par `-cloud`, pas `:cloud` (seuls les
    # modèles sans taille dans le tag, ex. `glm-5.2:cloud`, utilisent `:cloud`).
    # L'ancien test ratait silencieusement ces modèles → la protection mid-boucle
    # (bascule vers le local si un outil sensible est appelé) ne les aurait jamais
    # reconnus comme "cloud", laissant passer une fuite potentielle. Trouvé en
    # implémentant le routage par tâche (v2.141), qui introduit justement
    # `qwen3-coder:480b-cloud` comme override réel.
    n = name or ""
    return n.endswith(":cloud") or n.endswith("-cloud")


def get_cloud_config() -> tuple[bool, dict]:
    """cloud_enabled (bool, opt-in) + cloud_overrides ({profil: modèle_cloud})."""
    try:
        enabled = bool(db.get_setting("cloud_enabled"))
    except Exception:
        enabled = False
    try:
        overrides = db.get_setting("cloud_overrides") or {}
        if not isinstance(overrides, dict):
            overrides = {}
    except Exception:
        overrides = {}
    return enabled, overrides


# v2.141 — Routage par TÂCHE, plus fin que le routage par PROFIL ci-dessus. Demandé
# explicitement (« privilégier le cloud pour la puissance ») après avoir trouvé que
# `cloud_overrides` pointait les 3 profils vers le MÊME modèle cloud, alors que les
# benchmarks 2026 (LiveBench Agentic, tool-calling) montrent des écarts nets par
# spécialité : GLM-5.2 domine l'agentique/tool-calling (90,6% de succès), qwen3-coder
# domine le code long. Un signal de tâche détecté (ex. "code") prend le pas sur
# l'override de PROFIL, mais seulement si le cloud est activé et la requête non
# sensible — mêmes garanties que le reste de ce module, jamais contournées.
_CODE_TASK_KEYWORDS = (
    "script", "installation", "installer", "procedure d'installation",
    "commande powershell", "commande bash", "ligne de commande", ".ps1", ".sh",
    "code source", "programme informatique", "deploiement", "configuration serveur",
    "dockerfile", "docker compose", "automatiser", "automatisation",
)


def detect_task(text: str) -> str | None:
    """Détecte un type de tâche pour un routage cloud plus fin que par profil.
    Best-effort, conservateur : retourne None (pas de routage spécial) dès que le
    signal n'est pas clair — l'appelant garde alors son modèle par défaut (profil)."""
    norm = strip_accents((text or "").lower())
    if any(strip_accents(k) in norm for k in _CODE_TASK_KEYWORDS):
        return "code"
    return None


def get_task_overrides() -> dict:
    """cloud_task_overrides ({tâche: modèle_cloud}) — DÉPRÉCIÉ (v2.179), conservé pour
    compatibilité mais plus consulté par resolve_model() : un modèle cloud figé en dur dans
    un réglage devient périmé dès qu'Ollama Cloud retire/renomme ce modèle (constaté en réel :
    gemini-3-flash-preview et qwen3-coder:480b retirés ~2 jours après avoir été recommandés
    dans cette session même). `pick_best_cloud_model()` ci-dessous résout désormais le
    "meilleur modèle pour une tâche" EN DIRECT sur la liste réellement installée, par FAMILLE
    (préfixe) plutôt que par tag exact — résilient à la rotation des modèles cloud."""
    try:
        overrides = db.get_setting("cloud_task_overrides") or {}
        return overrides if isinstance(overrides, dict) else {}
    except Exception:
        return {}


# v2.179 — familles de modèles cloud connues par préfixe (jamais un tag EXACT, qui expire) :
# ordre de préférence général établi par les benchmarks 2026 (agentique/tool-calling) déjà
# documentés (v2.141), et l'ordre "vision" établi par un benchmark RÉEL mené dans cette
# session (llava-phi3 local hallucine ; gemini/gemma/qwen3.5 ont extrait 4 détails exacts
# d'une image de test en ~6s chacun — voir mémoire screenshots-documentation-v2175).
_GENERAL_PREFERENCE_FAMILIES = ("deepseek", "glm", "kimi", "nemotron")
_VISION_CAPABLE_FAMILIES = ("gemini", "gemma", "qwen3.5")
_CODE_SPECIALIST_MARKERS = ("coder",)


def list_installed_cloud_models() -> list[str]:
    """Modèles cloud REELLEMENT installés sur cette machine, interrogés en direct (jamais
    une liste figée en dur — c'est justement le problème que ça évite)."""
    try:
        import httpx
        from config import OLLAMA_URL
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        return [n for n in names if is_cloud_model(n)]
    except Exception:
        return []


def pick_best_cloud_model(need: str = "general", exclude: frozenset = frozenset()) -> str | None:
    """Choisit le meilleur modèle cloud INSTALLÉ pour un besoin donné (general/code/vision),
    par famille (préfixe/marqueur dans le nom), jamais par tag exact figé en dur — résilient
    à la rotation/au retrait des modèles cloud. Retourne None si aucun candidat installé pour
    ce besoin (l'appelant décide alors du repli, ex. local pour la vision)."""
    installed = [m for m in list_installed_cloud_models() if m not in exclude]
    if not installed:
        return None
    if need == "code":
        coder = next((m for m in installed if any(k in m.lower() for k in _CODE_SPECIALIST_MARKERS)), None)
        if coder:
            return coder
        need = "general"  # pas de spécialiste installé -> repli propre sur le généraliste
    if need == "vision":
        for fam in _VISION_CAPABLE_FAMILIES:
            m = next((m for m in installed if m.lower().startswith(fam)), None)
            if m:
                return m
        return None
    for fam in _GENERAL_PREFERENCE_FAMILIES:
        m = next((m for m in installed if m.lower().startswith(fam)), None)
        if m:
            return m
    return installed[0]


def list_vision_candidates() -> list[str]:
    """TOUS les modèles cloud installés réputés capables de vision (pas seulement le
    meilleur) — dans l'ordre de préférence des familles, pour permettre à l'appelant
    d'essayer le suivant si le premier échoue à l'exécution (réseau, quota...)."""
    installed = list_installed_cloud_models()
    out = []
    for fam in _VISION_CAPABLE_FAMILIES:
        out.extend(m for m in installed if m.lower().startswith(fam) and m not in out)
    return out


def is_local_only_lockdown() -> bool:
    """Mode « Hyper sécurisé » : coupe-circuit total, prioritaire sur tout le reste."""
    try:
        return bool(db.get_setting("local_only_lockdown"))
    except Exception:
        return False


def is_ultra_unrestricted() -> bool:
    """Mode « Ultra débridé » : désactive UNIQUEMENT la détection de sensibilité,
    jamais le garde-fou système de security.py."""
    try:
        return bool(db.get_setting("ultra_unrestricted"))
    except Exception:
        return False


def resolve_model(requested_model: str | None, profile: str = "agent",
                   local_fallback: str | None = None, text_for_sensitivity: str = "",
                   has_images: bool = False) -> str:
    """v2.122 — Décide quel modèle utiliser pour un appel LLM INTERNE à un outil
    (document_generate, email_*, text_summarize, upgrade_skill...), en appliquant
    les mêmes règles que la boucle de chat principale (agent.py::run_agent) :
    - Hyper sécurisé : jamais de cloud, quel que soit le reste.
    - Un appel avec IMAGES (OCR/vision) reste TOUJOURS local — pas de garantie que
      les modèles cloud installés supportent le multimodal, et ce type de contenu
      (scans de documents, captures d'écran) est justement le plus sensible.
    - Si l'appelant a déjà demandé un modèle LOCAL précis : respecté tel quel.
    - Sinon, un modèle cloud (demandé explicitement OU choisi automatiquement via
      cloud_overrides) n'est utilisé que si Ultra débridé est actif OU si le texte
      ne contient aucun mot-clé sensible.
    """
    from config import MODEL_PROFILES, DEFAULT_MODEL
    fallback = local_fallback or MODEL_PROFILES.get(profile, {}).get("model") or DEFAULT_MODEL

    if has_images:
        return requested_model if (requested_model and not is_cloud_model(requested_model)) else fallback

    lockdown = is_local_only_lockdown()
    if lockdown:
        return requested_model if (requested_model and not is_cloud_model(requested_model)) else fallback

    ultra = is_ultra_unrestricted()
    sensitive = (not ultra) and is_sensitive_text(text_for_sensitivity)

    if requested_model:
        if not is_cloud_model(requested_model):
            return requested_model  # choix local explicite — toujours respecté
        return fallback if sensitive else requested_model

    # Aucun modèle demandé : tenter le cloud auto si configuré pour ce profil/tâche.
    cloud_enabled, overrides = get_cloud_config()
    if cloud_enabled and not sensitive:
        # v2.141/v2.179 — un signal de TÂCHE (ex. "code") prend le pas sur l'override de
        # PROFIL : modèle cloud spécialisé plutôt que le généraliste du profil courant.
        # Résolu EN DIRECT sur la liste installée (pick_best_cloud_model), plus jamais sur un
        # tag figé dans un réglage — un modèle cloud recommandé aujourd'hui peut être retiré
        # par le fournisseur en quelques jours (constaté en réel, v2.179).
        task = detect_task(text_for_sensitivity)
        if task:
            picked = pick_best_cloud_model(task)
            if picked:
                return picked
        if profile in overrides:
            return overrides[profile]
    return fallback
