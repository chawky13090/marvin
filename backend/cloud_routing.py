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
    n = (name or "").lower()
    return (
        n.endswith(":cloud")
        or n.endswith("-cloud")
        or bool(__import__("re").fullmatch(r"gemma4:e\d+b", n))
    )


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
_RESEARCH_TASK_KEYWORDS = (
    "recherche web", "cherche sur internet", "sources officielles", "documentation actuelle",
    "état de l'art", "etat de l'art", "veille", "compare les offres", "renseigne toi",
)
_PRODUCTIVITY_TASK_KEYWORDS = (
    "document word", "docx", "excel", "xlsx", "powerpoint", "pptx", "présentation",
    "presentation", "rapport", "compte rendu", "mise en page", "tableur",
)
_MULTILINGUAL_TASK_KEYWORDS = (
    "traduis", "traduction", "translate", "multilingue", "bilingue",
)
_AGENTIC_TASK_KEYWORDS = (
    "workflow", "mission longue", "plusieurs étapes", "plusieurs etapes", "orchestration",
    "multi-agent", "utilise les outils", "automatise cette tâche", "automatise cette tache",
)
_REASONING_TASK_KEYWORDS = (
    "analyse approfondie", "raisonnement complexe", "diagnostic complexe", "architecture",
    "compare plusieurs", "évalue les compromis", "evalue les compromis", "résous ce problème",
    "resous ce probleme",
)


def detect_task(text: str) -> str | None:
    """Détecte un type de tâche pour un routage cloud plus fin que par profil.
    Best-effort, conservateur : retourne None (pas de routage spécial) dès que le
    signal n'est pas clair — l'appelant garde alors son modèle par défaut (profil)."""
    norm = strip_accents((text or "").lower())
    if any(strip_accents(k) in norm for k in _CODE_TASK_KEYWORDS):
        return "code"
    if any(strip_accents(k) in norm for k in _RESEARCH_TASK_KEYWORDS):
        return "research"
    if any(strip_accents(k) in norm for k in _PRODUCTIVITY_TASK_KEYWORDS):
        return "productivity"
    if any(strip_accents(k) in norm for k in _MULTILINGUAL_TASK_KEYWORDS):
        return "multilingual"
    if any(strip_accents(k) in norm for k in _AGENTIC_TASK_KEYWORDS):
        return "agentic"
    if any(strip_accents(k) in norm for k in _REASONING_TASK_KEYWORDS):
        return "reasoning"
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
_CODE_SPECIALIST_MARKERS = ("coder", "code")


def model_family(name: str) -> str:
    """Famille stable d'un modèle cloud, indépendante de sa taille et de son tag.

    Le Council utilise cette valeur pour éviter cinq variantes d'une même famille qui
    partageraient largement les mêmes angles morts.
    """
    low = (name or "").lower()
    for family in ("deepseek", "qwen", "glm", "kimi", "nemotron", "minimax",
                   "mistral", "gemma", "gemini", "gpt-oss", "llama"):
        if low.startswith(family):
            return family
    return low.split(":", 1)[0].split("-", 1)[0]


def list_distinct_cloud_models(need: str = "general") -> list[str]:
    """Retourne les modèles cloud installés, ordonnés par utilité et dédupliqués par
    famille. Aucune valeur de réglage périmée n'est inventée ni conservée."""
    installed = list_installed_cloud_models()
    if need == "code":
        families = ("kimi", "glm", "deepseek", "qwen", "minimax", "mistral", "nemotron")
    else:
        families = ("deepseek", "qwen", "glm", "nemotron", "mistral", "minimax", "kimi")
    ordered: list[str] = []
    for family in families:
        ordered.extend(m for m in installed if model_family(m) == family and m not in ordered)
    ordered.extend(m for m in installed if m not in ordered)
    distinct: list[str] = []
    seen: set[str] = set()
    for model in ordered:
        family = model_family(model)
        if family and family not in seen:
            seen.add(family)
            distinct.append(model)
    return distinct


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


# v2.180 — apprentissage PASSIF des capacités réelles (« que Marvin connaisse tous les
# modèles et leur utilité de façon autonome »). Volontairement PAS de sonde proactive
# (appeler chaque modèle installé juste pour tester coûterait du quota cloud réel pour
# aucun bénéfice utilisateur) : Marvin apprend de ses VRAIS appels — si un modèle échoue
# réellement sur un besoin (ex. refuse une image, erreur 4xx = incapacité, pas un incident
# réseau), c'est mémorisé et il n'est plus jamais retenté pour CE besoin. Même doctrine que
# l'auto-réparation des compétences (skills.py) : apprendre de l'échec réel, pas deviner.
def get_model_capabilities() -> dict:
    """{modèle: {besoin: {"ok": bool, "at": iso}}} — appris, jamais sondé à l'avance."""
    try:
        v = db.get_setting("cloud_model_capabilities") or {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def record_model_capability(model: str, need: str, ok: bool):
    """À appeler après un VRAI appel réel à `model` pour `need`. `ok=False` UNIQUEMENT sur
    une erreur de CAPACITÉ constatée (ex. HTTP 4xx = le modèle refuse ce type de contenu) —
    jamais sur un incident transitoire (timeout, 5xx, réseau), pour ne pas exclure à tort un
    modèle qui a juste eu un problème ponctuel."""
    try:
        from datetime import datetime as _dt
        caps = get_model_capabilities()
        caps.setdefault(model, {})[need] = {"ok": bool(ok), "at": _dt.now().isoformat()}
        db.set_setting("cloud_model_capabilities", caps)
    except Exception:
        pass


def _apply_learned_capabilities(installed: list[str], need: str) -> list[str]:
    """Exclut les modèles appris INCAPABLES pour ce besoin, et fait remonter en tête ceux
    appris CAPABLES (expérience réelle prioritaire sur la simple heuristique de famille)."""
    caps = get_model_capabilities()
    known_ok = lambda m: caps.get(m, {}).get(need, {}).get("ok")
    installed = [m for m in installed if known_ok(m) is not False]
    proven = [m for m in installed if known_ok(m) is True]
    if proven:
        installed = proven + [m for m in installed if m not in proven]
    return installed


def pick_best_cloud_model(need: str = "general", exclude: frozenset = frozenset()) -> str | None:
    """Choisit le meilleur modèle cloud INSTALLÉ pour un besoin donné (general/code/vision),
    par famille (préfixe/marqueur dans le nom) affinée par l'expérience réelle apprise, jamais
    par tag exact figé en dur — résilient à la rotation/au retrait des modèles cloud. Retourne
    None si aucun candidat installé pour ce besoin (l'appelant décide alors du repli, ex. local
    pour la vision)."""
    installed = [m for m in list_installed_cloud_models() if m not in exclude]
    if not installed:
        return None
    try:
        import model_market
        recommendations = model_market.recommend(
            need,
            count=1,
            exclude_models=set(exclude),
        )
        if recommendations:
            return str(recommendations[0]["model"])
    except Exception:
        pass
    if need == "code":
        candidates = _apply_learned_capabilities(installed, "code")
        coder = next((m for m in candidates if any(k in m.lower() for k in _CODE_SPECIALIST_MARKERS)), None)
        if coder:
            return coder
        need = "general"  # pas de spécialiste installé -> repli propre sur le généraliste
    if need == "vision":
        candidates = _apply_learned_capabilities(installed, "vision")
        for fam in _VISION_CAPABLE_FAMILIES:
            m = next((m for m in candidates if m.lower().startswith(fam)), None)
            if m:
                return m
        return candidates[0] if candidates else None
    candidates = _apply_learned_capabilities(installed, "general")
    for fam in _GENERAL_PREFERENCE_FAMILIES:
        m = next((m for m in candidates if m.lower().startswith(fam)), None)
        if m:
            return m
    return candidates[0] if candidates else None


def list_vision_candidates() -> list[str]:
    """TOUS les modèles cloud installés réputés capables de vision (pas seulement le
    meilleur) — dans l'ordre de préférence des familles PUIS de l'expérience apprise, pour
    permettre à l'appelant d'essayer le suivant si le premier échoue à l'exécution."""
    installed = _apply_learned_capabilities(list_installed_cloud_models(), "vision")
    out = []
    for fam in _VISION_CAPABLE_FAMILIES:
        out.extend(m for m in installed if m.lower().startswith(fam) and m not in out)
    out.extend(m for m in installed if m not in out)  # modèles appris capables hors familles connues
    return out


def is_local_only_lockdown() -> bool:
    """Mode « Hyper sécurisé » : coupe-circuit total, prioritaire sur tout le reste."""
    try:
        return bool(db.get_setting("local_only_lockdown"))
    except Exception:
        return False


def is_ultra_unrestricted() -> bool:
    """Mode « Ultra débridé » : autorise les données sensibles dans le cloud.

    Depuis v2.243, ce réglage porte aussi un contrat cloud-only pour les appels LLM
    génératifs. Le garde-fou système de security.py reste indépendant et actif.
    """
    try:
        return bool(db.get_setting("ultra_unrestricted"))
    except Exception:
        return False


class CloudOnlyModelUnavailable(RuntimeError):
    """Le mode Ultra exige le cloud mais aucun modèle cloud adapté n'est disponible."""


def is_cloud_only_mode() -> bool:
    """True uniquement quand Ultra est actif et que le coupe-circuit local ne l'est pas.

    Si les deux réglages sont accidentellement vrais, Hyper local gagne. Cette priorité
    préserve le garde-fou de défense en profondeur ajouté antérieurement.
    """
    return is_ultra_unrestricted() and not is_local_only_lockdown()


def require_cloud_model(
    need: str = "general",
    *,
    requested_model: str | None = None,
    exclude: frozenset[str] = frozenset(),
) -> str:
    """Résout un modèle cloud installé ou échoue explicitement, sans repli local."""
    installed = [model for model in list_installed_cloud_models() if model not in exclude]
    if requested_model and is_cloud_model(requested_model) and requested_model in installed:
        return requested_model
    picked = pick_best_cloud_model(need, exclude=exclude)
    if picked and picked in installed:
        return picked
    raise CloudOnlyModelUnavailable(
        "Mode Ultra débridé actif : aucun modèle Ollama Cloud adapté n'est disponible. "
        "Marvin refuse le repli local silencieux. Vérifiez Ollama Cloud ou changez de mode."
    )


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
    lockdown = is_local_only_lockdown()
    if lockdown:
        return requested_model if (requested_model and not is_cloud_model(requested_model)) else fallback

    # Ultra est un contrat cloud-only, pas seulement une levée du filtre de sensibilité.
    # Un choix manuel local, une image ou un modèle cloud retiré sont reroutés vers un
    # cloud réellement installé. À défaut, on échoue clairement au lieu de masquer un
    # repli sur qwen/llava local.
    if is_cloud_only_mode():
        task = "vision" if has_images else (detect_task(text_for_sensitivity) or {
            "analysis": "reasoning",
            "agent": "agentic",
            "vision": "vision",
        }.get(profile, "general"))
        return require_cloud_model(task, requested_model=requested_model)

    if has_images:
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
            configured = overrides[profile]
            # Un override peut rester en base après le retrait/renommage d'un modèle cloud.
            # Ne jamais provoquer un échec puis un repli local silencieux : valider contre
            # /api/tags et choisir un cloud réellement disponible.
            installed = list_installed_cloud_models()
            if configured in installed:
                return configured
            picked = pick_best_cloud_model("general")
            if picked:
                return picked
    return fallback
