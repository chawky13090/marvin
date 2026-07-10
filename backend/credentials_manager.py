"""
Marvin — Gestionnaire de credentials OAuth & API Keys
Stockage sécurisé dans la base SQLite locale.
"""
import json
import database as db

# Clés supportées et leurs métadonnées
CREDENTIAL_DEFINITIONS = {
    # ── Google ──────────────────────────────────────────────────────────────
    "google_client_id":      {"label": "Client ID",           "service": "Google",    "group": "google",    "secret": False},
    "google_client_secret":  {"label": "Client Secret",       "service": "Google",    "group": "google",    "secret": True},
    "google_access_token":   {"label": "Access Token",        "service": "Google",    "group": "google",    "secret": True,  "auto": True},
    "google_refresh_token":  {"label": "Refresh Token",       "service": "Google",    "group": "google",    "secret": True,  "auto": True},

    # ── Microsoft / OneDrive ─────────────────────────────────────────────────
    "ms_client_id":          {"label": "Client ID",           "service": "Microsoft", "group": "microsoft", "secret": False},
    "ms_client_secret":      {"label": "Client Secret",       "service": "Microsoft", "group": "microsoft", "secret": True},
    "ms_tenant_id":          {"label": "Tenant ID (optionnel)","service": "Microsoft","group": "microsoft", "secret": False},
    "ms_access_token":       {"label": "Access Token",        "service": "Microsoft", "group": "microsoft", "secret": True,  "auto": True},
    "ms_refresh_token":      {"label": "Refresh Token",       "service": "Microsoft", "group": "microsoft", "secret": True,  "auto": True},

    # ── Canva ────────────────────────────────────────────────────────────────
    "canva_api_key":         {"label": "API Key",             "service": "Canva",     "group": "canva",     "secret": True},
    "canva_client_id":       {"label": "Client ID",           "service": "Canva",     "group": "canva",     "secret": False},

    # ── Recherche web ────────────────────────────────────────────────────────
    "brave_search_api_key":  {"label": "API Key",             "service": "Brave Search", "group": "search", "secret": True},
    "google_search_api_key": {"label": "API Key",             "service": "Google Search","group": "search", "secret": True},
    "google_search_cx":      {"label": "Search Engine ID",   "service": "Google Search","group": "search", "secret": False},
    "serpapi_key":           {"label": "API Key",             "service": "SerpAPI",    "group": "search",   "secret": True},

    # ── Traduction ──────────────────────────────────────────────────────────
    "mymemory_api_key":      {"label": "API Key (optionnel)",  "service": "MyMemory",  "group": "translate", "secret": True},

    # ── Autres ──────────────────────────────────────────────────────────────
    "openai_api_key":        {"label": "API Key",             "service": "OpenAI",    "group": "ai",        "secret": True},
    "anthropic_api_key":     {"label": "API Key",             "service": "Anthropic", "group": "ai",        "secret": True},
    "replicate_api_token":   {"label": "API Token",           "service": "Replicate", "group": "video",     "secret": True},
    "falai_api_key":         {"label": "API Key",             "service": "fal.ai",    "group": "video",     "secret": True},
}


def _key(name: str) -> str:
    return f"cred_{name}"


def get_credential(name: str) -> str | None:
    return db.get_setting(_key(name))


def set_credential(name: str, value: str) -> None:
    db.set_setting(_key(name), value)


def delete_credential(name: str) -> None:
    db.set_setting(_key(name), None)


def get_all_credentials() -> dict:
    """Retourne toutes les credentials (avec masquage des secrets)."""
    result = {}
    for name, meta in CREDENTIAL_DEFINITIONS.items():
        if meta.get("auto"):  # Ne pas afficher les tokens auto-générés
            continue
        value = get_credential(name)
        result[name] = {
            **meta,
            "key": name,
            "has_value": bool(value),
            "value": "" if meta.get("secret") else (value or ""),
        }
    return result


def get_group_status() -> dict:
    """Retourne le statut de connexion pour chaque groupe."""
    groups = {}
    for name, meta in CREDENTIAL_DEFINITIONS.items():
        group = meta["group"]
        if group not in groups:
            groups[group] = {"service": meta["service"], "group": group, "connected": False, "keys_set": 0, "total_keys": 0}
        if not meta.get("auto"):
            groups[group]["total_keys"] += 1
            if get_credential(name):
                groups[group]["keys_set"] += 1
    # Marquer comme connecté si les clés essentielles sont définies
    essential = {
        "google": ["google_client_id", "google_client_secret"],
        "microsoft": ["ms_client_id"],
        "canva": ["canva_api_key"],
        "search": [],  # Au moins une clé de recherche
        "ai": [],
    }
    for group, keys in essential.items():
        if group in groups:
            if keys:
                groups[group]["connected"] = all(get_credential(k) for k in keys)
            else:
                groups[group]["connected"] = groups[group]["keys_set"] > 0
    return groups
