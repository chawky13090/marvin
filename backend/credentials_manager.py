"""Gestionnaire des identifiants OAuth et API de Marvin.

Les valeurs publiques restent dans SQLite. Les secrets sont protégés par le
coffre DPAPI de l'utilisateur Windows et ne sont effacés de leur emplacement
historique qu'après une relecture cryptographique réussie.
"""

from __future__ import annotations

import database as db
import secret_vault
import audit

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
    # v2.161 — SearXNG (méta-moteur auto-hébergé, Docker) : gratuit et illimité, sans
    # dépendre d'une clé/quota tiers. Prioritaire sur DuckDuckGo/Brave/Google en mode
    # auto (voir execute_web_search) quand une instance est renseignée ici.
    "searxng_url":           {"label": "URL de l'instance (ex: http://localhost:8080)",
                               "service": "SearXNG (auto-hébergé)", "group": "search", "secret": False},
    "brave_search_api_key":  {"label": "API Key",             "service": "Brave Search", "group": "search", "secret": True},
    "google_search_api_key": {"label": "API Key",             "service": "Google Search","group": "search", "secret": True},
    "google_search_cx":      {"label": "Search Engine ID",   "service": "Google Search","group": "search", "secret": False},
    "serpapi_key":           {"label": "API Key",             "service": "SerpAPI",    "group": "search",   "secret": True},

    # ── Traduction ──────────────────────────────────────────────────────────
    "mymemory_api_key":      {"label": "API Key (optionnel)",  "service": "MyMemory",  "group": "translate", "secret": True},

    # ── ITSM / GLPI ─────────────────────────────────────────────────────────
    "glpi_url":              {"label": "URL GLPI",             "service": "GLPI",      "group": "glpi",      "secret": False},
    "glpi_app_token":        {"label": "App Token",            "service": "GLPI",      "group": "glpi",      "secret": True},
    "glpi_user_token":       {"label": "User Token",           "service": "GLPI",      "group": "glpi",      "secret": True},

    # ── Autres ──────────────────────────────────────────────────────────────
    "openai_api_key":        {"label": "API Key",             "service": "OpenAI",    "group": "ai",        "secret": True},
    "anthropic_api_key":     {"label": "API Key",             "service": "Anthropic", "group": "ai",        "secret": True},
    "replicate_api_token":   {"label": "API Token",           "service": "Replicate", "group": "video",     "secret": True},
    "falai_api_key":         {"label": "API Key",             "service": "fal.ai",    "group": "video",     "secret": True},
}


def _key(name: str) -> str:
    return f"cred_{name}"


def _definition(name: str) -> dict:
    definition = CREDENTIAL_DEFINITIONS.get(name)
    if definition is None:
        raise ValueError("Identifiant inconnu.")
    return definition


def _legacy_value(name: str) -> str | None:
    value = db.get_setting(_key(name))
    return value if isinstance(value, str) and value else None


def _clear_legacy(name: str) -> None:
    db.set_setting(_key(name), None)


def get_credential(name: str) -> str | None:
    definition = _definition(name)
    legacy = _legacy_value(name)
    if not definition.get("secret"):
        return legacy

    protected = secret_vault.get_secret("credential", name, "value")
    if legacy is not None:
        # Une ancienne instance peut encore écrire dans SQLite pendant un
        # déploiement progressif. La valeur historique non vide est alors la
        # dernière écriture observable : elle remplace le coffre, puis est
        # nettoyée seulement après relecture DPAPI.
        secret_vault.set_secret("credential", name, "value", legacy)
        _clear_legacy(name)
        return legacy
    return protected


def set_credential(name: str, value: str) -> None:
    definition = _definition(name)
    if not isinstance(value, str):
        raise ValueError("La valeur doit être une chaîne.")
    value = value.strip()
    if not value:
        delete_credential(name)
        return
    if len(value) > 16_384:
        raise ValueError("La valeur est trop longue.")
    if definition.get("secret"):
        secret_vault.set_secret("credential", name, "value", value)
        _clear_legacy(name)
        audit.log_action(
            "credential_set",
            {"credential": name, "storage": "windows_dpapi_current_user"},
            {"success": True},
            source="credentials",
        )
        return
    db.set_setting(_key(name), value)
    audit.log_action(
        "credential_set",
        {"credential": name, "storage": "sqlite_public_setting"},
        {"success": True},
        source="credentials",
    )


def delete_credential(name: str) -> None:
    definition = _definition(name)
    if definition.get("secret"):
        secret_vault.delete_secret("credential", name, "value")
    _clear_legacy(name)
    audit.log_action(
        "credential_delete",
        {"credential": name},
        {"success": True},
        source="credentials",
    )


def migrate_legacy_secrets() -> dict[str, int]:
    """Migre tous les secrets historiques sans exposer leur nom ni leur valeur."""
    migrated = 0
    already_protected = 0
    absent = 0
    for name, definition in CREDENTIAL_DEFINITIONS.items():
        if not definition.get("secret"):
            continue
        legacy = _legacy_value(name)
        protected = secret_vault.get_secret("credential", name, "value")
        if legacy is not None:
            secret_vault.set_secret("credential", name, "value", legacy)
            _clear_legacy(name)
            migrated += 1
        elif protected is not None:
            already_protected += 1
        else:
            absent += 1
    result = {
        "migrated": migrated,
        "already_protected": already_protected,
        "absent": absent,
    }
    audit.log_action(
        "credential_vault_migration",
        {"provider": "windows_dpapi_current_user"},
        {"success": True, **result},
        source="migration",
    )
    return result


def restore_legacy_plaintext(*, confirmed: bool, delete_protected: bool = True) -> dict[str, int]:
    """Rollback explicite vers l'ancien format SQLite.

    Cette opération dégrade volontairement la protection au repos et doit
    uniquement être exécutée Marvin arrêté, juste avant une réversion du code.
    """
    if confirmed is not True:
        raise ValueError("La restauration en clair exige une confirmation explicite.")
    restored = 0
    absent = 0
    for name, definition in CREDENTIAL_DEFINITIONS.items():
        if not definition.get("secret"):
            continue
        protected = secret_vault.get_secret("credential", name, "value")
        if protected is None:
            absent += 1
            continue
        db.set_setting(_key(name), protected)
        if _legacy_value(name) != protected:
            raise RuntimeError("La vérification du rollback SQLite a échoué.")
        if delete_protected:
            secret_vault.delete_secret("credential", name, "value")
        restored += 1
    result = {"restored": restored, "absent": absent}
    audit.log_action(
        "credential_vault_rollback",
        {"plaintext_restoration": True},
        {"success": True, **result},
        source="rollback",
    )
    return result


def security_status() -> dict[str, int | str | bool]:
    encrypted = 0
    legacy_plaintext = 0
    absent = 0
    for name, definition in CREDENTIAL_DEFINITIONS.items():
        if not definition.get("secret"):
            continue
        legacy = _legacy_value(name)
        if legacy is not None:
            legacy_plaintext += 1
        if secret_vault.has_secret("credential", name, "value"):
            encrypted += 1
        elif legacy is None:
            absent += 1
    return {
        "provider": "windows_dpapi_current_user",
        "available": True,
        "encrypted": encrypted,
        "legacy_plaintext": legacy_plaintext,
        "absent": absent,
        "migration_complete": legacy_plaintext == 0,
    }


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
