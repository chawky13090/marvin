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


def is_sensitive_text(text: str) -> bool:
    """True si le texte (prompt d'un appel LLM interne, message utilisateur...)
    contient un mot-clé de donnée sensible."""
    norm = strip_accents((text or "").lower())
    return any(strip_accents(k) in norm for k in SENSITIVE_KEYWORDS)


def is_sensitive_tool(name: str) -> bool:
    return any((name or "").startswith(p) for p in SENSITIVE_TOOL_PREFIXES)


def is_cloud_model(name: str) -> bool:
    return (name or "").endswith(":cloud")


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

    # Aucun modèle demandé : tenter le cloud auto si configuré pour ce profil.
    cloud_enabled, overrides = get_cloud_config()
    if cloud_enabled and profile in overrides and not sensitive:
        return overrides[profile]
    return fallback
