"""
SecretaryAI Backend — Registre de tous les outils disponibles pour l'agent.
Chaque outil expose :
  - Une entrée dans TOOLS_SPEC (format Ollama/OpenAI) pour que l'IA sache quoi appeler.
  - Une fonction async execute_*(args) pour l'exécution réelle.
  - Les outils « dangereux » vérifient args.get('confirmed') avant d'agir.
"""
import os
import sys
import json
import re
import shutil
import asyncio
import subprocess
import time
import tempfile
from pathlib import Path
from typing import Any

import psutil
import database as db
import email_manager as email_manager_runtime
import cloud_routing as cloud_routing_runtime
import learning
import model_council as model_council_runtime
import parallel_reasoning as parallel_reasoning_runtime
import python_execution as python_execution_runtime
import mission_os as mission_os_runtime
import vector_store as vector_store_runtime
import voice_transcription as voice_transcription_runtime
import web_runtime
import proactive_briefing
import generation_runtime
import ollama_context_admission
import computer_runtime
from storage_layout import roots as storage_roots
from conversation_exports import export_conversation
from tool_domains import quiz as quiz_domain
from tool_domains import it_knowledge as it_knowledge_domain
from tool_domains import productivity as productivity_domain
from tool_domains import memory as memory_domain
from tool_domains import media as media_domain
from tool_domains import ssh as ssh_domain
from tool_domains import filesystem as filesystem_domain
from tool_domains import documents as documents_domain
from tool_domains import archives as archives_domain
from tool_domains import spreadsheets as spreadsheets_domain
from tool_domains import ocr as ocr_domain
from tool_domains import screenshots as screenshots_domain
from tool_domains import images as images_domain
from tool_domains import pdf_core as pdf_core_domain
from tool_domains import pdf_advanced as pdf_advanced_domain
from tool_domains import document_knowledge as document_knowledge_domain
from tool_domains import network as network_domain
from tool_domains import system_cleanup as system_cleanup_domain
from tool_domains import billing as billing_domain
from tool_domains import windows as windows_domain
from tool_domains import web as web_domain
from tool_domains import web_media as web_media_domain
from tool_domains import pc_control as pc_control_domain
from tool_domains import tailscale as tailscale_domain
from tool_domains import pc_diagnostics as pc_diagnostics_domain
from tool_domains import intervention_docs as intervention_docs_domain
from tool_domains import command_safety as command_safety_domain
from tool_domains import operations_safety as operations_safety_domain
from tool_domains import client_health as client_health_domain
from tool_domains import workspace_organization as workspace_organization_domain
from tool_domains import winget as winget_domain
from tool_domains import windows_settings as windows_settings_domain
from tool_domains import windows_devices as windows_devices_domain
from tool_domains import windows_registry as windows_registry_domain
from tool_domains import windows_tweaks as windows_tweaks_domain
from tool_domains import catharsis as catharsis_domain
from tool_domains import system_search as system_search_domain
from tool_domains import itsm as itsm_domain
from tool_domains import runtime_observability as runtime_observability_domain
from tool_domains import google_drive as google_drive_domain
from tool_domains import onedrive as onedrive_domain
from tool_domains import google_calendar as google_calendar_domain
from tool_domains import calendar_subscriptions as calendar_subscriptions_domain
from tool_domains import calendar_events as calendar_events_domain
from tool_domains import deterministic_utilities as deterministic_utilities_domain
from tool_domains import datetime_tools as datetime_tools_domain
from tool_domains import unit_conversion as unit_conversion_domain
from tool_domains import weather as weather_domain
from tool_domains import translation as translation_domain
from tool_domains import text_processing as text_processing_domain
from tool_domains import structured_data as structured_data_domain
from tool_domains import presentations as presentations_domain
from tool_domains import git_repository as git_repository_domain
from tool_domains import charts as charts_domain
from tool_domains import long_tasks as long_tasks_domain
from tool_domains import system_self_test as system_self_test_domain
from tool_domains import unified_search as unified_search_domain
from tool_domains import screen_ocr as screen_ocr_domain
from tool_domains import email_messages as email_messages_domain
from tool_domains import email_productivity as email_productivity_domain
from tool_domains import email_monitoring as email_monitoring_domain
from tool_domains import email_automation as email_automation_domain
from tool_domains import telegram as telegram_domain
from tool_domains import webapp as webapp_domain
from tool_domains import logos as logos_domain
import ssh_transport
from document_formatting import (
    markdown_inline_to_reportlab as _md_inline_to_rl,
    parse_markdown_blocks as _parse_md_blocks,
)
from document_profile import (
    TEMPLATES as _DOC_TEMPLATES,
    get_identity as _document_identity,
    list_templates as _doc_templates_list,
    set_identity as execute_document_identity_set,
)
from config import DANGEROUS_TOOLS, OLLAMA_URL, MODEL_PROFILES
from platform_paths import PATHS as _SYSTEM_PATHS, expand_user_path


# ══════════════════════════════════════════════════════════════════════════════
# Couche réseau robuste partagée : pooling de connexions, cache TTL, hors-ligne
# (rend tous les outils web plus rapides ET plus résistants aux coupures réseau)
# ══════════════════════════════════════════════════════════════════════════════

_get_http_client = web_runtime.get_http_client
_is_offline_error = web_runtime.is_offline_error
_net_error = web_runtime.network_error
_wcache_get = web_runtime.cache_get
_wcache_set = web_runtime.cache_set


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Fichiers & Documents
# ══════════════════════════════════════════════════════════════════════════════

import re as _re

_HOME = _SYSTEM_PATHS["home"]
_REAL_USER = _SYSTEM_PATHS["username"]
_DRIVE = _SYSTEM_PATHS["drive"]

# Tous les formats de chemins avec mauvais nom d'utilisateur que le modèle peut générer
# Format 1: C:\Users\<wrong>\...   C:/Users/<wrong>/...
_RE_WITH_DRIVE = _re.compile(
    r'^[A-Za-z]:[/\\][Uu]sers[/\\](?!%s(?:[/\\]|$))([^/\\]+)([/\\].*)?$' % _re.escape(_REAL_USER),
    _re.IGNORECASE,
)
# Format 2: \Users\<wrong>\...   ou  \\Users\<wrong>\...  (sans lettre de lecteur)
_RE_NO_DRIVE = _re.compile(
    r'^\\+[Uu]sers[/\\]([^/\\]+)([/\\].*)?$',
    _re.IGNORECASE,
)
# Format 3: /Users/<wrong>/...  (style Unix)
_RE_UNIX = _re.compile(
    r'^/[Uu]sers/([^/]+)(/.*)?$',
    _re.IGNORECASE,
)

_KNOWN_SUBFOLDERS = {
    "desktop": _SYSTEM_PATHS["desktop"],
    "bureau": _SYSTEM_PATHS["desktop"],
    "documents": _SYSTEM_PATHS["documents"],
    "mes documents": _SYSTEM_PATHS["documents"],
    "downloads": _SYSTEM_PATHS["downloads"],
    "telechargements": _SYSTEM_PATHS["downloads"],
    "téléchargements": _SYSTEM_PATHS["downloads"],
    "pictures": _SYSTEM_PATHS["pictures"],
    "images": _SYSTEM_PATHS["pictures"],
    "photos": _SYSTEM_PATHS["pictures"],
    "music": _SYSTEM_PATHS["music"],
    "musique": _SYSTEM_PATHS["music"],
    "videos": _SYSTEM_PATHS["videos"],
    "vidéos": _SYSTEM_PATHS["videos"],
    "appdata": _SYSTEM_PATHS["appdata_local"],
    "temp": _SYSTEM_PATHS["temp"],
}

# Noms génériques qu'un LLM invente souvent pour le nom d'utilisateur
_PLACEHOLDER_USERS = {
    "yourusername", "username", "yourname", "user", "utilisateur",
    "youruser", "your_username", "your-username", "<username>",
    "<user>", "nom_utilisateur", "nomdutilisateur", "exemple",
    "example", "admin", "votrenom",
}


def _resolve_path(raw: str) -> str:
    """
    Correction universelle de chemin.
    Intercepte TOUTES les variantes qu'un LLM peut générer :
      C:/Users/YourUsername/Desktop  →  dossier Bureau Windows courant
      \\Users\\username\\Desktop     →  dossier Bureau Windows courant
      /Users/user/Desktop            →  dossier Bureau Windows courant
      Bureau                         →  dossier Bureau Windows courant
      ~\\Documents                   →  dossier Documents du profil courant
    """
    if not raw:
        return _HOME

    raw = expand_user_path(raw)

    # 1. Expansion du tilde
    if raw.startswith("~"):
        rest = raw[1:].lstrip("/\\")
        if rest:
            return str(Path(_HOME) / rest.replace("/", "\\"))
        return _HOME

    # 2. Normaliser les séparateurs et supprimer les doublons de backslash
    # (ex: \\Users\\username → \Users\username)
    normalized = raw.replace("/", "\\")
    # Réduire les séquences de backslashes à un seul — sauf au tout début (chemins UNC)
    import re as _re2
    # Préserver au max 1 backslash entre segments (sauf si le chemin commence par \\)
    leading = len(normalized) - len(normalized.lstrip("\\"))
    inner = _re2.sub(r'\\{2,}', r'\\', normalized[leading:])
    normalized = "\\" * min(leading, 1) + inner  # garder au plus 1 backslash initial

    # 3. Raccourcis simples — nom de dossier seul (ex: "Desktop", "Bureau")
    lower = normalized.strip("\\").lower()
    if lower in _KNOWN_SUBFOLDERS:
        return _KNOWN_SUBFOLDERS[lower]

    def _fix_suffix(suffix: str) -> str:
        """Retourne le chemin corrigé à partir du suffixe après le nom d'utilisateur."""
        if not suffix:
            return _HOME
        suffix_norm = suffix.lstrip("\\")
        suffix_lower = suffix_norm.lower()
        # Vérifier les sous-dossiers connus
        for key, folder in _KNOWN_SUBFOLDERS.items():
            if suffix_lower.startswith(key) and (
                len(suffix_lower) == len(key) or suffix_lower[len(key)] == "\\"
            ):
                rest_after = suffix_norm[len(key):].lstrip("\\")
                base = folder
                return str(Path(base) / rest_after) if rest_after else base
        return str(Path(_HOME) / suffix_norm)

    # 4. Format: C:\Users\wrong\...
    m = _RE_WITH_DRIVE.match(normalized)
    if m:
        wrong_user = m.group(1)
        suffix = m.group(2) or ""
        if wrong_user.lower() in _PLACEHOLDER_USERS or wrong_user.lower() != _REAL_USER.lower():
            return _fix_suffix(suffix)
        # Bon utilisateur — mais le sous-dossier peut quand même être un alias non-anglais
        # (ex: C:\Users\Chawb\Bureau au lieu de \Desktop) → _fix_suffix() le corrige aussi ;
        # équivalent à `normalized` si le suffixe n'est pas un alias connu (pas de régression).
        return _fix_suffix(suffix) if suffix else normalized

    # 5. Format: \Users\wrong\... ou \\Users\wrong\...
    m = _RE_NO_DRIVE.match(normalized)
    if m:
        wrong_user = m.group(1)
        suffix = m.group(2) or ""
        if wrong_user.lower() in _PLACEHOLDER_USERS or wrong_user.lower() != _REAL_USER.lower():
            return _fix_suffix(suffix)
        return _fix_suffix(suffix) if suffix else (_DRIVE + "\\Users\\" + wrong_user + suffix)

    # 6. Format Unix: /Users/wrong/...
    m = _RE_UNIX.match(raw)
    if m:
        wrong_user = m.group(1)
        suffix = (m.group(2) or "").replace("/", "\\")
        if wrong_user.lower() in _PLACEHOLDER_USERS or wrong_user.lower() != _REAL_USER.lower():
            return _fix_suffix(suffix)
        return _DRIVE + "\\Users\\" + wrong_user + suffix

    # 7. Retourner le chemin normalisé tel quel
    return normalized


git_repository_domain.configure(resolve_path=_resolve_path)
structured_data_domain.configure(resolve_path=_resolve_path)
execute_file_list = filesystem_domain.list_entries
execute_file_info = filesystem_domain.info


execute_file_read = filesystem_domain.read
execute_file_write = filesystem_domain.write
execute_file_delete = filesystem_domain.delete
execute_file_rename = filesystem_domain.rename
execute_file_move = filesystem_domain.move
execute_file_copy = filesystem_domain.copy
execute_file_create_folder = filesystem_domain.create_folder


documents_domain.configure(resolve_path=_resolve_path)
presentations_domain.configure(resolve_path=_resolve_path)
web_media_domain.configure(resolve_path=_resolve_path)
execute_file_create_docx = documents_domain.create_docx
execute_file_convert_docx_to_pdf = documents_domain.convert_docx_to_pdf
execute_document_convert_format = documents_domain.convert_format
archives_domain.configure(resolve_path=_resolve_path)
execute_file_compress = archives_domain.compress
execute_file_extract = archives_domain.extract
spreadsheets_domain.configure(resolve_path=_resolve_path)
execute_file_create_xlsx = spreadsheets_domain.create_xlsx
execute_csv_to_xlsx = spreadsheets_domain.csv_to_xlsx
execute_xlsx_to_csv = spreadsheets_domain.xlsx_to_csv
execute_xlsx_read = spreadsheets_domain.read_xlsx
ocr_domain.configure(resolve_path=_resolve_path, ollama_url=OLLAMA_URL)
execute_ocr_extract = ocr_domain.extract
screenshots_domain.configure(
    list_screenshots=db.list_screenshots,
    ollama_url=OLLAMA_URL,
)
_analyze_screenshot = screenshots_domain.analyze
execute_screenshot_list = screenshots_domain.list_for_conversation
execute_doc_generate_from_screenshots = screenshots_domain.generate_document
images_domain.configure(resolve_path=_resolve_path)
execute_image_info = images_domain.info
execute_image_resize = images_domain.resize
execute_images_to_pdf = images_domain.images_to_pdf
execute_image_crop = images_domain.crop
execute_image_rotate = images_domain.rotate
execute_image_compress = images_domain.compress
execute_image_batch = images_domain.batch
pdf_core_domain.configure(resolve_path=_resolve_path)
execute_pdf_read = pdf_core_domain.read
execute_pdf_info = pdf_core_domain.info
execute_pdf_merge = pdf_core_domain.merge
execute_pdf_split = pdf_core_domain.split
execute_pdf_rotate = pdf_core_domain.rotate


execute_file_search_text = filesystem_domain.search_text


def _normalize_windows_path(path: str) -> str:
    """
    Convert French Windows display names back to real folder names.
    Windows Search Index returns the localized display names (Bureau, Documents)
    but the actual folders on disk use English names (Desktop, Documents).
    """
    if not path:
        return path
    # Map French display names to real folder names
    _FR_TO_EN = {
        "\\Utilisateurs\\": "\\Users\\",
        "\\Bureau\\":       "\\Desktop\\",
        "\\Téléchargements\\": "\\Downloads\\",
        "\\Telechargements\\": "\\Downloads\\",
        "\\Mes Documents\\":   "\\Documents\\",
        "\\Mes Images\\":      "\\Pictures\\",
        "\\Mes Vidéos\\":      "\\Videos\\",
        "\\Mes Videos\\":      "\\Videos\\",
        "\\Ma Musique\\":      "\\Music\\",
        "\\Favoris\\":         "\\Favorites\\",
    }
    # Also handle case where path ENDS with one of these
    _FR_TO_EN_SUFFIX = {
        "\\Bureau":       "\\Desktop",
        "\\Téléchargements": "\\Downloads",
        "\\Telechargements": "\\Downloads",
        "\\Mes Documents":   "\\Documents",
        "\\Mes Images":      "\\Pictures",
        "\\Mes Vidéos":      "\\Videos",
    }
    result = path
    for fr, en in _FR_TO_EN.items():
        result = result.replace(fr, en)
    for fr, en in _FR_TO_EN_SUFFIX.items():
        if result.endswith(fr):
            result = result[:-len(fr)] + en
    # Verify the translated path exists; if not, fall back to original
    import os as _os
    if _os.path.exists(result):
        return result
    if _os.path.exists(path):
        return path
    return result   # Best guess


execute_file_find = filesystem_domain.find

# L'index Windows expose parfois des noms d'affichage localisés (par exemple
# « Utilisateurs » et « Bureau »). Toutes les opérations filesystem doivent
# rendre des chemins natifs réutilisables par les appels suivants du LLM.
filesystem_domain.configure(
    resolve_path=_resolve_path,
    normalize_index_path=_normalize_windows_path,
)


async def execute_system_search(args: dict) -> dict:
    return await system_search_domain.search(args, normalize_path=_normalize_windows_path)


async def execute_system_search_content(args: dict) -> dict:
    return await system_search_domain.search_content(
        args, normalize_path=_normalize_windows_path
    )


# SECTION 2 — PC & Système
# ══════════════════════════════════════════════════════════════════════════════



def _drive_list():
    """Liste les lecteurs Windows présents (C:\\, D:\\…)."""
    import string, ctypes
    out = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                out.append(f"{letter}:\\")
    except Exception:
        out = ["C:\\"]
    return out






def _fmt_bytes(n):
    try:
        n = float(n)
    except Exception:
        return ""
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Po"


# v2.145 — « ChatGPT Sites » (juillet 2026) : générer une mini-appli web interactive sans
# quitter le chat. Marvin générait déjà des documents/graphiques/code (v2.142) mais rien qui
# produise une page consultable dans le navigateur — vrai trou identifié en comparant aux
# fonctionnalités des IA payantes. Réutilise le pattern déjà établi (GeneratedFileCard v2.128,
# étendu ici aux .html) : le fichier est juste un fichier de plus, ouvert via os.startfile()
# (déjà le comportement de pc_open_file — un .html ouvre le navigateur par défaut, zéro code
# supplémentaire nécessaire côté ouverture).
webapp_domain.configure(
    output_root=Path(__file__).resolve().parent.parent / "data" / "webapps"
)
execute_webapp_create = webapp_domain.create


















# ══════════════════════════════════════════════════════════════════════════════
#  Exécution ÉLEVÉE (pattern sidecar) — délègue au démon admin séparé
#  (backend/elevated_daemon.py) au lieu de faire tourner tout le backend en admin.
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
#  EMPORIUM — Gestionnaire de paquets universel (Winget)
#  Recherche / installation silencieuse / mise à jour / désinstallation.
# ══════════════════════════════════════════════════════════════════════════════



















# ══════════════════════════════════════════════════════════════════════════════
#  PANTHEON — Optimisation & durcissement Windows (tweaks SÛRS).
#  Règle d'or : toute modification crée d'ABORD une sauvegarde (.reg / point de
#  restauration) et exige une confirmation. Tout est RÉVERSIBLE.
# ══════════════════════════════════════════════════════════════════════════════























# ══════════════════════════════════════════════════════════════════════════════
#  CATHARSIS — Moteur de purge (style CCleaner) : SCAN d'abord (taille récupérable),
#  puis CLEAN confirmé. Ne touche QUE des dossiers temporaires/caches connus.
# ══════════════════════════════════════════════════════════════════════════════

#  (id) -> (libellé, [chemins PowerShell], groupe)   — groupe = tuile dans l'UI
# Groupe d'affichage de la corbeille (catégorie spéciale, hors _CLEAN_CATS)






# ══════════════════════════════════════════════════════════════════════════════
#  CODEX — Paramètres OS exposés en fonctions (remplace ms-settings:).
#  Lecture libre ; écriture confirmée. Plan d'alim, mode sombre, pare-feu, réseau…
# ══════════════════════════════════════════════════════════════════════════════













# ══════════════════════════════════════════════════════════════════════════════
# CATALOGUE « Windows+ » — raccourcis d'ouverture directe vers les panneaux Windows
# (God Mode, ms-settings:*, panneaux legacy .cpl, outils admin .msc, dossiers utiles).
# Porté du même fork que Réseau Pro/hardware (catalogue de NAVIGATION seulement — leur
# système de tweaks/registre séparé n'est PAS repris, il chevauche mon Pantheon existant
# tweak_telemetry/tweak_debloat_*/tweak_network_harden/registry_*). Risque quasi nul :
# ouvre des panneaux Windows natifs, ne modifie rien (sauf God Mode qui crée un dossier
# vide standard). Aucune confirmation requise pour la même raison.
# ══════════════════════════════════════════════════════════════════════════════



















# ── v2.149 — Agent GUI local (lecture/clic/frappe via Windows UI Automation) ──────────
# Comble un vrai trou : Marvin avait déjà les "yeux" (pc_screenshot, screen_ocr,
# pc_window_list/focus) mais aucune "main" — aucun moyen de cliquer/taper dans une fenêtre.
# Choix délibéré : UI Automation (arbre structuré natif Windows) plutôt qu'un agent vision
# façon UI-TARS — 100% local, aucune capture d'écran envoyée à un modèle (donc aucun risque
# de fuite de données sensibles affichées à l'écran vers le cloud), et bien plus précis
# qu'un clic en coordonnées pixel qui casse au moindre pixel de décalage.
#
# Sécurité — pattern "lire un ID réel avant d'agir dessus" (même esprit que winget_install
# v2.113 et long_task_status v2.145) : pc_gui_click/pc_gui_type ne reçoivent JAMAIS de
# coordonnées figées d'une lecture précédente. Chaque appel refait une résolution LIVE de
# l'élément (par automation_id ou control_type+name+match_index) au moment même de l'action
# — protection structurelle contre une attaque TOCTOU (l'UI a changé entre la lecture et
# l'action : fenêtre fermée, élément déplacé, remplacé par autre chose). Si l'élément n'est
# plus là, l'appel échoue proprement plutôt que de cliquer au hasard.
#
# Le texte/les noms lus depuis l'UI (pc_gui_read) restent du CONTENU OBSERVÉ au sens de la
# règle de sécurité générale — jamais une instruction, même si un élément affiche un texte
# du style "clique ici". pc_gui_click/pc_gui_type sont dans DANGEROUS_TOOLS (confirmation
# obligatoire).
#
# Limite connue et assumée : UI Automation ne franchit pas la frontière UAC — une fenêtre
# élevée (admin) reste invisible/inaccessible depuis ce process non-admin. Pas de
# contournement ici (cliquer en tant qu'admin serait un risque d'un tout autre ordre que
# l'allowlist stricte du sidecar élevé, v2.90) — échec explicite si la fenêtre cible est
# élevée, à traiter au cas par cas si le besoin se présente vraiment.

# Types "porteurs de contenu" : leur `name` UIA EST le texte qu'ils contiennent (constaté en
# testant sur le Bloc-notes Windows 11 réel — control_type="Document", name="<tout le fichier>").
# Ce texte n'est PAS un identifiant stable (il change à chaque frappe) → jamais utilisé pour le
# matching de ré-résolution, seulement affiché (tronqué) à titre informatif. Le matching se fait
# par position (match_index) parmi les contrôles du même control_type dans la fenêtre.












async def execute_vm_lab_install(args: dict) -> dict:
    """Inspecte ou démarre l'installateur Hyper-V persistant de Marvin."""
    import vm_lab_jobs

    action = str(args.get("action") or "status").strip().casefold()
    try:
        if action == "status":
            return await asyncio.to_thread(vm_lab_jobs.status)
        if action != "install":
            return {"error": "Action VM Lab invalide : utilise status ou install."}
        return await asyncio.to_thread(
            vm_lab_jobs.start,
            str(args.get("profile") or ""),
            confirmed=bool(args.get("confirmed")),
        )
    except (OSError, ValueError, vm_lab_jobs.VMLabJobError) as exc:
        return {"error": str(exc)}














# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Tâches
# ══════════════════════════════════════════════════════════════════════════════

execute_task_create = productivity_domain.task_create
execute_task_list = productivity_domain.task_list
execute_task_update = productivity_domain.task_update
execute_task_delete = productivity_domain.task_delete


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Notes
# ══════════════════════════════════════════════════════════════════════════════

execute_note_create = productivity_domain.note_create
execute_note_list = productivity_domain.note_list
execute_note_update = productivity_domain.note_update
execute_note_delete = productivity_domain.note_delete


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Mémoire
# ══════════════════════════════════════════════════════════════════════════════

execute_memory_save = memory_domain.save
execute_memory_list = memory_domain.list_memories
execute_memory_delete = memory_domain.delete
execute_memory_search = memory_domain.search


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Recherche sémantique (Qdrant)
# ══════════════════════════════════════════════════════════════════════════════

async def execute_search_semantic(args: dict) -> dict:
    query = args.get("query", "")
    collections = args.get("collections", None)
    limit = args.get("limit", 5)
    if not query:
        return {"error": "Requête vide"}
    try:
        from vector_store import search
        results = await search(query, collections, limit)
        return {"success": True, "query": query, "count": len(results), "results": results}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Recherche Web
# ══════════════════════════════════════════════════════════════════════════════





# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — Infographies & Images
# ══════════════════════════════════════════════════════════════════════════════

charts_domain.configure(
    resolve_path=_resolve_path,
    default_output=lambda: (
        Path(_SYSTEM_PATHS["desktop"])
        / f"infographie_{time.time_ns()}.png"
    ),
)
execute_infographic_create = charts_domain.create





# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9A — Google Calendar
# ══════════════════════════════════════════════════════════════════════════════

execute_file_create_pdf = documents_domain.create_pdf
screenshots_domain.configure_renderers(
    create_docx=execute_file_create_docx,
    create_pdf=execute_file_create_pdf,
)


_GOOGLE_SA_PATH = str(google_calendar_domain.SERVICE_ACCOUNT_PATH)


_google_sa_email = google_calendar_domain.service_account_email


_resolve_calendar_id = google_calendar_domain.resolve_calendar_id


_norm_google_dt = google_calendar_domain.normalize_datetime


_google_calendar_ready = google_calendar_domain.is_ready


_get_google_calendar_service = google_calendar_domain.build_service


async def execute_calendar_list(args: dict) -> dict:
    return await google_calendar_domain.list_events(args)


async def execute_calendar_create(args: dict) -> dict:
    return await google_calendar_domain.create_event(args)


async def execute_calendar_delete(args: dict) -> dict:
    return await google_calendar_domain.delete_event(args)


async def execute_calendar_update(args: dict) -> dict:
    return await google_calendar_domain.update_event(args)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9B — Google Drive
# ══════════════════════════════════════════════════════════════════════════════



async def execute_google_drive_list(args: dict) -> dict:
    return await google_drive_domain.list_files(args)


async def execute_google_drive_read(args: dict) -> dict:
    return await google_drive_domain.read_file(args)


async def execute_google_drive_upload(args: dict) -> dict:
    return await google_drive_domain.upload_file(args, resolve_path=_resolve_path)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — Microsoft OneDrive
# ══════════════════════════════════════════════════════════════════════════════



async def execute_onedrive_list(args: dict) -> dict:
    return await onedrive_domain.list_files(args)


async def execute_onedrive_read(args: dict) -> dict:
    return await onedrive_domain.read_file(args)


async def execute_onedrive_upload(args: dict) -> dict:
    return await onedrive_domain.upload_file(args, resolve_path=_resolve_path)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION R — Réseau & Connectivité
# ══════════════════════════════════════════════════════════════════════════════

import socket as _socket
import ipaddress as _ipaddress













# ══════════════════════════════════════════════════════════════════════════════
# SECTION RÉSEAU PRO — diagnostic avancé (nmap optionnel, TLS, HTTP, sweep, routage).
# Porté depuis un fork parallèle du même projet (secretary-ai-codex-groky-alpha) après
# audit : code propre, garde-fous existants (scans larges → confirmation obligatoire,
# limites de ports/hôtes). Adapté aux imports/conventions de ce fichier.
# ══════════════════════════════════════════════════════════════════════════════



































# ══════════════════════════════════════════════════════════════════════════════
# INVENTAIRE MATÉRIEL + liens officiels constructeur — porté du même fork que la
# section réseau. Utile pour un technicien : identifie la machine (marque/modèle/
# n° série) et propose les bons liens support/pilotes selon le fabricant détecté.
# ══════════════════════════════════════════════════════════════════════════════















# v2.134 — 3 outils de diagnostic matériel/logiciel RÉEL, ajoutés suite à un audit d'une vraie
# conversation : le rapport de diagnostic PC affirmait "aucune alerte de surchauffe détectée"
# alors qu'AUCUN outil existant ne lit jamais de capteur de température — une hallucination
# (règle d'or #3) rendue possible par l'absence de la donnée elle-même. Ces 3 outils lisent des
# capteurs/journaux RÉELS plutôt que de laisser le modèle deviner.







# v2.137 — 2 outils demandés explicitement après l'audit v2.136 (« fait les 3 » — le 3ᵉ,
# le repli OAuth de calendar_list, est traité séparément plus bas).







async def capture_system_snapshot() -> dict:
    """Enregistre UN instantané de santé système dans `system_snapshots` (RAM/disque via
    psutil, usure SSD + erreurs récurrentes via les outils déjà existants). Appelé une fois
    par jour par le worker de fond (`main.py::_health_trend_worker`) — jamais depuis le chat
    directement. Best-effort : n'importe quel échec partiel (ex. SMART indisponible) n'empêche
    pas d'enregistrer les métriques qui ont réussi."""
    ram_percent = None
    disk_max_percent = None
    disk_max_drive = None
    try:
        ram_percent = psutil.virtual_memory().percent
        worst = None
        for dp in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(dp.mountpoint)
                if worst is None or u.percent > worst[1]:
                    worst = (dp.device, u.percent)
            except Exception:
                pass
        if worst:
            disk_max_drive, disk_max_percent = worst
    except Exception:
        pass

    disk_max_wear = None
    try:
        smart = await execute_pc_disk_smart_health({})
        if smart.get("success"):
            wears = [d.get("Wear") for d in smart.get("disks", []) if isinstance(d.get("Wear"), (int, float))]
            if wears:
                disk_max_wear = max(wears)
    except Exception:
        pass

    recurring_errors_count = 0
    try:
        events = await execute_pc_event_log_errors({"days": 1, "max_events": 50})
        if events.get("success"):
            recurring_errors_count = len(events.get("recurring_sources", []))
    except Exception:
        pass

    return db.save_system_snapshot(
        ram_percent=ram_percent,
        disk_max_percent=disk_max_percent,
        disk_max_percent_drive=disk_max_drive,
        disk_max_wear=disk_max_wear,
        recurring_errors_count=recurring_errors_count,
    )




async def execute_bug_log_list(args: dict) -> dict:
    return await runtime_observability_domain.bug_log_list(args)










# ══════════════════════════════════════════════════════════════════════════════
# Connecteurs ITSM/ticketing (v2.139) — architecture GÉNÉRIQUE multi-produit, demandée
# explicitement (« les connecteurs doivent couvrir une large gamme de produit qui me seront
# utiles »). Un seul jeu d'outils (`itsm_ticket_list`/`itsm_ticket_create`/`itsm_asset_list`)
# avec un paramètre `system` qui sélectionne le backend — ajouter un nouveau produit (Zammad,
# osTicket, Freshservice...) ne touche QUE `_ITSM_BACKENDS`, jamais les outils eux-mêmes.
# GLPI implémenté en premier (celui réellement en cours de déploiement par l'utilisateur
# aujourd'hui) ; les autres retournent une erreur claire "pas encore implémenté" plutôt que
# d'échouer silencieusement ou d'halluciner un résultat.
# ══════════════════════════════════════════════════════════════════════════════

async def execute_itsm_ticket_list(args: dict) -> dict:
    return await itsm_domain.ticket_list(args)


async def execute_itsm_ticket_create(args: dict) -> dict:
    return await itsm_domain.ticket_create(args)


async def execute_itsm_asset_list(args: dict) -> dict:
    return await itsm_domain.asset_list(args)


async def execute_skill_learning_log(args: dict) -> dict:
    return await runtime_observability_domain.skill_learning_log(args)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION OCR — Extraction de texte par vision (llava-phi3)
# ══════════════════════════════════════════════════════════════════════════════

import local_image as local_image_runtime

logos_domain.configure(
    availability=local_image_runtime.is_available,
    generate_image=local_image_runtime.generate_logo_image,
    create_record=db.create_logo,
    list_records=db.list_logos,
    output_root=Path(__file__).resolve().parent.parent / "data" / "logos",
)
execute_logo_generate = logos_domain.generate
execute_logo_list = logos_domain.list_logos




# ══════════════════════════════════════════════════════════════════════════════
# SECTION ARCHIVES — Compression et extraction (ZIP/TAR)
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# SECTION EMAIL — Lecture IMAP et envoi SMTP
# ══════════════════════════════════════════════════════════════════════════════

def _all_email_cfgs() -> list[dict]:
    """Configs résolues des boîtes mail (mot de passe ou jeton OAuth frais)."""
    import email_accounts as _email_accounts
    return _email_accounts.list_resolved()


def _get_email_cfg(account: str | None = None) -> dict | None:
    """Config d'une boîte mail (multi-comptes). account = username ; sinon le 1er (défaut)."""
    import email_accounts as _email_accounts
    return _email_accounts.get(account, resolved=True)


def _list_email_accounts() -> list[dict]:
    """Liste des comptes (username/provider) pour le chat — sans mots de passe."""
    import email_accounts as _email_accounts
    return [_email_accounts.public(account) for account in _email_accounts.list_raw()]






email_messages_domain.configure(
    get_account=lambda account=None: _get_email_cfg(account),
    list_accounts=lambda: _all_email_cfgs(),
    list_public_accounts=lambda: _list_email_accounts(),
    fetch_inbox=lambda *args, **kwargs: email_manager_runtime.fetch_inbox(*args, **kwargs),
    fetch_email=lambda *args, **kwargs: email_manager_runtime.fetch_email(*args, **kwargs),
    search_emails=lambda *args, **kwargs: email_manager_runtime.search_emails(*args, **kwargs),
    send_email=lambda *args, **kwargs: email_manager_runtime.send_email(*args, **kwargs),
    generate=lambda prompt, **kwargs: _ollama_generate(prompt, **kwargs),
    network_error=lambda error, resource: _net_error(error, resource),
)
execute_email_accounts = email_messages_domain.accounts
execute_email_list = email_messages_domain.list_messages
execute_email_read = email_messages_domain.read
execute_email_search = email_messages_domain.search
execute_email_send = email_messages_domain.send
execute_email_draft_reply = email_messages_domain.draft_reply
execute_email_summarize = email_messages_domain.summarize
execute_email_digest = email_messages_domain.digest


email_automation_domain.configure(
    get_setting=lambda key: db.get_setting(key),
    set_setting=lambda key, value: db.set_setting(key, value),
    list_accounts=lambda: _all_email_cfgs(),
    fetch_inbox=lambda *args, **kwargs: email_manager_runtime.fetch_inbox(*args, **kwargs),
    fetch_email=lambda *args, **kwargs: email_manager_runtime.fetch_email(*args, **kwargs),
    draft_reply=lambda args: execute_email_draft_reply(args),
    send_email=lambda args: execute_email_send(args),
)
_email_automation_cfg = email_automation_domain.get_config
_email_effective_profile = email_automation_domain.effective_profile
execute_email_orchestrator_run = email_automation_domain.run
execute_email_outbox_flush = email_automation_domain.flush_outbox




email_productivity_domain.configure(
    get_account=lambda account=None: _get_email_cfg(account),
    fetch_email=lambda *args, **kwargs: email_manager_runtime.fetch_email(*args, **kwargs),
    fetch_attachment=lambda *args, **kwargs: email_manager_runtime.fetch_attachment(
        *args, **kwargs
    ),
    generate=lambda prompt, **kwargs: _ollama_generate(prompt, **kwargs),
    create_task=lambda args: execute_task_create(args),
    read_pdf=lambda args: execute_pdf_read(args),
    read_docx=lambda args: execute_docx_to_text(args),
    network_error=lambda error, resource: _net_error(error, resource),
)
execute_email_to_task = email_productivity_domain.to_task
execute_email_attachment_summary = email_productivity_domain.attachment_summary




email_monitoring_domain.configure(
    get_setting=lambda key: db.get_setting(key),
    set_setting=lambda key, value: db.set_setting(key, value),
    list_accounts=lambda: _all_email_cfgs(),
    fetch_inbox=lambda *args, **kwargs: email_manager_runtime.fetch_inbox(*args, **kwargs),
    move_email=lambda *args, **kwargs: email_manager_runtime.move_email(*args, **kwargs),
    mark_email=lambda *args, **kwargs: email_manager_runtime.mark_email(*args, **kwargs),
    generate=lambda prompt, **kwargs: _ollama_generate(prompt, **kwargs),
    desktop_notify=lambda args: execute_pc_notify(args),
    telegram_notify=lambda text: _telegram_notify(text),
)
execute_email_watch_check = email_monitoring_domain.watch_check
execute_email_apply_rules = email_monitoring_domain.apply_rules


# ─────────────────────── Briefing du jour (assistant) v2.47 ───────────────────────
_FR_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FR_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre"]




proactive_briefing.configure(
    list_tasks=lambda **kwargs: db.list_tasks(**kwargs),
    list_events=lambda **kwargs: db.list_events(**kwargs),
    list_accounts=lambda: _all_email_cfgs(),
    fetch_inbox=lambda *args, **kwargs: email_manager_runtime.fetch_inbox(*args, **kwargs),
    generate=lambda prompt, **kwargs: _ollama_generate(prompt, **kwargs),
    network_error=lambda error, resource: _net_error(error, resource),
)
execute_daily_briefing = proactive_briefing.build


# ══════════════════════════════════════════════════════════════════════════════
# SECTION AGENDA — Événements locaux (indépendant de Google Calendar)
# ══════════════════════════════════════════════════════════════════════════════

_now_iso = calendar_events_domain.now_iso
_period_range = calendar_events_domain.period_range


async def _ai_parse_when(text: str, model: str = None) -> dict:
    return await calendar_events_domain.parse_natural_when(
        text,
        generator=_ollama_generate,
        model=model,
        weekdays=_FR_JOURS,
        months=_FR_MOIS,
    )


async def execute_event_create(args: dict) -> dict:
    return await calendar_events_domain.create_event(
        args,
        storage=db,
        natural_parser=_ai_parse_when,
        google_ready=_google_calendar_ready,
        google_create=execute_calendar_create,
        google_sync=_sync_google_into_events,
    )


async def execute_event_list(args: dict) -> dict:
    return await calendar_events_domain.list_events(args, storage=db)


async def execute_event_update(args: dict) -> dict:
    return await calendar_events_domain.update_event(
        args,
        storage=db,
        google_update=execute_calendar_update,
        google_sync=_sync_google_into_events,
    )


async def execute_event_delete(args: dict) -> dict:
    return await calendar_events_domain.delete_event(
        args,
        storage=db,
        google_delete=execute_calendar_delete,
        google_sync=_sync_google_into_events,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION AGENDAS CONNECTÉS — Abonnements iCal (Google, Outlook, Apple, tout CalDAV)
# Lecture seule : synchronise les événements externes dans l'agenda local → Marvin
# en est « au courant » dans le briefing, l'agenda et les recherches.
# ══════════════════════════════════════════════════════════════════════════════

def _calendar_subs() -> list:
    return calendar_subscriptions_domain.load_subscriptions(storage=db)


def _save_calendar_subs(subs: list):
    calendar_subscriptions_domain.save_subscriptions(subs, storage=db)


_parse_ics = calendar_subscriptions_domain.parse_ics


_fetch_ics = calendar_subscriptions_domain.fetch_ics


async def _sync_subscription(sub: dict) -> dict:
    return await calendar_subscriptions_domain.sync_subscription(sub, storage=db)


async def execute_calendar_subscribe(args: dict) -> dict:
    return await calendar_subscriptions_domain.subscribe(args, storage=db)


async def execute_calendar_subscriptions(args: dict) -> dict:
    return await calendar_subscriptions_domain.list_subscriptions(args, storage=db)


async def execute_calendar_unsubscribe(args: dict) -> dict:
    return await calendar_subscriptions_domain.unsubscribe(args, storage=db)


async def _sync_google_into_events() -> dict:
    return await calendar_subscriptions_domain.sync_google(
        storage=db,
        service_factory=_get_google_calendar_service,
        calendar_id_resolver=_resolve_calendar_id,
    )


async def execute_calendar_sync(args: dict) -> dict:
    return await calendar_subscriptions_domain.sync_all(
        args,
        storage=db,
        google_synchronizer=lambda **kwargs: calendar_subscriptions_domain.sync_google(
            service_factory=_get_google_calendar_service,
            calendar_id_resolver=_resolve_calendar_id,
            **kwargs,
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION DOCUMENTS — « Parle à tes documents » (RAG : indexation + Q/R sourcée)
# Indexe PDF/Word/Excel/texte en local (embeddings nomic-embed-text + Qdrant) puis
# répond aux questions en citant les passages. 100 % local et privé.
# ══════════════════════════════════════════════════════════════════════════════








# v2.143 — RAG AGENTIQUE (2ᵉ passe de retrieval si la 1ʳᵉ ne suffit pas), au lieu d'une
# recherche unique figée. Recherche 2026 (cf. mémoire session) : « agentic RAG » — le
# modèle DÉCIDE si le contexte récupéré suffit, sinon reformule et récupère à nouveau —
# remplace le retrieval linéaire pour les questions complexes. Coût borné : AU PLUS 1
# passe supplémentaire + 1 petit appel de jugement (pas une boucle non bornée comme
# `web_deep_research`, le corpus local est petit — pas besoin de 6 passes).





# ══════════════════════════════════════════════════════════════════════════════
# SECTION NOTIFICATIONS EXTERNES — Telegram (recevoir les alertes sur le téléphone)
# ══════════════════════════════════════════════════════════════════════════════

telegram_domain.configure(get_setting=db.get_setting)
_telegram_cfg = telegram_domain.get_config
_send_telegram = telegram_domain.send
_telegram_notify = telegram_domain.notify
execute_telegram_send = telegram_domain.execute_send


# ══════════════════════════════════════════════════════════════════════════════
# SECTION WEB NAVIGATEUR — Accès web par VRAI navigateur (contourne l'anti-bot)
# ══════════════════════════════════════════════════════════════════════════════





# v2.142 — « Deep Research » : équivalent du mode phare des IA payantes 2026 (ChatGPT
# Deep Research, Claude Research, Gemini Deep Research, Perplexity Deep Research). Se
# distingue de `web_research` (1 recherche + quelques pages + 1 synthèse, quelques
# secondes) par une boucle MULTI-PASSES : après chaque round, un modèle juge si les
# sources trouvées suffisent, sinon propose une requête complémentaire CIBLÉE sur ce
# qui manque encore — jusqu'à `max_rounds` fois. Rapport final structuré avec citations
# numérotées. Volontairement un outil SÉPARÉ (pas un remplacement de web_research) :
# plusieurs minutes d'exécution, à réserver aux demandes explicites de recherche
# approfondie/exhaustive, jamais déclenché par défaut sur une question simple.


# Council : panel parallèle, critique et arbitrage vivent dans une frontière injectable.
model_council_runtime.configure(
    routing=cloud_routing_runtime,
    get_setting=db.get_setting,
    ollama_url=OLLAMA_URL,
)
execute_ai_model_council = model_council_runtime.run


# v2.214 — Cortex Search explore plusieurs stratégies, puis les soumet à cinq
# vérificateurs spécialisés avant arbitrage. Déclenchement explicite uniquement.
async def execute_ai_cortex_search(args: dict) -> dict:
    question = (args.get("question") or args.get("query") or "").strip()
    evidence = (args.get("evidence") or args.get("context") or "").strip()
    try:
        candidate_count = int(args.get("candidate_count") or 3)
    except (TypeError, ValueError):
        candidate_count = 3
    import cortex_search
    return await cortex_search.execute(question, evidence=evidence, candidate_count=candidate_count)


async def execute_ai_research_swarm(args: dict) -> dict:
    """Recherche Web adaptative avec cinq rôles Cloud et gate de preuves."""
    question = (args.get("question") or args.get("query") or "").strip()
    try:
        agent_count = int(args.get("agent_count") or 5)
        sources_per_agent = int(args.get("sources_per_agent") or 3)
        max_duration_seconds = int(args.get("max_duration_seconds") or 900)
    except (TypeError, ValueError):
        agent_count, sources_per_agent, max_duration_seconds = 5, 3, 900
    import research_swarm
    return await research_swarm.execute(
        question,
        agent_count=agent_count,
        sources_per_agent=sources_per_agent,
        engine_version=str(args.get("engine_version") or "auto"),
        max_duration_seconds=max_duration_seconds,
        research_options={
            key: args.get(key)
            for key in (
                "depth", "language", "region", "freshness", "source_policy",
                "preferred_domains", "excluded_domains", "deliverable",
            )
            if args.get(key) is not None
        },
    )


async def execute_ai_adaptive_team(args: dict) -> dict:
    """Compose automatiquement Research Swarm, Cortex Search ou Council selon le problème."""
    question = (args.get("question") or args.get("query") or "").strip()
    import adaptive_team
    return await adaptive_team.execute(question)


async def execute_ai_code_forge(args: dict) -> dict:
    """Produit un livrable code revu, testé en bac à sable puis validé."""
    request = (args.get("request") or args.get("question") or args.get("query") or "").strip()
    evidence = (args.get("evidence") or args.get("context") or "").strip()
    mission_id = str(args.get("mission_id") or "").strip()
    import code_forge
    return await code_forge.execute(request, evidence=evidence, mission_id=mission_id)


async def execute_ai_test_forge(args: dict) -> dict:
    """Analyse puis exécute un livrable dans Docker ou une VM native jetable."""
    code = str(args.get("code") or "")
    language = str(args.get("language") or "")
    test_code = str(args.get("test_code") or args.get("tests") or "")
    integration_test_code = str(args.get("integration_test_code") or "")
    files = args.get("files") if isinstance(args.get("files"), dict) else None
    require_online = bool(args.get("require_online"))
    try:
        timeout_seconds = int(args.get("timeout_seconds") or 90)
    except (TypeError, ValueError):
        timeout_seconds = 90
    import test_forge
    return await asyncio.to_thread(
        test_forge.execute,
        code,
        language,
        test_code=test_code,
        integration_test_code=integration_test_code,
        require_online=require_online,
        timeout_seconds=timeout_seconds,
        files=files,
    )


async def execute_code_workspace_start(args: dict) -> dict:
    """Create or resume a durable Code Workspace mission from the chat."""
    import coding_service
    try:
        # coding_jobs.create_job() programme le superviseur avec
        # asyncio.create_task(). Il doit donc rester sur la boucle FastAPI
        # courante et ne peut pas être déporté dans un thread de travail.
        return coding_service.start(
            str(args.get("request") or args.get("question") or ""),
            repository_path=str(args.get("repository_path") or ""),
            target_mode=str(args.get("target_mode") or "auto"),
            autonomy=str(args.get("autonomy") or "autonomous"),
            max_duration_minutes=int(args.get("max_duration_minutes") or 120),
            max_iterations=int(args.get("max_iterations") or 12),
            max_files_changed=int(args.get("max_files_changed") or 50),
            create_worktree=True,
            start_auto=str(args.get("autonomy") or "autonomous") == "autonomous",
            confirmed=bool(args.get("confirmed")),
            conversation_id=str(args.get("_conversation_id") or ""),
        )
    except (TypeError, ValueError, coding_service.CodingServiceError) as exc:
        return {"success": False, "error": str(exc)}


async def execute_code_workspace_status(args: dict) -> dict:
    """Read Code Workspace missions and evidence without changing them."""
    import coding_service
    try:
        return await asyncio.to_thread(coding_service.status, str(args.get("mission_id") or ""))
    except coding_service.CodingServiceError as exc:
        return {"success": False, "error": str(exc)}


async def execute_code_workspace_control(args: dict) -> dict:
    """Resume or cancel the persistent Auto job associated with a coding mission."""
    import coding_service
    try:
        # resume_job() relance lui aussi une tâche asyncio persistante.
        return coding_service.control(
            str(args.get("mission_id") or ""),
            str(args.get("action") or ""),
            confirmed=bool(args.get("confirmed")),
        )
    except (ValueError, coding_service.CodingServiceError) as exc:
        return {"success": False, "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION VOICE — Transcription audio (faster-whisper)
# ══════════════════════════════════════════════════════════════════════════════

def _configured_whisper_model() -> str:
    try:
        configured = db.get_setting("whisper_model")
        if configured and str(configured).strip():
            return str(configured).strip()
    except Exception:
        pass
    return os.getenv("WHISPER_MODEL", "small")


voice_transcription_runtime.configure(model_provider=_configured_whisper_model)


async def execute_voice_transcribe(args: dict) -> dict:
    """Transcrit un fichier audio local en texte via Whisper (faster-whisper)."""
    audio_path = str(args.get("audio_path") or "").strip()
    if not audio_path:
        return {"success": False, "error": "Paramètre 'audio_path' requis."}
    resolved = _resolve_path(audio_path)
    return await voice_transcription_runtime.transcribe_file(
        resolved,
        model_name=args.get("model"),
        language=args.get("language"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION SSH — façade vers tool_domains/ssh.py
# ══════════════════════════════════════════════════════════════════════════════

_ssh_load_key = ssh_transport.load_private_key
_ssh_connect = ssh_transport.connect
ssh_domain.configure(resolve_path=_resolve_path, format_size=_fmt_bytes, home=_HOME)
_resolve_ssh_target = ssh_domain.resolve_target
execute_ssh_list = ssh_domain.list_connections
execute_ssh_connection_save = ssh_domain.save_connection
execute_ssh_exec = ssh_domain.execute
execute_ssh_exec_multi = ssh_domain.execute_multi
execute_ssh_write_and_run = ssh_domain.write_and_run
execute_ssh_upload = ssh_domain.upload
execute_ssh_download = ssh_domain.download
execute_ssh_list_dir = ssh_domain.list_dir
execute_ssh_server_info = ssh_domain.server_info

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — Outils Utilitaires (Calculateur, Date/Heure, Météo)
# ══════════════════════════════════════════════════════════════════════════════

execute_calculator = deterministic_utilities_domain.calculator


execute_datetime_info = datetime_tools_domain.datetime_info


execute_unit_convert = unit_conversion_domain.unit_convert

execute_password_generate = deterministic_utilities_domain.password_generate


# SECTION 15 — Outils de traitement de données
# ══════════════════════════════════════════════════════════════════════════════

async def execute_hash_compute(args: dict) -> dict:
    return await deterministic_utilities_domain.hash_compute(
        args, resolve_path=_resolve_path
    )


execute_base64_tool = deterministic_utilities_domain.base64_tool


execute_text_extract = text_processing_domain.text_extract
execute_diff_text = text_processing_domain.diff_text


execute_qr_generate = images_domain.qr_generate


execute_json_tool = deterministic_utilities_domain.json_tool


execute_markdown_convert = text_processing_domain.markdown_convert
execute_regex_tool = text_processing_domain.regex_tool
execute_csv_analyze = structured_data_domain.csv_analyze

execute_text_stats = deterministic_utilities_domain.text_stats


execute_ip_info = network_domain.execute_ip_info


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — Documents, Archives & Utilitaires couleur
# ══════════════════════════════════════════════════════════════════════════════



# ───────────────────────── PDF & Image toolkit (v2.34) ─────────────────────────









execute_file_large_finder = filesystem_domain.large_finder


def _system_cleanup_candidates() -> list[str]:
    import tempfile

    return [
        tempfile.gettempdir(),
        os.environ.get("TEMP", ""),
        os.environ.get("TMP", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp"),
        os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Temp"),
    ]


system_cleanup_domain.configure(
    candidate_paths=_system_cleanup_candidates,
    format_bytes=_fmt_bytes,
)
execute_system_cleanup = system_cleanup_domain.cleanup


# ───────────────────────── PDF avancé & lot d'images (v2.35) ─────────────────────





# ════════════════ PDF render/OCR/forms, PPTX, conversions, IA (v2.36) ════════════
generation_runtime.configure(
    routing=cloud_routing_runtime,
    base_url=OLLAMA_URL,
    model_profiles=MODEL_PROFILES,
    cloud_only_unavailable=cloud_routing_runtime.CloudOnlyModelUnavailable,
    context_admitter=ollama_context_admission.admit_local_context,
)
_ollama_generate = generation_runtime.generate


long_tasks_domain.configure(
    database=db,
    missions=mission_os_runtime,
    generate=_ollama_generate,
)
execute_long_task_start = long_tasks_domain.start
execute_long_task_status = long_tasks_domain.status
execute_long_task_stop = long_tasks_domain.stop

parallel_reasoning_runtime.configure(generate=_ollama_generate)
execute_ai_subagents_run = parallel_reasoning_runtime.run


def _detect_translation_language(text: str) -> str:
    try:
        from langdetect import detect

        return str(detect(text))
    except Exception:
        return "fr"


translation_domain.configure(
    generate=_ollama_generate,
    detect_language=_detect_translation_language,
    is_cloud_model=cloud_routing_runtime.is_cloud_model,
)
execute_translate = translation_domain.translate


documents_domain.configure_generation(
    text_generator=_ollama_generate,
    generated_dir=storage_roots()[1] / "documents",
)
execute_document_generate = documents_domain.generate
pdf_advanced_domain.configure(
    resolve_path=_resolve_path,
    text_generator=_ollama_generate,
    get_setting=db.get_setting,
)
execute_pdf_watermark = pdf_advanced_domain.watermark
execute_pdf_protect = pdf_advanced_domain.protect
execute_pdf_extract_images = pdf_advanced_domain.extract_images
execute_pdf_to_images = pdf_advanced_domain.to_images
execute_pdf_ocr = pdf_advanced_domain.ocr
execute_pdf_form_fields = pdf_advanced_domain.form_fields
execute_pdf_fill_form = pdf_advanced_domain.fill_form
execute_pdf_compress = pdf_advanced_domain.compress
execute_pdf_add_page_numbers = pdf_advanced_domain.add_page_numbers
document_knowledge_domain.configure(
    resolve_path=_resolve_path,
    get_setting=db.get_setting,
    set_setting=db.set_setting,
    text_generator=_ollama_generate,
    create_docx=execute_file_create_docx,
    vector_store=vector_store_runtime,
    generated_dir=storage_roots()[1] / "documents",
)
execute_document_index = document_knowledge_domain.index
execute_document_ask = document_knowledge_domain.ask
execute_document_list = document_knowledge_domain.list_documents
execute_document_forget = document_knowledge_domain.forget
execute_document_refine_section = document_knowledge_domain.refine_section








execute_pptx_create = presentations_domain.create
execute_pptx_read = presentations_domain.read


execute_docx_to_text = documents_domain.extract_docx_text

async def execute_text_summarize(args: dict) -> dict:
    """Résume un texte ou un document (txt/pdf/docx) via l'IA locale. style: bref|détaillé|puces|action."""
    text = args.get("text", "")
    src_path = args.get("path", "").strip()
    if src_path and not text:
        rp = Path(_resolve_path(src_path))
        if not rp.exists():
            return {"error": f"Fichier introuvable : {rp}"}
        ext = rp.suffix.lower()
        if ext == ".pdf":
            r = await execute_pdf_read({"path": str(rp), "max_chars": 12000})
            text = r.get("text") or r.get("content") or ""
        elif ext == ".docx":
            r = await execute_docx_to_text({"path": str(rp), "format": "text"})
            text = r.get("text", "")
        else:
            try:
                # Borné : ne JAMAIS charger un fichier entier (un .log de plusieurs Go saturerait la RAM)
                with open(rp, "r", encoding="utf-8", errors="replace") as _f:
                    text = _f.read(200_000)
            except Exception as e:
                return {"error": f"Lecture impossible : {e}"}
    if not text or len(text.strip()) < 20:
        return {"error": "Fournir 'text' (≥20 caractères) ou 'path' vers un document."}
    style = (args.get("style") or "bref").lower()
    style_instr = {
        "bref": "Résume en 3-4 phrases claires.",
        "détaillé": "Fais un résumé structuré et complet (paragraphes).",
        "detaille": "Fais un résumé structuré et complet (paragraphes).",
        "puces": "Résume sous forme de 5-8 puces concises.",
        "action": "Extrais les points d'action / décisions / tâches sous forme de liste.",
    }.get(style, "Résume en 3-4 phrases claires.")
    lang = args.get("language", "français")
    prompt = (f"Tu es un assistant qui synthétise. {style_instr} Réponds en {lang}, "
              f"uniquement le résumé sans préambule.\n\nTEXTE:\n{text[:12000]}")
    try:
        summary = await _ollama_generate(prompt, model=args.get("model"), timeout=180)
        return {"success": True, "summary": summary, "style": style,
                "source_chars": len(text), "source": src_path or None,
                "message": "Résumé généré."}
    except Exception as e:
        return _net_error(e, "résumé IA") if "_net_error" in globals() else {"error": str(e)}


# ════════════════ Synthèse vocale, PDF compress/numérotation, data→chart (v2.37) ═══════════
_TTS_VOICES = {
    "henri": "fr-FR-HenriNeural", "denise": "fr-FR-DeniseNeural", "eloise": "fr-FR-EloiseNeural",
    "vivienne": "fr-FR-VivienneMultilingualNeural", "remy": "fr-FR-RemyMultilingualNeural",
    "thierry": "fr-CA-ThierryNeural", "sylvie": "fr-CA-SylvieNeural",
    "en-femme": "en-US-AriaNeural", "en-homme": "en-US-GuyNeural",
}


async def execute_text_to_speech(args: dict) -> dict:
    """🔊 Génère un fichier audio (MP3) parlant à partir d'un texte, voix neurale (edge-tts, en ligne)."""
    text = (args.get("text") or "").strip()
    if not text:
        return {"error": "Paramètre 'text' requis."}
    voice = (args.get("voice") or "denise").lower()
    voice_id = _TTS_VOICES.get(voice, args.get("voice") if "-" in str(args.get("voice", "")) else "fr-FR-DeniseNeural")
    rate = args.get("rate", "+0%"); pitch = args.get("pitch", "+0Hz")
    # nettoyer le markdown pour une lecture propre
    for pat, rep in [(r"\*\*(.+?)\*\*", r"\1"), (r"\*(.+?)\*", r"\1"), (r"`([^`]+)`", r"\1"),
                     (r"#{1,6}\s+", ""), (r"\[([^\]]+)\]\([^\)]+\)", r"\1")]:
        text = _re.sub(pat, rep, text)
    if len(text) > 8000:
        text = text[:8000] + "…"
    out = _resolve_path(args.get("output_path", "").strip() or str(Path(_HOME) / "Desktop" / "synthese_vocale.mp3"))
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice_id, rate=rate, pitch=pitch)
        chunks = []
        async for ch in communicate.stream():
            if ch["type"] == "audio":
                chunks.append(ch["data"])
        data = b"".join(chunks)
        if not data:
            return {"error": "Aucun audio généré (voix ou texte invalide)."}
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(data)
        return {"success": True, "path": out, "destination": out, "voice": voice_id,
                "chars": len(text), "size_human": _fmt_bytes(len(data)),
                "message": f"Audio généré ({_fmt_bytes(len(data))}, voix {voice_id}) → {out}"}
    except Exception as e:
        return _net_error(e, "synthèse vocale") if "_net_error" in globals() else {"error": str(e)}





execute_csv_to_chart = structured_data_domain.csv_to_chart


execute_url_analyze = web_domain.execute_url_analyze


execute_zip_list = archives_domain.list_contents


execute_color_tool = deterministic_utilities_domain.color_tool


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 17 — SQLite, Git & Fichiers avancés
# ══════════════════════════════════════════════════════════════════════════════

execute_sqlite_query = structured_data_domain.sqlite_query
execute_sqlite_tables = structured_data_domain.sqlite_tables

execute_git_info = git_repository_domain.git_info


execute_bulk_rename = filesystem_domain.bulk_rename


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 18 — Outils composés & productivité
# ══════════════════════════════════════════════════════════════════════════════

screen_ocr_domain.configure(
    vision_ocr=execute_ocr_extract,
    is_cloud_model=cloud_routing_runtime.is_cloud_model,
    output_dir=_SYSTEM_PATHS["desktop"],
)
execute_screen_ocr = screen_ocr_domain.extract


execute_file_batch_read = filesystem_domain.batch_read


async def execute_clipboard_append(args: dict) -> dict:
    """Ajoute du texte au presse-papiers (append) sans écraser le contenu existant."""
    text      = args.get("text", "")
    separator = args.get("separator", "\n")
    if not text:
        return {"error": "Paramètre 'text' requis."}
    try:
        import pyperclip
        current = pyperclip.paste() or ""
        new_content = (current + separator + text) if current else text
        pyperclip.copy(new_content)
        return {
            "success":      True,
            "old_length":   len(current),
            "new_length":   len(new_content),
            "appended":     len(text),
        }
    except ImportError:
        return {"error": "pyperclip non installé. Utilisez pc_clipboard_set à la place."}
    except Exception as e:
        return {"error": str(e)}


execute_text_join = text_processing_domain.text_join

# SECTION 19 — calcul Python rapide en processus séparé. Le confinement système réel
# appartient à Test Forge/VM; cette façade annonce explicitement ses limites.
python_execution_runtime.configure(
    output_root=Path(__file__).resolve().parent.parent / "data" / "code_outputs",
    python_executable=sys.executable,
)
execute_code_python = python_execution_runtime.execute


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 20 — Assistant Devis / Facturation IT
# ══════════════════════════════════════════════════════════════════════════════





















# ══════════════════════════════════════════════════════════════════════════════
# SECTION 28 — Devis IT avancé : comparaison web, pricing, propositions, factures
# Inspiré des meilleures pratiques IT (TCO, SLA, récurrent) et commerciales
# (ancrage 3 paliers, valeur, ROI, marges cibles par segment).
# ══════════════════════════════════════════════════════════════════════════════

def _parse_price_number(raw: str) -> float | None:
    """Parse un nombre de prix issu du web (formats EU/US) → float robuste."""
    s = (raw or "").strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    has_dot, has_com = "." in s, "," in s
    try:
        if has_dot and has_com:
            # le dernier séparateur = décimal
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif has_com:
            # ',XX' final (2 chiffres) = décimal, sinon milliers
            if _re.search(r",\d{2}$", s):
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")
        elif has_dot:
            # '.XXX' (3 chiffres) = milliers EU ; '.XX' = décimal
            if _re.search(r"\.\d{3}(?:\D|$)", s) and not _re.search(r"\.\d{2}$", s):
                s = s.replace(".", "")
        return float(s)
    except Exception:
        return None


def v_has_no_sep(raw: str) -> bool:
    """True si le nombre n'a aucun séparateur (espace, virgule, point)."""
    return not any(c in raw for c in (" ", ",", ".", " "))




def _parse_int(raw: str) -> int | None:
    try:
        return int(_re.sub(r"[ \xa0.]", "", raw))
    except Exception:
        return None


























# Catalogue moderne : services IT actuels (cloud, cyber, RGPD, VoIP, BaaS…)




# Catalogues PRÉ-DÉFINIS par métier (devis utilisable hors IT)
# Format : (catégorie, nom, description, unité, prix_basic, prix_standard, prix_premium, coût, heures)




# ══════════════════════════════════════════════════════════════════════════════
# SECTION 29 — Base de connaissances IT consultable par Marvin
# Recommandations instantanées d'outils/logiciels sans recherche web → rapide & smart.
# Utilisée par le chat, l'Agent Documentation Technique et l'assistant Devis.
# ══════════════════════════════════════════════════════════════════════════════

execute_it_kb_search = it_knowledge_domain.search
execute_it_kb_list = it_knowledge_domain.list_entries
execute_it_kb_recommend = it_knowledge_domain.recommend
execute_it_kb_add = it_knowledge_domain.add


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 21 — Outils Windows Admin (Win11 / Windows Server)
# ══════════════════════════════════════════════════════════════════════════════

















# ══════════════════════════════════════════════════════════════════════════════
# SECTION 26 — v2.31 Windows Diagnostics avancés (Win11 / Server)
# ══════════════════════════════════════════════════════════════════════════════

# Cache léger pour les diagnostics qui changent lentement (TTL en secondes)













execute_file_duplicate_finder = filesystem_domain.duplicate_finder


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 27 — Média local : façade vers tool_domains/media.py
# ══════════════════════════════════════════════════════════════════════════════

media_domain.configure(resolve_path=_resolve_path)
execute_video_info = media_domain.video_info
execute_video_to_gif = media_domain.video_to_gif
execute_gif_to_video = media_domain.gif_to_video
execute_video_trim = media_domain.video_trim
execute_video_compress = media_domain.video_compress
execute_video_resize = media_domain.video_resize
execute_video_extract_frames = media_domain.video_extract_frames
execute_video_speed = media_domain.video_speed
execute_video_watermark = media_domain.video_watermark
execute_gif_optimize = media_domain.gif_optimize
execute_screen_record_gif = media_domain.screen_record_gif
execute_audio_info = media_domain.audio_info
execute_audio_extract = media_domain.audio_extract
execute_audio_convert = media_domain.audio_convert
execute_audio_trim = media_domain.audio_trim
execute_audio_merge = media_domain.audio_merge
execute_audio_volume = media_domain.audio_volume

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 22 — Agent IA Documentation Technique
# Transforme des interventions brutes en documentation professionnelle.
# ══════════════════════════════════════════════════════════════════════════════









































# ══════════════════════════════════════════════════════════════════════════════
# SECTION 23 — v2.30.0 Operations Safety : Command Safety / Guardrails
# Analyse de risque des commandes (PowerShell, CMD, Bash, Linux, Proxmox, Cisco, FW)
# NB : aucune commande n'est jamais exécutée ici — analyse statique uniquement.
# ══════════════════════════════════════════════════════════════════════════════















# ══════════════════════════════════════════════════════════════════════════════
# SECTION 24 — v2.30.0 Operations Safety : Pre-Check / Post-Check
# ══════════════════════════════════════════════════════════════════════════════

# Points de contrôle automatiques selon le type d'intervention

















# ══════════════════════════════════════════════════════════════════════════════
# SECTION 25 — v2.30.0 Operations Safety : Client Health Score
# ══════════════════════════════════════════════════════════════════════════════











# ══════════════════════════════════════════════════════════════════════════════
# SECTION 30 — Auto-diagnostic de Marvin
# ══════════════════════════════════════════════════════════════════════════════

system_self_test_domain.configure(registry_provider=lambda: TOOLS_REGISTRY)
execute_system_self_test = system_self_test_domain.run


async def execute_tool_search(
    query: str | dict[str, Any],
    limit: int = 10,
) -> dict[str, Any]:
    """Recherche le catalogue réel sans transformer le résultat en appel d'outil."""
    from capability_catalog import CapabilityCatalog

    # Le registre historique appelle chaque exécuteur avec un dictionnaire unique.
    # Conserver aussi l'appel positionnel facilite les tests et les usages internes.
    if isinstance(query, dict):
        arguments = query
        query = str(arguments.get("query") or "")
        try:
            limit = int(arguments.get("limit", limit))
        except (TypeError, ValueError, OverflowError):
            limit = 10
    return CapabilityCatalog(TOOLS_SPEC).search(query, limit=limit)


# ══════════════════════════════════════════════════════════════════════════════
# Fiches de révision / quiz (v2.155) — répétition espacée minimale (voir database.py)
# ══════════════════════════════════════════════════════════════════════════════

async def execute_quiz_generate(args: dict) -> dict:
    return await quiz_domain.generate(args, _ollama_generate)


execute_quiz_next = quiz_domain.next_card
execute_quiz_answer = quiz_domain.answer
execute_quiz_stats = quiz_domain.stats


# ══════════════════════════════════════════════════════════════════════════════
execute_winget_search = winget_domain.execute_winget_search
execute_winget_list_upgrades = winget_domain.execute_winget_list_upgrades
execute_winget_list_installed = winget_domain.execute_winget_list_installed
execute_winget_install = winget_domain.execute_winget_install
execute_winget_upgrade = winget_domain.execute_winget_upgrade
execute_winget_uninstall = winget_domain.execute_winget_uninstall

pc_control_domain.configure(resolve_path=_resolve_path, format_size=_fmt_bytes)

execute_pc_app_launch = pc_control_domain.execute_pc_app_launch
execute_pc_tailscale_status = tailscale_domain.status
execute_pc_browse = pc_control_domain.execute_pc_browse
execute_pc_clipboard_get = pc_control_domain.execute_pc_clipboard_get
execute_pc_clipboard_set = pc_control_domain.execute_pc_clipboard_set
execute_pc_get_real_paths = pc_control_domain.execute_pc_get_real_paths
execute_pc_gui_click = pc_control_domain.execute_pc_gui_click
execute_pc_gui_read = pc_control_domain.execute_pc_gui_read
execute_pc_gui_type = pc_control_domain.execute_pc_gui_type
execute_computer_control = computer_runtime.execute
execute_pc_notify = pc_control_domain.execute_pc_notify
execute_pc_open_file = pc_control_domain.execute_pc_open_file
execute_pc_process_kill = pc_control_domain.execute_pc_process_kill
execute_pc_process_list = pc_control_domain.execute_pc_process_list
execute_pc_pull_ollama_model = pc_control_domain.execute_pc_pull_ollama_model
execute_pc_reveal = pc_control_domain.execute_pc_reveal
execute_pc_run_command = pc_control_domain.execute_pc_run_command
execute_pc_run_elevated = pc_control_domain.execute_pc_run_elevated
execute_pc_run_powershell = pc_control_domain.execute_pc_run_powershell
execute_pc_screenshot = pc_control_domain.execute_pc_screenshot
execute_pc_system_info = pc_control_domain.execute_pc_system_info
execute_pc_window_focus = pc_control_domain.execute_pc_window_focus
execute_pc_window_list = pc_control_domain.execute_pc_window_list

execute_pc_conversation_trace = pc_diagnostics_domain.execute_pc_conversation_trace
execute_pc_disk_smart_health = pc_diagnostics_domain.execute_pc_disk_smart_health
execute_pc_driver_check = pc_diagnostics_domain.execute_pc_driver_check
execute_pc_event_log_errors = pc_diagnostics_domain.execute_pc_event_log_errors
execute_pc_gpu_status = pc_diagnostics_domain.execute_pc_gpu_status
execute_pc_hardware_specs = pc_diagnostics_domain.execute_pc_hardware_specs
execute_pc_hardware_temps = pc_diagnostics_domain.execute_pc_hardware_temps
execute_pc_health_trend = pc_diagnostics_domain.execute_pc_health_trend
execute_pc_installed_software = pc_diagnostics_domain.execute_pc_installed_software
execute_pc_tool_reliability = pc_diagnostics_domain.execute_pc_tool_reliability

windows_domain.configure(run_powershell=execute_pc_run_powershell)

execute_win_disk_info = windows_domain.execute_win_disk_info
execute_win_event_log = windows_domain.execute_win_event_log
execute_win_firewall_status = windows_domain.execute_win_firewall_status
execute_win_network_config = windows_domain.execute_win_network_config
execute_win_quick_launch = windows_domain.execute_win_quick_launch
execute_win_quick_launch_list = windows_domain.execute_win_quick_launch_list
execute_win_scheduled_tasks = windows_domain.execute_win_scheduled_tasks
execute_win_service_action = windows_domain.execute_win_service_action
execute_win_services_list = windows_domain.execute_win_services_list
execute_win_startup_programs = windows_domain.execute_win_startup_programs
execute_win_system_report = windows_domain.execute_win_system_report
execute_win_update_status = windows_domain.execute_win_update_status
execute_win_uptime = windows_domain.execute_win_uptime
execute_win_users_list = windows_domain.execute_win_users_list

windows_registry_domain.configure(run_powershell=execute_pc_run_powershell)
_ps_reg_to_native = windows_registry_domain._ps_reg_to_native
_reg_backup = windows_registry_domain._reg_backup
execute_system_restore_point = windows_registry_domain.execute_system_restore_point
execute_registry_get = windows_registry_domain.execute_registry_get
execute_registry_backup = windows_registry_domain.execute_registry_backup
execute_registry_set = windows_registry_domain.execute_registry_set

windows_tweaks_domain.configure(
    run_powershell=execute_pc_run_powershell,
    registry_get=execute_registry_get,
    reg_backup=_reg_backup,
)
execute_tweak_telemetry = windows_tweaks_domain.execute_tweak_telemetry
execute_tweak_debloat_list = windows_tweaks_domain.execute_tweak_debloat_list
execute_tweak_debloat_remove = windows_tweaks_domain.execute_tweak_debloat_remove
execute_tweak_network_harden = windows_tweaks_domain.execute_tweak_network_harden

catharsis_domain.configure(run_powershell=execute_pc_run_powershell)
execute_catharsis_scan = catharsis_domain.execute_catharsis_scan
execute_catharsis_clean = catharsis_domain.execute_catharsis_clean

windows_settings_domain.configure(
    run_powershell=execute_pc_run_powershell,
    registry_get=execute_registry_get,
)
execute_os_power_plan = windows_settings_domain.execute_os_power_plan
execute_os_dark_mode = windows_settings_domain.execute_os_dark_mode
execute_os_firewall = windows_settings_domain.execute_os_firewall
execute_os_network_adapters = windows_settings_domain.execute_os_network_adapters
execute_os_hibernation = windows_settings_domain.execute_os_hibernation

windows_devices_domain.configure(run_powershell=execute_pc_run_powershell)
execute_pc_printer_list = windows_devices_domain.execute_pc_printer_list
execute_pc_printer_set_default = windows_devices_domain.execute_pc_printer_set_default
execute_pc_usb_list = windows_devices_domain.execute_pc_usb_list
execute_pc_bluetooth_status = windows_devices_domain.execute_pc_bluetooth_status

network_domain.configure(win_network_config=execute_win_network_config)

execute_net_ping = network_domain.execute_net_ping
execute_net_port_scan = network_domain.execute_net_port_scan
execute_net_dns_lookup = network_domain.execute_net_dns_lookup
execute_net_traceroute = network_domain.execute_net_traceroute
execute_net_scan_local = network_domain.execute_net_scan_local
execute_net_whois = network_domain.execute_net_whois
execute_net_nmap_scan = network_domain.execute_net_nmap_scan
execute_net_service_detect = network_domain.execute_net_service_detect
execute_net_http_probe = network_domain.execute_net_http_probe
execute_net_tls_check = network_domain.execute_net_tls_check
execute_net_tls_check_bulk = network_domain.execute_net_tls_check_bulk
execute_net_subnet_calc = network_domain.execute_net_subnet_calc
execute_net_snmp_query = network_domain.execute_net_snmp_query
execute_net_topology_diagram = network_domain.execute_net_topology_diagram
execute_net_subnet_sweep = network_domain.execute_net_subnet_sweep
execute_net_route_diagnostics = network_domain.execute_net_route_diagnostics
execute_net_inventory_scan = network_domain.execute_net_inventory_scan
execute_net_inventory_list = network_domain.execute_net_inventory_list
execute_net_inventory_annotate = network_domain.execute_net_inventory_annotate


web_domain.configure(
    generate=_ollama_generate, get_setting=db.get_setting,
    get_http_client=_get_http_client, cache_get=_wcache_get, cache_set=_wcache_set,
    net_error=_net_error,
)
weather_domain.configure(
    get_http_client=_get_http_client,
    cache_get=_wcache_get,
    cache_set=_wcache_set,
    net_error=_net_error,
)

execute_web_browse = web_domain.execute_web_browse
execute_web_site_crawl = web_domain.execute_web_site_crawl
execute_web_media_extract = web_media_domain.extract
execute_web_browser_open = web_domain.execute_web_browser_open
execute_web_deep_research = web_domain.execute_web_deep_research
execute_web_research = web_domain.execute_web_research
execute_web_search = web_domain.execute_web_search
execute_weather = weather_domain.weather

unified_search_domain.configure(
    vector_search=vector_store_runtime.search,
    system_search=execute_system_search,
    system_search_content=execute_system_search_content,
    list_notes=db.list_notes,
    list_tasks=db.list_tasks,
    list_events=db.list_events,
    memory_recall=learning.recall,
    email_search=execute_email_search,
    web_search=execute_web_search,
)
execute_unified_search = unified_search_domain.search

pc_diagnostics_domain.configure(
    run_powershell=execute_pc_run_powershell, web_search=execute_web_search
)

billing_domain.configure(
    web_search=execute_web_search, file_create_pdf=execute_file_create_pdf
)

execute_billing_analyze_need = billing_domain.execute_billing_analyze_need
execute_billing_catalog_enrich = billing_domain.execute_billing_catalog_enrich
execute_billing_catalog_list = billing_domain.execute_billing_catalog_list
execute_billing_client_create = billing_domain.execute_billing_client_create
execute_billing_client_list = billing_domain.execute_billing_client_list
execute_billing_find_products = billing_domain.execute_billing_find_products
execute_billing_generate_proposal = billing_domain.execute_billing_generate_proposal
execute_billing_invoice_create = billing_domain.execute_billing_invoice_create
execute_billing_invoice_list = billing_domain.execute_billing_invoice_list
execute_billing_invoice_mark_paid = billing_domain.execute_billing_invoice_mark_paid
execute_billing_market_research = billing_domain.execute_billing_market_research
execute_billing_price_recommendation = billing_domain.execute_billing_price_recommendation
execute_billing_product_reviews = billing_domain.execute_billing_product_reviews
execute_billing_quote_compare = billing_domain.execute_billing_quote_compare
execute_billing_quote_create = billing_domain.execute_billing_quote_create
execute_billing_quote_email = billing_domain.execute_billing_quote_email
execute_billing_quote_list = billing_domain.execute_billing_quote_list
execute_billing_quote_pdf = billing_domain.execute_billing_quote_pdf
execute_billing_revenue_dashboard = billing_domain.execute_billing_revenue_dashboard
execute_billing_seed_trade = billing_domain.execute_billing_seed_trade
execute_billing_tco_analysis = billing_domain.execute_billing_tco_analysis
execute_billing_tier_breakdown = billing_domain.execute_billing_tier_breakdown


_detect_command_platform = command_safety_domain._detect_command_platform
_analyze_command_risk = command_safety_domain._analyze_command_risk
execute_cmd_extract_from_text = command_safety_domain.execute_cmd_extract_from_text
execute_cmd_analyze_risk = command_safety_domain.execute_cmd_analyze_risk
execute_cmd_suggest_safer_alternative = command_safety_domain.execute_cmd_suggest_safer_alternative
execute_cmd_require_approval = command_safety_domain.execute_cmd_require_approval
execute_cmd_review_history = command_safety_domain.execute_cmd_review_history

intervention_docs_domain.configure(
    file_create_docx=execute_file_create_docx, file_create_pdf=execute_file_create_pdf,
    cmd_extract=execute_cmd_extract_from_text, analyze_risk=_analyze_command_risk,
)

execute_doc_analyze_input = intervention_docs_domain.execute_doc_analyze_input
execute_doc_asset_create = intervention_docs_domain.execute_doc_asset_create
execute_doc_asset_list = intervention_docs_domain.execute_doc_asset_list
execute_doc_generate_change = intervention_docs_domain.execute_doc_generate_change
execute_doc_generate_client_sheet = intervention_docs_domain.execute_doc_generate_client_sheet
execute_doc_generate_maintenance = intervention_docs_domain.execute_doc_generate_maintenance
execute_doc_generate_onboarding = intervention_docs_domain.execute_doc_generate_onboarding
execute_doc_generate_postmortem = intervention_docs_domain.execute_doc_generate_postmortem
execute_doc_generate_procedure = intervention_docs_domain.execute_doc_generate_procedure
execute_doc_generate_recovery_plan = intervention_docs_domain.execute_doc_generate_recovery_plan
execute_doc_generate_report = intervention_docs_domain.execute_doc_generate_report
execute_doc_generate_runbook = intervention_docs_domain.execute_doc_generate_runbook
execute_doc_generate_schema = intervention_docs_domain.execute_doc_generate_schema
execute_doc_intervention_create = intervention_docs_domain.execute_doc_intervention_create
execute_doc_intervention_list = intervention_docs_domain.execute_doc_intervention_list
execute_doc_intervention_update = intervention_docs_domain.execute_doc_intervention_update
execute_doc_knowledge_search = intervention_docs_domain.execute_doc_knowledge_search
execute_doc_template_list = intervention_docs_domain.execute_doc_template_list

operations_safety_domain.configure(
    file_create_docx=execute_file_create_docx,
    file_create_pdf=execute_file_create_pdf,
)
execute_ops_checklist_generate = operations_safety_domain.execute_ops_checklist_generate
execute_ops_precheck_create = operations_safety_domain.execute_ops_precheck_create
execute_ops_precheck_run = operations_safety_domain.execute_ops_precheck_run
execute_ops_postcheck_run = operations_safety_domain.execute_ops_postcheck_run
execute_ops_evidence_add = operations_safety_domain.execute_ops_evidence_add
execute_ops_validation_report_generate = operations_safety_domain.execute_ops_validation_report_generate

client_health_domain.configure(
    file_create_docx=execute_file_create_docx,
    file_create_pdf=execute_file_create_pdf,
)
execute_client_health_compute = client_health_domain.execute_client_health_compute
execute_client_health_get = client_health_domain.execute_client_health_get
execute_client_health_history = client_health_domain.execute_client_health_history
execute_client_recommendations_generate = client_health_domain.execute_client_recommendations_generate
execute_client_monthly_summary_generate = client_health_domain.execute_client_monthly_summary_generate

# Organisation de l'espace Marvin (projets et conversations).
execute_project_list = workspace_organization_domain.execute_project_list
execute_project_create = workspace_organization_domain.execute_project_create
execute_project_update = workspace_organization_domain.execute_project_update
execute_project_delete = workspace_organization_domain.execute_project_delete
execute_conversation_list = workspace_organization_domain.execute_conversation_list
execute_conversation_search = workspace_organization_domain.execute_conversation_search
execute_conversation_move = workspace_organization_domain.execute_conversation_move
execute_conversation_move_many = workspace_organization_domain.execute_conversation_move_many
execute_conversation_update = workspace_organization_domain.execute_conversation_update


async def execute_conversation_export(args: dict[str, Any]) -> dict[str, Any]:
    """Exporte une conversation depuis sa representation persistante canonique."""
    conversation_id = str(args.get("conversation_id") or args.get("_conversation_id") or "").strip()
    if not conversation_id:
        return {"needsClarification": True, "message": "Quelle conversation dois-je exporter ?"}
    try:
        return await asyncio.to_thread(
            export_conversation,
            conversation_id,
            str(args.get("format") or "md"),
            str(args.get("mode") or "lecture"),
        )
    except (OSError, ValueError, RuntimeError) as error:
        return {"error": str(error)}


# REGISTRE DES OUTILS
# ══════════════════════════════════════════════════════════════════════════════

TOOLS_REGISTRY: dict[str, Any] = {
    "quiz_generate": execute_quiz_generate,
    "quiz_next":     execute_quiz_next,
    "quiz_answer":   execute_quiz_answer,
    "quiz_stats":    execute_quiz_stats,
    "system_self_test": execute_system_self_test,
    "conversation_export": execute_conversation_export,
    "tool_search": execute_tool_search,
    "file_list": execute_file_list,
    "file_info": execute_file_info,
    "file_read": execute_file_read,
    "file_write": execute_file_write,
    "file_delete": execute_file_delete,
    "file_rename": execute_file_rename,
    "file_move": execute_file_move,
    "file_copy": execute_file_copy,
    "file_create_folder": execute_file_create_folder,
    "file_create_docx": execute_file_create_docx,
    "document_identity_set": execute_document_identity_set,
    "screenshot_list": execute_screenshot_list,
    "doc_generate_from_screenshots": execute_doc_generate_from_screenshots,
    "logo_generate": execute_logo_generate,
    "logo_list": execute_logo_list,
    "file_convert_docx_to_pdf": execute_file_convert_docx_to_pdf,
    "document_convert_format": execute_document_convert_format,
    "file_search_text": execute_file_search_text,
    "file_find":        execute_file_find,
    "system_search":    execute_system_search,
    "system_search_content": execute_system_search_content,
    "webapp_create": execute_webapp_create,
    "pc_open_file": execute_pc_open_file,
    "pc_reveal": execute_pc_reveal,
    "pc_browse": execute_pc_browse,
    "pc_app_launch": execute_pc_app_launch,
    "pc_tailscale_status": execute_pc_tailscale_status,
    "pc_run_command":     execute_pc_run_command,
    "pc_run_powershell":  execute_pc_run_powershell,
    "pc_run_elevated":    execute_pc_run_elevated,
    "winget_search":          execute_winget_search,
    "winget_list_upgrades":   execute_winget_list_upgrades,
    "winget_list_installed":  execute_winget_list_installed,
    "winget_install":         execute_winget_install,
    "winget_upgrade":         execute_winget_upgrade,
    "winget_uninstall":       execute_winget_uninstall,
    "system_restore_point":   execute_system_restore_point,
    "registry_get":           execute_registry_get,
    "registry_backup":        execute_registry_backup,
    "registry_set":           execute_registry_set,
    "tweak_telemetry":        execute_tweak_telemetry,
    "tweak_debloat_list":     execute_tweak_debloat_list,
    "tweak_debloat_remove":   execute_tweak_debloat_remove,
    "tweak_network_harden":   execute_tweak_network_harden,
    "catharsis_scan":         execute_catharsis_scan,
    "catharsis_clean":        execute_catharsis_clean,
    "os_power_plan":          execute_os_power_plan,
    "os_dark_mode":           execute_os_dark_mode,
    "os_firewall":            execute_os_firewall,
    "os_network_adapters":    execute_os_network_adapters,
    "os_hibernation":         execute_os_hibernation,
    "pc_printer_list":        execute_pc_printer_list,
    "pc_printer_set_default": execute_pc_printer_set_default,
    "pc_usb_list":            execute_pc_usb_list,
    "pc_bluetooth_status":    execute_pc_bluetooth_status,
    "pc_system_info": execute_pc_system_info,
    "pc_screenshot": execute_pc_screenshot,
    "pc_window_list": execute_pc_window_list,
    "pc_window_focus": execute_pc_window_focus,
    "pc_gui_read": execute_pc_gui_read,
    "pc_gui_click": execute_pc_gui_click,
    "pc_gui_type": execute_pc_gui_type,
    "computer_control": execute_computer_control,
    "vm_lab_install": execute_vm_lab_install,
    "pc_notify": execute_pc_notify,
    "pc_pull_ollama_model": execute_pc_pull_ollama_model,
    "pc_clipboard_get": execute_pc_clipboard_get,
    "pc_clipboard_set": execute_pc_clipboard_set,
    "pc_process_list": execute_pc_process_list,
    "pc_process_kill": execute_pc_process_kill,
    "project_list": execute_project_list,
    "project_create": execute_project_create,
    "project_update": execute_project_update,
    "project_delete": execute_project_delete,
    "conversation_list": execute_conversation_list,
    "conversation_search": execute_conversation_search,
    "conversation_move": execute_conversation_move,
    "conversation_move_many": execute_conversation_move_many,
    "conversation_update": execute_conversation_update,
    "task_create": execute_task_create,
    "task_list": execute_task_list,
    "task_update": execute_task_update,
    "task_delete": execute_task_delete,
    "note_create": execute_note_create,
    "note_list": execute_note_list,
    "note_update": execute_note_update,
    "note_delete": execute_note_delete,
    "memory_save": execute_memory_save,
    "memory_list": execute_memory_list,
    "memory_delete": execute_memory_delete,
    "memory_search": execute_memory_search,
    "search_semantic": execute_search_semantic,
    # PC — découverte
    "pc_get_real_paths": execute_pc_get_real_paths,
    # Web
    "web_search": execute_web_search,
    "web_browse": execute_web_browse,
    "web_site_crawl": execute_web_site_crawl,
    "web_media_extract": execute_web_media_extract,
    # Documents avancés
    "infographic_create": execute_infographic_create,
    "file_create_xlsx": execute_file_create_xlsx,
    "file_create_pdf": execute_file_create_pdf,
    # Google Calendar
    "calendar_list":   execute_calendar_list,
    "calendar_create": execute_calendar_create,
    "calendar_update": execute_calendar_update,
    "calendar_delete": execute_calendar_delete,
    # Google Drive
    "google_drive_list": execute_google_drive_list,
    "google_drive_read": execute_google_drive_read,
    "google_drive_upload": execute_google_drive_upload,
    # OneDrive
    "onedrive_list": execute_onedrive_list,
    "onedrive_read": execute_onedrive_read,
    "onedrive_upload": execute_onedrive_upload,
    # Réseau
    "net_ping": execute_net_ping,
    "net_port_scan": execute_net_port_scan,
    "net_dns_lookup": execute_net_dns_lookup,
    "net_traceroute": execute_net_traceroute,
    "net_scan_local": execute_net_scan_local,
    "net_whois": execute_net_whois,
    "net_nmap_scan":         execute_net_nmap_scan,
    "net_service_detect":    execute_net_service_detect,
    "net_http_probe":        execute_net_http_probe,
    "net_tls_check":         execute_net_tls_check,
    "net_tls_check_bulk":    execute_net_tls_check_bulk,
    "net_subnet_calc":       execute_net_subnet_calc,
    "net_subnet_sweep":      execute_net_subnet_sweep,
    "net_route_diagnostics": execute_net_route_diagnostics,
    "net_snmp_query":        execute_net_snmp_query,
    "net_topology_diagram":  execute_net_topology_diagram,
    "pc_hardware_specs":     execute_pc_hardware_specs,
    "pc_gpu_status":         execute_pc_gpu_status,
    "pc_hardware_temps":     execute_pc_hardware_temps,
    "pc_disk_smart_health":  execute_pc_disk_smart_health,
    "pc_event_log_errors":   execute_pc_event_log_errors,
    "win_firewall_status":   execute_win_firewall_status,
    "pc_driver_check":       execute_pc_driver_check,
    "pc_health_trend":       execute_pc_health_trend,
    "pc_tool_reliability":   execute_pc_tool_reliability,
    "bug_log_list":          execute_bug_log_list,
    "pc_conversation_trace": execute_pc_conversation_trace,
    "net_inventory_scan":    execute_net_inventory_scan,
    "net_inventory_list":    execute_net_inventory_list,
    "net_inventory_annotate": execute_net_inventory_annotate,
    "itsm_ticket_list":      execute_itsm_ticket_list,
    "itsm_ticket_create":    execute_itsm_ticket_create,
    "itsm_asset_list":       execute_itsm_asset_list,
    "skill_learning_log":    execute_skill_learning_log,
    "win_quick_launch_list": execute_win_quick_launch_list,
    "win_quick_launch":      execute_win_quick_launch,
    # OCR
    "ocr_extract": execute_ocr_extract,
    # Archives
    "file_compress": execute_file_compress,
    "file_extract": execute_file_extract,
    # Email
    "email_accounts": execute_email_accounts,
    "email_list": execute_email_list,
    "email_read": execute_email_read,
    "email_search": execute_email_search,
    "email_send": execute_email_send,
    "email_draft_reply": execute_email_draft_reply,
    "email_summarize": execute_email_summarize,
    "email_digest": execute_email_digest,
    "email_automation_run": execute_email_orchestrator_run,
    "email_to_task": execute_email_to_task,
    "email_attachment_summary": execute_email_attachment_summary,
    "email_watch_check": execute_email_watch_check,
    "email_apply_rules": execute_email_apply_rules,
    "daily_briefing": execute_daily_briefing,
    # Agenda local
    "event_create": execute_event_create,
    "event_list": execute_event_list,
    "event_update": execute_event_update,
    "event_delete": execute_event_delete,
    # Agendas connectés (abonnements iCal)
    "calendar_subscribe": execute_calendar_subscribe,
    "calendar_subscriptions": execute_calendar_subscriptions,
    "calendar_unsubscribe": execute_calendar_unsubscribe,
    "calendar_sync": execute_calendar_sync,
    # Génération de documentation (notes → Word complet)
    "document_generate": execute_document_generate,
    # Documents (RAG : parle à tes documents)
    "document_index": execute_document_index,
    "document_ask": execute_document_ask,
    "document_list": execute_document_list,
    "document_forget": execute_document_forget,
    "document_refine_section": execute_document_refine_section,
    "unified_search": execute_unified_search,
    # Notifications externes
    "telegram_send": execute_telegram_send,
    # Web par vrai navigateur (anti-blocage)
    "web_browser_open": execute_web_browser_open,
    "web_research": execute_web_research,
    "web_deep_research": execute_web_deep_research,
    "ai_model_council": execute_ai_model_council,
    "ai_cortex_search": execute_ai_cortex_search,
    "ai_research_swarm": execute_ai_research_swarm,
    "ai_adaptive_team": execute_ai_adaptive_team,
    "ai_code_forge": execute_ai_code_forge,
    "ai_test_forge": execute_ai_test_forge,
    "code_workspace_start": execute_code_workspace_start,
    "code_workspace_status": execute_code_workspace_status,
    "code_workspace_control": execute_code_workspace_control,
    "ai_subagents_run": execute_ai_subagents_run,
    "long_task_start": execute_long_task_start,
    "long_task_status": execute_long_task_status,
    "long_task_stop": execute_long_task_stop,
    # SSH
    "ssh_list": execute_ssh_list,
    "ssh_connection_save": execute_ssh_connection_save,
    "ssh_exec": execute_ssh_exec,
    "ssh_exec_multi": execute_ssh_exec_multi,
    "ssh_write_and_run": execute_ssh_write_and_run,
    "ssh_upload": execute_ssh_upload,
    "ssh_download": execute_ssh_download,
    "ssh_list_dir": execute_ssh_list_dir,
    "ssh_server_info": execute_ssh_server_info,
    # Voice
    "voice_transcribe": execute_voice_transcribe,
    # Utilitaires
    "calculator":        execute_calculator,
    "datetime_info":     execute_datetime_info,
    "weather":           execute_weather,
    "translate":         execute_translate,
    "unit_convert":      execute_unit_convert,
    "password_generate": execute_password_generate,
    # Section 15 — traitement de données
    "text_stats":        execute_text_stats,
    "ip_info":           execute_ip_info,
    "markdown_convert":  execute_markdown_convert,
    "regex_tool":        execute_regex_tool,
    "csv_analyze":       execute_csv_analyze,
    "hash_compute":      execute_hash_compute,
    "base64_tool":       execute_base64_tool,
    "text_extract":      execute_text_extract,
    "diff_text":         execute_diff_text,
    "image_info":        execute_image_info,
    "image_resize":      execute_image_resize,
    "qr_generate":       execute_qr_generate,
    "json_tool":         execute_json_tool,
    # Section 16 — Documents, Archives & Couleurs
    "pdf_read":          execute_pdf_read,
    "pdf_info":          execute_pdf_info,
    "pdf_merge":         execute_pdf_merge,
    "pdf_split":         execute_pdf_split,
    "pdf_rotate":        execute_pdf_rotate,
    "pdf_watermark":     execute_pdf_watermark,
    "pdf_protect":       execute_pdf_protect,
    "pdf_extract_images": execute_pdf_extract_images,
    "pdf_to_images":     execute_pdf_to_images,
    "pdf_ocr":           execute_pdf_ocr,
    "pdf_form_fields":   execute_pdf_form_fields,
    "pdf_fill_form":     execute_pdf_fill_form,
    "images_to_pdf":     execute_images_to_pdf,
    "image_crop":        execute_image_crop,
    "image_rotate":      execute_image_rotate,
    "image_compress":    execute_image_compress,
    "image_batch":       execute_image_batch,
    "file_large_finder": execute_file_large_finder,
    "system_cleanup":    execute_system_cleanup,
    # Bureautique & IA documentaire (v2.36)
    "pptx_create":       execute_pptx_create,
    "pptx_read":         execute_pptx_read,
    "csv_to_xlsx":       execute_csv_to_xlsx,
    "xlsx_to_csv":       execute_xlsx_to_csv,
    "docx_to_text":      execute_docx_to_text,
    "text_summarize":    execute_text_summarize,
    # v2.37 — Synthèse vocale, PDF compress/numérotation, data→chart
    "text_to_speech":      execute_text_to_speech,
    "pdf_compress":        execute_pdf_compress,
    "pdf_add_page_numbers": execute_pdf_add_page_numbers,
    "csv_to_chart":        execute_csv_to_chart,
    "xlsx_read":         execute_xlsx_read,
    "url_analyze":       execute_url_analyze,
    "zip_list":          execute_zip_list,
    "color_tool":        execute_color_tool,
    # Section 17 — SQLite, Git & Fichiers avancés
    "sqlite_query":      execute_sqlite_query,
    "sqlite_tables":     execute_sqlite_tables,
    "git_info":          execute_git_info,
    "bulk_rename":       execute_bulk_rename,
    # Section 18 — Outils composés & productivité
    "screen_ocr":        execute_screen_ocr,
    "file_batch_read":   execute_file_batch_read,
    "clipboard_append":  execute_clipboard_append,
    "text_join":         execute_text_join,
    # Section 19 — Exécution de code
    "code_python":       execute_code_python,
    # Section 20 — Devis / Facturation IT
    "billing_client_create":  execute_billing_client_create,
    "billing_client_list":    execute_billing_client_list,
    "billing_catalog_list":   execute_billing_catalog_list,
    "billing_analyze_need":   execute_billing_analyze_need,
    "billing_quote_create":   execute_billing_quote_create,
    "billing_quote_list":     execute_billing_quote_list,
    "billing_quote_compare":  execute_billing_quote_compare,
    "billing_quote_pdf":      execute_billing_quote_pdf,
    "billing_quote_email":    execute_billing_quote_email,
    "billing_tier_breakdown": execute_billing_tier_breakdown,
    # Section 28 — Devis IT avancé (comparaison web, pricing, propositions, factures)
    "billing_market_research":     execute_billing_market_research,
    "billing_find_products":       execute_billing_find_products,
    "billing_product_reviews":     execute_billing_product_reviews,
    "billing_price_recommendation":execute_billing_price_recommendation,
    "billing_generate_proposal":   execute_billing_generate_proposal,
    "billing_tco_analysis":        execute_billing_tco_analysis,
    "billing_invoice_create":      execute_billing_invoice_create,
    "billing_invoice_list":        execute_billing_invoice_list,
    "billing_invoice_mark_paid":   execute_billing_invoice_mark_paid,
    "billing_revenue_dashboard":   execute_billing_revenue_dashboard,
    "billing_catalog_enrich":      execute_billing_catalog_enrich,
    "billing_seed_trade":          execute_billing_seed_trade,
    # Section 29 — Base de connaissances IT
    "it_kb_search":                execute_it_kb_search,
    "it_kb_list":                  execute_it_kb_list,
    "it_kb_recommend":             execute_it_kb_recommend,
    "it_kb_add":                   execute_it_kb_add,
    # Section 21 — Windows Admin
    "pc_installed_software":   execute_pc_installed_software,
    "win_services_list":      execute_win_services_list,
    "win_service_action":     execute_win_service_action,
    "win_event_log":          execute_win_event_log,
    "win_users_list":         execute_win_users_list,
    "win_disk_info":          execute_win_disk_info,
    "win_update_status":      execute_win_update_status,
    # Section 26 — v2.31 Windows Diagnostics avancés
    "win_uptime":             execute_win_uptime,
    "win_startup_programs":   execute_win_startup_programs,
    "win_scheduled_tasks":    execute_win_scheduled_tasks,
    "win_network_config":     execute_win_network_config,
    "win_system_report":      execute_win_system_report,
    "file_duplicate_finder":  execute_file_duplicate_finder,
    # Section 27 — v2.32 Édition vidéo / GIF
    "video_info":             execute_video_info,
    "video_to_gif":           execute_video_to_gif,
    "gif_to_video":           execute_gif_to_video,
    "video_trim":             execute_video_trim,
    "video_compress":         execute_video_compress,
    "video_resize":           execute_video_resize,
    "video_extract_frames":   execute_video_extract_frames,
    "video_speed":            execute_video_speed,
    "video_watermark":        execute_video_watermark,
    "gif_optimize":           execute_gif_optimize,
    "screen_record_gif":      execute_screen_record_gif,
    # Audio (ffmpeg embarqué)
    "audio_info":             execute_audio_info,
    "audio_extract":          execute_audio_extract,
    "audio_convert":          execute_audio_convert,
    "audio_trim":             execute_audio_trim,
    "audio_merge":            execute_audio_merge,
    "audio_volume":           execute_audio_volume,
    # Section 22 — Agent IA Documentation Technique
    "doc_intervention_create":   execute_doc_intervention_create,
    "doc_intervention_list":     execute_doc_intervention_list,
    "doc_intervention_update":   execute_doc_intervention_update,
    "doc_analyze_input":         execute_doc_analyze_input,
    "doc_generate_report":       execute_doc_generate_report,
    "doc_generate_procedure":    execute_doc_generate_procedure,
    "doc_generate_client_sheet": execute_doc_generate_client_sheet,
    "doc_generate_recovery_plan": execute_doc_generate_recovery_plan,
    "doc_generate_maintenance":  execute_doc_generate_maintenance,
    "doc_generate_runbook":      execute_doc_generate_runbook,
    "doc_generate_schema":       execute_doc_generate_schema,
    "doc_generate_postmortem":   execute_doc_generate_postmortem,
    "doc_generate_change":       execute_doc_generate_change,
    "doc_generate_onboarding":   execute_doc_generate_onboarding,
    "doc_template_list":         execute_doc_template_list,
    "doc_asset_create":          execute_doc_asset_create,
    "doc_asset_list":            execute_doc_asset_list,
    "doc_knowledge_search":      execute_doc_knowledge_search,
    # Section 23 — v2.30 Command Safety / Guardrails
    "cmd_extract_from_text":         execute_cmd_extract_from_text,
    "cmd_analyze_risk":              execute_cmd_analyze_risk,
    "cmd_suggest_safer_alternative": execute_cmd_suggest_safer_alternative,
    "cmd_require_approval":          execute_cmd_require_approval,
    "cmd_review_history":            execute_cmd_review_history,
    # Section 24 — v2.30 Pre-Check / Post-Check
    "ops_checklist_generate":        execute_ops_checklist_generate,
    "ops_precheck_create":           execute_ops_precheck_create,
    "ops_precheck_run":              execute_ops_precheck_run,
    "ops_postcheck_run":             execute_ops_postcheck_run,
    "ops_evidence_add":              execute_ops_evidence_add,
    "ops_validation_report_generate": execute_ops_validation_report_generate,
    # Section 25 — v2.30 Client Health Score
    "client_health_compute":           execute_client_health_compute,
    "client_health_get":               execute_client_health_get,
    "client_health_history":           execute_client_health_history,
    "client_recommendations_generate": execute_client_recommendations_generate,
    "client_monthly_summary_generate": execute_client_monthly_summary_generate,
}

computer_runtime.configure(TOOLS_REGISTRY)


# ══════════════════════════════════════════════════════════════════════════════
# SPÉCIFICATION OLLAMA (JSON Schema pour chaque outil)
# ══════════════════════════════════════════════════════════════════════════════

def _t(name: str, description: str, properties: dict, required: list = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


TOOLS_SPEC = [
    _t(
       "tool_search",
       "Découvre les outils Marvin pertinents pour atteindre un objectif. Retourne des "
       "candidats avec titre, cas d'usage, contre-indications, outils voisins et paramètres, "
       "mais n'exécute rien. À utiliser quand les outils actuellement visibles ne suffisent "
       "pas ou sont ambigus.",
       {
           "query": {
               "type": "string",
               "description": "Capacité recherchée, formulée comme un objectif précis",
           },
           "limit": {
               "type": "integer",
               "description": "Nombre de candidats, de 1 à 20",
               "minimum": 1,
               "maximum": 20,
           },
       },
       ["query"],
    ),
    _t("system_self_test",
       "Auto-diagnostic : Marvin teste un échantillon de ses propres outils et rapporte ceux qui fonctionnent ou non (+ latence). include_web=true teste aussi les outils réseau. Pour répondre à 'est-ce que tout fonctionne ?'.",
       {"category":    {"type": "string", "description": "Filtrer par catégorie/outil (optionnel)"},
        "include_web": {"type": "boolean", "description": "Inclure les outils réseau (web, météo)"}}, []),
    _t("file_list", "Liste un dossier avec pagination exacte. Si l'utilisateur demande tout, rappelle l'outil avec next_offset jusqu'à has_more=false ; n'affirme jamais qu'il manque des éléments sans lire ces pages.",
       {"path": {"type": "string", "description": "Chemin du répertoire à lister"},
        "show_hidden": {"type": "boolean", "description": "Afficher les fichiers cachés"},
        "offset": {"type": "integer", "minimum": 0, "description": "Position de départ (défaut 0)"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Éléments par page (défaut 100)"}},
       ["path"]),

    _t("file_info", "Retourne les métadonnées d'un chemin exact. Avec hash=true, calcule MD5 ET SHA-256. Pour vérifier un fichier dont le chemin est déjà connu, utiliser cet outil et jamais file_search_text.",
       {"path": {"type": "string", "description": "Chemin du fichier ou dossier"},
        "hash": {"type": "boolean", "description": "Calculer MD5 et SHA-256 (défaut : false)"}},
       ["path"]),

    _t("file_read", "Lit le contenu d'un fichier (TXT, PDF, Word DOCX, Excel XLSX, CSV, Markdown, code source...).",
       {"path": {"type": "string", "description": "Chemin du fichier à lire"}},
       ["path"]),

    _t("file_write", "Écrit du contenu dans un fichier texte ou markdown. Crée le fichier s'il n'existe pas.",
       {"path": {"type": "string", "description": "Chemin du fichier à écrire"},
        "content": {"type": "string", "description": "Contenu à écrire"},
        "overwrite": {"type": "boolean", "description": "Autoriser l'écrasement d'un fichier existant (défaut historique : true)"},
        "append": {"type": "boolean", "description": "Ajouter au fichier existant (true) ou écraser (false, défaut)"},
        "mode": {"type": "string", "enum": ["overwrite", "append"], "description": "Mode d'écriture : 'overwrite' (défaut) ou 'append'"}},
       ["path", "content"]),

    _t("file_delete",
       "Envoie un fichier ou un dossier à la Corbeille (récupérable), demande confirmation. "
       "N'utiliser permanent=true QUE si l'utilisateur demande explicitement une suppression "
       "définitive (« supprime définitivement », « vide la corbeille de ce fichier »).",
       {"path": {"type": "string", "description": "Chemin à supprimer"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"},
        "permanent": {"type": "boolean",
                      "description": "true = suppression définitive au lieu de la Corbeille "
                                     "(demandé explicitement uniquement)"}},
       ["path"]),

    _t("file_rename", "Renomme un fichier ou un dossier.",
       {"source": {"type": "string", "description": "Chemin actuel (absolu)"},
        "destination": {"type": "string", "description": "Nouveau chemin complet ou nouveau nom seul"},
        "new_name": {"type": "string", "description": "Nouveau nom simple (ex: 'rapport_v2.docx'). Alternative à 'destination'."}},
       ["source"]),

    _t("file_move", "Déplace un fichier ou un dossier vers un autre emplacement.",
       {"source": {"type": "string", "description": "Chemin source"},
        "destination": {"type": "string", "description": "Chemin de destination"}},
       ["source", "destination"]),

    _t("file_copy", "Copie un fichier ou un dossier.",
       {"source": {"type": "string", "description": "Chemin source"},
        "destination": {"type": "string", "description": "Chemin de destination"}},
       ["source", "destination"]),

    _t("file_create_folder", "Crée un nouveau dossier (et ses parents si nécessaire).",
       {"path": {"type": "string", "description": "Chemin du dossier à créer"}},
       ["path"]),

    _t("document_identity_set", "Enregistre l'identité document par défaut (auteur, organisation, coordonnées, logo, pied de page, mention de confidentialité) — réutilisée AUTOMATIQUEMENT par file_create_docx/file_create_pdf pour tout futur document sans avoir à la répéter. Appelle-le quand l'utilisateur te communique ces infos (dans ce message ou en réponse à ta question), pour qu'il n'ait plus jamais à te les redonner.",
       {"author": {"type": "string", "description": "Nom de l'auteur par défaut"},
        "org": {"type": "string", "description": "Nom de l'organisation"},
        "address": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string"},
        "website": {"type": "string"}, "logo": {"type": "string", "description": "Chemin d'une image logo"},
        "footer_text": {"type": "string", "description": "Texte libre par défaut en pied de page"},
        "confidentiality": {"type": "string", "description": "Mention de confidentialité par défaut (ex. 'Confidentiel — usage interne')"}},
       []),

    _t("screenshot_list", "Liste les captures d'écran attachées au chat dans cette conversation et déjà analysées (légende + texte relevé pour chacune). Utilise-le pour savoir ce qui est disponible avant de proposer une documentation.",
       {"limit": {"type": "integer", "description": "Nombre max de captures à lister (défaut 100)"}},
       []),

    _t("doc_generate_from_screenshots", "Génère un document Word ou PDF de documentation à partir de TOUTES les captures d'écran attachées au chat dans cette conversation (une section par capture : image intégrée + légende + texte relevé), avec sommaire automatique. Utilise-le quand l'utilisateur demande de compiler/documenter son travail à partir de ses captures d'écran.",
       {"title": {"type": "string", "description": "Titre du document (défaut 'Documentation technique')"},
        "subtitle": {"type": "string", "description": "Sous-titre optionnel"},
        "intro": {"type": "string", "description": "Paragraphe d'introduction optionnel, avant la liste des captures"},
        "format": {"type": "string", "enum": ["docx", "pdf"], "description": "Format de sortie (défaut docx)"},
        "path": {"type": "string", "description": "Chemin du fichier à créer (défaut : Bureau, nommé d'après le titre)"},
        "author": {"type": "string", "description": "Auteur (sinon : identité document par défaut)"}},
       []),

    _t("logo_generate", "Génère un LOGO/icône localement (GPU, aucune donnée envoyée au cloud) à partir d'une description visuelle, l'enregistre dans une base réutilisable. À utiliser chaque fois qu'un logo/icône de marque est demandé pour un document ou une mise en page — JAMAIS en écrivant du code (PowerShell/System.Drawing, Python...) à la main : lent, fragile, et ce n'est pas le rôle d'un shell. Vérifie d'abord logo_list si un logo existe déjà pour ce nom/contexte.",
       {"name": {"type": "string", "description": "Nom court identifiant ce logo (ex. nom de l'entreprise/du projet) — sert de clé de réutilisation"},
        "prompt": {"type": "string", "description": "Description visuelle du logo souhaité (style, symbole, couleurs) — en anglais de préférence, le modèle de génération d'image le comprend mieux"},
        "size": {"type": "integer", "enum": [256, 384, 512, 640, 768, 1024], "description": "Taille carrée en pixels (défaut 512)"},
        "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295, "description": "Graine optionnelle pour reproduire exactement une génération"}},
       ["name", "prompt"]),

    _t("logo_list", "Liste les logos déjà générés localement (nom, description, chemin) — à consulter AVANT logo_generate pour réutiliser un logo existant plutôt que d'en régénérer un nouveau pour le même client/contexte.",
       {"limit": {"type": "integer", "description": "Nombre max à lister (défaut 50)"}},
       []),

    _t("file_create_docx", "Crée un vrai document Word (.docx) PROFESSIONNEL. Pour une lettre de motivation : document_kind=letter, une page de préférence, prose sobre et personnalisée, aucun champ [placeholder], aucune page de titre de rapport et aucune compétence inventée ; omettre les coordonnées inconnues. Pour un rapport : page de titre, markdown, tableaux, citations, sommaire et signature sont disponibles. Pour un document STRUCTURÉ/officiel sans identité connue, demander l'identité plutôt que de la deviner.",
       {"path": {"type": "string", "description": "Chemin explicite du fichier Word. Si absent, Marvin le classe dans sa racine portable documents."},
        "title": {"type": "string", "description": "Titre principal du document"},
        "subtitle": {"type": "string", "description": "Sous-titre (optionnel)"},
        "content": {"type": "string", "description": "Contenu markdown : # titres, **gras**, *italique*, - listes, tableaux | a | b |, > citations, ``` code, ![légende](chemin) pour embarquer une vraie image (ex. une capture d'écran)"},
        "document_kind": {"type": "string", "enum": ["document", "letter", "report", "proposal"], "description": "Nature du document. letter active une composition compacte de lettre sans couverture."},
        "author": {"type": "string", "description": "Auteur du document (sinon : identité document par défaut, sinon 'Marvin')"},
        "theme": {"type": "string", "enum": ["professional", "executive", "minimal", "technical", "galactic", "luxury", "nature", "ocean", "editorial", "creative"], "description": "Thème déterministe et vérifiable du document."},
        "design_prompt": {"type": "string", "description": "Direction artistique demandée, reprise fidèlement (ex. magazine nature premium, brochure cyber futuriste). Le moteur en déduit palette et composition."},
        "layout": {"type": "string", "enum": ["masthead", "editorial", "proposal", "customer_pack", "immersive", "minimal"], "description": "Composition de première page. Si absent, déduite de design_prompt."},
        "density": {"type": "string", "enum": ["airy", "balanced", "compact"], "description": "Densité éditoriale et rythme vertical."},
        "design_system": {"type": "object", "description": "Palette personnalisée optionnelle : accent, secondary, text, muted, surface, cover, cover_text (hex #RRGGBB uniquement)."},
        "accent": {"type": "string", "description": "Couleur d'accent hex (défaut #c9a84c)"},
        "logo_position": {"type": "string", "enum": ["left", "center", "right"], "description": "Position réelle du logo dans l'en-tête, sans superposition."},
        "toc": {"type": "boolean", "description": "Insère un sommaire auto-généré (champ Word natif) après la page de titre — recommandé pour un document de plusieurs sections"},
        "footer_text": {"type": "string", "description": "Texte libre en pied de page, à côté du numéro de page (ex. nom d'organisation, référence)"},
        "confidentiality": {"type": "string", "description": "Mention de confidentialité en pied de page (ex. 'Confidentiel — usage interne')"},
        "letterhead": {"type": "object", "description": "En-tête personnalisé sur toutes les pages", "properties": {
            "org": {"type": "string", "description": "Nom de l'organisation"},
            "address": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string"},
            "website": {"type": "string"}, "logo": {"type": "string", "description": "Chemin d'une image logo"}}},
        "references": {"type": "object", "description": "Référence document affichée sous le titre", "properties": {
            "client": {"type": "string"}, "reference": {"type": "string"}}},
        "signature": {"type": "object", "description": "Bloc signature en fin de document", "properties": {
            "lieu": {"type": "string"}, "name": {"type": "string"}, "title": {"type": "string"}}}},
       ["title", "content"]),

    _t("file_convert_docx_to_pdf", "Convertit un document Word (.docx/.doc) en PDF.",
       {"path": {"type": "string", "description": "Chemin du fichier Word"},
        "output_dir": {"type": "string", "description": "Répertoire de sortie (optionnel)"}},
       ["path"]),

    _t("document_convert_format", "Convertit un document déjà généré vers un AUTRE format (docx<->pdf), SANS regénérer le contenu depuis zéro. À utiliser quand l'utilisateur demande 'plutôt en Word'/'plutôt en PDF' après avoir déjà reçu un document dans l'autre format.",
       {"path": {"type": "string", "description": "Chemin du document déjà généré (.docx ou .pdf)"},
        "target_format": {"type": "string", "enum": ["pdf", "docx"], "description": "Format cible"}},
       ["path", "target_format"]),

    _t("file_search_text", "Recherche un texte ou mot-clé dans le contenu des fichiers d'un répertoire.",
       {"directory": {"type": "string", "description": "Répertoire où chercher"},
        "query": {"type": "string", "description": "Texte ou mot-clé à rechercher"},
        "extensions": {"type": "array", "items": {"type": "string"}, "description": "Extensions à chercher (.txt, .pdf, .docx...)"},
        "case_sensitive": {"type": "boolean", "description": "Recherche sensible à la casse"}},
       ["directory", "query"]),
    _t("file_find", "Trouve des fichiers par nom/motif glob. Utilise l'index Windows Search (très rapide ~50ms) ou os.walk en fallback. Pour chercher sur TOUT le PC, omettez 'path' ou utilisez path='all'. Pour lister UNIQUEMENT le contenu direct d'un dossier précis (ex: « qu'y a-t-il sur mon bureau »), utilisez recursive=false — sinon pattern='*' recurse dans tous les sous-dossiers et peut plafonner sans montrer le premier niveau proprement.",
       {"pattern":      {"type": "string",  "description": "Motif : *.pdf, rapport*, *2024*, ou simplement un nom. Supporte * et ?"},
        "path":         {"type": "string",  "description": "Dossier de recherche, ou 'all' pour tout le PC (défaut : tout le PC via l'index Windows)"},
        "max_results":  {"type": "integer", "description": "Limite de résultats (défaut 100)"},
        "include_dirs": {"type": "boolean", "description": "Inclure les dossiers dans les résultats (défaut false)"},
        "recursive":    {"type": "boolean", "description": "false = uniquement le contenu direct de 'path' (pas les sous-dossiers), sans plafond artificiel de troncature ambiguë. Défaut true."}},
       ["pattern"]),
    _t("system_search", "🚀 RECHERCHE ULTRA-RAPIDE sur tout le PC via l'index Windows Search (~50ms). Utilisez cet outil EN PRIORITÉ quand l'utilisateur cherche un fichier ou dossier dont il ne connaît pas l'emplacement exact.",
       {"query":      {"type": "string", "description": "Mot-clé à chercher dans les noms de fichiers/dossiers (ex: 'abdou', 'rapport', 'photo vacances')"},
        "file_type":  {"type": "string", "enum": ["all", "folder", "file", "pdf", "docx", "xlsx", "image"],
                       "description": "Filtrer par type. Utilisez 'folder' pour chercher seulement des dossiers"},
        "max_results":{"type": "integer", "description": "Limite de résultats (défaut 30)"}},
       ["query"]),
    _t("system_search_content", "🔎 RECHERCHE PAR CONTENU sur tout le PC (index plein-texte Windows). Trouve les documents d'après ce qu'ils CONTIENNENT, pas seulement leur nom. Pour « retrouve le document qui parle de X », « où est le contrat avec Y », « le fichier où j'ai écrit Z ». Renvoie un extrait du passage.",
       {"query":      {"type": "string", "description": "Termes à chercher DANS le contenu des fichiers (ex: 'clause de résiliation', 'facture Dupont')"},
        "file_type":  {"type": "string", "enum": ["all", "pdf", "docx", "xlsx", "text"],
                       "description": "Filtrer par type de document"},
        "max_results":{"type": "integer", "description": "Limite de résultats (défaut 25)"}},
       ["query"]),

    _t("pc_get_real_paths", (
           "OUTIL DE RÉFÉRENCE — Retourne les vrais chemins Windows de cet ordinateur "
           "(bureau, documents, téléchargements, nom d'utilisateur réel). "
           "À utiliser EN PRIORITÉ si tu n'es pas certain du chemin correct."),
       {}, []),

    _t("webapp_create",
       "Génère une mini-application web autonome (HTML/CSS/JS auto-contenu en un seul "
       "fichier) et l'ouvre dans le navigateur — pour un dashboard, un prototype, un outil "
       "interactif, une page de suivi de projet. Pour « crée-moi une page/un dashboard/une "
       "mini-appli qui... », « fais-moi une interface pour... ». Le HTML doit être "
       "self-contained (CSS/JS inline, pas de CDN externe).",
       {"content": {"type": "string", "description": "Le code HTML complet de la page (ou un fragment, enveloppé automatiquement)"},
        "title": {"type": "string", "description": "Titre de la mini-appli (utilisé comme nom de fichier)"}},
       ["content"]),
    _t("pc_open_file", (
           "Ouvre un fichier ou dossier dans son application Windows par défaut. "
           "Capacité destinée à ouvrir ou afficher un fichier, un PDF ou un document dans Windows. "
           "À choisir pour « ouvre ce fichier », « affiche ce PDF » ou « lance ce document ». "
           "Ne lit pas et n'extrait pas le contenu du document."),
       {"path": {"type": "string", "description": "Chemin du fichier à ouvrir"}},
       ["path"]),

    _t("pc_browse", "Explore un dossier Windows (sous-dossiers + fichiers avec taille/date) et donne les accès rapides (Bureau, Documents, lecteurs). Pour naviguer l'arborescence sans connaître le chemin exact.",
       {"path": {"type": "string", "description": "Dossier à explorer (vide = Accueil)"},
        "show_hidden": {"type": "boolean", "description": "Afficher les éléments cachés"}},
       []),
    _t("pc_reveal", "Ouvre l'Explorateur Windows sur l'emplacement d'un fichier/dossier (le met en surbrillance).",
       {"path": {"type": "string", "description": "Chemin du fichier/dossier à révéler"}},
       ["path"]),

    _t("pc_app_launch", "Lance une application Windows installée par son nom et vérifie le résultat par processus ou fenêtre. Ne jamais l'utiliser pour ouvrir un chemin local : utiliser pc_open_file. Résout via PATH, registre App Paths et menu Démarrer. Pour Tailscale, utilise explicitement l'interface graphique tailscale-ipn.exe. Pour un navigateur (chrome/firefox/msedge/brave/opera), fournir aussi 'url' ouvre directement cette page dans la fenêtre lancée, en un seul appel.",
       {"app_name": {"type": "string", "description": "Nom de l'application à lancer"},
        "url": {"type": "string", "description": "Navigateurs uniquement : URL à charger directement dans la fenêtre lancée"}},
       ["app_name"]),

    _t("pc_tailscale_status", "Diagnostique Tailscale sous Windows sans le modifier : installation, service, connexion VPN et interface graphique. À utiliser avant ou après le lancement.",
       {},
       []),

    _t("pc_run_command", "Exécute une commande système Windows (demande confirmation).",
       {"command": {"type": "string", "description": "Commande shell à exécuter"},
        "timeout": {"type": "integer", "description": "Délai max en secondes"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       ["command"]),

    _t("pc_run_powershell", "Repli générique avec confirmation UI obligatoire. Pour un logiciel absent de Winget, peut lancer son désinstalleur officiel en séparant correctement exécutable cité et arguments ; ne jamais supprimer registre ou profil pour simuler un succès.",
       {"script":    {"type": "string",  "description": "Script ou commande PowerShell à exécuter"},
        "timeout":   {"type": "integer", "description": "Délai max en secondes (défaut 30)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       ["script"]),

    _t("pc_run_elevated", "Exécute une commande ou un script PowerShell AVEC DROITS ADMINISTRATEUR, "
       "via le démon élevé séparé (le backend reste en utilisateur normal). N'utilise ceci QUE si "
       "pc_run_command/pc_run_powershell ont échoué par manque de droits admin. Demande confirmation.",
       {"command":   {"type": "string",  "description": "Commande cmd.exe à exécuter en admin"},
        "script":    {"type": "string",  "description": "Script/commande PowerShell à exécuter en admin"},
        "timeout":   {"type": "integer", "description": "Délai max en secondes (défaut 30)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       []),

    # ── Emporium : gestionnaire de paquets Winget ────────────────────────────
    _t("winget_search", "Recherche des logiciels installables via Winget (renvoie nom, ID, version, source).",
       {"query":  {"type": "string",  "description": "Terme de recherche (nom du logiciel)"},
        "source": {"type": "string",  "description": "Source : 'winget' ou 'msstore' (optionnel)"},
        "limit":  {"type": "integer", "description": "Nombre max de résultats (défaut 20)"}},
       ["query"]),
    _t("winget_list_upgrades", "Liste les logiciels installés ayant une mise à jour disponible (Winget).",
       {}, []),
    _t("winget_list_installed", "Liste les logiciels INSTALLÉS sur le PC (filtrable par nom) — pour les voir/désinstaller.",
       {"query": {"type": "string", "description": "Filtre optionnel (nom partiel)"}}, []),
    _t("winget_install", "Outil privilégié pour installer un logiciel Windows : installation silencieuse puis vérification dans l'inventaire. Ne jamais lancer un second installateur après un succès vérifié.",
       {"id":        {"type": "string",  "description": "ID exact du paquet (ex: 7zip.7zip) — préférable"},
        "query":     {"type": "string",  "description": "À défaut d'ID, nom approximatif (moins fiable)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       []),
    _t("winget_upgrade", "Met à jour un paquet précis (id) ou TOUS les paquets (all=true) via Winget (demande confirmation).",
       {"id":        {"type": "string",  "description": "ID du paquet à mettre à jour"},
        "all":       {"type": "boolean", "description": "true = mettre à jour TOUS les paquets"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       []),
    _t("winget_uninstall", "Outil privilégié pour désinstaller puis vérifier l'absence du logiciel. Préserve le profil utilisateur ; sa suppression exige une action séparée et confirmée.",
       {"id":        {"type": "string",  "description": "ID exact du paquet (préférable)"},
        "query":     {"type": "string",  "description": "À défaut d'ID, nom approximatif"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       []),

    # ── Pantheon : optimisation & durcissement (tweaks sûrs, réversibles) ─────
    _t("system_restore_point", "Crée un point de restauration système (filet de sécurité avant optimisation). Demande confirmation.",
       {"description": {"type": "string",  "description": "Libellé du point de restauration"},
        "confirmed":   {"type": "boolean", "description": "Confirmation de l'utilisateur"}}, []),
    _t("registry_get", "Lit une valeur (ou toute une clé) du registre Windows (lecture seule).",
       {"path": {"type": "string", "description": "Chemin PowerShell, ex: HKLM:\\SOFTWARE\\Microsoft\\Windows"},
        "name": {"type": "string", "description": "Nom de la valeur (optionnel ; sinon toutes)"}}, ["path"]),
    _t("registry_backup", "Exporte une clé de registre dans un fichier .reg de secours.",
       {"path": {"type": "string", "description": "Chemin de la clé (HKLM:\\...)"}}, ["path"]),
    _t("registry_set", "Écrit une valeur de registre (SAUVEGARDE auto de la clé + confirmation).",
       {"path":      {"type": "string", "description": "Chemin de la clé (HKLM:\\...)"},
        "name":      {"type": "string", "description": "Nom de la valeur"},
        "value":     {"type": "string", "description": "Valeur à écrire"},
        "type":      {"type": "string", "description": "DWord | String | QWord | ExpandString (défaut DWord)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}}, ["path", "name", "value"]),
    _t("tweak_telemetry", "Statut / désactivation / réactivation de la télémétrie Windows (DiagTrack + AllowTelemetry). Réversible, sauvegarde auto.",
       {"action":    {"type": "string", "enum": ["status", "disable", "enable"]},
        "confirmed": {"type": "boolean", "description": "Requis pour disable/enable"}}, ["action"]),
    _t("tweak_debloat_list", "Liste les applications d'usine non essentielles (bloatware UWP) désinstallables.",
       {}, []),
    _t("tweak_debloat_remove", "Désinstalle des applications UWP (bloatware). Demande confirmation.",
       {"packages":  {"type": "array", "items": {"type": "string"}, "description": "Noms UWP à retirer (ex: Microsoft.BingNews)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}}, ["packages"]),
    _t("tweak_network_harden", "Statut / optimisations réseau légères (cache DNS, auto-tuning TCP). 'apply' demande confirmation.",
       {"action":    {"type": "string", "enum": ["status", "apply"]},
        "confirmed": {"type": "boolean", "description": "Requis pour apply"}}, ["action"]),

    # ── Catharsis : moteur de purge (scan d'abord, puis nettoyage confirmé) ───
    _t("catharsis_scan", "Analyse l'espace disque récupérable par catégorie (temp, caches navigateurs, .dmp, corbeille…). Ne supprime rien.",
       {}, []),
    _t("catharsis_clean", "Purge les catégories choisies (ids issus de catharsis_scan). Demande confirmation.",
       {"categories": {"type": "array", "items": {"type": "string"}, "description": "Ids de catégories à vider (ex: temp_user, edge_cache, recycle_bin)"},
        "confirmed":  {"type": "boolean", "description": "Confirmation de l'utilisateur"}}, ["categories"]),

    # ── Codex : paramètres OS exposés en fonctions ───────────────────────────
    _t("os_power_plan", "Lit ou change le plan d'alimentation Windows (équilibré/performances/économie).",
       {"action":    {"type": "string", "enum": ["get", "set"]},
        "plan":      {"type": "string", "enum": ["balanced", "performance", "powersaver"]},
        "confirmed": {"type": "boolean", "description": "Requis pour set"}}, ["action"]),
    _t("os_dark_mode", "Lit ou bascule le mode sombre/clair de Windows (sans droits admin).",
       {"action":    {"type": "string", "enum": ["get", "dark", "light", "toggle"]},
        "confirmed": {"type": "boolean", "description": "Requis pour changer"}}, ["action"]),
    _t("os_firewall", "Statut / activation / désactivation du pare-feu Windows Defender (tous profils).",
       {"action":    {"type": "string", "enum": ["status", "on", "off"]},
        "confirmed": {"type": "boolean", "description": "Requis pour on/off"}}, ["action"]),
    _t("os_network_adapters", "Liste / active / désactive les cartes réseau.",
       {"action":    {"type": "string", "enum": ["list", "enable", "disable"]},
        "name":      {"type": "string", "description": "Nom de la carte (pour enable/disable)"},
        "confirmed": {"type": "boolean", "description": "Requis pour enable/disable"}}, ["action"]),
    _t("os_hibernation", "Statut / activation / désactivation de l'hibernation (libère hiberfil.sys).",
       {"action":    {"type": "string", "enum": ["status", "on", "off"]},
        "confirmed": {"type": "boolean", "description": "Requis pour on/off"}}, ["action"]),

    _t("pc_printer_list", "Liste les imprimantes installées (nom, statut, pilote, si c'est la défaut, partagée).",
       {}, []),
    _t("pc_printer_set_default", "Définit l'imprimante par défaut (demande confirmation).",
       {"name":      {"type": "string", "description": "Nom exact de l'imprimante (voir pc_printer_list)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}}, ["name"]),
    _t("pc_usb_list", "Liste les périphériques USB actuellement connectés (nom, classe, statut).",
       {}, []),
    _t("pc_bluetooth_status", "Statut du Bluetooth : radio disponible/activé et périphériques appairés.",
       {}, []),

    _t("csv_analyze", "Analyse un fichier CSV : aperçu, statistiques par colonne, valeurs uniques.",
       {"path":      {"type": "string", "maxLength": 32767, "description": "Chemin du fichier CSV"},
        "action":    {"type": "string",  "enum": ["summary", "head", "stats", "unique"],
                      "description": "Action : summary (défaut), head (5 premières lignes), stats (stats numériques colonne), unique (valeurs uniques colonne)"},
        "column":    {"type": "string", "maxLength": 1000, "description": "Colonne cible pour stats ou unique"},
        "max_rows":  {"type": "integer", "minimum": 1, "maximum": 10000, "description": "Nombre max de lignes à charger (défaut 100)"},
        "delimiter": {"type": "string", "minLength": 1, "maxLength": 2, "description": "Séparateur unique (défaut ',', utiliser \\\\t pour une tabulation)"}},
       ["path"]),

    _t("pc_system_info", "Retourne les informations techniques du PC : CPU, RAM, disques, uptime.",
       {}, []),

    _t("pc_screenshot", "Prend une capture d'écran du bureau Windows. Avec embed=true, retourne l'image base64 pour l'afficher dans le chat.",
       {"output_path": {"type": "string", "description": "Chemin de sauvegarde PNG (optionnel, défaut : Bureau)"},
        "embed": {"type": "boolean", "description": "Si true, retourner l'image base64 dans la réponse (pour affichage dans le chat)"}},
       []),

    _t("pc_window_list", "Liste toutes les fenêtres ouvertes sur le bureau.",
       {}, []),

    _t("pc_window_focus", "Met une fenêtre au premier plan par son titre, ou par son hwnd exact (renvoyé par observe/list_windows) si plusieurs fenêtres se ressemblent.",
       {"search": {"type": "string", "description": "Texte à rechercher dans le titre de la fenêtre"},
        "hwnd": {"type": "integer", "description": "Identifiant hwnd exact — prioritaire sur 'search' si fourni"}},
       []),

    _t("pc_gui_read", "Lit l'arbre des éléments cliquables (boutons/champs/menus/listes) d'une fenêtre Windows "
                       "via UI Automation — PAS une capture d'écran, une lecture structurée 100% locale. Utilise "
                       "ceci AVANT tout pc_gui_click/pc_gui_type pour obtenir les identifiants réels des éléments "
                       "(jamais deviner un automation_id). Sans 'window', lit la fenêtre au premier plan. "
                       "Échoue proprement si la fenêtre est élevée (admin) — inaccessible depuis ce process.",
       {"window": {"type": "string", "description": "Sous-chaîne du titre de fenêtre ciblée (optionnel, défaut : premier plan)"},
        "max_elements": {"type": "integer", "description": "Nombre max d'éléments retournés (défaut 40, max 100)"}},
       []),

    _t("pc_gui_click", "Clique sur un élément d'une fenêtre Windows (bouton, case, item de menu/liste...) via UI "
                        "Automation. Les paramètres control_type/name/automation_id/match_index DOIVENT venir "
                        "d'un pc_gui_read RÉCENT sur la même fenêtre — l'élément est re-résolu en direct au "
                        "moment du clic (jamais de coordonnées figées), donc si l'UI a changé depuis la lecture "
                        "l'appel échoue proprement plutôt que de cliquer au hasard.",
       {"window": {"type": "string", "description": "Sous-chaîne du titre de fenêtre (doit correspondre à celle du pc_gui_read)"},
        "control_type": {"type": "string", "description": "control_type exact renvoyé par pc_gui_read (ex: Button, MenuItem)"},
        "name": {"type": "string", "description": "name exact renvoyé par pc_gui_read"},
        "automation_id": {"type": "string", "description": "automation_id renvoyé par pc_gui_read, si présent (plus fiable que name)"},
        "match_index": {"type": "integer", "description": "match_index renvoyé par pc_gui_read si plusieurs éléments partagent control_type+name (défaut 0)"},
        "confirmed": {"type": "boolean", "description": "Requis pour exécuter réellement le clic"}},
       []),

    _t("pc_gui_type", "Écrit du texte dans un champ d'une fenêtre Windows via UI Automation. Mêmes règles que "
                       "pc_gui_click : control_type/name/automation_id/match_index viennent d'un pc_gui_read "
                       "récent, élément re-résolu en direct au moment de l'écriture.",
       {"window": {"type": "string", "description": "Sous-chaîne du titre de fenêtre (doit correspondre à celle du pc_gui_read)"},
        "control_type": {"type": "string", "description": "control_type exact renvoyé par pc_gui_read (ex: Edit)"},
        "name": {"type": "string", "description": "name exact renvoyé par pc_gui_read"},
        "automation_id": {"type": "string", "description": "automation_id renvoyé par pc_gui_read, si présent"},
        "match_index": {"type": "integer", "description": "match_index renvoyé par pc_gui_read si ambigu (défaut 0)"},
        "text": {"type": "string", "description": "Texte à écrire dans le champ"},
        "confirmed": {"type": "boolean", "description": "Requis pour exécuter réellement l'écriture"}},
       ["text"]),

    _t("vm_lab_install", "Consulte ou lance l'installation sans assistance d'une VM Test Forge Hyper-V Debian 13 "
                          "ou Windows 11. L'installation persistante recrée uniquement la VM choisie, vérifie "
                          "l'ISO, provisionne le compte de test au moindre privilège, crée un checkpoint propre "
                          "et conserve les preuves. Utilise action=status pour suivre le job. action=install exige "
                          "une demande explicite de l'utilisateur et confirmed=true.",
       {"action": {"type": "string", "enum": ["status", "install"], "description": "Action à effectuer"},
        "profile": {"type": "string", "enum": ["debian13", "windows11"], "description": "Profil à installer"},
        "confirmed": {"type": "boolean", "description": "Confirmation explicite requise pour recréer la VM"}},
       ["action"]),

    _t("pc_notify", "Envoie une notification Windows à l'utilisateur.",
       {"title": {"type": "string", "description": "Titre de la notification"},
        "message": {"type": "string", "description": "Corps de la notification"}},
       ["title", "message"]),

    _t("pc_pull_ollama_model", "Télécharge un modèle Ollama (ex: llama3.2:3b) pour accélérer les réponses.",
       {"model": {"type": "string", "description": "Nom du modèle à télécharger (ex: llama3.2:3b)"}},
       ["model"]),

    _t("pc_clipboard_get", "Lit le contenu actuel du presse-papiers Windows.",
       {}, []),

    _t("pc_clipboard_set", "Copie un texte dans le presse-papiers Windows.",
       {"text": {"type": "string", "description": "Texte à copier"}},
       ["text"]),

    _t("pc_process_list", "Liste les processus actifs sur le PC (top 50 par mémoire).",
       {}, []),

    _t("pc_process_kill", "Arrête un processus par PID ou nom (demande confirmation).",
       {"pid": {"type": "integer", "description": "PID du processus"},
        "name": {"type": "string", "description": "Nom du processus (si PID inconnu)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       []),

    _t("project_list", "Liste les projets persistants affichés dans la barre latérale Marvin, avec leur nombre de conversations.",
       {}, []),

    _t("project_create", "Crée un projet persistant dans la barre latérale Marvin. Ne crée pas un dossier Windows.",
       {"name": {"type": "string", "description": "Nom du projet, 120 caractères maximum"},
        "instructions": {"type": "string", "description": "Instructions communes facultatives du projet"}},
       ["name"]),

    _t("project_update", "Renomme un projet Marvin et/ou modifie ses instructions persistantes.",
       {"project_id": {"type": "string", "description": "Identifiant exact du projet"},
        "project_name": {"type": "string", "description": "Nom exact si l'identifiant est inconnu"},
        "new_name": {"type": "string", "description": "Nouveau nom facultatif"},
        "instructions": {"type": "string", "description": "Nouvelles instructions facultatives"}},
       []),

    _t("project_delete", "Supprime un projet Marvin après confirmation UI. Les conversations sont conservées et deviennent sans projet.",
       {"project_id": {"type": "string", "description": "Identifiant exact du projet"},
        "project_name": {"type": "string", "description": "Nom exact si l'identifiant est inconnu"},
        "confirmed": {"type": "boolean", "description": "Confirmation affichée par l'interface"}},
       []),

    _t("conversation_list", "Liste les conversations récentes, éventuellement par projet, archivées ou sans projet.",
       {"project_id": {"type": "string", "description": "Identifiant du projet"},
        "project_name": {"type": "string", "description": "Nom exact du projet"},
        "unassigned": {"type": "boolean", "description": "Limiter aux conversations sans projet"},
        "archived": {"type": "boolean", "description": "Lister les conversations archivées"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200}},
       []),

    _t("conversation_search", "Recherche des conversations persistantes par titre ou contenu afin d'obtenir leurs identifiants exacts.",
       {"query": {"type": "string", "description": "Texte à rechercher"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
       ["query"]),

    _t("conversation_move", "Déplace une conversation vers un projet Marvin ou la remet dans Sans projet. Sans identifiant ni titre, agit sur la conversation courante.",
       {"conversation_id": {"type": "string", "description": "Identifiant exact ; omettre pour la conversation courante"},
        "conversation_title": {"type": "string", "description": "Titre exact si l'identifiant est inconnu"},
        "project_id": {"type": "string", "description": "Identifiant du projet cible, ou none"},
        "project_name": {"type": "string", "description": "Nom exact du projet cible"},
        "remove_from_project": {"type": "boolean", "description": "True pour remettre dans Sans projet"}},
       []),

    _t("conversation_move_many", "Déplace atomiquement jusqu'à 50 conversations identifiées vers un projet Marvin ou Sans projet. Utilise conversation_search avant si les identifiants sont inconnus.",
       {"conversation_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 50,
                             "description": "Identifiants exacts des conversations"},
        "project_id": {"type": "string", "description": "Identifiant du projet cible, ou none"},
        "project_name": {"type": "string", "description": "Nom exact du projet cible"},
        "remove_from_project": {"type": "boolean", "description": "True pour remettre dans Sans projet"}},
       ["conversation_ids"]),

    _t("conversation_update", "Renomme, épingle, désépingle, archive ou restaure une conversation. Sans identifiant ni titre, agit sur la conversation courante.",
       {"conversation_id": {"type": "string", "description": "Identifiant exact ; omettre pour la conversation courante"},
        "conversation_title": {"type": "string", "description": "Titre exact si l'identifiant est inconnu"},
        "action": {"type": "string", "enum": ["rename", "pin", "unpin", "archive", "restore"]},
        "new_title": {"type": "string", "description": "Nouveau titre requis pour rename"}},
       ["action"]),

    _t("task_create", "Crée une nouvelle tâche (todo).",
       {"title": {"type": "string", "description": "Titre de la tâche"},
        "description": {"type": "string", "description": "Description détaillée"},
        "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Priorité"},
        "due_date": {"type": "string", "description": "Date d'échéance (YYYY-MM-DD)"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"}},
       ["title"]),

    _t("task_list", "Liste et filtre les tâches.",
       {"status": {"type": "string", "enum": ["pending", "in_progress", "done", "cancelled"], "description": "Filtrer par statut"},
        "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Filtrer par priorité"}},
       []),

    _t("task_update", "Met à jour une tâche existante.",
       {"id": {"type": "string", "description": "ID de la tâche"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "status": {"type": "string", "enum": ["pending", "in_progress", "done", "cancelled"]},
        "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
        "due_date": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}}},
       ["id"]),

    _t("task_delete", "Supprime une tâche (demande confirmation).",
       {"id": {"type": "string", "description": "ID de la tâche"},
        "confirmed": {"type": "boolean"}},
       ["id"]),

    _t("note_create", "Crée une nouvelle note personnelle.",
       {"title": {"type": "string", "description": "Titre de la note"},
        "content": {"type": "string", "description": "Contenu en markdown"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "pinned": {"type": "boolean", "description": "Épingler la note"}},
       ["title"]),

    _t("note_list", "Liste et recherche les notes.",
       {"search": {"type": "string", "description": "Texte à rechercher dans le titre ou contenu"},
        "pinned": {"type": "boolean", "description": "Filtrer les notes épinglées"}},
       []),

    _t("note_update", "Met à jour une note existante.",
       {"id": {"type": "string", "description": "ID de la note"},
        "title": {"type": "string"},
        "content": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "pinned": {"type": "boolean"}},
       ["id"]),

    _t("note_delete", "Supprime une note (demande confirmation).",
       {"id": {"type": "string", "description": "ID de la note"},
        "confirmed": {"type": "boolean"}},
       ["id"]),

    _t("memory_save", "Enregistre un fait, une préférence ou une habitude en mémoire à long terme.",
       {"content": {"type": "string", "description": "Fait ou préférence à mémoriser"},
        "category": {"type": "string", "enum": ["user_profile", "preference", "fact", "habit"], "description": "Catégorie"}},
       ["content"]),

    _t("memory_list", "Liste tous les souvenirs enregistrés.",
       {}, []),

    _t("memory_delete", "Oublie un souvenir obsolète ou erroné (demande confirmation).",
       {"id": {"type": "string", "description": "ID du souvenir à supprimer"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       ["id"]),

    _t("memory_search", "Cherche dans les souvenirs mémorisés par sens ou par mots-clés.",
       {"query": {"type": "string", "description": "Requête de recherche"},
        "limit": {"type": "integer", "description": "Nombre de résultats max (défaut 5)"}},
       ["query"]),

    _t("search_semantic", "Recherche sémantique dans notes, mémoires et documents indexés (Qdrant).",
       {"query": {"type": "string", "description": "Requête en langage naturel"},
        "collections": {"type": "array", "items": {"type": "string"}, "description": "Collections : memories, notes, documents"},
        "limit": {"type": "integer", "description": "Nombre de résultats (défaut 5)"}},
       ["query"]),

    _t("web_search",
       "Découverte Web rapide exclusivement via SearXNG. Retourne titres, URL et extraits, "
       "sans lire les pages ni produire une synthèse vérifiée. Pour une réponse actuelle "
       "sourcée, utiliser ensuite web_browse/web_browser_open ou directement web_research.",
       {"query": {"type": "string", "description": "Requête de recherche"},
        "provider": {"type": "string", "enum": ["auto", "searxng"], "description": "Les deux valeurs utilisent exclusivement SearXNG"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 50,
                        "description": "Nombre de résultats (défaut 12)"},
        "language": {"type": "string", "description": "Langue SearXNG, par exemple fr-FR ou en-US"},
        "categories": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["general", "news", "images", "videos", "map", "music",
                         "it", "science", "files", "social media"],
            },
            "description": "Catégories SearXNG optionnelles; si absentes Marvin les déduit du sujet.",
        },
        "time_range": {"type": "string", "enum": ["day", "week", "month", "year"], "description": "Fenêtre temporelle optionnelle"}},
       ["query"]),

    _t("web_browse",
       "Lit une page Web précise trouvée via SearXNG et extrait son contenu principal. "
       "À utiliser pour vérifier une source primaire avant de la citer.",
       {"url": {"type": "string", "description": "URL de la page à visiter"},
        "max_chars": {"type": "integer", "description": "Limite de caractères à retourner (défaut 25000, max 60000)"}},
       ["url"]),

    _t(
       "web_site_crawl",
       "Aspire automatiquement un site public complet à partir de ses sitemaps et liens "
       "internes. À choisir dès que l'utilisateur demande d'aspirer, crawler, parcourir "
       "tout un site ou analyser plusieurs pages du même domaine. Conserve chaque page "
       "dans un artefact local et retourne textes, titres et URL directes. Ne remplace "
       "pas web_browser_open pour un parcours interactif ou une authentification.",
       {
        "url": {"type": "string", "description": "URL de départ du site"},
        "site": {"type": "string", "description": "Nom ou demande décrivant le site lorsque l'URL n'est pas connue; Marvin le résout d'abord exclusivement via SearXNG"},
        "max_pages": {"type": "integer", "minimum": 1, "maximum": 5000,
                      "description": "Plafond adaptatif de pages (défaut 250, maximum 5000)"},
        "max_depth": {"type": "integer", "minimum": 0, "maximum": 20,
                      "description": "Profondeur maximale des liens internes (défaut 8)"},
        "include_subdomains": {"type": "boolean",
                               "description": "Inclure les sous-domaines du domaine initial"},
        "use_sitemaps": {"type": "boolean",
                         "description": "Découvrir prioritairement les sitemaps (défaut true)"},
        "browser_fallback": {"type": "boolean",
                             "description": "Rendre avec le vrai navigateur en cas de 401, 403 ou 429 (défaut true); ne contourne aucun contrôle d'accès"},
        "resume": {"type": "boolean",
                   "description": "Reprendre automatiquement le dernier crawl incomplet de la même URL (défaut true)"},
        "per_page_chars": {"type": "integer", "minimum": 1000, "maximum": 100000,
                           "description": "Texte maximal renvoyé au LLM par page"},
        "max_return_chars": {"type": "integer", "minimum": 5000, "maximum": 500000,
                             "description": "Corpus total maximal renvoyé au LLM; le contenu complet reste dans les artefacts"},
        "job_id": {"type": "string",
                   "description": "Identifiant optionnel pour retrouver les artefacts du crawl"}
       },
       []),

    _t(
       "web_media_extract",
       "Inventorie, vérifie et télécharge les images réelles d'une page ou d'un crawl Web public. "
       "Extrait img/srcset/lazy-loading/OpenGraph/favicon et arrière-plans CSS, conserve la page "
       "source, les dimensions, le MIME et le SHA-256 dans un manifeste. À utiliser pour obtenir "
       "les visuels d'un site; ne pas employer computer_control ni inventer des URL d'images.",
       {
        "url": {"type": "string", "description": "Page Web publique à analyser"},
        "crawl_job_id": {"type": "string", "description": "Identifiant d'un crawl existant dont les pages doivent être analysées"},
        "max_pages": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Pages maximales analysées (défaut 25)"},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Images maximales téléchargées (défaut 50)"},
        "max_total_bytes": {"type": "integer", "minimum": 1000000, "maximum": 200000000, "description": "Volume total maximal (défaut 50 Mo)"},
        "min_width": {"type": "integer", "minimum": 1, "maximum": 20000, "description": "Largeur minimale en pixels (défaut 200)"},
        "min_height": {"type": "integer", "minimum": 1, "maximum": 20000, "description": "Hauteur minimale en pixels (défaut 120)"},
        "browser_fallback": {"type": "boolean", "description": "Rendre la page avec Playwright si le HTML contient moins de trois médias (défaut true)"},
        "output_dir": {"type": "string", "maxLength": 32767, "description": "Dossier de sortie facultatif"}
       },
       []),

    _t("infographic_create", "Crée un graphique PNG. Types : bar, horizontal_bar, pie, donut, line, area, multi_line, scatter, radar, grouped_bar, stacked_bar. Pour les multi-séries (grouped/stacked/multi_line/radar), fournir 'series' = [{name, values}].",
       {"chart_type": {"type": "string", "enum": ["bar", "horizontal_bar", "pie", "donut", "line", "area", "multi_line", "scatter", "radar", "grouped_bar", "stacked_bar"], "description": "Type de graphique"},
        "title": {"type": "string", "maxLength": 500, "description": "Titre du graphique"},
        "labels": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "string", "maxLength": 200}, "description": "Étiquettes (axe / catégories)"},
        "values": {"type": "array", "maxItems": 100, "items": {"type": "number"}, "description": "Valeurs (mono-série)"},
        "series": {"type": "array", "maxItems": 20, "items": {"type": "object", "properties": {"name": {"type": "string", "maxLength": 200}, "values": {"type": "array", "maxItems": 100, "items": {"type": "number"}}}, "required": ["values"], "additionalProperties": False}, "description": "Multi-séries : [{\"name\":\"2024\",\"values\":[...]}, …]"},
        "x_values": {"type": "array", "maxItems": 100, "items": {"type": "number"}, "description": "Abscisses pour scatter"},
        "theme": {"type": "string", "enum": ["dark", "light"], "description": "Thème (défaut sombre)"},
        "output_path": {"type": "string", "maxLength": 32767, "description": "Chemin de sauvegarde PNG (défaut : Bureau)"},
        "subtitle": {"type": "string", "maxLength": 1000, "description": "Sous-titre optionnel"},
        "colors": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "string", "maxLength": 50}, "description": "Couleurs optionnelles reconnues par Matplotlib"}},
       ["title", "labels"]),

    _t("file_create_xlsx", "Crée un fichier Excel (.xlsx) avec titres, en-têtes et données.",
       {"path": {"type": "string", "description": "Chemin du fichier Excel"},
        "title": {"type": "string", "description": "Titre du tableau"},
        "headers": {"type": "array", "items": {"type": "string"}, "description": "En-têtes des colonnes"},
        "rows": {"type": "array", "items": {"type": "array"}, "description": "Lignes de données (tableau de tableaux)"},
        "sheet_name": {"type": "string", "description": "Nom de la feuille"}},
       ["headers", "rows"]),

    _t("file_create_pdf", "Crée un PDF PROFESSIONNEL (sans Word) : page de titre, **gras**/*italique*/`code`, tableaux markdown stylés, citations, blocs de code, liens, en-tête/pied de page personnalisables, sommaire auto. Pour un document STRUCTURÉ/officiel (rapport, procédure, devis, présentation) sans identité document déjà connue (voir document_identity_set), demande d'abord auteur/organisation/en-tête à l'utilisateur plutôt que de deviner.",
       {"path": {"type": "string", "description": "Chemin explicite du PDF. Si absent, Marvin le classe dans sa racine portable documents."},
        "title": {"type": "string", "description": "Titre du document"},
        "subtitle": {"type": "string", "description": "Sous-titre (optionnel)"},
        "content": {"type": "string", "description": "Contenu markdown : # titres, **gras**, *italique*, - listes, tableaux | a | b |, > citations, [lien](url), ![légende](chemin) pour embarquer une vraie image (ex. une capture d'écran)"},
        "author": {"type": "string", "description": "Auteur (sinon : identité document par défaut, sinon 'Marvin')"},
        "theme": {"type": "string", "enum": ["professional", "executive", "minimal", "technical", "galactic", "luxury", "nature", "ocean", "editorial", "creative"], "description": "Thème déterministe et vérifiable."},
        "design_prompt": {"type": "string", "description": "Direction artistique demandée, reprise fidèlement. Le moteur en déduit palette et composition."},
        "layout": {"type": "string", "enum": ["masthead", "editorial", "proposal", "customer_pack", "immersive", "minimal"], "description": "Composition de la couverture ; déduite du brief si absente."},
        "density": {"type": "string", "enum": ["airy", "balanced", "compact"], "description": "Densité éditoriale."},
        "document_label": {"type": "string", "description": "Kicker court de couverture, ex. Rapport annuel ou Édition spéciale."},
        "design_system": {"type": "object", "description": "Palette personnalisée optionnelle avec couleurs hex #RRGGBB bornées."},
        "accent": {"type": "string", "description": "Couleur d'accent hex (défaut #c9a84c)"},
        "logo_position": {"type": "string", "enum": ["left", "center", "right"], "description": "Position du logo d'en-tête sans superposition."},
        "toc": {"type": "boolean", "description": "Insère un sommaire auto-généré (cliquable, avec signets PDF) après la page de titre — recommandé pour un document de plusieurs sections"},
        "footer_text": {"type": "string", "description": "Texte libre en pied de page (ex. nom d'organisation, référence)"},
        "confidentiality": {"type": "string", "description": "Mention de confidentialité en pied de page (ex. 'Confidentiel — usage interne')"},
        "header": {"type": "object", "description": "En-tête personnalisé sur toutes les pages", "properties": {
            "org": {"type": "string", "description": "Nom de l'organisation"},
            "address": {"type": "string"}, "phone": {"type": "string"}, "email": {"type": "string"},
            "website": {"type": "string"}, "logo": {"type": "string", "description": "Chemin d'une image logo"}}}},
       ["title", "content"]),

    # ── Google Calendar ───────────────────────────────────────────────────────
    _t("calendar_list", "Liste les événements Google Calendar à venir (nécessite OAuth Google configuré).",
       {"calendar_id":  {"type": "string",  "description": "ID du calendrier (défaut : 'primary')"},
        "days":         {"type": "integer", "description": "Nombre de jours à afficher à partir de time_min (défaut 7, max 90)"},
        "max_results":  {"type": "integer", "description": "Nombre max d'événements (défaut 20, max 50)"},
        "time_min":     {"type": "string",  "description": "Début de la plage (ISO 8601). Défaut : maintenant."}},
       []),

    _t("calendar_create", "Crée un événement dans Google Calendar (nécessite OAuth Google configuré).",
       {"title": {"type": "string", "description": "Titre de l'événement"},
        "start": {"type": "string", "description": "Début : 'YYYY-MM-DD' (toute la journée) ou 'YYYY-MM-DDTHH:MM:SS' (précis)"},
        "end": {"type": "string", "description": "Fin : même format que 'start'. Défaut : +1h ou lendemain."},
        "location": {"type": "string", "description": "Lieu de l'événement (optionnel)"},
        "description": {"type": "string", "description": "Description / notes (optionnel)"},
        "calendar_id": {"type": "string", "description": "ID du calendrier (défaut : 'primary')"}},
       ["title", "start"]),

    _t("calendar_delete", "Supprime un événement Google Calendar par son ID (nécessite OAuth Google configuré).",
       {"event_id":    {"type": "string", "description": "ID de l'événement Google Calendar à supprimer"},
        "calendar_id": {"type": "string", "description": "ID du calendrier (défaut : 'primary')"}},
       ["event_id"]),

    _t("calendar_update", "Met à jour un événement Google Calendar existant (nécessite OAuth Google configuré).",
       {"event_id":    {"type": "string",  "description": "ID de l'événement Google Calendar à modifier"},
        "calendar_id": {"type": "string",  "description": "ID du calendrier (défaut : 'primary')"},
        "title":       {"type": "string",  "description": "Nouveau titre"},
        "start":       {"type": "string",  "description": "Nouveau début (ISO 8601)"},
        "end":         {"type": "string",  "description": "Nouvelle fin (ISO 8601)"},
        "description": {"type": "string",  "description": "Nouvelle description"},
        "location":    {"type": "string",  "description": "Nouveau lieu"}},
       ["event_id"]),

    _t("google_drive_list", "Liste les fichiers Google Drive (nécessite OAuth Google configuré).",
       {"folder_id": {"type": "string", "description": "ID du dossier (défaut : racine)"},
        "max_results": {"type": "integer", "description": "Nombre de résultats"},
        "query": {"type": "string", "description": "Recherche par nom"}},
       []),

    _t("google_drive_read", "Lit le contenu texte d'un Google Doc ou Google Sheet.",
       {"file_id": {"type": "string", "description": "ID du fichier Google Drive"}},
       ["file_id"]),

    _t("google_drive_upload", "Téléverse un fichier local vers Google Drive.",
       {"local_path": {"type": "string", "description": "Chemin du fichier local"},
        "folder_id": {"type": "string", "description": "ID du dossier de destination (défaut : racine)"},
        "file_name": {"type": "string", "description": "Nom du fichier dans Drive (optionnel)"}},
       ["local_path"]),

    _t("onedrive_list", "Liste les fichiers OneDrive (nécessite OAuth Microsoft configuré).",
       {"folder_id": {"type": "string", "description": "ID du dossier (défaut : root)"},
        "max_results": {"type": "integer", "description": "Nombre de résultats"},
        "query": {"type": "string", "description": "Recherche par nom"}},
       []),

    _t("onedrive_read", "Lit le contenu texte d'un fichier OneDrive.",
       {"file_id": {"type": "string", "description": "ID du fichier OneDrive"}},
       ["file_id"]),

    _t("onedrive_upload", "Téléverse un fichier local vers OneDrive.",
       {"local_path": {"type": "string", "description": "Chemin du fichier local"},
        "dest_path": {"type": "string", "description": "Chemin de destination dans OneDrive (ex: Documents/rapport.pdf)"}},
       ["local_path"]),

    # ── Réseau ────────────────────────────────────────────────────────────────
    _t("net_ping", "Ping une adresse IP ou un nom d'hôte pour tester la connectivité.",
       {"host": {"type": "string", "description": "Adresse IP ou nom d'hôte"},
        "count": {"type": "integer", "description": "Nombre de paquets à envoyer (défaut 4, max 20)"}},
       ["host"]),

    _t("net_port_scan", "Scanne les ports TCP ouverts sur un hôte donné.",
       {"host": {"type": "string", "description": "Adresse IP ou nom d'hôte"},
        "ports": {"type": "string", "description": "Ports à scanner : '80,443' ou '20-25' ou mix (défaut : ports communs)"},
        "timeout": {"type": "number", "description": "Timeout par port en secondes (défaut 1.0)"}},
       ["host"]),

    _t("net_dns_lookup", "Résolution DNS d'un nom d'hôte (ou reverse lookup d'une IP).",
       {"host": {"type": "string", "description": "Nom d'hôte ou adresse IP"},
        "type": {"type": "string", "enum": ["A", "AAAA", "MX", "NS", "PTR"], "description": "Type d'enregistrement (défaut A)"}},
       ["host"]),

    _t("net_traceroute", "Affiche le chemin réseau (hops) jusqu'à une adresse IP ou un hôte.",
       {"host": {"type": "string", "description": "Adresse IP ou nom d'hôte"},
        "max_hops": {"type": "integer", "description": "Nombre maximum de sauts (défaut 15, max 30)"}},
       ["host"]),

    _t("net_scan_local", "Scanne le réseau local via ARP pour détecter tous les appareils connectés.",
       {}, []),

    _t("net_whois", "Requête WHOIS sur un domaine ou une adresse IP pour obtenir les infos d'enregistrement.",
       {"host": {"type": "string", "description": "Nom de domaine ou adresse IP"}},
       ["host"]),

    # ── Réseau Pro : diagnostic avancé (nmap optionnel, TLS, HTTP, sweep, routage) ──
    _t("net_nmap_scan", "Scan réseau avancé type Nmap. Utilise nmap.exe si installé, sinon repli TCP local borné. Idéal pour audit de ports sur un hôte ou un petit CIDR.",
       {"target":    {"type": "string",  "description": "IP, hôte ou CIDR, ex: 192.168.1.10 ou 192.168.1.0/24"},
        "profile":   {"type": "string",  "enum": ["quick", "web", "windows", "remote", "top100"], "description": "Profil de ports si 'ports' est vide"},
        "ports":     {"type": "string",  "description": "Ports CSV/plages, ex: 22,80,443 ou 1-1024"},
        "timeout":   {"type": "number",  "description": "Timeout TCP par port en secondes"},
        "confirmed": {"type": "boolean", "description": "Confirmation pour scans larges CIDR/plages"}},
       ["target"]),

    _t("net_service_detect", "Détecte les services TCP ouverts sur un hôte et tente une capture de bannière simple (sans scan agressif).",
       {"host":    {"type": "string", "description": "Hôte ou IP"},
        "ports":   {"type": "string", "description": "Ports CSV/plages à tester"},
        "timeout": {"type": "number", "description": "Timeout par port en secondes"}},
       ["host"]),

    _t("net_http_probe", "Analyse un site ou endpoint HTTP/HTTPS : code de statut, titre, redirections, en-têtes et en-têtes de sécurité.",
       {"url":     {"type": "string", "description": "URL ou nom de domaine"},
        "timeout": {"type": "number", "description": "Timeout HTTP en secondes"}},
       ["url"]),

    _t("net_tls_check", "Contrôle le certificat TLS d'un hôte HTTPS : expiration, émetteur, SAN, protocole, cipher.",
       {"host":    {"type": "string",  "description": "Domaine ou IP"},
        "port":    {"type": "integer", "description": "Port TLS, défaut 443"},
        "timeout": {"type": "number",  "description": "Timeout en secondes"}},
       ["host"]),

    _t("net_tls_check_bulk", "Contrôle TLS/certificat sur PLUSIEURS hôtes en une fois (parallèle) — pour surveiller "
                              "les expirations d'un parc de services auto-hébergés sans un appel par hôte. Signale "
                              "ceux qui expirent sous 30 jours.",
       {"hosts":   {"type": "array", "items": {"type": "string"}, "description": "Liste de domaines/IP (max 25)"},
        "port":    {"type": "integer", "description": "Port TLS, défaut 443"},
        "timeout": {"type": "number",  "description": "Timeout par hôte en secondes"}},
       ["hosts"]),

    _t("net_subnet_calc", "Calculateur de sous-réseau (VLSM/CIDR) : adresse réseau, broadcast, masque, masque "
                           "générique (wildcard), plage d'hôtes utilisables, nombre d'adresses. Avec new_prefix, "
                           "découpe le CIDR en sous-réseaux de cette taille (VLSM) — utile pour étudier le "
                           "subnetting ou planifier un plan d'adressage réel.",
       {"cidr":       {"type": "string",  "description": "CIDR, ex: 192.168.1.0/24 ou 10.0.0.0/8"},
        "new_prefix": {"type": "integer", "description": "Préfixe cible pour découper en sous-réseaux (VLSM), doit être > au préfixe actuel"}},
       ["cidr"]),

    _t("net_snmp_query", "Interroge un équipement réseau via SNMP (v2c) — action='sysinfo' (défaut : nom, "
                          "description, uptime, contact, localisation), action='interfaces' (liste des "
                          "interfaces réseau + état up/down), ou action='get' avec un OID précis. Utile pour "
                          "un switch/routeur/serveur exposant SNMP (souvent activé par défaut sur du matériel "
                          "réseau pro/labo, community 'public' fréquente en lecture seule).",
       {"host":      {"type": "string",  "description": "IP ou nom de l'équipement SNMP"},
        "community": {"type": "string",  "description": "Community SNMP (défaut 'public')"},
        "port":      {"type": "integer", "description": "Port SNMP, défaut 161"},
        "action":    {"type": "string",  "enum": ["sysinfo", "interfaces", "get"], "description": "Type de requête (défaut sysinfo)"},
        "oid":       {"type": "string",  "description": "OID précis pour action='get' (ex: 1.3.6.1.2.1.1.1.0)"},
        "timeout":   {"type": "integer", "description": "Timeout en secondes (défaut 4)"}},
       ["host"]),

    _t("net_topology_diagram", "Génère un diagramme visuel de topologie réseau (image affichée directement dans "
                                "le chat) — passerelle au centre, appareils autour. Sans 'hosts', scanne le réseau "
                                "local automatiquement. Utile pour documenter ou réviser une architecture réseau.",
       {"hosts":   {"type": "array", "items": {"type": "string"}, "description": "IPs/noms à représenter (optionnel, sinon scan local automatique, max 20)"},
        "gateway": {"type": "string", "description": "IP de la passerelle à afficher au centre (optionnel si 'hosts' fourni)"}},
       []),

    _t("quiz_generate", "Génère des fiches de révision (question/réponse) sur un sujet technique et les enregistre "
                         "pour une révision espacée — pour préparer une certification (Network+, CCNA, Security+...) "
                         "ou réviser un sujet étudié récemment.",
       {"topic": {"type": "string",  "description": "Sujet des fiches, ex: 'Modèle OSI', 'Sous-réseaux IPv4', 'Protocoles de routage'"},
        "count": {"type": "integer", "description": "Nombre de fiches à générer (défaut 5, max 15)"}},
       ["topic"]),

    _t("quiz_next", "Renvoie la PROCHAINE fiche de révision à réviser (priorité aux fiches dues, sinon au hasard) — "
                     "ne montre PAS la réponse, pose la question à l'utilisateur puis appelle quiz_answer avec le résultat.",
       {"topic": {"type": "string", "description": "Limiter à un sujet précis (optionnel, sinon toutes fiches confondues)"}},
       []),

    _t("quiz_answer", "Enregistre si l'utilisateur a bien répondu à une fiche (id renvoyé par quiz_next) — "
                       "programme la prochaine révision et révèle la réponse correcte.",
       {"id":      {"type": "string",  "description": "id de la fiche (renvoyé par quiz_next)"},
        "correct": {"type": "boolean", "description": "true si l'utilisateur a bien répondu"}},
       ["id", "correct"]),

    _t("quiz_stats", "Statistiques de révision par sujet : nombre de fiches, fiches dues maintenant, réussite cumulée.",
       {}, []),

    _t("net_subnet_sweep", "Sweep TCP borné d'un CIDR local pour repérer les hôtes actifs sur des ports courants.",
       {"cidr":      {"type": "string",  "description": "CIDR, ex: 192.168.1.0/24"},
        "ports":     {"type": "string",  "description": "Ports de détection, défaut 22,80,443,445,3389,5985,8080"},
        "timeout":   {"type": "number",  "description": "Timeout court par port"},
        "confirmed": {"type": "boolean", "description": "Confirmation pour sous-réseaux larges"}},
       ["cidr"]),

    _t("net_route_diagnostics", "Diagnostic réseau complet : config locale, DNS, ping internet/cible et traceroute optionnel. Utile pour « pourquoi je n'ai pas internet ».",
       {"target":        {"type": "string",  "description": "Cible à diagnostiquer, défaut 1.1.1.1"},
        "include_trace": {"type": "boolean", "description": "Inclure un traceroute (plus lent)"}},
       []),

    _t("pc_hardware_specs", "Inventaire matériel complet du PC (fabricant/modèle/n° de série, CPU, RAM, disques, GPU, cartes réseau) avec liens officiels support/pilotes selon le fabricant détecté (Dell, HP, Lenovo, ASUS, Acer, Surface, MSI, GIGABYTE, ASRock, Intel, AMD, NVIDIA, Samsung/WD/Seagate/Crucial).",
       {}, []),

    _t("pc_gpu_status", "État du GPU utilisé pour l'IA locale (vidéo…) : marque, VRAM, backend de calcul (CUDA NVIDIA / DirectML AMD-Intel / CPU). Utilise ceci si l'utilisateur a changé de carte graphique et veut que Marvin s'en rende compte tout de suite.",
       {"refresh": {"type": "boolean", "description": "true pour forcer une redétection immédiate (après changement de carte)"}},
       []),

    _t("pc_hardware_temps", "Températures RÉELLES du CPU et du GPU (capteur ACPI + nvidia-smi) — se déclenche pour tout diagnostic de surchauffe/plantage/ventilateur bruyant, ou avant d'affirmer quoi que ce soit sur une température. Ne devine JAMAIS une température, appelle toujours cet outil d'abord.",
       {}, []),

    _t("pc_disk_smart_health", "Santé RÉELLE des disques (compteurs de fiabilité S.M.A.R.T. Windows : usure SSD, erreurs de lecture non corrigées, heures de fonctionnement) — bien plus fiable que le simple statut Healthy/Unhealthy. Utilise ceci pour tout diagnostic PC complet ou si l'utilisateur suspecte un problème de disque.",
       {}, []),

    _t("pc_event_log_errors", "Erreurs/critiques récentes des journaux d'événements Windows (Système + Application) — détecte des plantages/pilotes en échec/erreurs disque INTERMITTENTS invisibles dans un instantané CPU/RAM/disque. Utilise ceci pour tout diagnostic PC complet, ou si l'utilisateur signale des plantages/lenteurs intermittentes.",
       {"days": {"type": "number", "description": "Nombre de jours en arrière à scanner (défaut 7, max 30)"},
        "max_events": {"type": "number", "description": "Nombre maximum d'événements à retourner (défaut 20, max 50)"}},
       []),

    _t("win_firewall_status", "État RÉEL du pare-feu Windows (profils Domaine/Privé/Public actifs, nombre de règles entrantes autorisées) — rendu structuré au lieu de parser du texte PowerShell. Utilise ceci pour tout audit de sécurité poste ou question sur le pare-feu.",
       {}, []),

    _t("pc_driver_check", "Vérifie si un pilote/composant matériel a une version plus récente disponible, via une VRAIE recherche web ciblée (pas une supposition). Utilise ceci systématiquement avant d'affirmer qu'un pilote est à jour ou obsolète — ne dis jamais « vérifie toi-même ».",
       {"component": {"type": "string", "description": "Nom exact du composant (ex: 'NVIDIA GeForce RTX 2060')"},
        "installed_version": {"type": "string", "description": "Version actuellement installée, si connue (optionnel)"}},
       ["component"]),

    _t("pc_health_trend", "Tendance RÉELLE de santé du PC dans le temps (RAM/disque/usure SSD/erreurs), basée sur des instantanés quotidiens enregistrés automatiquement — pas un instantané isolé. Utilise ceci pour « est-ce que ça empire ? », « dans combien de temps le disque sera plein ? » ou tout diagnostic dans la durée.",
       {"days": {"type": "number", "description": "Nombre de jours d'historique à analyser (défaut 30, max 90)"}},
       []),

    _t("pc_tool_reliability", "Taux d'échec RÉEL de chaque outil Marvin (pas une estimation) — sépare le volume d'appels de la fiabilité. Inclut aussi un taux RÉCENT (7j par défaut) et un flag likely_already_fixed pour distinguer un outil cassé maintenant d'un outil déjà corrigé mais qui traîne encore en tête du classement global. Utilise ceci quand l'utilisateur demande quels outils échouent le plus, ou pour un audit de fiabilité.",
       {"min_calls": {"type": "number", "description": "Nombre minimum d'appels pour qu'un outil soit inclus (défaut 3, évite le bruit statistique)"},
        "days": {"type": "number", "description": "Période analysée en jours (défaut 90)"},
        "recent_days": {"type": "number", "description": "Fenêtre récente pour détecter les bugs déjà corrigés (défaut 7)"}},
       []),

    _t("bug_log_list", "Liste les VRAIS bugs récents (exceptions Python avec traceback complet, capturées automatiquement dès qu'un outil ou une route plante) — pour un audit/débogage a posteriori après une période d'usage sans supervision. Chaque entrée contient le traceback complet, à lire avant de proposer un correctif.",
       {"limit": {"type": "number", "description": "Nombre max de bugs à lister (défaut 20, max 100)"},
        "kind": {"type": "string", "enum": ["tool_exception", "http_exception"], "description": "Filtre par type (par défaut : tous)"}},
       []),

    _t("pc_conversation_trace", "Chronologie complète des appels d'outils d'UNE conversation (durée réelle de chacun, ordre, succès/échec). Utilise ceci quand l'utilisateur demande pourquoi une réponse a été lente.",
       {"conversation_id": {"type": "string", "description": "ID de la conversation à analyser"}},
       ["conversation_id"]),

    _t("net_inventory_scan", "Scanne le réseau local ET enregistre les appareils dans un inventaire PERSISTANT (pas un instantané jetable) — première/dernière apparition suivies dans le temps. Utilise ceci pour un vrai inventaire réseau à jour.",
       {}, []),

    _t("net_inventory_list", "Liste l'inventaire réseau déjà enregistré (appareils vus précédemment, avec noms personnalisés/notes) — pas un scan en direct, utilise net_inventory_scan pour rafraîchir d'abord.",
       {"days": {"type": "number", "description": "Ne montrer que les appareils vus dans les N derniers jours (défaut 30)"}},
       []),

    _t("net_inventory_annotate", "Ajoute un nom personnalisé et/ou une note à un appareil de l'inventaire réseau (ex: « imprimante bureau »).",
       {"device_id": {"type": "string", "description": "ID de l'appareil (obtenu via net_inventory_list)"},
        "custom_name": {"type": "string", "description": "Nom personnalisé à donner à l'appareil"},
        "notes": {"type": "string", "description": "Note libre sur l'appareil"}},
       ["device_id"]),

    _t("itsm_ticket_list", "Liste les tickets d'un système ITSM/ticketing connecté (GLPI). Utilise ceci pour voir les tickets ouverts/en cours.",
       {"system": {"type": "string", "description": "Système ITSM (défaut 'glpi')"},
        "limit": {"type": "number", "description": "Nombre max de tickets (défaut 20)"}},
       []),

    _t("itsm_ticket_create", "Crée un ticket dans un système ITSM/ticketing connecté (GLPI). Confirme toujours le contenu avec l'utilisateur avant d'appeler.",
       {"system": {"type": "string", "description": "Système ITSM (défaut 'glpi')"},
        "title": {"type": "string", "description": "Titre du ticket"},
        "description": {"type": "string", "description": "Description détaillée"},
        "urgency": {"type": "number", "description": "Urgence GLPI 1 (très basse) à 5 (très haute)"},
        "confirmed": {"type": "boolean", "description": "Confirmation explicite de création"}},
       ["title"]),

    _t("itsm_asset_list", "Liste le matériel enregistré dans l'inventaire d'un système ITSM (GLPI).",
       {"system": {"type": "string", "description": "Système ITSM (défaut 'glpi')"},
        "limit": {"type": "number", "description": "Nombre max d'éléments (défaut 50)"}},
       []),

    _t("skill_learning_log", "Historique d'apprentissage de Marvin : compétences créées/améliorées après un échec ou un succès, consolidations automatiques (y compris la revue nocturne). Utilise ceci quand l'utilisateur demande ce que tu as appris récemment, pourquoi une compétence a changé, ou pour prouver que l'auto-amélioration fonctionne.",
       {"skill": {"type": "string", "description": "Nom d'une compétence précise (optionnel, sinon tout l'historique récent)"},
        "limit": {"type": "number", "description": "Nombre d'événements à retourner (défaut 10)"}},
       []),

    _t("win_quick_launch_list", "Liste les raccourcis Windows disponibles (God Mode, Paramètres, panneaux legacy, outils admin, dossiers utiles) avec leur id — catalogue « Windows+ ».",
       {}, []),

    _t("win_quick_launch", "Ouvre directement un panneau/outil Windows par son id (God Mode, ms-settings:*, appwiz.cpl, services.msc, taskmgr, dossier Temp…). Utilise win_quick_launch_list pour voir les id disponibles. N'écrit/ne modifie rien.",
       {"id": {"type": "string", "description": "Id du raccourci (ex : settings_privacy, tools_services, control_programs, folder_temp, god_mode)"}},
       ["id"]),

    # ── OCR ───────────────────────────────────────────────────────────────────
    _t("ocr_extract", "Extrait le texte visible dans une image avec le meilleur modèle vision local compatible.",
       {"image_path": {"type": "string", "description": "Chemin vers le fichier image (PNG, JPG, etc.)"},
        "prompt": {"type": "string", "description": "Instruction personnalisée pour l'extraction (optionnel)"},
        "model": {"type": "string", "description": "Modèle vision Ollama optionnel ; sélection locale dynamique par défaut."}},
       ["image_path"]),

    # ── Archives ─────────────────────────────────────────────────────────────
    _t("file_compress", "Compresse des fichiers ou dossiers en une archive ZIP.",
       {"sources": {"type": "array", "items": {"type": "string"}, "description": "Liste de chemins à compresser (fichiers ou dossiers)"},
        "output_path": {"type": "string", "description": "Chemin du fichier ZIP de sortie (défaut : Bureau)"}},
       ["sources"]),

    _t("file_extract", "Extrait une archive ZIP ou TAR vers un dossier de destination.",
       {"archive_path": {"type": "string", "description": "Chemin de l'archive à extraire (ZIP, TAR, TGZ...)"},
        "dest_path": {"type": "string", "description": "Dossier de destination (défaut : dossier de l'archive)"}},
       ["archive_path"]),

    # ── Email (multi-comptes : param 'account' = adresse de la boîte à cibler) ──
    _t("email_accounts", "Liste les boîtes mail connectées (multi-comptes). À utiliser pour savoir quelle adresse cibler.",
       {}, []),
    _t("email_list", "Liste les emails récents d'un dossier (IMAP). 'account' = adresse de la boîte (sinon la 1ère).",
       {"folder": {"type": "string", "description": "Dossier IMAP (défaut : INBOX)"},
        "limit": {"type": "integer", "description": "Nombre d'emails à récupérer (défaut 20, max 50)"},
        "offset": {"type": "integer", "description": "Décalage pour la pagination (défaut 0)"},
        "account": {"type": "string", "description": "Adresse de la boîte mail à consulter (multi-comptes)"}},
       []),

    _t("email_read", "Lit le contenu complet d'un email par son UID.",
       {"uid": {"type": "string", "description": "UID de l'email (récupéré via email_list)"},
        "folder": {"type": "string", "description": "Dossier IMAP (défaut : INBOX)"},
        "account": {"type": "string", "description": "Adresse de la boîte mail (multi-comptes)"}},
       ["uid"]),

    _t("email_search", "Recherche des emails par sujet, expéditeur ou mot-clé.",
       {"query": {"type": "string", "description": "Terme de recherche (sujet ou expéditeur)"},
        "folder": {"type": "string", "description": "Dossier IMAP (défaut : INBOX)"},
        "limit": {"type": "integer", "description": "Nombre de résultats max (défaut 20)"},
        "account": {"type": "string", "description": "Adresse de la boîte mail (multi-comptes)"}},
       ["query"]),

    _t("email_send", "Envoie un email via SMTP. Requiert confirmation explicite. Nécessite la config email dans Paramètres.",
       {"to": {"type": "string", "description": "Adresse email du destinataire"},
        "subject": {"type": "string", "description": "Objet de l'email"},
        "body": {"type": "string", "description": "Corps du message (texte ou markdown)"},
        "cc": {"type": "string", "description": "Adresse email en copie (optionnel)"},
        "account": {"type": "string", "description": "Adresse de la boîte EXPÉDITRICE (multi-comptes ; sinon la 1ère)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur (obligatoire avant envoi)"},
        "attachments": {"type": "array", "description": "Pièces jointes : [{path, sha256}]. Le sha256 est recommandé depuis l'outil de création mais le harnais le calcule avant confirmation s'il manque.", "items": {"type": "object", "properties": {"path": {"type": "string"}, "sha256": {"type": "string"}}, "required": ["path"]}}},
       ["to", "subject", "body"]),

    _t("conversation_export", "Exporte une conversation persistante en Markdown, DOCX, PDF ou JSON. Utiliser ensuite email_send avec le path et le sha256 retournes pour la partager.",
       {"conversation_id": {"type": "string", "description": "Identifiant UUID de la conversation"},
        "format": {"type": "string", "enum": ["md", "docx", "pdf", "json"]},
        "mode": {"type": "string", "enum": ["lecture", "technique", "audit"]}},
       []),

    _t("email_draft_reply", "Rédige par IA la meilleure réponse à un email, en français impeccable (sans fautes). Génère un brouillon — n'envoie PAS.",
       {"uid": {"type": "string", "description": "UID de l'email auquel répondre (sera lu automatiquement)"},
        "body": {"type": "string", "description": "Ou collez directement le contenu de l'email reçu"},
        "subject": {"type": "string", "description": "Objet de l'email reçu (optionnel)"},
        "from": {"type": "string", "description": "Expéditeur de l'email reçu (optionnel)"},
        "instruction": {"type": "string", "description": "Consigne libre (ex : 'accepte poliment', 'demande un délai')"},
        "tone": {"type": "string", "description": "Ton souhaité (défaut : professionnel et courtois)"},
        "account": {"type": "string", "description": "Boîte mail concernée (multi-comptes)"},
        "folder": {"type": "string", "description": "Dossier IMAP si lecture par uid (défaut INBOX)"}},
       []),

    _t("email_summarize", "Résume un email par IA en français : synthèse, points clés, action attendue. Fournir 'uid' ou 'body'.",
       {"uid": {"type": "string", "description": "UID de l'email à résumer (lu automatiquement)"},
        "body": {"type": "string", "description": "Ou contenu de l'email directement"},
        "subject": {"type": "string", "description": "Objet (optionnel)"},
        "from": {"type": "string", "description": "Expéditeur (optionnel)"},
        "account": {"type": "string", "description": "Boîte mail concernée (multi-comptes)"},
        "folder": {"type": "string", "description": "Dossier IMAP (défaut INBOX)"}},
       []),

    _t("email_digest", "Briefing IA de la boîte : scanne les emails récents et les PRIORISE (urgent/à traiter/info) avec actions suggérées.",
       {"account": {"type": "string", "description": "Boîte mail (adresse) ou '__all__' pour toutes les boîtes"},
        "limit": {"type": "integer", "description": "Nombre d'emails à analyser (défaut 15, max 25)"},
        "folder": {"type": "string", "description": "Dossier IMAP (défaut INBOX)"}},
       []),

    _t("email_automation_run", "Traite les emails non lus selon le mode configuré (brouillon = prépare, autonome = ENVOIE). dry_run=true pour simuler sans envoyer.",
       {"mode": {"type": "string", "enum": ["manuel", "brouillon", "autonome"], "description": "Forcer un mode (sinon celui configuré)"},
        "dry_run": {"type": "boolean", "description": "true = simulation sans envoi réel (recommandé pour tester)"},
        "confirmed": {"type": "boolean", "description": "Confirmation explicite du traitement réel"}},
       []),

    _t("email_to_task", "Transforme un email en tâche actionnable (l'IA extrait l'action + l'échéance, puis crée la tâche).",
       {"uid": {"type": "string", "description": "UID de l'email (lu automatiquement)"},
        "body": {"type": "string", "description": "Ou contenu de l'email directement"},
        "subject": {"type": "string", "description": "Objet (optionnel)"},
        "from": {"type": "string", "description": "Expéditeur (optionnel)"},
        "account": {"type": "string", "description": "Boîte mail concernée (multi-comptes)"},
        "folder": {"type": "string", "description": "Dossier IMAP (défaut INBOX)"}},
       []),

    _t("email_attachment_summary", "Résume par IA une pièce jointe d'un email (PDF, Word .docx, texte).",
       {"uid": {"type": "string", "description": "UID de l'email contenant la pièce jointe"},
        "name": {"type": "string", "description": "Nom de la pièce jointe (sinon la première)"},
        "account": {"type": "string", "description": "Boîte mail concernée (multi-comptes)"},
        "folder": {"type": "string", "description": "Dossier IMAP (défaut INBOX)"}},
       ["uid"]),

    _t("email_watch_check", "Surveille les emails non lus, détecte les importants par IA et notifie sur le bureau. force=true pour forcer, dry_run=true pour ne pas notifier.",
       {"force": {"type": "boolean", "description": "Forcer même si la surveillance est désactivée"},
        "dry_run": {"type": "boolean", "description": "Ne pas envoyer de notification (test)"}},
       []),

    _t("email_apply_rules", "Applique les règles de classement (déplacer/marquer lu) aux emails récents. dry_run=true pour simuler.",
       {"account": {"type": "string", "description": "Limiter à une boîte (sinon toutes)"},
        "dry_run": {"type": "boolean", "description": "Simuler sans rien déplacer"},
        "limit": {"type": "integer", "description": "Nb d'emails à examiner par boîte (défaut 25)"}},
       []),

    _t("daily_briefing", "Génère le briefing du jour : réunit les emails non lus et les tâches en attente en une synthèse IA priorisée. Pour « fais le point », « ma journée », « briefing ».",
       {}, []),

    # ── Agenda local ─────────────────────────────────────────────────────────
    _t("event_create", "Ajoute un rendez-vous/événement. Comprend le langage naturel : « ajoute rdv dentiste mardi 14h », « réunion équipe demain 10h-11h ». Si Google Agenda est connecté, l'événement est créé SUR Google (visible sur le téléphone) ; sinon en local. Pour planifier, agender, noter un RDV.",
       {"natural": {"type": "string", "description": "Demande en langage naturel (l'IA en extrait date/heure/titre)"},
        "title": {"type": "string", "description": "Titre de l'événement (si déjà séparé)"},
        "start_at": {"type": "string", "description": "Début explicite 'YYYY-MM-DD HH:MM' (sinon déduit du texte)"},
        "end_at": {"type": "string", "description": "Fin optionnelle 'YYYY-MM-DD HH:MM'"},
        "location": {"type": "string", "description": "Lieu"},
        "all_day": {"type": "boolean", "description": "Toute la journée"},
        "reminder_minutes": {"type": "integer", "minimum": 0, "maximum": 40320, "description": "Rappel X minutes avant (0 à 40320)"},
        "local_only": {"type": "boolean", "description": "Forcer l'agenda LOCAL même si Google est connecté"}},
       []),
    _t("event_list", "Liste les rendez-vous de l'agenda. Pour « mon agenda », « mes rendez-vous », « quels RDV cette semaine ».",
       {"period": {"type": "string", "enum": ["today", "jour", "aujourd'hui", "aujourdhui", "tomorrow", "demain", "week", "semaine", "7days", "month", "mois", "30days", "upcoming", "all", "tout"], "description": "Période prédéfinie"},
        "start": {"type": "string", "description": "Borne début YYYY-MM-DD (optionnel)"},
        "end": {"type": "string", "description": "Borne fin YYYY-MM-DD (optionnel)"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Nombre maximal d'événements"}},
       []),
    _t("event_update", "Modifie ou replanifie un événement existant (par id).",
       {"id": {"type": "string", "description": "Identifiant de l'événement"},
        "title": {"type": "string"}, "start_at": {"type": "string"}, "end_at": {"type": "string"},
        "location": {"type": "string"},
        "reminder_minutes": {"type": "integer", "minimum": 0, "maximum": 40320}},
       ["id"]),
    _t("event_delete", "Supprime un événement de l'agenda (par id, ou par titre approchant).",
       {"id": {"type": "string", "description": "Identifiant de l'événement"},
        "title": {"type": "string", "description": "Ou titre à rechercher"},
        "confirmed": {"type": "boolean", "description": "Confirmation explicite de suppression"}},
       []),

    # ── Agendas connectés (abonnements iCal) ───────────────────────────────────
    _t("calendar_subscribe", "Connecte un agenda externe (Google, Outlook, Apple…) via son lien iCal/webcal pour que Marvin voie ses événements. Pour « connecte mon agenda », « ajoute mon calendrier Google ».",
       {"url": {"type": "string", "description": "Lien iCal (.ics) ou webcal de l'agenda"},
        "name": {"type": "string", "description": "Nom de l'agenda (ex : Perso, Boulot)"},
        "color": {"type": "string", "description": "Couleur hex (optionnel)"}},
       ["url"]),
    _t("calendar_subscriptions", "Liste les agendas connectés (abonnements iCal) et leur état de synchronisation.",
       {}, []),
    _t("calendar_unsubscribe", "Déconnecte un agenda connecté et retire ses événements.",
       {"id": {"type": "string", "description": "Id de l'agenda"},
        "name": {"type": "string", "description": "Ou nom de l'agenda"}},
       []),
    _t("calendar_sync", "Resynchronise les agendas connectés (rafraîchit les événements externes). Pour « mets à jour mes agendas ».",
       {"id": {"type": "string", "description": "Limiter à un agenda (optionnel)"}},
       []),

    # ── Génération de documentation ────────────────────────────────────────────
    _t("document_generate", "Génère un document professionnel COMPLET au format Word (.docx) à partir de notes brutes, selon un modèle (rapport d'intervention, dossier professionnel, procédure, cahier des charges, compte-rendu, doc technique). Pour « rédige un rapport », « fais-moi un dossier Word », « génère une procédure ».",
       {"text": {"type": "string", "description": "Les notes / éléments bruts à mettre en forme"},
        "template": {"type": "string", "description": "Modèle : rapport_intervention, dossier_pro, procedure, cahier_charges, compte_rendu, doc_technique, libre"},
        "title": {"type": "string", "description": "Titre du document"},
        "output_path": {"type": "string", "description": "Chemin explicite du DOCX. Si absent, classement automatique dans la racine portable documents."},
        "theme": {"type": "string", "enum": ["professional", "executive", "minimal", "technical", "galactic", "luxury", "nature", "ocean", "editorial", "creative"], "description": "Thème graphique professionnel déterministe."},
        "design_prompt": {"type": "string", "description": "Brief visuel libre à respecter dans le rendu."},
        "layout": {"type": "string", "enum": ["masthead", "editorial", "proposal", "customer_pack", "immersive", "minimal"], "description": "Composition documentaire."},
        "density": {"type": "string", "enum": ["airy", "balanced", "compact"], "description": "Densité éditoriale."},
        "logo_position": {"type": "string", "enum": ["left", "center", "right"], "description": "Position du logo de l'en-tête."},
        "author": {"type": "string", "description": "Auteur (sinon déduit ou « Marvin »)"},
        "pdf": {"type": "boolean", "description": "Aussi exporter en PDF"},
        "mode": {"type": "string", "description": "rapide (1 passe, défaut) ou detaille (section par section, plus complet mais plus lent)"},
        "use_documents": {"type": "boolean", "description": "Enrichir avec les documents indexés"},
        "client": {"type": "string", "description": "Nom du client (apparaît sur la page de titre)"},
        "reference": {"type": "string", "description": "Référence du document"},
        "include_header": {"type": "boolean", "description": "Inclure l'en-tête configuré (défaut oui)"},
        "sign": {"type": "boolean", "description": "Ajouter un bloc signature à la fin"},
        "lieu": {"type": "string", "description": "Lieu pour la signature (« Fait à … »)"}},
       ["text"]),

    _t(
       "computer_control",
       "Contrôle visuel agentique du PC et du navigateur. Le LLM conduit librement la boucle "
       "Observer → Décider → Agir → Vérifier → Corriger. observe renvoie une capture et des "
       "element_ref facultatives. Utilise les coordonnées de frame_id lorsque l'UIA ne suffit "
       "pas. action=commit est obligatoire pour le clic final qui réserve, achète, publie ou "
       "envoie un formulaire : il demande toujours un clic utilisateur. Pour « ouvre [navigateur] "
       "et va sur [site] » : utilise action=open avec target=navigateur ET url=le site, EN UN SEUL "
       "APPEL — ne jamais enchaîner action=navigate ensuite, qui pilote un navigateur headless "
       "séparé et n'affecte jamais la fenêtre visible ouverte par open.",
       {
        "action": {"type": "string", "enum": [
            "observe", "verify", "screenshot", "list_windows", "wait", "open", "focus",
            "click", "double_click", "right_click", "move", "drag", "type",
            "keypress", "scroll", "navigate", "commit"
        ]},
        "surface": {"type": "string", "enum": ["auto", "desktop", "browser"],
                    "description": "Surface ciblée. Préciser browser pour les éléments Web Playwright."},
        "target": {"type": "string", "description": "Application à ouvrir ou URL à parcourir"},
        "url": {"type": "string", "description": "Avec action=open sur un navigateur (chrome/firefox/msedge/brave/opera) : URL à charger directement dans la fenêtre lancée, en un seul appel. Ne pas utiliser action=navigate après open pour ce cas — navigate pilote un navigateur headless séparé, jamais la fenêtre visible ouverte par open."},
        "window": {"type": "string", "description": "Sous-chaîne exacte du titre de fenêtre"},
        "hwnd": {"type": "integer", "description": "Identifiant hwnd exact renvoyé par observe/list_windows — cible plus fiable qu'un titre quand plusieurs fenêtres se ressemblent (utilisable avec action=focus)."},
        "control_type": {"type": "string", "description": "Type UIA desktop ou rôle ARIA Web issu de l'observation"},
        "name": {"type": "string", "description": "Nom accessible exact issu de l'observation"},
        "automation_id": {"type": "string", "description": "Identifiant UIA issu de l'observation"},
        "element_ref": {"type": "string", "description": "Référence opaque récente issue de observe"},
        "match_index": {"type": "integer", "minimum": 0, "description": "Index UIA en cas d'ambiguïté"},
        "text": {"type": "string", "description": "Texte à saisir, touche Playwright ou amplitude de scroll"},
        "frame_id": {"type": "string", "description": "Capture récente dont proviennent x et y"},
        "x": {"type": "number", "minimum": 0, "description": "Coordonnée horizontale dans frame_id"},
        "y": {"type": "number", "minimum": 0, "description": "Coordonnée verticale dans frame_id"},
        "end_x": {"type": "number", "minimum": 0, "description": "Destination horizontale du glisser-déposer"},
        "end_y": {"type": "number", "minimum": 0, "description": "Destination verticale du glisser-déposer"},
        "amount": {"type": "integer", "minimum": -10000, "maximum": 10000},
        "duration_ms": {"type": "integer", "minimum": 50, "maximum": 10000},
        "visual": {"type": "boolean", "description": "Inclure la capture ; vrai par défaut"},
        "commitment_summary": {"type": "string", "maxLength": 1000, "description": "Résumé humain obligatoire pour action=commit"},
        "expected": {"type": "string", "description": "Texte ou état attendu après l'action"},
        "max_elements": {"type": "integer", "minimum": 1, "maximum": 100},
        "embed": {"type": "boolean", "description": "Inclure la capture dans le résultat"},
        "capture_before": {"type": "boolean", "description": "Observer l'état avant une mutation"},
        "confirmed": {"type": "boolean", "description": "Injecté uniquement par le gateway après autorisation"}
       },
       ["action"]),

    # ── Documents (RAG) ────────────────────────────────────────────────────────
    _t("document_index", "Indexe un fichier ou un dossier (PDF, Word, Excel, PowerPoint, texte) pour pouvoir l'interroger. Pour « indexe ce document », « apprends ce dossier ».",
       {"path": {"type": "string", "description": "Chemin du fichier ou dossier à indexer"}},
       ["path"]),
    _t("document_ask", "Répond à une question en s'appuyant sur tes documents indexés, en citant les sources. Pour « que dit le contrat sur… », « cherche dans mes documents ».",
       {"question": {"type": "string", "description": "La question posée aux documents"},
        "k": {"type": "integer", "description": "Nombre de passages à récupérer (défaut 6)"}},
       ["question"]),
    _t("document_list", "Liste les documents actuellement indexés (interrogeables).", {}, []),
    _t("document_forget", "Retire un document de l'index (par id ou nom).",
       {"id": {"type": "string"}, "name": {"type": "string"}},
       []),
    _t("document_refine_section", "Affine UNE section d'un document déjà généré : développe, raccourcit, reformule, ajoute un tableau… puis régénère le .docx (en-tête/signature conservés). Pour « développe la partie Diagnostic », « complète la section Solution ».",
       {"file": {"type": "string", "description": "Le fichier .docx généré (nom ou chemin dans documents_generes)"},
        "section": {"type": "string", "description": "Le titre exact de la section à affiner (ex: 'Diagnostic')"},
        "instruction": {"type": "string", "description": "Ce qu'il faut faire (développe, raccourcis, ajoute un tableau, reformule plus formel…)"},
        "notes": {"type": "string", "description": "Éléments supplémentaires à intégrer (optionnel)"}},
       ["file", "section"]),
    _t("unified_search", "RECHERCHE UNIFIÉE : cherche le même terme PARTOUT à la fois (documents indexés, fichiers du PC par nom ET par contenu, notes, tâches, agenda, mémoire ; emails et web en option). Pour « retrouve tout ce qui concerne X », « cherche partout Y ».",
       {"query": {"type": "string", "description": "Ce que tu cherches"},
        "scope": {"type": "array", "items": {"type": "string"}, "description": "Sources à interroger (défaut : documents, fichiers, notes, tâches, agenda, mémoire). Ajoute 'emails' et 'web' au besoin, ou 'all'."},
        "limit": {"type": "integer", "description": "Résultats max par source (défaut 5)"}},
       ["query"]),

    # ── Notifications externes ─────────────────────────────────────────────────
    _t("telegram_send", "Envoie un message sur le Telegram de l'utilisateur (alerte/rappel sur son téléphone). Nécessite la config Telegram.",
       {"text": {"type": "string", "description": "Le message à envoyer"}},
       ["text"]),

    # ── Web par vrai navigateur ────────────────────────────────────────────────
    _t("web_research",
       "Recherche Web normale et sourcée : planifie plusieurs requêtes via SearXNG, "
       "déduplique les résultats, lit les meilleures pages avec un vrai navigateur et "
       "produit une synthèse avec liens directs. À préférer à web_search lorsque "
       "l'utilisateur demande une information actuelle, un résumé ou des sources.",
       {"query": {"type": "string", "description": "La question / les mots-clés à rechercher"}},
       ["query"]),
    _t("ai_model_council",
       "COUNCIL V2 : consulte exactement CINQ modèles Ollama Cloud de CINQ familles différentes, "
       "avec cinq rôles indépendants, une critique aveugle et un arbitrage final traçable. À appeler "
       "obligatoirement si l'utilisateur dit « mode Council », « Model Council » ou demande cinq "
       "modèles. Pour une recherche web, effectue d'abord la recherche puis passe les faits vérifiés "
       "dans evidence. Ne jamais l'utiliser spontanément pour une question simple.",
       {"question": {"type": "string", "maxLength": 50000, "description": "La question à poser à plusieurs modèles"},
        "evidence": {"type": "string", "maxLength": 12000, "description": "Faits ou sources déjà vérifiés à soumettre aux cinq modèles (optionnel)"}},
       ["question"]),
    _t("ai_cortex_search",
       "CORTEX SEARCH : explore 2 à 3 stratégies indépendantes avec Ollama Cloud, puis les "
       "fait contrôler par cinq vérificateurs spécialisés (exactitude, preuves, contraintes, "
       "risques et exécution) avant arbitrage. À utiliser uniquement lorsque l'utilisateur "
       "sélectionne explicitement Cortex Search pour un problème complexe et non sensible.",
       {"question": {"type": "string", "description": "Le problème complexe à explorer"},
        "evidence": {"type": "string", "description": "Faits ou sources déjà vérifiés (optionnel)"},
        "candidate_count": {"type": "integer", "description": "Nombre de stratégies, entre 2 et 3", "minimum": 2, "maximum": 3}},
        ["question"]),
    _t("ai_research_swarm",
       "RECHERCHE APPROFONDIE : planifie une recherche adaptative exclusivement via SearXNG, "
       "lit et déduplique les sources, comble les angles morts, puis fait analyser, contredire "
       "et vérifier les citations par cinq rôles Ollama Cloud. À utiliser lorsque l'utilisateur "
       "demande explicitement une recherche approfondie, exhaustive ou un état de l'art.",
       {"question": {"type": "string", "description": "Question de recherche complexe"},
        "agent_count": {"type": "integer", "minimum": 3, "maximum": 5,
                        "description": "Nombre de rôles d'analyse, défaut 5"},
        "sources_per_agent": {"type": "integer", "minimum": 1, "maximum": 8,
                              "description": "Pages retenues par requête, défaut 3"},
        "depth": {"type": "string", "enum": ["quick", "deep", "exhaustive"],
                  "description": "Profondeur de recherche"},
        "freshness": {"type": "string", "enum": ["day", "week", "month", "year"],
                      "description": "Filtre temporel optionnel"},
        "source_policy": {"type": "string",
                          "enum": ["balanced", "primary_first", "academic", "official_only"],
                          "description": "Politique de sélection des sources"},
        "preferred_domains": {"type": "array", "items": {"type": "string"},
                              "description": "Domaines à privilégier"},
        "excluded_domains": {"type": "array", "items": {"type": "string"},
                             "description": "Domaines à exclure"},
        "max_duration_seconds": {"type": "integer", "minimum": 60, "maximum": 1800}},
       ["question"]),
    _t("ai_adaptive_team",
       "ADAPTIVE TEAM : pour une demande explicitement approfondie et complexe, compose "
       "automatiquement le meilleur pipeline parmi Research Swarm, Cortex Search et Council. "
       "Peut rechercher d'abord puis soumettre les preuves à plusieurs stratégies vérifiées. "
       "Ne jamais l'utiliser pour une question simple, une rédaction directe ou sans demande "
       "de profondeur. Bloqué pour les données sensibles hors Ultra débridé.",
       {"question": {"type": "string", "description": "Problème complexe à confier à l'équipe adaptative"}},
       ["question"]),
    _t("ai_code_forge",
       "CODE FORGE : génère ou corrige un script/code avec contrat d'architecture, implémentation "
        "complète, deux revues indépendantes, réparation, tests générés et exécution dans un "
        "environnement jetable. Les contrôles initiaux restent hors ligne ; les dépendances sont "
        "ensuite installées et testées avec Internet dans Docker Linux ou Windows Sandbox. "
        "Les projets avancés créent une mission durable avec snapshots et reprise par mission_id. "
       "À utiliser pour toute demande de script d'installation, "
       "déploiement, administration ou code complet nécessitant une qualité de production. "
       "Les données sensibles restent bloquées hors Ultra débridé.",
        {"request": {"type": "string", "description": "Exigence complète du script ou programme"},
         "evidence": {"type": "string", "description": "Documentation et faits déjà vérifiés (optionnel)"},
         "mission_id": {"type": "string", "description": "Mission de coding durable à reprendre (optionnel)"}},
       ["request"]),
    _t("ai_test_forge",
       "TEST FORGE : analyse puis exécute un code dans un environnement jetable. Le premier passage "
       "Docker est sans réseau, en lecture seule et à ressources bornées. Si require_online=true, "
        "un second passage avec Internet dans la toolchain du langage installe les dépendances puis Test Forge lance lui-même "
       "les tests. Les scripts Bash exigeant systemd ou des services sont automatiquement escaladés "
       "vers la VM Debian Hyper-V restaurée avant et après le test. PowerShell utilise Windows Sandbox avec Internet et réseaux privés bloqués. "
       "Bash utilise ShellCheck+Bats, Python compile+unittest et JavaScript node --check+node:test. "
       "Sans Windows Sandbox disponible, PowerShell reste refusé pour la production. Une suite de "
       "tests est obligatoire pour obtenir production_ready=true. Un script qui installe des "
       "paquets ou services force automatiquement require_online=true et reste refusé sans "
       "harness d'intégration réel.",
       {"code": {"type": "string", "description": "Code complet à valider"},
        "language": {"type": "string", "enum": ["bash", "python", "javascript", "json", "powershell", "go"],
                     "description": "Langage du livrable"},
        "test_code": {"type": "string", "description": "Suite de tests complète adaptée au langage"},
         "integration_test_code": {"type": "string",
                                   "description": "Harness Bash d'intégration Debian en ligne"},
         "files": {"type": "object", "additionalProperties": {"type": "string"},
                   "description": "Fichiers auxiliaires indexés par chemin relatif sûr"},
        "require_online": {"type": "boolean",
                           "description": "Exige un test Internet réel après les tests hors ligne"},
        "timeout_seconds": {"type": "integer", "minimum": 10, "maximum": 180,
                            "description": "Timeout par étape, défaut 90 secondes"}},
       ["code", "language", "test_code"]),
    _t("code_workspace_start",
       "CODE WORKSPACE : crée une Coding Mission durable depuis le chat. Si repository_path est "
       "vide, Marvin crée automatiquement un dépôt Git isolé dans sa bibliothèque locale. Déduit "
       "la cible Linux ou Windows depuis la demande, lance Code Forge, Test Forge et les reprises "
       "Auto jusqu'au succès. À utiliser quand l'utilisateur demande de travailler dans Code "
       "Workspace, de coder un projet long ou de suivre les fichiers et preuves dans /code.",
       {"request": {"type": "string", "description": "Demande de code complète"},
        "repository_path": {"type": "string", "description": "Dépôt Git existant, optionnel"},
        "target_mode": {"type": "string", "enum": ["auto", "windows", "linux", "both"],
                        "description": "Cible, auto par défaut"},
        "autonomy": {"type": "string", "enum": ["autonomous", "supervised"],
                     "description": "Mode Auto ou supervisé"},
        "max_duration_minutes": {"type": "integer", "minimum": 5, "maximum": 1440},
        "max_iterations": {"type": "integer", "minimum": 1, "maximum": 100},
        "max_files_changed": {"type": "integer", "minimum": 1, "maximum": 1000},
        "confirmed": {"type": "boolean", "description": "Confirmation de création et démarrage"}},
       ["request"]),
    _t("code_workspace_status",
       "Consulte depuis le chat les Coding Missions, leur job Auto, fichiers de snapshot lisibles, "
       "phases, preuves et capacités réelles Docker/VM. Sans mission_id, liste les missions; avec "
       "mission_id, retourne le détail durable. Lis toujours artifacts.files au lieu de deviner un "
       "chemin dans le worktree : un livrable refusé reste dans le snapshot sans être appliqué.",
       {"mission_id": {"type": "string", "description": "Identifiant de mission optionnel"}}, []),
    _t("code_workspace_control",
       "Reprend ou annule depuis le chat le job Auto d'une Coding Mission existante. L'action est "
       "persistante et doit être confirmée.",
       {"mission_id": {"type": "string", "description": "Identifiant exact de Coding Mission"},
        "action": {"type": "string", "enum": ["resume", "cancel"]},
        "confirmed": {"type": "boolean", "description": "Confirmation explicite"}},
       ["mission_id", "action"]),
    _t("ai_subagents_run",
       "Décompose un objectif en 2-5 sous-tâches INDÉPENDANTES traitées EN PARALLÈLE puis "
       "fusionnées en un résultat cohérent (équivalent Ultra mode de GPT-5.6 Sol, sans accès "
       "aux outils par sous-tâche). Pour un objectif qui se découpe naturellement en angles "
       "indépendants (« rédige une politique de sécurité couvrant accès/incidents/"
       "sauvegardes », « analyse ce sujet sous 3 angles différents »). PAS pour une tâche qui "
       "a besoin d'outils (fichiers, PC, web) — utilise la conversation normale pour ça.",
       {"goal": {"type": "string", "description": "L'objectif global à décomposer"},
        "subtasks": {"type": "array", "items": {"type": "string"}, "description": "Sous-tâches explicites (optionnel — auto-décomposées si absent)"}},
       ["goal"]),
    _t("long_task_start",
       "Démarre une TÂCHE LONGUE AUTONOME : décompose l'objectif en étapes (créées dans "
       "Tâches), avance immédiatement dessus avec tes outils normaux, puis continue "
       "automatiquement en arrière-plan (reprise toutes les 5 min) jusqu'à ce que tout soit "
       "fait — même après la fin de cette conversation. Pour « occupe-toi de X en tâche de "
       "fond », « fais avancer ce projet pendant que je fais autre chose », un objectif à "
       "plusieurs étapes qui n'a pas besoin de supervision constante. PAS pour une question "
       "simple ou une action en un seul appel d'outil (équivalent ChatGPT Work, en plus léger). "
       "PLAN MODE : le 1er appel (sans confirmed) renvoie un PLAN proposé sans rien créer — "
       "présente-le à l'utilisateur, puis si accepté, RAPPELLE cet outil avec confirmed=true "
       "et les MÊMES 'steps' reçus pour démarrer réellement.",
       {"goal": {"type": "string", "description": "L'objectif à accomplir en tâche de fond"},
        "steps": {"type": "array", "items": {"type": "string"},
                  "description": "Étapes du plan déjà proposé (à fournir identiques lors du rappel confirmé — sinon un nouveau plan est généré)"},
        "confirmed": {"type": "boolean", "description": "true pour démarrer réellement après validation du plan par l'utilisateur"}},
       ["goal"]),
    _t("long_task_status", "Vérifie l'avancement d'une ou de toutes les tâches longues en cours (voir long_task_start).",
       {"tag": {"type": "string", "description": "Tag précis (ex. longtask:xxx) — optionnel, toutes si absent"}},
       []),
    _t("long_task_stop", "Arrête la reprise automatique d'une tâche longue (les étapes déjà faites restent visibles).",
       {"tag": {"type": "string", "description": "Le tag de la tâche longue (voir long_task_status)"}},
       ["tag"]),
    _t("web_deep_research",
       "Recherche APPROFONDIE multi-passes sur le web (équivalent Deep Research de ChatGPT/Claude/"
       "Gemini/Perplexity) : plusieurs cycles recherche→analyse des trous→recherche complémentaire, "
       "rapport structuré avec citations numérotées. PREND PLUSIEURS MINUTES — à utiliser quand "
       "l'utilisateur demande explicitement une recherche approfondie/exhaustive, un rapport "
       "détaillé ou impose une couverture multi-source importante, "
       "jamais pour une question simple (utiliser web_research à la place, bien plus rapide).",
       {"query": {"type": "string", "description": "Le sujet à rechercher en profondeur"},
        "depth": {"type": "string", "enum": ["deep", "exhaustive"],
                  "description": "deep vise 50 pages; exhaustive vise au moins 100 requêtes et 50 pages"},
        "freshness": {"type": "string", "enum": ["day", "week", "month", "year"],
                      "description": "Fenêtre temporelle SearXNG optionnelle"}},
       ["query"]),
    _t("web_browser_open", "Ouvre une page web précise dans un vrai navigateur et renvoie son texte (utile si l'outil web interne est bloqué ou pour un site dynamique).",
       {"url": {"type": "string", "description": "L'adresse de la page à ouvrir"}},
       ["url"]),

    # ── SSH ───────────────────────────────────────────────────────────────────
    _t("ssh_list", "Liste les connexions SSH sauvegardées dans Marvin.",
       {}, []),

    _t("ssh_connection_save",
       "Enregistre une cible SSH (nom, hôte, port, utilisateur) SANS mot de passe ni clé. Pour "
       "« ajoute/enregistre cette connexion SSH ». Les secrets doivent ensuite être saisis par "
       "l'utilisateur lui-même dans l'onglet SSH.",
       {"name": {"type": "string", "description": "Nom lisible de la connexion"},
        "host": {"type": "string", "description": "Adresse IP ou nom DNS"},
        "port": {"type": "integer", "description": "Port, défaut 22"},
        "username": {"type": "string", "description": "Nom d'utilisateur SSH"}},
       ["name", "host", "username"]),

    _t("ssh_exec",
       "Exécute une commande sur un serveur SSH — connexion SAUVEGARDÉE (connection_id, voir "
       "ssh_list) OU PONCTUELLE (host + username + password ou private_key, sans l'enregistrer "
       "au préalable — pour « connecte-toi à cette IP avec ces identifiants »). Requiert "
       "confirmation explicite dans tous les cas.",
       {"connection_id": {"type": "string", "description": "ID d'une connexion SSH déjà sauvegardée (voir ssh_list)"},
        "host": {"type": "string", "description": "Adresse du serveur (connexion ponctuelle, alternative à connection_id)"},
        "port": {"type": "integer", "description": "Port SSH (défaut 22)"},
        "username": {"type": "string", "description": "Utilisateur SSH (connexion ponctuelle)"},
        "password": {"type": "string", "description": "Mot de passe (connexion ponctuelle, si pas de clé)"},
        "private_key": {"type": "string", "description": "Clé privée SSH complète (connexion ponctuelle, si pas de mot de passe)"},
        "command": {"type": "string", "description": "Commande à exécuter sur le serveur distant"},
        "timeout": {"type": "integer", "description": "Délai maximum en secondes (défaut 30, max 120)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur (obligatoire avant exécution)"}},
       ["command"]),
    _t("ssh_exec_multi", "Exécute une commande sur PLUSIEURS serveurs SSH SAUVEGARDÉS en parallèle (administration de parc).",
       {"connection_ids": {"type": "array", "description": "Liste d'IDs de connexions SSH"},
        "command": {"type": "string"},
        "timeout": {"type": "integer"},
        "confirmed": {"type": "boolean"}},
       ["connection_ids", "command"]),
    _t("ssh_write_and_run",
       "Écrit un script (texte généré) sur une machine distante via SFTP PUIS l'exécute — "
       "connexion sauvegardée (connection_id) OU ponctuelle (host+username+password/private_key). "
       "Pour « crée un script d'installation de X et lance-le sur ce serveur » — plus fiable "
       "qu'un heredoc dans ssh_exec (pas de souci d'échappement de quotes).",
       {"connection_id": {"type": "string", "description": "ID d'une connexion SSH sauvegardée"},
        "host": {"type": "string", "description": "Adresse du serveur (connexion ponctuelle)"},
        "port": {"type": "integer", "description": "Port SSH (défaut 22)"},
        "username": {"type": "string", "description": "Utilisateur SSH (connexion ponctuelle)"},
        "password": {"type": "string", "description": "Mot de passe (connexion ponctuelle)"},
        "private_key": {"type": "string", "description": "Clé privée SSH (connexion ponctuelle)"},
        "content": {"type": "string", "description": "Contenu du script à écrire sur la machine distante"},
        "remote_path": {"type": "string", "description": "Chemin distant du script (ex. /tmp/install.sh)"},
        "run_command": {"type": "string", "description": "Commande d'exécution (défaut : chmod +x puis lance le script)"},
        "timeout": {"type": "integer", "description": "Délai maximum en secondes (défaut 120, max 600)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur (obligatoire)"}},
       ["content", "remote_path"]),
    _t("ssh_upload", "Envoie un fichier local vers un serveur SSH via SFTP.",
       {"connection_id": {"type": "string"},
        "local_path": {"type": "string", "description": "Fichier local à envoyer"},
        "remote_path": {"type": "string", "description": "Destination sur le serveur"},
        "confirmed": {"type": "boolean"}},
       ["connection_id", "local_path", "remote_path"]),
    _t("ssh_download", "Télécharge un fichier d'un serveur SSH vers le PC (SFTP).",
       {"connection_id": {"type": "string"},
        "remote_path": {"type": "string", "description": "Fichier distant à récupérer"},
        "local_path": {"type": "string", "description": "Destination locale (défaut : Téléchargements)"}},
       ["connection_id", "remote_path"]),
    _t("ssh_list_dir", "Liste un dossier distant d'un serveur SSH (SFTP).",
       {"connection_id": {"type": "string"},
        "remote_path": {"type": "string", "description": "Dossier distant (défaut : ~)"}},
       ["connection_id"]),
    _t("ssh_server_info", "Diagnostic rapide d'un serveur SSH : OS, uptime, RAM, disque, charge.",
       {"connection_id": {"type": "string"}},
       ["connection_id"]),

    # ── Voice ─────────────────────────────────────────────────────────────────
    _t("voice_transcribe", "Transcrit un fichier audio local en texte via Whisper (faster-whisper, entièrement local).",
       {"audio_path": {"type": "string", "description": "Chemin du fichier audio (mp3, wav, ogg, webm, mp4...)"},
        "model": {"type": "string", "enum": ["tiny", "base", "small", "medium", "large-v3"],
                  "description": "Taille du modèle Whisper (défaut : base). Plus grand = plus précis mais plus lent."},
        "language": {"type": "string", "description": "Code langue ISO (ex: fr, en). Omis = détection automatique."}},
       ["audio_path"]),

    # ── Utilitaires ───────────────────────────────────────────────────────────
    _t("calculator", "Évalue une expression mathématique bornée (arithmétique, trigonométrie, logarithmes, factorielle, etc.).",
       {"expression": {"type": "string", "description": "Expression à évaluer. Exemples : '(12 + 4) * 3 / 2', 'sqrt(144)', 'sin(pi/2)', 'factorial(10)'"}},
       ["expression"]),

    _t("datetime_info",
       "Retourne la date/heure actuelle, convertit entre fuseaux horaires, calcule des différences ou ajoute un delta à une date.",
       {"action":    {"type": "string", "enum": ["now", "convert", "diff", "add"],
                      "description": "Action : now=heure actuelle, convert=changer fuseau, diff=durée entre deux dates, add=ajouter un delta"},
        "timezone":  {"type": "string", "description": "Nom du fuseau horaire IANA (ex: Europe/Paris, America/New_York). Défaut : Europe/Paris"},
        "datetime":  {"type": "string", "description": "Date/heure ISO 8601 (requis pour convert, diff, add). Ex: '2025-06-01T14:30:00'"},
        "datetime2": {"type": "string", "description": "Deuxième date/heure ISO 8601 (requis pour action=diff)"},
        "delta":     {"type": "object",
                      "properties": {
                          "weeks": {"type": "integer", "minimum": -1000000, "maximum": 1000000},
                          "days": {"type": "integer", "minimum": -1000000, "maximum": 1000000},
                          "hours": {"type": "integer", "minimum": -1000000, "maximum": 1000000},
                          "minutes": {"type": "integer", "minimum": -1000000, "maximum": 1000000},
                          "seconds": {"type": "integer", "minimum": -1000000, "maximum": 1000000}},
                      "additionalProperties": False,
                      "description": "Durée à ajouter (action=add). Ex: {\"days\": 5, \"hours\": 2, \"minutes\": 30}"}},
       []),

    _t("weather", "Récupère la météo actuelle et les prévisions (jusqu'à 7 jours) via Open-Meteo (gratuit, sans clé API).",
       {"city":    {"type": "string", "description": "Nom de la ville (ex: Paris, Lyon, Toulouse)"},
        "country": {"type": "string", "description": "Code pays ISO 2 lettres (ex: FR, BE, CH). Aide à disambiguïser."},
        "days":    {"type": "integer", "minimum": 1, "maximum": 7,
                    "description": "Nombre de jours de prévisions (1 à 7, défaut : 1)"}},
       ["city"]),

    _t("translate", "Traduit du texte via Ollama en respectant le profil de confidentialité cloud/local actif.",
       {"text":        {"type": "string",  "description": "Texte à traduire"},
        "target_lang": {"type": "string",  "description": "Langue cible (code ISO 2 lettres : fr, en, es, de, it, pt, ar, zh, ja, ru…)"},
        "source_lang": {"type": "string",  "description": "Langue source (code ISO ou 'auto' pour détection automatique — défaut : auto)"}},
       ["text", "target_lang"]),

    _t("unit_convert", "Convertit une valeur entre unités (longueur, masse, volume, vitesse, surface, énergie, données numériques, température).",
       {"value":     {"type": "number", "description": "Valeur numérique à convertir"},
        "from_unit": {"type": "string", "description": "Unité source (ex: km, lb, L, °C, km/h, GB…)"},
        "to_unit":   {"type": "string", "description": "Unité destination (ex: m, kg, ml, °F, m/s, MB…)"}},
       ["value", "from_unit", "to_unit"]),

    _t("password_generate", "Génère des mots de passe ou PINs sécurisés avec critères configurables.",
       {"length":  {"type": "integer", "minimum": 4, "maximum": 128, "description": "Longueur du mot de passe (défaut 16)"},
        "count":   {"type": "integer", "minimum": 1, "maximum": 20, "description": "Nombre de mots de passe à générer (défaut 1)"},
        "include": {"type": "array",   "items": {"type": "string", "enum": ["letters", "digits", "symbols"]},
                    "description": "Catégories incluses : ['letters', 'digits', 'symbols']. Défaut : les trois."},
        "exclude": {"type": "string",  "description": "Caractères à exclure (ex: 'Il1O0' pour éviter confusions)"},
        "pin":     {"type": "boolean", "description": "Mode PIN numérique uniquement (défaut false)"}},
       []),

    # ── Section 15 — traitement de données ────────────────────────────────────
    _t("hash_compute", "Calcule une empreinte d'un texte ou fichier. SHA-2/SHA-3/BLAKE2 sont recommandés; MD5/SHA-1 restent disponibles avec avertissement.",
       {"text":      {"type": "string", "description": "Texte à hacher"},
        "file_path": {"type": "string", "description": "Chemin du fichier à hacher"},
        "algorithm": {"type": "string", "enum": ["md5", "sha1", "sha256", "sha512", "sha3_256", "blake2b"],
                      "description": "Algorithme (défaut : sha256)"}},
       []),

    _t("base64_tool", "Encode ou décode en Base64 (standard ou URL-safe).",
       {"data":     {"type": "string",  "description": "Texte à encoder ou chaîne Base64 à décoder"},
        "action":   {"type": "string",  "enum": ["encode", "decode"], "description": "Action (défaut : encode)"},
        "url_safe": {"type": "boolean", "description": "Utiliser le variant URL-safe (défaut false)"}},
       ["data"]),

    _t("text_extract", "Extrait des emails, URLs et numéros de téléphone d'un texte.",
       {"text":    {"type": "string", "maxLength": 1000000, "description": "Texte source à analyser"},
        "extract": {"type": "string", "enum": ["emails", "urls", "phones", "all"],
                    "description": "Type à extraire (défaut : all)"}},
       ["text"]),

    _t("diff_text", "Compare deux textes et affiche les différences (unified diff ou ratio de similarité).",
       {"text_a":        {"type": "string", "maxLength": 500000, "description": "Premier texte"},
        "text_b":        {"type": "string", "maxLength": 500000, "description": "Second texte"},
        "mode":          {"type": "string", "enum": ["unified", "context", "ndiff", "ratio"],
                          "description": "Mode de diff (défaut : unified)"},
        "context_lines": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Lignes de contexte (défaut 3)"}},
       ["text_a", "text_b"]),

    _t("image_info", "Retourne les métadonnées d'une image (dimensions, format, taille, EXIF).",
       {"path": {"type": "string", "description": "Chemin de l'image"}},
       ["path"]),

    _t("image_resize", "Redimensionne ou convertit une image (PNG, JPEG, WEBP) via Pillow.",
       {"path":        {"type": "string",  "description": "Chemin de l'image source"},
        "width":       {"type": "integer", "description": "Largeur cible en pixels"},
        "height":      {"type": "integer", "description": "Hauteur cible en pixels"},
        "output_path": {"type": "string",  "description": "Chemin de sortie (défaut : même dossier _resized)"},
        "format":      {"type": "string",  "enum": ["JPEG", "PNG", "WEBP"], "description": "Format de sortie"},
        "quality":     {"type": "integer", "description": "Qualité JPEG/WEBP (1-95, défaut 85)"},
        "keep_ratio":  {"type": "boolean", "description": "Conserver le ratio (défaut true)"}},
       ["path"]),

    _t("qr_generate", "Génère un QR code PNG depuis un texte ou une URL.",
       {"data":        {"type": "string",  "maxLength": 4000, "description": "Texte ou URL à encoder dans le QR code"},
        "output_path": {"type": "string",  "description": "Chemin du fichier PNG de sortie (défaut : Bureau)"},
        "size":        {"type": "integer", "minimum": 1, "maximum": 50, "description": "Taille des modules en pixels (défaut 10)"},
        "border":      {"type": "integer", "minimum": 0, "maximum": 20, "description": "Bordure autour (défaut 4 modules)"},
        "fg_color":    {"type": "string",  "description": "Couleur des modules (défaut black)"},
        "bg_color":    {"type": "string",  "description": "Couleur de fond (défaut white)"}},
       ["data"]),

    _t("json_tool", "Formate, minifie, valide ou interroge un JSON (dot-notation path).",
       {"data":   {"type": "string", "description": "JSON en texte"},
        "action": {"type": "string", "enum": ["format", "minify", "validate", "query"],
                   "description": "Action (défaut : format)"},
        "path":   {"type": "string", "description": "Chemin JSON pour l'action query (ex: 'user.address.city')"}},
       ["data"]),

    _t("text_stats", "Analyse un texte : nombre de mots, caractères, phrases, temps de lecture et mots fréquents.",
       {"text":      {"type": "string",  "description": "Texte à analyser"},
        "top_words": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Nombre de mots fréquents à retourner (défaut 10)"}},
       ["text"]),

    _t("ip_info", "Retourne via HTTPS la géolocalisation et les infos réseau d'une adresse IP publique globale (IPWhois, sans clé).",
       {"ip": {"type": "string", "maxLength": 64, "description": "Adresse IPv4/IPv6 globale à analyser (vide = IP publique de la machine)"}},
       []),

    _t("markdown_convert", "Convertit du Markdown en HTML, texte brut ou retourne des statistiques (titres, liens, blocs de code).",
       {"text":   {"type": "string", "maxLength": 1000000, "description": "Contenu Markdown à convertir"},
        "to":     {"type": "string", "enum": ["html", "plain", "stats"],
                   "description": "Format cible : html (défaut), plain (texte brut), stats"}},
       ["text"]),

    _t("regex_tool", "Applique une expression régulière à un texte : recherche, extraction, remplacement ou validation.",
       {"pattern":     {"type": "string", "maxLength": 2048, "description": "Expression régulière"},
        "text":        {"type": "string", "maxLength": 1000000, "description": "Texte cible"},
        "action":      {"type": "string", "enum": ["findall", "match", "replace", "split", "test"],
                        "description": "Action (défaut : findall)"},
        "replace":     {"type": "string", "maxLength": 100000, "description": "Texte de remplacement (pour action replace)"},
        "flags":       {"type": "string", "pattern": "^[IMSims]*$", "description": "Flags : I (insensible à la casse), M (multiline), S (dot-all)"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Limite de résultats (défaut 100)"}},
       ["pattern"]),
    # ── Section 16 ──────────────────────────────────────────────────────────
    _t("pdf_read", (
           "Extrait le texte d'un fichier PDF page par page pour une analyse, une citation "
           "ou un résumé de son contenu."),
       {"path":      {"type": "string", "description": "Chemin du fichier PDF"},
        "pages":     {"type": "string", "description": "Pages à lire : '1-3', '2' ou null pour tout (défaut : tout)"},
        "max_chars": {"type": "integer", "description": "Limite de caractères retournés (défaut 4000)"}},
       ["path"]),
    _t("pdf_info", "Retourne les métadonnées d'un fichier PDF : titre, auteur, nombre de pages, taille.",
       {"path": {"type": "string", "description": "Chemin du fichier PDF"}},
       ["path"]),
    _t("pdf_merge", "Fusionne plusieurs PDF en un seul fichier, dans l'ordre fourni.",
       {"sources": {"type": "array", "items": {"type": "string"}, "description": "Liste des PDF à fusionner (≥2)"},
        "output_path": {"type": "string", "description": "PDF de sortie (défaut : Bureau/fusion.pdf)"}},
       ["sources"]),
    _t("pdf_split", "Découpe un PDF : une page par fichier (per_page) ou extrait des pages précises (pages='1-3,5').",
       {"path": {"type": "string", "description": "PDF source"},
        "pages": {"type": "string", "description": "Pages à extraire, ex '1-3,5' (vide = toutes)"},
        "per_page": {"type": "boolean", "description": "Un fichier par page (défaut si pages vide)"},
        "output_dir": {"type": "string", "description": "Dossier de sortie (défaut : dossier du PDF)"}},
       ["path"]),
    _t("pdf_rotate", "Pivote des pages d'un PDF (angle multiple de 90).",
       {"path": {"type": "string", "description": "PDF source"},
        "angle": {"type": "integer", "enum": [90, 180, 270], "description": "Angle de rotation horaire"},
        "pages": {"type": "string", "description": "Pages à pivoter, ex '1,3-4' (vide = toutes)"},
        "output_path": {"type": "string", "description": "PDF de sortie"}},
       ["path"]),
    _t("pdf_watermark", "Appose un filigrane texte en diagonale sur chaque page d'un PDF (ex : CONFIDENTIEL).",
       {"path": {"type": "string", "description": "PDF source"},
        "text": {"type": "string", "description": "Texte du filigrane"},
        "opacity": {"type": "number", "description": "Opacité 0-1 (défaut 0.12)"},
        "font_size": {"type": "integer", "description": "Taille de police (auto si absent)"},
        "output_path": {"type": "string", "description": "PDF de sortie"}},
       ["path", "text"]),
    _t("pdf_protect", "Protège un PDF par mot de passe (chiffrement AES-256).",
       {"path": {"type": "string", "description": "PDF source"},
        "password": {"type": "string", "description": "Mot de passe d'ouverture"},
        "owner_password": {"type": "string", "description": "Mot de passe propriétaire (optionnel)"},
        "output_path": {"type": "string", "description": "PDF de sortie"}},
       ["path", "password"]),
    _t("pdf_extract_images", "Extrait les images intégrées d'un PDF vers un dossier.",
       {"path": {"type": "string", "description": "PDF source"},
        "output_dir": {"type": "string", "description": "Dossier de sortie (défaut : <pdf>_images)"}},
       ["path"]),
    _t("pdf_to_images", "Convertit chaque page d'un PDF en image PNG (rendu visuel haute qualité).",
       {"path": {"type": "string", "description": "PDF source"},
        "pages": {"type": "string", "description": "Pages, ex '1-3,5' (vide = toutes)"},
        "dpi": {"type": "integer", "description": "Résolution en DPI (défaut 150)"},
        "output_dir": {"type": "string", "description": "Dossier de sortie (défaut : <pdf>_pages)"}},
       ["path"]),
    _t("pdf_ocr", "OCR d'un PDF même SCANNÉ → texte. Utilise le texte intégré si présent, sinon rend la page et l'OCR par IA (llava).",
       {"path": {"type": "string", "description": "PDF source"},
        "pages": {"type": "string", "description": "Pages à traiter, ex '1-3' (vide = toutes)"},
        "max_pages": {"type": "integer", "description": "Limite de pages à traiter (défaut 15)"},
        "output_path": {"type": "string", "description": "Fichier .txt de sortie (optionnel)"}},
       ["path"]),
    _t("pdf_form_fields", "Liste les champs de formulaire remplissables (AcroForm) d'un PDF.",
       {"path": {"type": "string", "description": "PDF source"}},
       ["path"]),
    _t("pdf_fill_form", "Remplit les champs d'un formulaire PDF depuis un objet {champ: valeur}.",
       {"path": {"type": "string", "description": "PDF formulaire source"},
        "data": {"type": "object", "description": "Dictionnaire {nom_du_champ: valeur}"},
        "output_path": {"type": "string", "description": "PDF de sortie (défaut : _rempli)"}},
       ["path", "data"]),
    _t("images_to_pdf", "Assemble plusieurs images en un PDF (une image par page).",
       {"sources": {"type": "array", "items": {"type": "string"}, "description": "Images à assembler (ordre conservé)"},
        "output_path": {"type": "string", "description": "PDF de sortie (défaut : Bureau/images.pdf)"},
        "dpi": {"type": "integer", "description": "Résolution (défaut 150)"}},
       ["sources"]),
    _t("image_crop", "Rogne une image : boîte (left/top/right/bottom) ou aspect ('1:1','16:9') centré.",
       {"path": {"type": "string", "description": "Image source"},
        "aspect": {"type": "string", "description": "Ratio cible centré, ex '1:1', '16:9'"},
        "left": {"type": "integer"}, "top": {"type": "integer"},
        "right": {"type": "integer"}, "bottom": {"type": "integer"},
        "output_path": {"type": "string", "description": "Image de sortie"}},
       ["path"]),
    _t("image_rotate", "Pivote (angle horaire) et/ou retourne (flip horizontal/vertical) une image.",
       {"path": {"type": "string", "description": "Image source"},
        "angle": {"type": "number", "description": "Angle horaire en degrés"},
        "flip": {"type": "string", "enum": ["horizontal", "vertical"], "description": "Miroir"},
        "output_path": {"type": "string", "description": "Image de sortie"}},
       ["path"]),
    _t("image_compress", "Compresse une image vers un poids cible (target_kb) ou une qualité fixe (JPEG/WEBP).",
       {"path": {"type": "string", "description": "Image source"},
        "target_kb": {"type": "integer", "description": "Poids cible en Ko (ajuste la qualité automatiquement)"},
        "quality": {"type": "integer", "description": "Qualité fixe 1-100 (défaut 80) si pas de target_kb"},
        "format": {"type": "string", "enum": ["JPEG", "WEBP"], "description": "Format de sortie"},
        "output_path": {"type": "string", "description": "Image de sortie"}},
       ["path"]),
    _t("image_batch", "Traite en LOT toutes les images d'un dossier : convert/resize/compress/rotate/watermark.",
       {"directory": {"type": "string", "description": "Dossier contenant les images"},
        "operation": {"type": "string", "enum": ["convert", "resize", "compress", "rotate", "watermark"], "description": "Opération à appliquer"},
        "output_dir": {"type": "string", "description": "Dossier de sortie (défaut : <dossier>_traite)"},
        "format": {"type": "string", "description": "Format cible pour convert (JPEG/PNG/WEBP)"},
        "width": {"type": "integer", "description": "Largeur pour resize"},
        "height": {"type": "integer", "description": "Hauteur pour resize"},
        "target_kb": {"type": "integer", "description": "Poids cible pour compress"},
        "quality": {"type": "integer", "description": "Qualité JPEG (défaut 85)"},
        "angle": {"type": "number", "description": "Angle pour rotate"},
        "flip": {"type": "string", "enum": ["horizontal", "vertical"], "description": "Miroir pour rotate"},
        "text": {"type": "string", "description": "Texte pour watermark"},
        "recursive": {"type": "boolean", "description": "Inclure les sous-dossiers"}},
       ["directory", "operation"]),
    _t("file_large_finder", "Liste les plus gros fichiers d'un dossier (récursif) pour repérer ce qui occupe l'espace disque.",
       {"directory": {"type": "string", "maxLength": 32767, "description": "Dossier à analyser (défaut : dossier personnel)"},
        "top": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Nombre de fichiers à retourner (défaut 20)"},
        "min_mb": {"type": "number", "minimum": 0, "maximum": 1000000, "description": "Taille minimale en Mo à considérer"},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 1000000, "description": "Nombre maximal de fichiers parcourus (défaut 100000)"}},
       []),
    _t("system_cleanup", "Analyse les fichiers temporaires et l'espace réellement récupérable. delete=true supprime uniquement les fichiers assez anciens (action sensible).",
       {"delete": {"type": "boolean", "description": "true = supprimer réellement (sinon rapport seul)"},
        "min_age_days": {"type": "number", "minimum": 0, "maximum": 3650, "description": "Âge minimal des fichiers à supprimer en jours (défaut 1)"},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 500000, "description": "Nombre maximal de fichiers inspectés (défaut 500000)"},
        "confirmed": {"type": "boolean", "description": "Confirmation explicite de suppression"}},
       []),
    _t("pptx_create", "Crée et vérifie un PowerPoint professionnel. Outil exclusif pour créer ou refaire le design d'une présentation : ne jamais utiliser Test Forge ou Python à sa place. Gère un fichier ouvert en livrant automatiquement une nouvelle version. Retourne l'artefact, sa taille et son SHA-256.",
       {"title": {"type": "string", "maxLength": 10000, "description": "Titre de la présentation (diapo de couverture)"},
        "subtitle": {"type": "string", "maxLength": 10000, "description": "Sous-titre de couverture"},
        "slides": {"type": "array", "maxItems": 100,
                   "items": {"type": "object", "additionalProperties": False,
                             "properties": {
                                 "title": {"type": "string", "maxLength": 10000},
                                 "bullets": {"type": "array", "maxItems": 100,
                                             "items": {"type": "string", "maxLength": 10000}},
                                 "points": {"type": "array", "maxItems": 100,
                                            "items": {"type": "string", "maxLength": 10000}},
                                 "image_path": {"type": "string", "maxLength": 32767,
                                                "description": "Image locale vérifiée à intégrer dans la diapositive"},
                                 "image_caption": {"type": "string", "maxLength": 1000},
                                 "source_url": {"type": "string", "maxLength": 8192,
                                                "description": "URL de provenance du contenu ou de l'image"}
                             }},
                   "description": "Diapos : [{title, bullets:[...]}, …]"},
        "output_path": {"type": "string", "maxLength": 32767, "description": "Fichier .pptx ou dossier de sortie (défaut : Bureau)"},
        "style": {"type": "string", "enum": ["professional_dark", "office"], "description": "professional_dark (défaut) ou office"},
        "source_job_id": {"type": "string", "maxLength": 80, "description": "Identifiant du crawl ayant fondé la présentation"}},
       []),
    _t("pptx_read", "Extrait le texte de toutes les diapos d'un PowerPoint (.pptx).",
       {"path": {"type": "string", "maxLength": 32767, "description": "Fichier .pptx"}},
       ["path"]),
    _t("csv_to_xlsx", "Convertit un fichier CSV en classeur Excel (.xlsx) avec en-têtes en gras.",
       {"path": {"type": "string", "description": "Fichier CSV source"},
        "delimiter": {"type": "string", "description": "Séparateur (auto-détecté si absent)"},
        "output_path": {"type": "string", "description": "Fichier .xlsx de sortie"}},
       ["path"]),
    _t("xlsx_to_csv", "Convertit une feuille Excel (.xlsx) en CSV.",
       {"path": {"type": "string", "description": "Fichier Excel source"},
        "sheet": {"type": "string", "description": "Nom de la feuille (défaut : active)"},
        "delimiter": {"type": "string", "description": "Séparateur de sortie (défaut ',')"},
        "output_path": {"type": "string", "description": "Fichier .csv de sortie"}},
       ["path"]),
    _t("docx_to_text", "Extrait le texte d'un document Word (.docx) en texte brut ou Markdown (titres, listes, tableaux).",
       {"path": {"type": "string", "maxLength": 32767, "description": "Fichier .docx"},
        "format": {"type": "string", "enum": ["markdown", "text"], "description": "Format de sortie (défaut markdown)"},
        "output_path": {"type": "string", "maxLength": 32767, "description": "Fichier texte de sortie (optionnel)"}},
       ["path"]),
    _t("text_summarize", "Résume un texte OU un document (txt/pdf/docx) via l'IA locale. Styles : bref, détaillé, puces, action.",
       {"text": {"type": "string", "description": "Texte à résumer (ou utiliser 'path')"},
        "path": {"type": "string", "description": "Document à résumer (txt/pdf/docx)"},
        "style": {"type": "string", "enum": ["bref", "détaillé", "puces", "action"], "description": "Style de résumé"},
        "language": {"type": "string", "description": "Langue du résumé (défaut français)"}},
       []),
    _t("text_to_speech", "Génère un fichier audio MP3 parlant à partir d'un texte (voix neurale FR/EN, edge-tts).",
       {"text": {"type": "string", "description": "Texte à lire à voix haute"},
        "voice": {"type": "string", "enum": ["henri","denise","eloise","vivienne","remy","thierry","sylvie","en-femme","en-homme"], "description": "Voix (défaut denise)"},
        "rate": {"type": "string", "description": "Vitesse, ex '+10%' ou '-10%'"},
        "pitch": {"type": "string", "description": "Hauteur, ex '+5Hz' ou '-5Hz'"},
        "output_path": {"type": "string", "description": "Fichier .mp3 de sortie (défaut : Bureau)"}},
       ["text"]),
    _t("pdf_compress", "Réduit le poids d'un fichier PDF (recompression des flux) via pikepdf.",
       {"path": {"type": "string", "description": "PDF source"},
        "output_path": {"type": "string", "description": "PDF de sortie (défaut : _compresse)"}},
       ["path"]),
    _t("pdf_add_page_numbers", "Ajoute une numérotation (ou un texte) sur chaque page d'un PDF. {n}=numéro, {total}=total.",
       {"path": {"type": "string", "description": "PDF source"},
        "format": {"type": "string", "description": "Modèle, ex 'Page {n} / {total}'"},
        "position": {"type": "string", "enum": ["bottom-center","bottom-right","bottom-left","top-center","top-right","top-left"], "description": "Position"},
        "start_number": {"type": "integer", "description": "Numéro de départ (défaut 1)"},
        "font_size": {"type": "integer", "description": "Taille de police (défaut 9)"},
        "output_path": {"type": "string", "description": "PDF de sortie (défaut : _numerote)"}},
       ["path"]),
    _t("csv_to_chart", "Génère un graphique PNG directement depuis un fichier CSV (bar/line/pie, colonnes numériques auto-détectées).",
       {"path": {"type": "string", "maxLength": 32767, "description": "Fichier CSV source"},
        "chart_type": {"type": "string", "enum": ["bar","line","pie"], "description": "Type de graphique"},
        "label_column": {"type": "integer", "minimum": 0, "maximum": 499, "description": "Index de la colonne des étiquettes (défaut 0)"},
        "value_columns": {"type": "string", "maxLength": 200, "pattern": "^\\s*\\d+(?:\\s*,\\s*\\d+)*\\s*$", "description": "Indices des colonnes de valeurs, ex '1,2' (auto si absent)"},
        "title": {"type": "string", "maxLength": 300, "description": "Titre du graphique"},
        "output_path": {"type": "string", "maxLength": 32767, "description": "Image PNG de sortie"}},
       ["path"]),
    _t("xlsx_read", "Lit un fichier Excel (.xlsx) et retourne le contenu d'une feuille.",
       {"path":     {"type": "string", "description": "Chemin du fichier Excel (.xlsx)"},
        "sheet":    {"type": "string", "description": "Nom de la feuille (défaut : première feuille active)"},
        "action":   {"type": "string", "enum": ["read", "sheets", "summary"],
                     "description": "read = données, sheets = liste des onglets, summary = dimensions (défaut : read)"},
        "max_rows": {"type": "integer", "description": "Nombre max de lignes à retourner (défaut 50)"}},
       ["path"]),
    _t("url_analyze", "Analyse une URL : titre, meta description, statut HTTP, serveur et temps de réponse.",
       {"url": {"type": "string", "maxLength": 8192, "description": "URL publique à analyser (HTTP/HTTPS, ports 80/443)"}},
       ["url"]),
    _t("zip_list", "Liste le contenu d'une archive ZIP sans l'extraire.",
       {"path": {"type": "string", "description": "Chemin de l'archive ZIP"}},
       ["path"]),
    _t("color_tool", "Convertit une couleur entre HEX, RGB et HSL, et calcule la couleur complémentaire.",
       {"color": {"type": "string", "maxLength": 64,
                  "description": "Couleur à convertir. Formats acceptés : #RRGGBB (#FF5733), rgb(r,g,b) (rgb(255,87,51)) ou hsl(h,s%,l%)"}},
       ["color"]),
    # ── Section 17 ──────────────────────────────────────────────────────────
    _t("sqlite_query", "Exécute une requête SQL (SELECT ou écriture avec confirmation) sur une base SQLite locale.",
       {"db_path":   {"type": "string", "maxLength": 32767, "description": "Chemin du fichier .db ou .sqlite"},
        "query":     {"type": "string", "maxLength": 100000, "description": "Requête SQL unique à exécuter"},
        "max_rows":  {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Nombre max de lignes retournées (défaut 100)"},
        "confirmed": {"type": "boolean", "description": "Requis pour les requêtes d'écriture (INSERT/UPDATE/DELETE…)"}},
       ["db_path", "query"]),
    _t("sqlite_tables", "Liste les tables et leur schéma dans une base SQLite.",
       {"db_path": {"type": "string", "maxLength": 32767, "description": "Chemin du fichier SQLite (.db, .sqlite)"}},
       ["db_path"]),
    _t("git_info", "Retourne des informations sur un dépôt Git : branche, statut, commits, branches.",
       {"path":   {"type": "string", "maxLength": 32767, "description": "Chemin du dépôt (défaut : dossier courant)"},
        "action": {"type": "string", "enum": ["status", "log", "branches", "diff"],
                   "description": "status = fichiers modifiés, log = historique, branches = liste, diff = statistiques"},
        "count":  {"type": "integer", "minimum": 1, "maximum": 100, "description": "Nombre de commits pour l'action 'log' (défaut 10)"}},
       []),
    _t("bulk_rename", "Renomme en masse des fichiers d'un dossier selon un motif regex (avec confirmation et mode dry_run).",
       {"folder":   {"type": "string", "maxLength": 32767, "description": "Dossier contenant les fichiers"},
        "pattern":  {"type": "string", "maxLength": 1000, "description": "Expression régulière à trouver dans le nom de fichier"},
        "replace":  {"type": "string", "maxLength": 1000, "description": "Texte de remplacement; groupes Python : \\g<1> ou \\g<nom>"},
        "glob":     {"type": "string", "maxLength": 255, "description": "Filtre de fichiers ex: *.jpg (défaut: *)"},
        "dry_run":  {"type": "boolean", "description": "Si true, simule seulement et demande confirmation (défaut : true)"},
        "action":   {"type": "string", "enum": ["preview", "apply", "rollback"], "description": "Action explicite (défaut : preview/apply selon confirmation)"},
        "rollback_manifest": {"type": "string", "maxLength": 32767, "description": "Manifeste retourné par une exécution pour restaurer les noms"},
        "confirmed":{"type": "boolean", "description": "Requis pour appliquer ou restaurer"}},
       []),
    # ── Section 18 ──────────────────────────────────────────────────────────
    _t("screen_ocr", "Capture l'écran et en extrait le texte. La vision suit la confidentialité Marvin : locale hors Ultra, Cloud en Ultra débridé. Le résultat expose moteur, modèle et route Cloud.",
       {"lang":  {"type": "string", "description": "Langue OCR (défaut : fra+eng). Exemples : eng, fra, deu"},
        "region":{"type": "array",  "description": "Région [x, y, largeur, hauteur] ou null pour tout l'écran"},
        "save":  {"type": "boolean","description": "Sauvegarder le screenshot sur le Bureau (défaut : false)"},
        "method":{"type": "string", "enum": ["auto", "vision", "tesseract"], "description": "Moteur OCR (défaut : auto)"},
        "prompt":{"type": "string", "maxLength": 4000, "description": "Instruction OCR vision optionnelle"}},
       []),
    _t("file_batch_read", "Lit plusieurs fichiers texte en une seule requête et retourne leur contenu agrégé.",
       {"paths":              {"type": "array", "minItems": 1, "maxItems": 20,
                               "items": {"type": "string", "maxLength": 32767},
                               "description": "Liste des chemins de fichiers à lire"},
        "max_chars_per_file": {"type": "integer", "minimum": 1, "maximum": 100000, "description": "Limite de caractères par fichier (défaut 5000)"},
        "encoding":           {"type": "string", "maxLength": 64, "description": "Encodage Python reconnu (défaut utf-8)"}},
       ["paths"]),
    _t("clipboard_append", "Ajoute du texte au contenu actuel du presse-papiers (append) sans écraser ce qui est déjà dedans.",
       {"text":      {"type": "string", "description": "Texte à ajouter au presse-papiers"},
        "separator": {"type": "string", "description": "Séparateur entre l'ancien et le nouveau contenu (défaut : saut de ligne)"}},
       ["text"]),
    _t("text_join", "Fusionne une liste de textes avec un séparateur personnalisé (jointure, concaténation, déduplication).",
       {"texts":     {"type": "array", "minItems": 1, "maxItems": 10000,
                      "items": {"type": "string"}, "description": "Liste des textes à fusionner"},
        "separator": {"type": "string", "maxLength": 10000, "description": "Séparateur entre les textes (défaut : saut de ligne)"},
        "prefix":    {"type": "string", "maxLength": 10000, "description": "Préfixe ajouté à chaque élément"},
        "suffix":    {"type": "string", "maxLength": 10000, "description": "Suffixe ajouté à chaque élément"},
        "dedupe":    {"type": "boolean", "description": "Supprimer les doublons avant la fusion (défaut : false)"}},
       ["texts"]),
    # ── Section 19 ──────────────────────────────────────────────────────────
    _t("code_python",
       "Exécute un calcul Python rapide dans un processus séparé. Ce n'est PAS une sandbox OS : "
       "pour du code non fiable ou une validation de production, utiliser Test Forge/VM. "
       "Idéal pour : calculs de données, statistiques, transformations, et GRAPHIQUES — un simple "
       "plt.savefig('nom.png') suffit, l'image est automatiquement détectée et affichée cliquable "
       "dans le chat (pas besoin de chemin spécial). Bibliothèques disponibles : json, math, re, "
       "datetime, collections, statistics, random, numpy/pandas/matplotlib (si installés) — utilise "
       "un simple 'import'. Imprime le résultat avec print() pour le voir, ou définis une variable "
       "'result'/'output' pour qu'elle apparaisse dans le champ 'result'. "
       "os/subprocess/réseau/fichiers (open/read/save) demandent une confirmation explicite.",
       {"code":      {"type": "string", "maxLength": 100000, "description": "Code Python à exécuter"},
        "timeout":   {"type": "integer", "minimum": 1, "maximum": 60, "description": "Délai max en secondes (1–60, défaut 15)"},
        "confirmed": {"type": "boolean", "description": "Requis si le code utilise open(), import os/subprocess/socket, eval/exec, etc."}},
       ["code"]),

    # ── Section 20 — Devis / Facturation IT ────────────────────────────────
    _t("billing_client_create", "Crée un nouveau client dans le module devis/facturation.",
       {"name":           {"type": "string", "description": "Nom du client/société"},
        "client_type":    {"type": "string", "enum": ["mairie","pme","asso","particulier","autre"], "description": "Type de client"},
        "contact_name":   {"type": "string"},
        "contact_email":  {"type": "string"},
        "contact_phone":  {"type": "string"},
        "address":        {"type": "string"},
        "siret":          {"type": "string"},
        "previous_provider": {"type": "string", "description": "Nom du prestataire actuel à remplacer"},
        "previous_amount":{"type": "number", "description": "Montant annuel du prestataire actuel"}},
       ["name"]),
    _t("billing_client_list", "Liste les clients, filtrable par type.",
       {"client_type": {"type": "string", "enum": ["mairie","pme","asso","particulier","autre"]}}, []),
    _t("billing_catalog_list", "Liste le catalogue des prestations IT (avec prix Basic/Standard/Premium).",
       {"category": {"type": "string", "description": "Filtrer par catégorie (Support, Infrastructure, Sécurité, etc.)"}}, []),
    _t("billing_analyze_need",
       "Analyse le besoin d'un client et propose les prestations pertinentes du catalogue avec estimations Basic/Standard/Premium.",
       {"description":  {"type": "string", "description": "Description libre du besoin client"},
        "client_type":  {"type": "string", "description": "mairie | pme | asso | particulier"}},
       ["description"]),
    _t("billing_quote_create",
       "Crée un devis avec lignes (items). Calcule automatiquement HT/TTC/marge.",
       {"client_id":     {"type": "string", "description": "ID du client (billing_client_list)"},
        "title":         {"type": "string"},
        "tier":          {"type": "string", "enum": ["basic","standard","premium","custom"]},
        "items":         {"type": "array",  "description": "Liste de prestations : [{label, qty, unit_price, total, cost}]"},
        "tva_rate":      {"type": "number", "description": "Taux TVA (défaut 20.0)"},
        "need_analysis": {"type": "string"},
        "notes":         {"type": "string"},
        "valid_until":   {"type": "string", "description": "Date de fin de validité (texte libre ou ISO)"}},
       ["client_id","items"]),
    _t("billing_quote_list", "Liste les devis (filtrable par client_id ou status).",
       {"client_id": {"type": "string"},
        "status":    {"type": "string", "enum": ["draft","sent","accepted","refused","expired"]}}, []),
    _t("billing_quote_compare",
       "Compare un devis avec l'ancien prestataire du client (économies, gains).",
       {"quote_id": {"type": "string"}}, ["quote_id"]),
    _t("billing_quote_pdf", "Génère un PDF professionnel du devis.",
       {"quote_id":    {"type": "string"},
        "output_path": {"type": "string", "description": "Chemin du PDF (défaut : Bureau)"}},
       ["quote_id"]),
    _t("billing_quote_email",
       "Génère un email d'accompagnement professionnel pour envoyer un devis. Ton adapté au type de client (mairie=formel, asso=chaleureux, pme=pro).",
       {"quote_id": {"type": "string"}}, ["quote_id"]),
    _t("billing_tier_breakdown",
       "Génère 3 propositions Basic/Standard/Premium pour une liste de prestations sélectionnées.",
       {"service_ids": {"type": "array", "description": "Liste d'IDs du catalogue de services"}},
       ["service_ids"]),

    # ── Section 28 — Devis IT avancé ───────────────────────────────────────
    _t("billing_market_research",
       "Compare les offres du marché sur le WEB pour un produit/prestation IT : cherche les prix en ligne, agrège (min/médiane/max), liste les sources et recommande un prix de revient + prix de vente selon la marge cible. Idéal pour chiffrer du matériel/licences au juste prix.",
       {"query":            {"type": "string", "description": "Produit/prestation à comparer (ex: 'Dell Latitude 5550 i5 16Go', 'Microsoft 365 Business Premium', 'pare-feu Fortinet 60F')"},
        "target_margin_pct":{"type": "number", "description": "Marge cible en % (défaut 30)"},
        "usd_to_eur":       {"type": "number", "description": "Taux USD→EUR (défaut 0.92)"}},
       ["query"]),
    _t("billing_find_products",
       "Recherche du MATÉRIEL/produits selon une CONTRAINTE DE BUDGET sur le web (ex: 'PC portable bureautique à moins de 500€'). Renvoie les offres dans le budget, triées par prix, avec le meilleur rapport qualité/prix (avis) et les sources.",
       {"query":      {"type": "string", "description": "Type de produit/besoin (ex: 'PC portable bureautique', 'écran 27 pouces', 'serveur NAS')"},
        "max_budget": {"type": "number", "description": "Budget maximum en € (ex: 500)"},
        "min_budget": {"type": "number", "description": "Budget minimum en € (optionnel)"}},
       ["query"]),
    _t("billing_product_reviews",
       "Recherche et agrège les AVIS d'un produit/prestation sur le web : note moyenne /5 pondérée, total d'avis, sentiment et extraits. Utile pour conseiller le meilleur produit.",
       {"query": {"type": "string", "description": "Produit/prestation (ex: 'Veeam Backup', 'Bitdefender GravityZone')"}},
       ["query"]),
    _t("billing_price_recommendation",
       "Recommande un prix de vente compétitif (3 paliers) à partir d'un coût d'achat, selon les marges-cibles par segment client et nature de prestation.",
       {"cost":        {"type": "number", "description": "Coût d'achat HT"},
        "client_type": {"type": "string", "enum": ["mairie","pme","asso","particulier","autre"]},
        "category":    {"type": "string", "description": "Nature (matériel, conseil, sécurité, support…)"}},
       ["cost"]),
    _t("billing_generate_proposal",
       "Génère une PROPOSITION COMMERCIALE structurée et persuasive depuis un devis (résumé exécutif, solution, bénéfices, investissement, garanties, appel à l'action). Sortie Markdown prête à présenter.",
       {"quote_id": {"type": "string", "description": "ID du devis"}}, ["quote_id"]),
    _t("billing_tco_analysis",
       "Analyse le coût total de possession (TCO) sur N années + ROI vs une alternative (cloud/location). Justifie un investissement IT.",
       {"years":             {"type": "integer", "description": "Durée d'analyse (défaut 3)"},
        "upfront_cost":      {"type": "number", "description": "Coût initial (matériel/setup)"},
        "monthly_cost":      {"type": "number", "description": "Coût mensuel récurrent (support/licences)"},
        "alternative_monthly":{"type": "number", "description": "Coût mensuel de l'alternative comparée"},
        "alternative_upfront":{"type": "number"},
        "downtime_hours_year_saved": {"type": "number", "description": "Heures d'arrêt évitées/an"},
        "hourly_value":      {"type": "number", "description": "Valeur d'une heure d'arrêt (défaut 50€)"}},
       []),
    _t("billing_invoice_create",
       "Crée une FACTURE, optionnellement depuis un devis accepté (from_quote_id reprend client, lignes et montants).",
       {"from_quote_id": {"type": "string", "description": "ID d'un devis à facturer (optionnel)"},
        "client_id":     {"type": "string"},
        "title":         {"type": "string"},
        "total_ht":      {"type": "number"},
        "tva_rate":      {"type": "number"},
        "items":         {"type": "array"},
        "payment_terms": {"type": "string", "description": "Délai de paiement en jours (défaut 30)"}}, []),
    _t("billing_invoice_list",
       "Liste les factures (filtrable par client_id/status). Signale les impayés et retards.",
       {"client_id": {"type": "string"},
        "status":    {"type": "string", "enum": ["draft","sent","paid","partial","overdue","cancelled"]}}, []),
    _t("billing_invoice_mark_paid",
       "Marque une facture payée (totalement ou partiellement avec 'amount').",
       {"invoice_id":     {"type": "string"},
        "amount":         {"type": "number", "description": "Montant payé (défaut = total)"},
        "payment_method": {"type": "string"}}, ["invoice_id"]),
    _t("billing_revenue_dashboard",
       "Tableau de bord commercial : CA facturé/encaissé, impayés, MRR/ARR (récurrent), taux de conversion des devis, pipeline.",
       {}, []),
    _t("billing_catalog_enrich",
       "Ajoute au catalogue les prestations IT modernes (cybersécurité, cloud, sauvegarde, RGPD, VoIP, supervision…) si absentes.",
       {}, []),
    _t("billing_seed_trade",
       "Charge un catalogue de prestations TYPES pour un MÉTIER (hors IT) : plomberie, électricité, peinture, menuiserie, jardinage, ménage, coiffure_esthétique, photographie, web_design, conseil, comptabilité. Rend le module devis/facture utilisable pour tout métier. trade='list' pour voir les métiers.",
       {"trade": {"type": "string", "description": "Métier (ex: plomberie, électricité, jardinage…) ou 'list'"}},
       []),

    # ── Section 29 — Base de connaissances IT (consultable par Marvin) ──────
    _t("it_kb_search",
       "Recherche dans la base de connaissances IT de Marvin (outils/logiciels/produits) : sauvegarde, antivirus, supervision, virtualisation, pare-feu, diagnostic… Réponse instantanée sans recherche web.",
       {"query":    {"type": "string", "description": "Mots-clés (ex: 'sauvegarde VM', 'antivirus', 'accès distant gratuit')"},
        "category": {"type": "string", "description": "Filtrer par catégorie (optionnel)"},
        "limit":    {"type": "integer"}}, []),
    _t("it_kb_list",
       "Liste/parcourt la base de connaissances IT (groupée par catégorie).",
       {"category": {"type": "string"}}, []),
    _t("it_kb_recommend",
       "Recommande le(s) MEILLEUR(S) outil(s) IT pour un besoin, depuis la base de Marvin (instantané). Tient compte du budget (gratuit/open source) et de la souveraineté (RGPD/ANSSI). Idéal pour l'Agent Documentation Technique et les devis.",
       {"need": {"type": "string", "description": "Besoin en clair (ex: 'sauvegarde pour une mairie budget limité', 'pare-feu souverain', 'supervision réseau gratuite')"}},
       ["need"]),
    _t("it_kb_add",
       "Ajoute ou met à jour un outil dans la base de connaissances IT de Marvin (apprentissage). Utile après une recherche web concluante.",
       {"name":          {"type": "string"},
        "category":      {"type": "string"},
        "vendor":        {"type": "string"},
        "description":   {"type": "string"},
        "use_cases":     {"type": "string"},
        "pricing_model": {"type": "string", "enum": ["opensource","free","freemium","paid","saas","unknown"]},
        "typical_price": {"type": "string"},
        "platforms":     {"type": "string"},
        "best_for":      {"type": "string"},
        "official_url":  {"type": "string"},
        "tags":          {"type": "string"},
        "rating":        {"type": "number"}},
       ["name"]),

    # ── Section 21 — Windows Admin ─────────────────────────────────────────
    _t("pc_installed_software",
       "Liste les LOGICIELS INSTALLÉS sur ce PC (nom, version, éditeur) — AUCUN argument. Utilise cet outil EN PRIORITÉ pour « inventaire logiciel », « liste des programmes installés », « quels logiciels sur ce PC ».",
       {}, []),
    _t("win_services_list",
       "Liste les services Windows avec leur état (running/stopped). Filtre par nom ou statut.",
       {"filter": {"type": "string", "description": "Filtre sur le nom (substring)"},
        "status": {"type": "string", "enum": ["running","stopped","paused","start_pending","stop_pending"]}}, []),
    _t("win_service_action",
       "Interroge (query) ou pilote un service Windows. 'query' = lecture seule de l'état "
       "(sans confirmation) ; start/stop/restart/pause/resume = action (peut nécessiter droits admin).",
       {"name":      {"type": "string", "description": "Nom du service Windows"},
        "action":    {"type": "string", "enum": ["query","start","stop","restart","pause","resume"],
                      "description": "query pour lire l'état ; sinon l'action à effectuer"},
        "confirmed": {"type": "boolean", "description": "Requis pour les actions de modification (pas pour query)"}},
       ["name","action"]),
    _t("win_event_log",
       "Lit les derniers événements du journal Windows (System / Application / Security / Setup).",
       {"log":        {"type": "string", "enum": ["System","Application","Security","Setup"]},
        "max_events": {"type": "integer", "description": "Nombre max d'événements (défaut 30)"},
        "level":      {"type": "string", "enum": ["error","warning","information"]}}, []),
    _t("win_users_list", "Liste les comptes utilisateurs locaux Windows.", {}, []),
    _t("win_disk_info",
       "Infos détaillées sur les disques Windows (lettre, label, taille, utilisation, santé).",
       {}, []),
    _t("win_update_status",
       "Affiche les 10 dernières mises à jour Windows installées.", {}, []),

    # ── Section 26 — v2.31 Windows Diagnostics avancés ────────────────────
    _t("win_uptime", "Uptime du système et date de dernier démarrage Windows.", {}, []),
    _t("win_startup_programs", "Liste les programmes lancés au démarrage de Windows (diagnostic boot lent).", {}, []),
    _t("win_scheduled_tasks",
       "Liste les tâches planifiées Windows (exclut Microsoft par défaut).",
       {"include_microsoft": {"type": "boolean", "description": "Inclure les tâches Microsoft système"},
        "state": {"type": "string", "enum": ["Ready","Running","Disabled"], "description": "Filtrer par état"}}, []),
    _t("win_network_config",
       "Configuration réseau complète : adaptateurs, IPs, passerelle, DNS, MAC.", {}, []),
    _t("win_system_report",
       "🔍 Rapport diagnostic système COMPLET en un seul appel : OS, uptime, CPU, RAM, disques, top processus, alertes. Idéal pour un support rapide.",
       {}, []),
    _t("file_duplicate_finder",
       "Trouve les fichiers en double dans un dossier (par taille + hash). Utile pour le nettoyage disque. Ne supprime rien.",
       {"path": {"type": "string", "maxLength": 32767, "description": "Dossier à analyser"},
        "min_size_kb": {"type": "integer", "minimum": 0, "maximum": 1000000000, "description": "Taille minimale en Ko (défaut 10)"},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 1000000, "description": "Limite de fichiers scannés (défaut 5000)"}},
       ["path"]),

    # ── Section 27 — v2.32 Édition vidéo / GIF (ffmpeg local) ─────────────
    _t("video_info",
       "Donne les métadonnées d'une vidéo ou d'un GIF : durée, résolution, fps, codec, taille.",
       {"path": {"type": "string", "description": "Chemin du fichier vidéo/GIF"}},
       ["path"]),
    _t("video_to_gif",
       "Convertit une vidéo en GIF animé optimisé (palette haute qualité). Idéal pour partager un extrait léger.",
       {"path":     {"type": "string", "description": "Chemin de la vidéo source"},
        "fps":      {"type": "integer", "description": "Images par seconde du GIF (défaut 12)"},
        "width":    {"type": "integer", "description": "Largeur en px, hauteur auto (défaut 480)"},
        "start":    {"type": "number",  "description": "Début en secondes (optionnel)"},
        "duration": {"type": "number",  "description": "Durée en secondes (optionnel)"},
        "output_path": {"type": "string", "description": "Chemin de sortie (optionnel)"}},
       ["path"]),
    _t("gif_to_video",
       "Convertit un GIF en vidéo MP4, bien plus légère pour le stockage et le partage.",
       {"path": {"type": "string", "description": "Chemin du GIF source"},
        "fps":  {"type": "integer", "description": "Images par seconde (optionnel)"},
        "output_path": {"type": "string", "description": "Chemin de sortie (optionnel)"}},
       ["path"]),
    _t("video_trim",
       "Découpe un segment d'une vidéo (sans réencodage si possible). Fournir start + end OU start + duration.",
       {"path":     {"type": "string", "description": "Chemin de la vidéo"},
        "start":    {"type": "number", "description": "Début en secondes (défaut 0)"},
        "end":      {"type": "number", "description": "Fin en secondes"},
        "duration": {"type": "number", "description": "Durée en secondes"},
        "output_path": {"type": "string", "description": "Chemin de sortie (optionnel)"}},
       ["path"]),
    _t("video_compress",
       "Compresse une vidéo (H.264). crf 18=haute qualité, 28=équilibré, 35=très léger. Retourne le % de réduction.",
       {"path":        {"type": "string",  "description": "Chemin de la vidéo"},
        "crf":         {"type": "integer", "description": "Facteur de qualité 18-35 (défaut 28)"},
        "scale_width": {"type": "integer", "description": "Réduire la largeur en px (optionnel)"},
        "output_path": {"type": "string",  "description": "Chemin de sortie (optionnel)"}},
       ["path"]),
    _t("video_resize",
       "Redimensionne une vidéo (ratio préservé si une seule dimension est fournie).",
       {"path":   {"type": "string",  "description": "Chemin de la vidéo"},
        "width":  {"type": "integer", "description": "Nouvelle largeur en px"},
        "height": {"type": "integer", "description": "Nouvelle hauteur en px"},
        "output_path": {"type": "string", "description": "Chemin de sortie (optionnel)"}},
       ["path"]),
    _t("video_extract_frames",
       "Extrait des images d'une vidéo (fps=1 → une image par seconde). Utile pour créer des miniatures ou analyser.",
       {"path":      {"type": "string", "description": "Chemin de la vidéo"},
        "fps":       {"type": "number", "description": "Images extraites par seconde (défaut 1)"},
        "max_frames":{"type": "integer", "description": "Nombre max d'images (défaut 30)"}},
       ["path"]),
    _t("video_speed",
       "Change la vitesse d'une vidéo. factor=2.0 → 2x plus rapide, 0.5 → ralenti.",
       {"path":   {"type": "string", "description": "Chemin de la vidéo"},
        "factor": {"type": "number", "description": "Facteur de vitesse (défaut 2.0)"},
        "output_path": {"type": "string", "description": "Chemin de sortie (optionnel)"}},
       ["path"]),
    _t("video_watermark",
       "Ajoute un filigrane texte sur une vidéo (date, nom de société, mention confidentielle…).",
       {"path":      {"type": "string", "description": "Chemin de la vidéo"},
        "text":      {"type": "string", "description": "Texte à incruster"},
        "position":  {"type": "string", "enum": ["top-left","top-right","bottom-left","bottom-right","center"], "description": "Position (défaut bottom-right)"},
        "font_size": {"type": "integer", "description": "Taille de police (défaut 24)"},
        "output_path": {"type": "string", "description": "Chemin de sortie (optionnel)"}},
       ["path", "text"]),
    _t("gif_optimize",
       "Optimise un GIF existant (réduit fps, couleurs et taille). Retourne le % de réduction.",
       {"path":   {"type": "string",  "description": "Chemin du GIF"},
        "fps":    {"type": "integer", "description": "Images par seconde (défaut 10)"},
        "width":  {"type": "integer", "description": "Nouvelle largeur en px (optionnel)"},
        "colors": {"type": "integer", "description": "Nombre de couleurs 2-256 (défaut 128)"},
        "output_path": {"type": "string", "description": "Chemin de sortie (optionnel)"}},
       ["path"]),
    _t("screen_record_gif",
       "Enregistre l'écran en GIF animé (durée limitée à 20s). region=[x,y,largeur,hauteur] ou écran entier.",
       {"duration": {"type": "number",  "description": "Durée en secondes (max 20, défaut 5)"},
        "fps":      {"type": "integer", "description": "Images par seconde (défaut 10)"},
        "region":   {"type": "array",   "description": "Zone [x, y, largeur, hauteur] (optionnel)"},
        "output_path": {"type": "string", "description": "Chemin de sortie (optionnel)"}},
       []),

    # ── Audio (ffmpeg embarqué) ───────────────────────────────────────────
    _t("audio_info", "Métadonnées d'un fichier audio : durée, débit, fréquence d'échantillonnage, canaux.",
       {"path": {"type": "string", "description": "Chemin du fichier audio"}},
       ["path"]),
    _t("audio_extract", "Extrait la piste audio d'une vidéo vers un fichier audio (mp3/wav/aac…).",
       {"path":   {"type": "string", "description": "Chemin de la vidéo"},
        "format": {"type": "string", "enum": ["mp3","wav","ogg","flac","aac","m4a","opus"], "description": "Format audio (défaut mp3)"},
        "bitrate":{"type": "string", "description": "Débit ex '192k' (défaut 192k)"},
        "output_path": {"type": "string", "description": "Fichier de sortie"}},
       ["path"]),
    _t("audio_convert", "Convertit un fichier audio vers un autre format (mp3/wav/ogg/flac/aac/opus).",
       {"path":   {"type": "string", "description": "Fichier audio source"},
        "format": {"type": "string", "enum": ["mp3","wav","ogg","flac","aac","m4a","opus"], "description": "Format cible"},
        "bitrate":{"type": "string", "description": "Débit ex '192k'"},
        "sample_rate": {"type": "integer", "description": "Fréquence d'échantillonnage ex 44100"},
        "output_path": {"type": "string", "description": "Fichier de sortie"}},
       ["path", "format"]),
    _t("audio_trim", "Découpe un segment audio (start/end ou start + duration, en secondes).",
       {"path":     {"type": "string", "description": "Fichier audio source"},
        "start":    {"type": "number", "description": "Début en secondes (défaut 0)"},
        "end":      {"type": "number", "description": "Fin en secondes"},
        "duration": {"type": "number", "description": "Durée en secondes (alternative à end)"},
        "output_path": {"type": "string", "description": "Fichier de sortie"}},
       ["path"]),
    _t("audio_merge", "Concatène plusieurs fichiers audio bout à bout (formats différents acceptés).",
       {"paths":  {"type": "array", "items": {"type": "string"}, "description": "Fichiers audio à concaténer (≥2, ordre conservé)"},
        "format": {"type": "string", "enum": ["mp3","wav","ogg","flac","aac","opus"], "description": "Format de sortie (défaut mp3)"},
        "output_path": {"type": "string", "description": "Fichier de sortie"}},
       ["paths"]),
    _t("audio_volume", "Ajuste le volume (factor ex 1.5, gain_db ex +6/-6) ou normalise (normalize=true).",
       {"path":      {"type": "string", "description": "Fichier audio source"},
        "factor":    {"type": "number", "description": "Facteur multiplicatif (1.5 = +50%)"},
        "gain_db":   {"type": "number", "description": "Gain en décibels (ex 6 ou -6)"},
        "normalize": {"type": "boolean", "description": "Normalisation loudness (EBU R128)"},
        "output_path": {"type": "string", "description": "Fichier de sortie"}},
       ["path"]),

    # ── Section 22 — Agent IA Documentation Technique ─────────────────────
    _t("doc_intervention_create",
       "Crée une nouvelle intervention IT (incident, déploiement, maintenance, audit…).",
       {"title":            {"type": "string", "description": "Titre court de l'intervention"},
        "intervention_type":{"type": "string", "enum": ["incident","request","change","problem","deployment","maintenance","audit","other"]},
        "priority":         {"type": "string", "enum": ["low","medium","high","critical"]},
        "client_id":        {"type": "string", "description": "ID du client concerné"},
        "technician":       {"type": "string"},
        "raw_notes":        {"type": "string", "description": "Notes brutes du technicien"},
        "commands_executed":{"type": "string", "description": "Commandes exécutées pendant l'intervention"},
        "ticket_refs":      {"type": "string"},
        "client_emails":    {"type": "string"},
        "network_config":   {"type": "string"},
        "summary":          {"type": "string"},
        "resolution":       {"type": "string"},
        "recommendations":  {"type": "string"},
        "tags":             {"type": "array"},
        "duration_minutes": {"type": "integer"}},
       ["title"]),
    _t("doc_intervention_list",
       "Liste les interventions documentées (filtrable par client_id et status).",
       {"client_id": {"type": "string"},
        "status":    {"type": "string", "enum": ["open","in_progress","resolved","closed","cancelled"]},
        "limit":     {"type": "integer", "description": "Nombre max (défaut 50)"}}, []),
    _t("doc_intervention_update",
       "Met à jour une intervention (status, résolution, notes…).",
       {"id":             {"type": "string"},
        "status":         {"type": "string", "enum": ["open","in_progress","resolved","closed","cancelled"]},
        "summary":        {"type": "string"},
        "root_cause":     {"type": "string"},
        "resolution":     {"type": "string"},
        "recommendations":{"type": "string"}},
       ["id"]),
    _t("doc_analyze_input",
       "Analyse intelligente d'un contenu brut d'intervention. Extrait commandes, IPs, MACs, type ITIL, priorité suggérée, pertinence RGPD.",
       {"raw_text": {"type": "string", "description": "Notes brutes / log / texte d'intervention"}},
       ["raw_text"]),
    _t("doc_generate_report",
       "Génère un rapport d'intervention professionnel (PDF/DOCX/MD).",
       {"intervention_id": {"type": "string"},
        "format":          {"type": "string", "enum": ["pdf","docx","md"]},
        "template_id":     {"type": "string", "description": "ID du template à utiliser (optionnel)"},
        "output_path":     {"type": "string"}},
       ["intervention_id"]),
    _t("doc_generate_procedure",
       "Génère une procédure technique pas-à-pas (PDF/DOCX/MD) reproductible.",
       {"intervention_id": {"type": "string"},
        "format":          {"type": "string", "enum": ["pdf","docx","md"]},
        "objective":       {"type": "string"},
        "prerequisites":   {"type": "string"},
        "tools_required":  {"type": "string"},
        "steps":           {"type": "string", "description": "Étapes numérotées"},
        "validation":      {"type": "string"},
        "rollback":        {"type": "string"},
        "difficulty":      {"type": "string", "enum": ["Facile","Moyenne","Avancée","Expert"]}},
       ["intervention_id"]),
    _t("doc_generate_client_sheet",
       "Génère une fiche client complète (infrastructure + assets + historique des interventions).",
       {"client_id":   {"type": "string"},
        "format":      {"type": "string", "enum": ["pdf","docx","md"]},
        "security":    {"type": "string"},
        "backup":      {"type": "string"},
        "contracts":   {"type": "string"},
        "contacts":    {"type": "string"}},
       ["client_id"]),
    _t("doc_generate_recovery_plan",
       "Génère un Plan de Reprise d'Activité (PRA/PCA) conforme ISO 22301.",
       {"client_id":     {"type": "string"},
        "format":        {"type": "string", "enum": ["pdf","docx"]},
        "scope":         {"type": "string"},
        "risks":         {"type": "array"},
        "services":      {"type": "array"},
        "backup_arch":   {"type": "string"},
        "recovery_steps":{"type": "string"},
        "tests":         {"type": "string"},
        "contacts":      {"type": "string"},
        "validator":     {"type": "string"}},
       ["client_id"]),
    _t("doc_generate_maintenance",
       "Génère une procédure de maintenance préventive (checklist mensuelle/trimestrielle/annuelle).",
       {"client_id":     {"type": "string"},
        "format":        {"type": "string", "enum": ["pdf","docx"]},
        "frequency":     {"type": "string", "enum": ["Hebdomadaire","Mensuelle","Trimestrielle","Annuelle"]},
        "duration":      {"type": "string"},
        "anomalies":     {"type": "string"},
        "corrective_actions": {"type": "string"}},
       ["client_id"]),
    _t("doc_generate_runbook",
       "Génère un runbook (procédure d'urgence) pour un incident critique.",
       {"intervention_id":   {"type": "string"},
        "format":            {"type": "string", "enum": ["pdf","docx"]},
        "service":           {"type": "string"},
        "symptoms":          {"type": "string"},
        "business_impact":   {"type": "string"},
        "diagnostic_steps":  {"type": "string"},
        "step1":             {"type": "string"},
        "step2":             {"type": "string"},
        "step3":             {"type": "string"},
        "step4":             {"type": "string"},
        "level1_contact":    {"type": "string"},
        "level2_contact":    {"type": "string"},
        "level3_contact":    {"type": "string"}},
       ["intervention_id"]),
    _t("doc_generate_schema",
       "Génère un schéma logique d'infrastructure en Mermaid à partir d'une description ou config réseau.",
       {"network_config": {"type": "string", "description": "Texte décrivant l'infra réseau (équipements, IPs, etc.)"},
        "title":          {"type": "string"},
        "save":           {"type": "boolean", "description": "Sauvegarder en .md (défaut true)"},
        "output_path":    {"type": "string"}},
       ["network_config"]),
    _t("doc_generate_postmortem",
       "Génère un POST-MORTEM / analyse de cause racine (RCA) d'un incident : chronologie, cause racine, impact, résolution, actions correctives, leçons. PDF ou Word.",
       {"intervention_id": {"type": "string", "description": "Intervention liée (optionnel, pour reprendre le contexte)"},
        "title": {"type": "string"}, "severity": {"type": "string", "enum": ["low","medium","high","critical"]},
        "summary": {"type": "string"}, "timeline": {"type": "string"}, "root_cause": {"type": "string"},
        "business_impact": {"type": "string"}, "resolution": {"type": "string"},
        "corrective_actions": {"type": "string"}, "lessons": {"type": "string"},
        "downtime": {"type": "string"}, "services_impacted": {"type": "string"},
        "format": {"type": "string", "enum": ["pdf","docx"]}, "output_path": {"type": "string"}},
       []),
    _t("doc_generate_change",
       "Génère une DEMANDE DE CHANGEMENT (Change Request ITIL) : justification, plan de mise en œuvre, analyse de risque, plan de rollback, validation. PDF ou Word.",
       {"intervention_id": {"type": "string"}, "title": {"type": "string"},
        "description": {"type": "string"}, "change_type": {"type": "string"},
        "risk": {"type": "string", "enum": ["low","medium","high","critical"]},
        "justification": {"type": "string"}, "implementation_plan": {"type": "string"},
        "rollback_plan": {"type": "string"}, "planned_date": {"type": "string"},
        "format": {"type": "string", "enum": ["pdf","docx"]}, "output_path": {"type": "string"}},
       []),
    _t("doc_generate_onboarding",
       "Génère une fiche d'ARRIVÉE ou de DÉPART IT d'un collaborateur (checklist comptes, matériel, accès, données, sécurité). PDF ou Word.",
       {"mode": {"type": "string", "enum": ["onboarding","offboarding"], "description": "Arrivée ou départ"},
        "person_name": {"type": "string"}, "role": {"type": "string"}, "date": {"type": "string"},
        "manager": {"type": "string"}, "technician": {"type": "string"},
        "format": {"type": "string", "enum": ["pdf","docx"]}, "output_path": {"type": "string"}},
       ["person_name"]),
    _t("doc_template_list",
       "Liste les templates de documentation disponibles.",
       {"doc_type": {"type": "string", "enum": ["report","procedure","client_sheet","recovery_plan","maintenance","schema","runbook"]}}, []),
    _t("doc_asset_create",
       "Crée un asset dans la CMDB-lite (poste, serveur, firewall, switch, NAS, etc.).",
       {"name":        {"type": "string"},
        "asset_type":  {"type": "string", "enum": ["workstation","server","firewall","switch","router","printer","phone","nas","vm","other"]},
        "client_id":   {"type": "string"},
        "ip_address":  {"type": "string"},
        "mac_address": {"type": "string"},
        "os":          {"type": "string"},
        "specs":       {"type": "string"},
        "location":    {"type": "string"},
        "criticality": {"type": "string", "enum": ["low","medium","high","critical"]},
        "notes":       {"type": "string"}},
       ["name"]),
    _t("doc_asset_list", "Liste les assets de la CMDB.",
       {"client_id": {"type": "string"}}, []),
    _t("doc_knowledge_search",
       "Cherche dans la base de connaissances (interventions passées) par mot-clé pour résoudre rapidement des problèmes similaires.",
       {"query": {"type": "string", "description": "Mot-clé ou phrase à chercher"}},
       ["query"]),

    # ── Section 23 — v2.30 Command Safety / Guardrails ────────────────────
    _t("cmd_extract_from_text",
       "Extrait les commandes (PowerShell/CMD/Bash/Linux/Proxmox/Cisco/firewall) présentes dans un texte.",
       {"text": {"type": "string", "description": "Texte/notes contenant des commandes"}},
       ["text"]),
    _t("cmd_analyze_risk",
       "Analyse le niveau de risque d'une ou plusieurs commandes (safe/medium/high/critical/blocked). Journalise l'analyse. N'exécute JAMAIS la commande.",
       {"command":         {"type": "string", "description": "Une commande à analyser"},
        "commands":        {"type": "array",  "description": "Liste de commandes à analyser"},
        "intervention_id": {"type": "string", "description": "Lier l'analyse à une intervention"}},
       []),
    _t("cmd_suggest_safer_alternative",
       "Propose une alternative plus sûre pour une commande risquée.",
       {"command": {"type": "string"}}, ["command"]),
    _t("cmd_require_approval",
       "Crée une demande d'approbation pour une commande destructive (la commande n'est pas exécutée).",
       {"command":           {"type": "string"},
        "command_review_id": {"type": "string"},
        "intervention_id":   {"type": "string"},
        "requested_by":      {"type": "string"},
        "reason":            {"type": "string"}},
       ["command"]),
    _t("cmd_review_history",
       "Historique des analyses de commandes (filtrable par intervention ou niveau de risque).",
       {"intervention_id": {"type": "string"},
        "risk_level":      {"type": "string", "enum": ["safe","medium","high","critical","blocked"]},
        "limit":           {"type": "integer"}},
       []),

    # ── Section 24 — v2.30 Pre-Check / Post-Check ─────────────────────────
    _t("ops_checklist_generate",
       "Génère automatiquement des points de contrôle selon le type d'intervention (sans rien créer en base).",
       {"intervention_type": {"type": "string", "enum": ["incident","request","change","problem","deployment","maintenance","audit","other","default"]},
        "check_type":        {"type": "string", "enum": ["precheck","postcheck"]}},
       []),
    _t("ops_precheck_create",
       "Crée une checklist (pre-check ou post-check) liée à une intervention, avec points de contrôle auto-générés.",
       {"intervention_id": {"type": "string"},
        "check_type":      {"type": "string", "enum": ["precheck","postcheck"]},
        "title":           {"type": "string"},
        "items":           {"type": "array", "description": "Points personnalisés (optionnel)"}},
       ["intervention_id"]),
    _t("ops_precheck_run",
       "Enregistre les résultats d'un pre-check (ok/warning/failed/skipped par point). N'exécute aucune commande.",
       {"check_id": {"type": "string"},
        "results":  {"type": "array", "description": "[{item_id, status, actual_value, notes}]"}},
       ["check_id"]),
    _t("ops_postcheck_run",
       "Enregistre les résultats d'un post-check (validation après intervention).",
       {"check_id": {"type": "string"},
        "results":  {"type": "array", "description": "[{item_id, status, actual_value, notes}]"}},
       ["check_id"]),
    _t("ops_evidence_add",
       "Associe une preuve à une checklist : texte, commande, chemin fichier, capture ou log.",
       {"evidence_type":   {"type": "string", "enum": ["text","command","file_path","screenshot","log"]},
        "content":         {"type": "string"},
        "check_id":        {"type": "string"},
        "item_id":         {"type": "string"},
        "intervention_id": {"type": "string"}},
       ["content"]),
    _t("ops_validation_report_generate",
       "Génère un rapport de validation (pre-check + post-check + preuves) en MD/PDF/DOCX.",
       {"intervention_id": {"type": "string"},
        "format":          {"type": "string", "enum": ["pdf","docx","md"]},
        "output_path":     {"type": "string"}},
       ["intervention_id"]),

    # ── Section 25 — v2.30 Client Health Score ────────────────────────────
    _t("client_health_compute",
       "Calcule le score de santé opérationnelle d'un client (backup, sécurité, doc, infra, incidents) et génère des recommandations.",
       {"client_id": {"type": "string"}}, ["client_id"]),
    _t("client_health_get",
       "Récupère le dernier score de santé calculé pour un client.",
       {"client_id": {"type": "string"}}, ["client_id"]),
    _t("client_health_history",
       "Historique des scores de santé d'un client (évolution).",
       {"client_id": {"type": "string"}, "limit": {"type": "integer"}}, ["client_id"]),
    _t("client_recommendations_generate",
       "Liste/génère les recommandations issues du score de santé d'un client.",
       {"client_id": {"type": "string"},
        "status":    {"type": "string", "enum": ["open","done","dismissed"]},
        "recompute": {"type": "boolean", "description": "Recalculer le score d'abord"}},
       ["client_id"]),
    _t("client_monthly_summary_generate",
       "Génère un compte-rendu mensuel client (interventions + score santé + recommandations) en MD/PDF/DOCX.",
       {"client_id":   {"type": "string"},
        "format":      {"type": "string", "enum": ["pdf","docx","md"]},
        "output_path": {"type": "string"}},
       ["client_id"]),
]
