"""
SecretaryAI Backend — Registre de tous les outils disponibles pour l'agent.
Chaque outil expose :
  - Une entrée dans TOOLS_SPEC (format Ollama/OpenAI) pour que l'IA sache quoi appeler.
  - Une fonction async execute_*(args) pour l'exécution réelle.
  - Les outils « dangereux » vérifient args.get('confirmed') avant d'agir.
"""
import os
import sys
import ast
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
import vector_store as vector_store_runtime
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
from tool_domains import billing as billing_domain
from tool_domains import windows as windows_domain
from tool_domains import web as web_domain
from tool_domains import pc_control as pc_control_domain
from tool_domains import pc_diagnostics as pc_diagnostics_domain
from tool_domains import intervention_docs as intervention_docs_domain
from tool_domains import command_safety as command_safety_domain
from tool_domains import operations_safety as operations_safety_domain
from tool_domains import client_health as client_health_domain
from tool_domains import winget as winget_domain
from tool_domains import windows_settings as windows_settings_domain
from tool_domains import windows_registry as windows_registry_domain
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
from config import DANGEROUS_TOOLS, OLLAMA_URL, DEFAULT_MODEL, MODEL_PROFILES
from platform_paths import PATHS as _SYSTEM_PATHS, expand_user_path


# ══════════════════════════════════════════════════════════════════════════════
# Couche réseau robuste partagée : pooling de connexions, cache TTL, hors-ligne
# (rend tous les outils web plus rapides ET plus résistants aux coupures réseau)
# ══════════════════════════════════════════════════════════════════════════════

_HTTP_CLIENT = None


def _get_http_client():
    """Client httpx PARTAGÉ (pool de connexions réutilisé) → évite le handshake
    TCP/TLS à chaque appel = bien plus rapide. Recréé s'il a été fermé."""
    global _HTTP_CLIENT
    import httpx
    if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
        _HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=4.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"},
        )
    return _HTTP_CLIENT


def _is_offline_error(e) -> bool:
    """Détecte une panne réseau / DNS / connexion (vs une vraie erreur applicative)."""
    s = str(e).lower()
    return any(k in s for k in (
        "getaddrinfo", "name or service", "temporary failure", "connecterror",
        "connection refused", "network is unreachable", "no address associated",
        "timed out", "readtimeout", "connecttimeout", "[errno 11001]", "[errno -3]",
        "failed to establish", "max retries", "nodename nor servname"))


def _net_error(e, what="la ressource") -> dict:
    """Erreur réseau lisible : distingue 'hors-ligne' d'une erreur applicative."""
    if _is_offline_error(e):
        return {"error": f"Pas de connexion internet (ou {what} injoignable). "
                         f"Vérifiez votre réseau puis réessayez.", "offline": True}
    return {"error": str(e)}


# Cache TTL en mémoire pour les résultats web (évite les appels réseau redondants)
_WEB_CACHE: dict = {}
_WEB_CACHE_TTL = 600  # 10 minutes


def _wcache_get(key):
    v = _WEB_CACHE.get(key)
    if v and (time.time() - v[0]) < _WEB_CACHE_TTL:
        return v[1]
    if v:
        _WEB_CACHE.pop(key, None)
    return None


def _wcache_set(key, value):
    if len(_WEB_CACHE) > 256:        # borne mémoire
        for k in list(_WEB_CACHE)[:128]:
            _WEB_CACHE.pop(k, None)
    _WEB_CACHE[key] = (time.time(), value)


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


filesystem_domain.configure(resolve_path=_resolve_path)
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


async def execute_system_search(args: dict) -> dict:
    """
    Recherche ULTRA-RAPIDE sur TOUT le PC via l'index Windows Search.
    Idéal pour trouver un fichier/dossier dont on connaît une partie du nom.
    Limites : seuls les dossiers indexés (Desktop, Documents, Downloads, Pictures, etc.)
    Pour les autres emplacements, utilisez file_find avec un path spécifique.
    """
    query = args.get("query", "").strip()
    file_type = args.get("file_type", "").strip().lower()  # all | folder | file | pdf | docx | xlsx | image
    max_results = int(args.get("max_results", 30))

    if not query and not file_type:
        return {"error": "Paramètre 'query' requis. Ex: 'abdou', 'rapport', 'photo' (ou un 'file_type' pour tout lister d'un type)."}

    # Convert query to SQL LIKE pattern (auto-add wildcards)
    # Sans terme mais avec un type (ex: « tous mes PDF ») → on liste tout le type.
    pattern = '%' if not query else (query if any(c in query for c in '*?%') else f'%{query}%')

    try:
        import win32com.client as _w32com
        import pythoncom

        def _run_query():
            # CoInitialize is required for COM access from non-main threads
            try:
                pythoncom.CoInitialize()
                com_inited = True
            except Exception:
                com_inited = False

            try:
                sql_pattern = pattern.replace('*', '%').replace('?', '_').replace("'", "''")

                conn = _w32com.Dispatch('ADODB.Connection')
                conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
                rs = _w32com.Dispatch('ADODB.Recordset')

                where_parts = [f"System.FileName LIKE '{sql_pattern}'"]

                # Filter by type
                if file_type == "folder":
                    where_parts.append("System.ItemType = 'Directory'")
                elif file_type == "pdf":
                    where_parts.append("System.FileExtension = '.pdf'")
                elif file_type == "docx":
                    where_parts.append("(System.FileExtension = '.docx' OR System.FileExtension = '.doc')")
                elif file_type == "xlsx":
                    where_parts.append("(System.FileExtension = '.xlsx' OR System.FileExtension = '.xls' OR System.FileExtension = '.csv')")
                elif file_type == "image":
                    where_parts.append("(System.FileExtension = '.jpg' OR System.FileExtension = '.jpeg' OR System.FileExtension = '.png' OR System.FileExtension = '.gif' OR System.FileExtension = '.webp')")
                elif file_type == "file":
                    where_parts.append("System.ItemType <> 'Directory'")

                sql = (
                    f"SELECT TOP {max_results} "
                    f"System.ItemPathDisplay, System.ItemName, System.Size, "
                    f"System.DateModified, System.ItemType, System.FileExtension "
                    f"FROM SystemIndex WHERE {' AND '.join(where_parts)} "
                    f"ORDER BY System.DateModified DESC"
                )
                rs.Open(sql, conn)

                results = []
                while not rs.EOF:
                    path_val = rs.Fields("System.ItemPathDisplay").Value
                    if path_val:
                        path_val = _normalize_windows_path(str(path_val))
                    name_val = rs.Fields("System.ItemName").Value
                    try:    size_val = int(rs.Fields("System.Size").Value or 0)
                    except: size_val = 0
                    try:    mod_val = rs.Fields("System.DateModified").Value
                    except: mod_val = None
                    try:    type_val = rs.Fields("System.ItemType").Value or ""
                    except: type_val = ""
                    try:    ext_val = rs.Fields("System.FileExtension").Value or ""
                    except: ext_val = ""

                    is_dir = (str(type_val) == "Directory")
                    results.append({
                        "name":     str(name_val) if name_val else "",
                        "path":     path_val or "",
                        "is_dir":   is_dir,
                        "size":     size_val,
                        "size_kb":  round(size_val / 1024, 1) if size_val else 0,
                        "extension": str(ext_val),
                        "modified": str(mod_val) if mod_val else "",
                    })
                    rs.MoveNext()

                rs.Close()
                conn.Close()
                return results
            finally:
                if com_inited:
                    try: pythoncom.CoUninitialize()
                    except Exception: pass

        import time as _t
        loop = asyncio.get_running_loop()
        t0 = _t.time()
        results = await loop.run_in_executor(None, _run_query)
        elapsed_ms = int((_t.time() - t0) * 1000)

        return {
            "success":     True,
            "query":       query,
            "file_type":   file_type or "all",
            "count":       len(results),
            "elapsed_ms":  elapsed_ms,
            "method":      "windows_search_index",
            "results":     results,
            "hint":        ("Pour voir le contenu d'un dossier trouvé, utilisez file_list avec son chemin."
                            if results else
                            "Aucun résultat. Vérifiez que le dossier est indexé par Windows Search (Panneau de configuration > Options d'indexation)."),
        }

    except ImportError:
        return {"error": "win32com indisponible. Installez avec : pip install pywin32"}
    except Exception as e:
        return {"error": f"Erreur Windows Search : {str(e)[:200]}. Vérifiez que le service 'Windows Search' est démarré."}


async def execute_system_search_content(args: dict) -> dict:
    """
    Recherche par CONTENU sur TOUT le PC via l'index plein-texte de Windows Search.
    Trouve les documents d'après ce qu'ils CONTIENNENT (pas seulement leur nom).
    Idéal pour « retrouve le document qui parle de X », « où est le contrat avec Y ».
    Renvoie un extrait (AutoSummary) du passage. Seuls les dossiers indexés sont couverts.
    """
    query = (args.get("query") or "").strip()
    file_type = (args.get("file_type") or "").strip().lower()
    max_results = int(args.get("max_results", 25))
    if not query:
        return {"error": "Paramètre 'query' requis (ex: 'clause de résiliation', 'facture Dupont')."}

    try:
        import win32com.client as _w32com
        import pythoncom
        import re as _re

        def _run_query():
            try:
                pythoncom.CoInitialize(); com_inited = True
            except Exception:
                com_inited = False
            try:
                conn = _w32com.Dispatch('ADODB.Connection')
                conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
                rs = _w32com.Dispatch('ADODB.Recordset')

                # CONTAINS plein-texte : chaque mot en préfixe, tous requis (AND).
                words = [w for w in _re.findall(r"\w+", query, _re.UNICODE) if len(w) > 1]
                if words:
                    terms = " AND ".join(f'"{w}*"' for w in words)
                else:
                    terms = f'"{query}"'
                where_parts = [f"CONTAINS(System.Search.Contents, '{terms}')"]

                if file_type == "pdf":
                    where_parts.append("System.FileExtension = '.pdf'")
                elif file_type == "docx":
                    where_parts.append("(System.FileExtension = '.docx' OR System.FileExtension = '.doc')")
                elif file_type == "xlsx":
                    where_parts.append("(System.FileExtension = '.xlsx' OR System.FileExtension = '.xls' OR System.FileExtension = '.csv')")
                elif file_type == "text":
                    where_parts.append("(System.FileExtension = '.txt' OR System.FileExtension = '.md' OR System.FileExtension = '.log')")

                sql = (
                    f"SELECT TOP {max_results} "
                    f"System.ItemPathDisplay, System.ItemName, System.Size, "
                    f"System.DateModified, System.FileExtension, System.Search.AutoSummary "
                    f"FROM SystemIndex WHERE {' AND '.join(where_parts)} "
                    f"ORDER BY System.DateModified DESC"
                )
                rs.Open(sql, conn)

                results = []
                while not rs.EOF:
                    path_val = rs.Fields("System.ItemPathDisplay").Value
                    if path_val:
                        path_val = _normalize_windows_path(str(path_val))
                    name_val = rs.Fields("System.ItemName").Value
                    try:    size_val = int(rs.Fields("System.Size").Value or 0)
                    except: size_val = 0
                    try:    mod_val = rs.Fields("System.DateModified").Value
                    except: mod_val = None
                    try:    ext_val = rs.Fields("System.FileExtension").Value or ""
                    except: ext_val = ""
                    try:    snippet = rs.Fields("System.Search.AutoSummary").Value or ""
                    except: snippet = ""
                    snippet = " ".join(str(snippet).split())[:280]
                    results.append({
                        "name":      str(name_val) if name_val else "",
                        "path":      path_val or "",
                        "size":      size_val,
                        "size_kb":   round(size_val / 1024, 1) if size_val else 0,
                        "extension": str(ext_val),
                        "modified":  str(mod_val) if mod_val else "",
                        "snippet":   snippet,
                    })
                    rs.MoveNext()
                rs.Close(); conn.Close()
                return results
            finally:
                if com_inited:
                    try: pythoncom.CoUninitialize()
                    except Exception: pass

        import time as _t
        loop = asyncio.get_running_loop()
        t0 = _t.time()
        results = await loop.run_in_executor(None, _run_query)
        elapsed_ms = int((_t.time() - t0) * 1000)
        return {
            "success":    True,
            "query":      query,
            "file_type":  file_type or "all",
            "count":      len(results),
            "elapsed_ms": elapsed_ms,
            "method":     "windows_search_content",
            "results":    results,
            "hint":       ("Tu peux indexer un résultat (document_index) pour interroger son contenu ensuite."
                           if results else
                           "Aucun document ne contient ces termes (ou l'emplacement n'est pas indexé par Windows Search)."),
        }
    except ImportError:
        return {"error": "win32com indisponible. Installez avec : pip install pywin32"}
    except Exception as e:
        return {"error": f"Erreur Windows Search (contenu) : {str(e)[:200]}. Le service 'Windows Search' doit être démarré."}


# ══════════════════════════════════════════════════════════════════════════════
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
async def execute_webapp_create(args: dict) -> dict:
    """Génère une mini-application web autonome (HTML/CSS/JS auto-contenu, un seul fichier)
    et l'enregistre localement — pour un dashboard, un prototype, un outil interactif, une
    page de suivi de projet... Ouvrable directement dans le navigateur (clic sur la carte
    dans le chat). Le contenu doit être self-contained : CSS/JS inline, pas de dépendance
    CDN externe (fonctionne même hors-ligne, cohérent avec un usage local)."""
    content = (args.get("content") or "").strip()
    title = (args.get("title") or "webapp").strip()
    if not content:
        return {"error": "Paramètre 'content' requis (le code HTML complet de la page)."}
    if "<html" not in content.lower():
        content = (
            f'<!DOCTYPE html>\n<html lang="fr"><head><meta charset="utf-8">'
            f'<title>{title}</title></head><body>\n{content}\n</body></html>'
        )
    import re as _re, uuid as _uuid
    safe_name = _re.sub(r"[^a-zA-Z0-9_-]+", "_", title)[:60].strip("_") or "webapp"
    out_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "data", "webapps", f"{safe_name}_{_uuid.uuid4().hex[:8]}"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"success": True, "path": path,
            "message": f"Mini-appli « {title} » créée — clique pour l'ouvrir dans ton navigateur."}


















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

_TELEMETRY_KEY = r"HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection"
_BLOATWARE = [
    "Microsoft.BingNews", "Microsoft.BingWeather", "Microsoft.GamingApp", "Microsoft.GetHelp",
    "Microsoft.Getstarted", "Microsoft.MicrosoftSolitaireCollection", "Microsoft.People",
    "Microsoft.PowerAutomateDesktop", "Microsoft.Todos", "Microsoft.WindowsFeedbackHub",
    "Microsoft.WindowsMaps", "Microsoft.Xbox.TCUI", "Microsoft.XboxGameOverlay",
    "Microsoft.XboxGamingOverlay", "Microsoft.XboxIdentityProvider", "Microsoft.XboxSpeechToTextOverlay",
    "Microsoft.ZuneMusic", "Microsoft.ZuneVideo", "Microsoft.YourPhone", "Clipchamp.Clipchamp",
    "Microsoft.549981C3F5F10", "MicrosoftTeams", "Microsoft.MicrosoftStickyNotes",
]














async def execute_tweak_telemetry(args: dict) -> dict:
    """Statut / désactivation / réactivation de la télémétrie Windows (DiagTrack + AllowTelemetry)."""
    action = (args.get("action") or "status").lower()
    if action in ("status", "query", "get"):
        svc = await execute_pc_run_powershell({"script": "(Get-Service DiagTrack -EA SilentlyContinue).Status",
                                               "confirmed": True, "timeout": 15})
        key = await execute_registry_get({"path": _TELEMETRY_KEY, "name": "AllowTelemetry"})
        return {"success": True, "action": "status",
                "diagtrack": (svc.get("stdout") or "").strip() or "inconnu",
                "allow_telemetry": (key.get("value") if key.get("success") else "non défini (défaut : activé)")}
    if action not in ("disable", "enable"):
        return {"error": "action attendue : status | disable | enable"}
    if not args.get("confirmed"):
        verb = "Désactiver" if action == "disable" else "Réactiver"
        return {"requiresConfirmation": True,
                "message": f"{verb} la télémétrie Windows (service DiagTrack + clé AllowTelemetry) ? "
                           f"(sauvegarde auto, totalement réversible)"}
    backup = await _reg_backup(_TELEMETRY_KEY)
    if action == "disable":
        ps = (f"if(-not (Test-Path '{_TELEMETRY_KEY}')){{New-Item -Path '{_TELEMETRY_KEY}' -Force|Out-Null}};"
              f"New-ItemProperty -Path '{_TELEMETRY_KEY}' -Name AllowTelemetry -Value 0 -PropertyType DWord -Force|Out-Null;"
              "Stop-Service DiagTrack -Force -EA SilentlyContinue;"
              "Set-Service DiagTrack -StartupType Disabled -EA SilentlyContinue;"
              "Stop-Service dmwappushservice -Force -EA SilentlyContinue;"
              "Set-Service dmwappushservice -StartupType Disabled -EA SilentlyContinue; 'OK'")
    else:
        ps = (f"New-ItemProperty -Path '{_TELEMETRY_KEY}' -Name AllowTelemetry -Value 1 -PropertyType DWord -Force -EA SilentlyContinue|Out-Null;"
              "Set-Service DiagTrack -StartupType Automatic -EA SilentlyContinue; Start-Service DiagTrack -EA SilentlyContinue;"
              "Set-Service dmwappushservice -StartupType Manual -EA SilentlyContinue; 'OK'")
    r = await execute_pc_run_powershell({"script": ps, "confirmed": True, "timeout": 45})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "action": action, "backup": backup,
            "message": (f"✅ Télémétrie {'désactivée' if action == 'disable' else 'réactivée'}." if ok else
                        "❌ Échec — droits ADMINISTRATEUR requis."),
            "detail": (r.get("stderr") or "")[:250]}


async def execute_tweak_debloat_list(args: dict) -> dict:
    """Liste les bloatwares d'usine (UWP) présents et désinstallables (lecture seule)."""
    r = await execute_pc_run_powershell({"script": "Get-AppxPackage | Select-Object -ExpandProperty Name",
                                         "confirmed": True, "timeout": 45})
    installed = [i.strip() for i in (r.get("stdout") or "").splitlines() if i.strip()]
    inst_lc = {i.lower() for i in installed}
    present = [b for b in _BLOATWARE if b.lower() in inst_lc or any(i.startswith(b.lower()) for i in inst_lc)]
    return {"success": True, "removable": present, "count": len(present),
            "note": "Applications d'usine non essentielles détectées (réinstallables via le Microsoft Store)."}


async def execute_tweak_debloat_remove(args: dict) -> dict:
    """Désinstalle des applications UWP (bloatware). Nécessite confirmation."""
    pkgs = args.get("packages") or ([args["package"]] if args.get("package") else [])
    pkgs = [p for p in pkgs if isinstance(p, str) and p.strip()][:30]
    if not pkgs:
        return {"error": "Paramètre 'packages' (liste de noms UWP) requis."}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True,
                "message": f"Désinstaller {len(pkgs)} application(s) : {', '.join(pkgs)} ?"}
    removed, failed = [], []
    for p in pkgs:
        safe = p.replace("'", "")
        ps = f"Get-AppxPackage -Name '{safe}*' | Remove-AppxPackage -EA SilentlyContinue; 'done'"
        r = await execute_pc_run_powershell({"script": ps, "confirmed": True, "timeout": 60})
        (removed if r.get("returncode") == 0 else failed).append(p)
    return {"success": bool(removed) or not failed, "removed": removed, "failed": failed,
            "message": f"✅ {len(removed)} application(s) retirée(s)" + (f", {len(failed)} échec(s)" if failed else "")}


async def execute_tweak_network_harden(args: dict) -> dict:
    """Statut / application d'optimisations réseau légères (cache DNS, auto-tuning TCP)."""
    action = (args.get("action") or "status").lower()
    if action in ("status", "query", "get"):
        ps = ("Get-DnsClientCache -EA SilentlyContinue | Measure-Object | "
              "ForEach-Object { 'Entrees cache DNS: ' + $_.Count };"
              "netsh int tcp show global")
        r = await execute_pc_run_powershell({"script": ps, "confirmed": True, "timeout": 20})
        return {"success": True, "action": "status", "output": (r.get("stdout") or "").strip()[:800]}
    if action != "apply":
        return {"error": "action attendue : status | apply"}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True,
                "message": "Appliquer un durcissement réseau léger (vider le cache DNS + ajuster l'auto-tuning TCP) ?"}
    ps = ("Clear-DnsClientCache -EA SilentlyContinue;"
          "netsh int tcp set global autotuninglevel=normal | Out-Null;"
          "netsh int tcp set heuristics disabled | Out-Null; 'OK'")
    r = await execute_pc_run_powershell({"script": ps, "confirmed": True, "timeout": 40})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "action": "apply",
            "message": ("✅ Réseau optimisé (cache DNS vidé, TCP ajusté)." if ok else
                        "❌ Échec — droits ADMINISTRATEUR requis pour netsh."),
            "detail": (r.get("stderr") or "")[:200]}


# ══════════════════════════════════════════════════════════════════════════════
#  CATHARSIS — Moteur de purge (style CCleaner) : SCAN d'abord (taille récupérable),
#  puis CLEAN confirmé. Ne touche QUE des dossiers temporaires/caches connus.
# ══════════════════════════════════════════════════════════════════════════════

#  (id) -> (libellé, [chemins PowerShell], groupe)   — groupe = tuile dans l'UI
_CLEAN_CATS = {
    # ── Windows ──
    "temp_user":     ("Fichiers temporaires (utilisateur)", [r"$env:TEMP\*"], "Windows"),
    "temp_windows":  ("Fichiers temporaires (Windows)",     [r"C:\Windows\Temp\*"], "Windows"),
    "thumbnails":    ("Cache des vignettes",                [r"$env:LOCALAPPDATA\Microsoft\Windows\Explorer\thumbcache_*.db"], "Windows"),
    "prefetch":      ("Prefetch (préchargement)",           [r"C:\Windows\Prefetch\*"], "Windows"),
    "recent":        ("Documents récents (raccourcis)",     [r"$env:APPDATA\Microsoft\Windows\Recent\*"], "Windows"),
    "error_reports": ("Rapports d'erreurs (WER)",           [r"$env:LOCALAPPDATA\Microsoft\Windows\WER\*", r"$env:ProgramData\Microsoft\Windows\WER\*"], "Windows"),
    "delivery_opt":  ("Cache Windows Update",               [r"C:\Windows\SoftwareDistribution\DeliveryOptimization\*"], "Windows"),
    # ── Système ──
    "crash_dumps":   ("Rapports de plantage (.dmp)",        [r"C:\Windows\Minidump\*", r"$env:LOCALAPPDATA\CrashDumps\*"], "Système"),
    "dx_cache":      ("Cache shaders DirectX / GPU",        [r"$env:LOCALAPPDATA\D3DSCache\*", r"$env:LOCALAPPDATA\NVIDIA\DXCache\*"], "Système"),
    "font_cache":    ("Cache des polices (logs)",           [r"$env:LOCALAPPDATA\FontCache\*"], "Système"),
    # ── Navigateurs ──
    "edge_cache":    ("Cache Microsoft Edge",               [r"$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache\*"], "Navigateurs"),
    "chrome_cache":  ("Cache Google Chrome",                [r"$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Cache\*"], "Navigateurs"),
    "firefox_cache": ("Cache Mozilla Firefox",              [r"$env:LOCALAPPDATA\Mozilla\Firefox\Profiles\*\cache2\*"], "Navigateurs"),
}
# Groupe d'affichage de la corbeille (catégorie spéciale, hors _CLEAN_CATS)
_RECYCLE_GROUP = "Windows"


async def execute_catharsis_scan(args: dict) -> dict:
    """Analyse l'espace récupérable par catégorie (NE SUPPRIME RIEN)."""
    lines = ["$o=@{}"]
    for cid, (_label, paths, _grp) in _CLEAN_CATS.items():
        # double quotes → PowerShell développe bien $env:TEMP, $env:LOCALAPPDATA, etc.
        ps_paths = ",".join('"' + p + '"' for p in paths)
        lines.append(
            f"$s=0; foreach($p in @({ps_paths})){{ "
            f"Get-ChildItem -Path $p -Recurse -Force -EA SilentlyContinue | "
            f"ForEach-Object {{ $s += $_.Length }} }}; $o['{cid}']=[int64]$s")
    lines.append("try{ $rb=((New-Object -ComObject Shell.Application).Namespace(10).Items() | "
                 "ForEach-Object { $_.Size } | Measure-Object -Sum).Sum; $o['recycle_bin']=[int64]$rb }"
                 "catch{ $o['recycle_bin']=0 }")
    lines.append("$o | ConvertTo-Json -Compress")
    r = await execute_pc_run_powershell({"script": ";".join(lines), "confirmed": True, "timeout": 150})
    import json as _j
    try:
        data = _j.loads((r.get("stdout") or "{}").strip())
    except Exception:
        data = {}
    labels = {cid: lbl for cid, (lbl, _p, _g) in _CLEAN_CATS.items()}
    groups = {cid: g for cid, (_l, _p, g) in _CLEAN_CATS.items()}
    labels["recycle_bin"] = "Corbeille"; groups["recycle_bin"] = _RECYCLE_GROUP
    cats, total = [], 0
    for cid, by in (data or {}).items():
        by = int(by or 0)
        total += by
        cats.append({"id": cid, "label": labels.get(cid, cid), "group": groups.get(cid, "Autres"),
                     "bytes": by, "mb": round(by / 1048576, 1)})
    cats.sort(key=lambda c: -c["bytes"])
    return {"success": True, "categories": cats, "total_mb": round(total / 1048576, 1)}


async def execute_catharsis_clean(args: dict) -> dict:
    """Purge les catégories choisies (ids issus de catharsis_scan). Demande confirmation."""
    cats = [c for c in (args.get("categories") or []) if c in _CLEAN_CATS or c == "recycle_bin"]
    if not cats:
        return {"error": "Paramètre 'categories' requis (ids depuis catharsis_scan)."}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True,
                "message": f"Vider {len(cats)} catégorie(s) : {', '.join(cats)} ? "
                           f"(suppression définitive de fichiers temporaires/caches)"}
    lines = []
    for cid in cats:
        if cid == "recycle_bin":
            lines.append("Clear-RecycleBin -Force -EA SilentlyContinue")
            continue
        for p in _CLEAN_CATS[cid][1]:
            lines.append(f'Get-ChildItem -Path "{p}" -Force -EA SilentlyContinue | '
                         f'Remove-Item -Recurse -Force -EA SilentlyContinue')
    lines.append("'OK'")
    r = await execute_pc_run_powershell({"script": ";".join(lines), "confirmed": True, "timeout": 240})
    ok = "OK" in (r.get("stdout") or "")
    return {"success": ok, "cleaned": cats,
            "message": (f"✅ {len(cats)} catégorie(s) nettoyée(s)." if ok else
                        "⚠️ Nettoyage partiel (certains fichiers étaient verrouillés/en usage).")}


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

_GUI_INTERACTIVE_TYPES = {
    "Button", "Edit", "Document", "ComboBox", "CheckBox", "RadioButton", "MenuItem", "MenuBar",
    "ListItem", "List", "TabItem", "Hyperlink", "Slider", "Spinner", "TreeItem",
    "SplitButton", "ToggleButton", "DataItem",
}




# Types "porteurs de contenu" : leur `name` UIA EST le texte qu'ils contiennent (constaté en
# testant sur le Bloc-notes Windows 11 réel — control_type="Document", name="<tout le fichier>").
# Ce texte n'est PAS un identifiant stable (il change à chaque frappe) → jamais utilisé pour le
# matching de ré-résolution, seulement affiché (tronqué) à titre informatif. Le matching se fait
# par position (match_index) parmi les contrôles du même control_type dans la fenêtre.
_GUI_CONTENT_TYPES = {"Edit", "Document"}












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

async def execute_infographic_create(args: dict) -> dict:
    """Crée une infographie/graphique matplotlib et la sauvegarde en PNG."""
    chart_type = args.get("chart_type", "bar")   # bar, pie, line, horizontal_bar
    title = args.get("title", "Graphique")
    labels = args.get("labels", [])
    values = args.get("values", [])
    _op_raw = args.get("output_path", "")
    if _op_raw:
        output_path = _resolve_path(_op_raw)
    else:
        output_path = str(Path(_SYSTEM_PATHS["desktop"]) / f"infographie_{int(time.time())}.png")
    colors = args.get("colors", None)
    subtitle = args.get("subtitle", "")

    _series = args.get("series") or []
    if not labels:
        return {"error": "Labels (étiquettes) requis"}
    if not values and not _series:
        return {"error": "Fournir 'values' (mono-série) ou 'series' (multi-série : [{name, values}])"}
    if values and len(labels) != len(values):
        return {"error": "Le nombre de labels doit correspondre au nombre de valeurs"}

    # Run the blocking matplotlib operation in a thread pool to avoid blocking the event loop
    def _render_chart():
      try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np

        # Thème (sombre par défaut, clair optionnel)
        theme = (args.get("theme") or "dark").lower()
        GOLD = "#c9a84c"
        if theme == "light":
            BG, TEXT_COLOR, GRID_COLOR = "#ffffff", "#222222", "#dddddd"
        else:
            BG, TEXT_COLOR, GRID_COLOR = "#111111", "#c3c3c3", "#2a2a2a"
        default_colors = [GOLD, "#e8c96d", "#5b9bd5", "#70ad47", "#ed7d31", "#a07830",
                          "#d4b060", "#7030a0", "#c0504d", "#4bacc6"]

        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(BG)

        used_colors = colors or (default_colors * 4)[:max(len(labels), 1)]
        vals = [float(v) for v in values] if values else []
        # Multi-séries : [{"name":..., "values":[...]}, ...]
        series = args.get("series") or []
        x = np.arange(len(labels))

        def _style_axes(grid_axis="y"):
            ax.set_xticks(x); ax.set_xticklabels(labels, color=TEXT_COLOR, fontsize=9, rotation=0)
            ax.tick_params(colors=TEXT_COLOR)
            ax.grid(axis=grid_axis, color=GRID_COLOR, linewidth=0.7)
            for s in ax.spines.values():
                s.set_color(GRID_COLOR)

        ct = chart_type
        if ct in ("pie", "donut"):
            wedges, texts, autotexts = ax.pie(
                vals, labels=labels, colors=used_colors, autopct="%1.1f%%", startangle=140,
                pctdistance=0.8, textprops={"color": TEXT_COLOR, "fontsize": 10},
                wedgeprops=dict(width=0.42) if ct == "donut" else None)
            for at in autotexts:
                at.set_color(BG if theme == "dark" else "#ffffff"); at.set_fontweight("bold")
            if ct == "donut":
                ax.text(0, 0, f"{sum(vals):g}", ha="center", va="center", color=GOLD, fontsize=16, fontweight="bold")
        elif ct in ("line", "area", "multi_line"):
            sset = series if series else [{"name": "", "values": vals}]
            for idx, s in enumerate(sset):
                c = used_colors[idx % len(used_colors)]
                sv = [float(v) for v in s["values"]]
                ax.plot(x, sv, color=c, linewidth=2.5, marker="o", markersize=6,
                        markerfacecolor=BG, markeredgewidth=2, label=s.get("name", ""))
                if ct == "area":
                    ax.fill_between(x, sv, alpha=0.18, color=c)
            _style_axes("y")
            if series:
                ax.legend(facecolor=BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9)
        elif ct == "scatter":
            xv = [float(v) for v in (args.get("x_values") or x)]
            ax.scatter(xv, vals, color=GOLD, s=80, alpha=0.8, edgecolors=BG, linewidths=1)
            ax.tick_params(colors=TEXT_COLOR); ax.grid(color=GRID_COLOR, linewidth=0.7)
            for sp in ax.spines.values():
                sp.set_color(GRID_COLOR)
        elif ct == "radar":
            ax.remove()
            ax = fig.add_subplot(111, polar=True); ax.set_facecolor(BG)
            ang = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
            sset = series if series else [{"name": "", "values": vals}]
            for idx, s in enumerate(sset):
                sv = [float(v) for v in s["values"]]; sv += sv[:1]
                aa = ang + ang[:1]; c = used_colors[idx % len(used_colors)]
                ax.plot(aa, sv, color=c, linewidth=2, label=s.get("name", ""))
                ax.fill(aa, sv, color=c, alpha=0.15)
            ax.set_xticks(ang); ax.set_xticklabels(labels, color=TEXT_COLOR, fontsize=9)
            ax.tick_params(colors=TEXT_COLOR)
            if series:
                ax.legend(facecolor=BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8, loc="upper right")
        elif ct in ("grouped_bar", "stacked_bar") and series:
            n = len(series); w = 0.8 / max(n, 1)
            bottom = np.zeros(len(labels))
            for idx, s in enumerate(series):
                sv = np.array([float(v) for v in s["values"]]); c = used_colors[idx % len(used_colors)]
                if ct == "stacked_bar":
                    ax.bar(x, sv, bottom=bottom, color=c, width=0.55, label=s.get("name", "")); bottom += sv
                else:
                    ax.bar(x + idx * w - 0.4 + w / 2, sv, color=c, width=w, label=s.get("name", ""))
            _style_axes("y")
            ax.legend(facecolor=BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=9)
        elif ct == "horizontal_bar":
            y = np.arange(len(labels))
            bars = ax.barh(y, vals, color=used_colors, edgecolor="none", height=0.55)
            ax.set_yticks(y); ax.set_yticklabels(labels, color=TEXT_COLOR, fontsize=9)
            ax.tick_params(colors=TEXT_COLOR); ax.grid(axis="x", color=GRID_COLOR, linewidth=0.7)
            for sp in ax.spines.values():
                sp.set_color(GRID_COLOR)
            for bar, val in zip(bars, vals):
                ax.text(bar.get_width() + max(vals) * 0.01, bar.get_y() + bar.get_height() / 2,
                        f"{val:g}", va="center", color=TEXT_COLOR, fontsize=8)
        else:  # bar (défaut)
            bars = ax.bar(x, vals, color=used_colors, edgecolor="none", width=0.55)
            _style_axes("y")
            for bar, val in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(vals) * 0.01,
                        f"{val:g}", ha="center", va="bottom", color=TEXT_COLOR, fontsize=8)

        ax.set_title(title, color=GOLD, fontsize=14, fontweight="bold", pad=16)
        if subtitle:
            fig.text(0.5, 0.93, subtitle, ha="center", color=TEXT_COLOR, fontsize=9)

        plt.tight_layout()
        out = Path(output_path)
        if not out.suffix:
            out = out.with_suffix(".png")
        out.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(out), dpi=150, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        return {"success": True, "message": f"Infographie créée : {out}", "path": str(out)}
      except Exception as e:
        return {"error": str(e)}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _render_chart)





# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9A — Google Calendar
# ══════════════════════════════════════════════════════════════════════════════

execute_file_create_pdf = documents_domain.create_pdf
screenshots_domain.configure_renderers(
    create_docx=execute_file_create_docx,
    create_pdf=execute_file_create_pdf,
)


_GOOGLE_SA_PATH = os.path.join(os.path.dirname(__file__), "data", "google_service_account.json")


def _google_sa_email() -> str | None:
    """Email du compte de service si une clé est présente (pour partager l'agenda)."""
    try:
        if os.path.exists(_GOOGLE_SA_PATH):
            import json as _j
            with open(_GOOGLE_SA_PATH, encoding="utf-8") as f:
                return _j.load(f).get("client_email")
    except Exception:
        pass
    return None


def _resolve_calendar_id(requested: str | None) -> str:
    """Avec un compte de service, « primary » = l'agenda VIDE du robot.
    On cible donc l'agenda partagé configuré (google_calendar_id = ton email)."""
    requested = (requested or "primary").strip()
    if requested == "primary" and os.path.exists(_GOOGLE_SA_PATH):
        cid = db.get_setting("google_calendar_id")
        if cid:
            return str(cid)
    return requested


def _norm_google_dt(s: str) -> str:
    """Google exige un RFC3339 complet avec secondes (sinon 400). 'YYYY-MM-DD HH:MM' →
    'YYYY-MM-DDTHH:MM:SS'. Laisse les dates (toute-journée, sans 'T') intactes."""
    if not s:
        return s
    s = str(s).replace(" ", "T")
    if "T" not in s:
        return s
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(s).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return s


def _google_calendar_ready() -> bool:
    """Vrai si l'agenda Google est configuré (sans appel réseau) : compte de service + agenda
    cible défini, OU tokens OAuth présents (backend credentials ou table frontend oauth_tokens)."""
    try:
        if os.path.exists(_GOOGLE_SA_PATH) and db.get_setting("google_calendar_id"):
            return True
        import credentials_manager as cm
        if cm.get_credential("google_access_token") or cm.get_credential("google_refresh_token"):
            return True
        with db.db() as connection:
            row = connection.execute(
                "SELECT access_token FROM oauth_tokens WHERE provider='google'"
            ).fetchone()
        return bool(row and row["access_token"])
    except Exception:
        return False


def _get_google_calendar_service(prefer_oauth: bool = False):
    """Construit le service Google Calendar. Priorité au COMPTE DE SERVICE (permanent,
    sans expiration) si une clé JSON est présente ; sinon OAuth (tokens utilisateur).
    v2.137 — `prefer_oauth=True` force le repli OAuth même si le compte de service est
    configuré : utilisé quand le compte de service renvoie 404 sur l'agenda ciblé (le
    calendrier personnel n'a pas été partagé avec l'e-mail du compte de service — cas
    fréquent, corrigible soit en partageant l'agenda, soit en retombant sur OAuth qui a
    directement accès aux agendas de l'utilisateur connecté)."""
    from googleapiclient.discovery import build

    # 1) Compte de service (recommandé pour un agenda perso permanent)
    if os.path.exists(_GOOGLE_SA_PATH) and not prefer_oauth:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            _GOOGLE_SA_PATH, scopes=["https://www.googleapis.com/auth/calendar"])
        return build("calendar", "v3", credentials=creds)

    # 2) OAuth utilisateur (tokens)
    import credentials_manager as cm
    from google.oauth2.credentials import Credentials

    access_token = cm.get_credential("google_access_token")
    refresh_token = cm.get_credential("google_refresh_token")
    client_id = cm.get_credential("google_client_id")
    client_secret = cm.get_credential("google_client_secret")

    # Pont : si le flux backend n'a pas de tokens, réutilise ceux du flux frontend
    # (table oauth_tokens, provider='google'). Le client_id/secret backend sert au refresh.
    if not access_token and not refresh_token:
        try:
            with db.db() as connection:
                row = connection.execute(
                    "SELECT access_token, refresh_token FROM oauth_tokens WHERE provider='google'"
                ).fetchone()
            if row:
                access_token = row["access_token"]
                refresh_token = row["refresh_token"]
        except Exception:
            pass

    if not access_token and not refresh_token:
        raise ValueError("Google non connecté. Configurez OAuth dans Paramètres > Connexions.")

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds)


async def execute_calendar_list(args: dict) -> dict:
    """Liste les événements Google Calendar pour une période donnée."""
    from datetime import datetime, timezone, timedelta
    calendar_id = _resolve_calendar_id(args.get("calendar_id"))
    days_ahead  = max(1, min(int(args.get("days", 7)), 90))
    max_results = max(1, min(int(args.get("max_results", 20)), 50))

    now = datetime.now(timezone.utc)

    # Support time_min custom (ex. 1er du mois envoyé par le calendrier frontend)
    raw_min = args.get("time_min", "")
    if raw_min:
        try:
            from dateutil import parser as dtparser
            time_min = dtparser.parse(raw_min).astimezone(timezone.utc).isoformat()
        except Exception:
            time_min = now.isoformat()
    else:
        time_min = now.isoformat()

    time_max = (now + timedelta(days=days_ahead)).isoformat()

    def _list_events(service):
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = []
        for e in events_result.get("items", []):
            start = e["start"].get("dateTime") or e["start"].get("date", "")
            end   = e["end"].get("dateTime")   or e["end"].get("date", "")
            events.append({
                "id":          e.get("id", ""),
                "title":       e.get("summary", "(Sans titre)"),
                "start":       start,
                "end":         end,
                "location":    e.get("location", ""),
                "description": (e.get("description", "") or "")[:300],
                "organizer":   e.get("organizer", {}).get("email", ""),
                "status":      e.get("status", ""),
                "colorId":     e.get("colorId", ""),
                "link":        e.get("htmlLink", ""),
            })
        return events

    def _fetch():
        # v2.137 — repli OAuth quand le compte de service renvoie 404 (l'agenda ciblé n'est
        # pas partagé avec l'e-mail du compte de service) : trouvé en auditant 60 échecs
        # historiques de calendar_list, tous ce même 404 sur calendars/<email>/events.
        # Sans repli, un utilisateur dont l'agenda n'a jamais été partagé avec le compte de
        # service voit TOUJOURS échouer calendar_list, alors qu'OAuth (s'il est configuré)
        # a un accès direct à ses propres agendas sans configuration supplémentaire.
        try:
            return _list_events(_get_google_calendar_service())
        except Exception as e:
            from googleapiclient.errors import HttpError
            _status = getattr(getattr(e, "resp", None), "status", None)
            if isinstance(e, HttpError) and _status == 404:
                try:
                    return _list_events(_get_google_calendar_service(prefer_oauth=True))
                except Exception:
                    pass
            raise

    try:
        loop = asyncio.get_running_loop()
        events = await loop.run_in_executor(None, _fetch)
        return {
            "success":     True,
            "calendar_id": calendar_id,
            "period_days": days_ahead,
            "count":       len(events),
            "events":      events,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_calendar_create(args: dict) -> dict:
    """Crée un événement dans Google Calendar."""
    title = args.get("title", "").strip()
    start = args.get("start", "").strip()    # ISO 8601 ou date YYYY-MM-DD
    end   = args.get("end",   "").strip()
    if not title:
        return {"error": "Paramètre 'title' requis."}
    if not start:
        return {"error": "Paramètre 'start' requis. Format : YYYY-MM-DDTHH:MM:SS ou YYYY-MM-DD."}

    location    = args.get("location", "")
    description = args.get("description", "")
    calendar_id = _resolve_calendar_id(args.get("calendar_id"))

    # Déterminer si c'est un événement toute-journée ou avec heure précise
    all_day = "T" not in start
    if not end:
        # v2.160 : 'start' mal formé (ex. valeur non-date) levait une ValueError non
        # rattrapée → 500 au lieu d'une erreur de validation propre.
        try:
            if all_day:
                # Toute la journée → fin = jour suivant
                from datetime import datetime, timedelta
                d = datetime.strptime(start, "%Y-%m-%d")
                end = (d + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                # 1 heure par défaut
                from datetime import datetime, timedelta
                d = datetime.fromisoformat(start)
                end = (d + timedelta(hours=1)).isoformat()
        except ValueError:
            return {"error": f"Date 'start' invalide : « {start} ». Format attendu : YYYY-MM-DDTHH:MM:SS ou YYYY-MM-DD."}

    def _create():
        service = _get_google_calendar_service()
        if all_day:
            event_body = {
                "summary": title,
                "start": {"date": start},
                "end": {"date": end},
            }
        else:
            event_body = {
                "summary": title,
                "start": {"dateTime": _norm_google_dt(start), "timeZone": "Europe/Paris"},
                "end":   {"dateTime": _norm_google_dt(end),   "timeZone": "Europe/Paris"},
            }
        if location:
            event_body["location"] = location
        if description:
            event_body["description"] = description
        # Rappel Google natif → notifie aussi sur le téléphone
        _rem = args.get("reminder_minutes")
        if _rem not in (None, ""):
            try:
                event_body["reminders"] = {"useDefault": False,
                                           "overrides": [{"method": "popup", "minutes": int(_rem)}]}
            except Exception:
                pass

        created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
        s_raw = created.get("start", {})
        e_raw = created.get("end",   {})
        return {
            "success":     True,
            "message":     f"Événement créé : « {title} »",
            "id":          created.get("id", ""),
            "event_id":    created.get("id", ""),
            "summary":     created.get("summary", title),
            "start":       {"dateTime": s_raw.get("dateTime"), "date": s_raw.get("date")} if s_raw else {"dateTime": start},
            "end":         {"dateTime": e_raw.get("dateTime"), "date": e_raw.get("date")} if e_raw else {"dateTime": end},
            "location":    created.get("location", location),
            "description": created.get("description", description),
            "htmlLink":    created.get("htmlLink", ""),
        }

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _create)
    except Exception as e:
        return {"error": str(e)}


async def execute_calendar_delete(args: dict) -> dict:
    """Supprime un événement Google Calendar par son ID."""
    event_id    = args.get("event_id", "").strip()
    calendar_id = _resolve_calendar_id(args.get("calendar_id"))
    if not event_id:
        return {"error": "Paramètre 'event_id' requis."}

    confirmed = args.get("confirmed", False)
    if not confirmed:
        return {
            "requiresConfirmation": True,
            "message": f"Supprimer l'événement Google Calendar ID «{event_id}» ?\n⚠️ Cette action est irréversible.",
        }

    def _delete():
        service = _get_google_calendar_service()
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return {"success": True, "message": f"Événement {event_id} supprimé du calendrier."}

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _delete)
    except Exception as e:
        return {"error": str(e)}


async def execute_calendar_update(args: dict) -> dict:
    """Met à jour un événement Google Calendar existant."""
    event_id    = args.get("event_id", "").strip()
    calendar_id = _resolve_calendar_id(args.get("calendar_id"))
    if not event_id:
        return {"error": "Paramètre 'event_id' requis."}

    # Champs optionnels à mettre à jour
    title       = args.get("title")
    start       = args.get("start")
    end         = args.get("end")
    description = args.get("description")
    location    = args.get("location")

    def _update():
        service = _get_google_calendar_service()
        # Récupérer l'événement existant
        existing = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        if title       is not None: existing["summary"]     = title
        if description is not None: existing["description"] = description
        if location    is not None: existing["location"]    = location

        if start is not None:
            if "T" in str(start).replace(" ", "T"):
                existing["start"] = {"dateTime": _norm_google_dt(start), "timeZone": "Europe/Paris"}
            else:
                existing["start"] = {"date": start}
        if end is not None:
            if "T" in str(end).replace(" ", "T"):
                existing["end"] = {"dateTime": _norm_google_dt(end), "timeZone": "Europe/Paris"}
            else:
                existing["end"] = {"date": end}

        updated = service.events().update(
            calendarId=calendar_id, eventId=event_id, body=existing
        ).execute()

        return {
            "id":          updated.get("id"),
            "title":       updated.get("summary", ""),
            "start":       updated.get("start", {}),
            "end":         updated.get("end", {}),
            "description": updated.get("description", ""),
            "location":    updated.get("location", ""),
            "colorId":     updated.get("colorId"),
            "success":     True,
            "message":     f"Événement «{updated.get('summary')}» mis à jour.",
        }

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _update)
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9B — Google Drive
# ══════════════════════════════════════════════════════════════════════════════

def _get_google_drive_service():
    """Construit le service Google Drive depuis les credentials stockés."""
    import credentials_manager as cm
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    access_token = cm.get_credential("google_access_token")
    refresh_token = cm.get_credential("google_refresh_token")
    client_id = cm.get_credential("google_client_id")
    client_secret = cm.get_credential("google_client_secret")

    if not access_token and not refresh_token:
        raise ValueError("Google non connecté. Configurez OAuth dans Paramètres > Connexions.")

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds)


async def execute_google_drive_list(args: dict) -> dict:
    """Liste les fichiers Google Drive."""
    folder_id = args.get("folder_id", "root")
    max_results = args.get("max_results", 30)
    query = args.get("query", "")
    try:
        service = _get_google_drive_service()
        q = f"'{folder_id}' in parents and trashed=false"
        if query:
            # Escape single quotes in query for Google Drive API query language
            safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
            q += f" and name contains '{safe_query}'"
        results = service.files().list(
            q=q,
            pageSize=max_results,
            fields="files(id, name, mimeType, size, modifiedTime, parents)",
        ).execute()
        files = results.get("files", [])
        for f in files:
            f["type"] = "dossier" if f["mimeType"] == "application/vnd.google-apps.folder" else "fichier"
        return {"success": True, "count": len(files), "files": files}
    except Exception as e:
        return {"error": str(e)}


async def execute_google_drive_read(args: dict) -> dict:
    """Lit le contenu d'un fichier Google Drive (Docs → texte, autres → téléchargement)."""
    file_id = args.get("file_id", "")
    if not file_id:
        return {"error": "file_id requis"}
    try:
        service = _get_google_drive_service()
        meta = service.files().get(fileId=file_id, fields="name,mimeType").execute()
        mime = meta.get("mimeType", "")
        name = meta.get("name", "")
        if mime == "application/vnd.google-apps.document":
            resp = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            return {"success": True, "name": name, "content": resp.decode("utf-8", errors="replace")[:50000]}
        elif mime == "application/vnd.google-apps.spreadsheet":
            resp = service.files().export(fileId=file_id, mimeType="text/csv").execute()
            return {"success": True, "name": name, "content": resp.decode("utf-8", errors="replace")[:50000]}
        else:
            return {"error": f"Type de fichier non supporté pour la lecture directe : {mime}. Utilisez le téléchargement."}
    except Exception as e:
        return {"error": str(e)}


async def execute_google_drive_upload(args: dict) -> dict:
    """Téléverse un fichier local vers Google Drive."""
    local_path = _resolve_path(args.get("local_path", ""))
    folder_id = args.get("folder_id", "root")
    file_name = args.get("file_name", "")
    if not local_path:
        return {"error": "local_path requis"}
    try:
        from googleapiclient.http import MediaFileUpload
        service = _get_google_drive_service()
        p = Path(local_path)
        if not p.exists():
            return {"error": f"Fichier introuvable : {local_path}"}
        name = file_name or p.name
        media = MediaFileUpload(str(p), resumable=True)
        meta = {"name": name, "parents": [folder_id]}
        result = service.files().create(body=meta, media_body=media, fields="id,name,webViewLink").execute()
        return {"success": True, "message": f"Fichier téléversé : {name}", "file_id": result["id"], "link": result.get("webViewLink", "")}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — Microsoft OneDrive
# ══════════════════════════════════════════════════════════════════════════════

async def _get_ms_token() -> str:
    """Obtient un access token Microsoft valide (refresh si nécessaire)."""
    import credentials_manager as cm
    import httpx

    access_token = cm.get_credential("ms_access_token")
    refresh_token = cm.get_credential("ms_refresh_token")
    client_id = cm.get_credential("ms_client_id")
    client_secret = cm.get_credential("ms_client_secret")
    tenant_id = cm.get_credential("ms_tenant_id") or "common"

    if not access_token and not refresh_token:
        raise ValueError("Microsoft non connecté. Configurez OAuth dans Paramètres > Connexions.")

    # Si access_token disponible, l'utiliser directement
    if access_token:
        return access_token

    # Rafraîchir le token
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret or "",
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        new_token = data["access_token"]
        cm.set_credential("ms_access_token", new_token)
        if "refresh_token" in data:
            cm.set_credential("ms_refresh_token", data["refresh_token"])
        return new_token


async def execute_onedrive_list(args: dict) -> dict:
    """Liste les fichiers OneDrive."""
    folder_id = args.get("folder_id", "root")
    max_results = args.get("max_results", 30)
    query = args.get("query", "")
    try:
        import httpx
        token = await _get_ms_token()
        headers = {"Authorization": f"Bearer {token}"}
        if query:
            from urllib.parse import quote
            url = f"https://graph.microsoft.com/v1.0/me/drive/root/search(q='{quote(query, safe='')}')"
            params = {"$top": max_results}
        else:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
            params = {"$top": max_results}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
        items = data.get("value", [])
        result = []
        for item in items:
            result.append({
                "id": item["id"],
                "name": item["name"],
                "type": "dossier" if "folder" in item else "fichier",
                "size": item.get("size", 0),
                "modified": item.get("lastModifiedDateTime", ""),
                "web_url": item.get("webUrl", ""),
            })
        return {"success": True, "count": len(result), "files": result}
    except Exception as e:
        return {"error": str(e)}


async def execute_onedrive_read(args: dict) -> dict:
    """Lit le contenu d'un fichier OneDrive texte."""
    file_id = args.get("file_id", "")
    if not file_id:
        return {"error": "file_id requis"}
    try:
        import httpx
        token = await _get_ms_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/content",
                headers=headers, follow_redirects=True,
            )
            resp.raise_for_status()
        content = resp.text[:50000] if resp.headers.get("content-type", "").startswith("text/") else None
        if content is None:
            return {"error": "Contenu binaire non supporté pour lecture directe."}
        return {"success": True, "content": content}
    except Exception as e:
        return {"error": str(e)}


async def execute_onedrive_upload(args: dict) -> dict:
    """Téléverse un fichier local vers OneDrive."""
    local_path = _resolve_path(args.get("local_path", ""))
    dest_path = args.get("dest_path", "")  # ex: "Documents/rapport.pdf"
    if not local_path:
        return {"error": "local_path requis"}
    try:
        import httpx
        token = await _get_ms_token()
        headers = {"Authorization": f"Bearer {token}"}
        p = Path(local_path)
        if not p.exists():
            return {"error": f"Fichier introuvable : {local_path}"}
        name = dest_path or p.name
        with open(str(p), "rb") as f:
            data = f.read()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(
                f"https://graph.microsoft.com/v1.0/me/drive/root:/{name}:/content",
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=data,
            )
            resp.raise_for_status()
            result = resp.json()
        return {"success": True, "message": f"Fichier téléversé : {name}", "file_id": result.get("id", ""), "web_url": result.get("webUrl", "")}
    except Exception as e:
        return {"error": str(e)}


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
    """Liste les VRAIS bugs récents (exceptions Python avec traceback complet, capturées
    automatiquement dès qu'un outil ou une route plante) — pour un audit/débogage a posteriori,
    typiquement après une période d'usage sans supervision. Différent de pc_tool_reliability
    (qui trace les TAUX d'échec) : ceci donne le détail exploitable de chaque crash individuel."""
    limit = max(1, min(int(args.get("limit", 20)), 100))
    kind = args.get("kind")  # 'tool_exception' | 'http_exception' | None (tous)
    import bug_log as _bug_log
    bugs = _bug_log.recent(limit=limit, kind=kind)
    return {
        "success": True,
        "count": len(bugs),
        "bugs": bugs,
        "note": "Chaque entrée a un traceback complet dans son champ 'traceback' — lis-le avant de proposer un correctif." if bugs else "Aucun bug enregistré sur la période.",
    }










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

async def _glpi_request(method: str, endpoint: str, json_body: dict = None, params: dict = None) -> dict:
    """Appel GLPI REST API — ouvre/ferme une session à chaque appel (simple et robuste plutôt
    que de gérer un cache de session_token entre requêtes, le volume d'appels reste faible).
    Credentials lues via credentials_manager (jamais tapées en dur) : glpi_url, glpi_app_token,
    glpi_user_token — configurables dans Réglages > Connexions, comme les autres clés API."""
    import credentials_manager as cm
    base_url = (cm.get_credential("glpi_url") or "").rstrip("/")
    app_token = cm.get_credential("glpi_app_token") or ""
    user_token = cm.get_credential("glpi_user_token") or ""
    if not base_url or not app_token or not user_token:
        return {"error": (
            "GLPI non configuré. Il faut renseigner glpi_url, glpi_app_token et glpi_user_token "
            "dans Réglages > Connexions (générés depuis GLPI : Configuration > Générale > API, "
            "puis Préférences utilisateur > Clé d'accès à distance)."
        )}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            init = await client.get(
                f"{base_url}/apirest.php/initSession",
                headers={"Authorization": f"user_token {user_token}", "App-Token": app_token},
            )
            if init.status_code != 200:
                return {"error": f"Connexion GLPI échouée (HTTP {init.status_code}) : {init.text[:200]}"}
            session_token = init.json().get("session_token")
            headers = {"Session-Token": session_token, "App-Token": app_token}
            resp = await client.request(method, f"{base_url}/apirest.php/{endpoint}",
                                         headers=headers, json=json_body, params=params)
            data = resp.json() if resp.content else {}
            await client.get(f"{base_url}/apirest.php/killSession", headers=headers)
            if resp.status_code >= 400:
                return {"error": f"GLPI a refusé la requête (HTTP {resp.status_code}) : {str(data)[:300]}"}
            return {"success": True, "data": data}
    except Exception as e:
        return {"error": f"Erreur de connexion à GLPI : {e}"}


_ITSM_BACKENDS = {"glpi"}  # systèmes réellement implémentés — étendre ici + ajouter le backend


async def execute_itsm_ticket_list(args: dict) -> dict:
    """Liste les tickets d'un système ITSM/ticketing connecté (GLPI pour l'instant — architecture
    prête pour d'autres produits). Utilise ceci pour voir les tickets ouverts/en cours."""
    system = (args.get("system") or "glpi").lower()
    if system not in _ITSM_BACKENDS:
        return {"error": f"Système '{system}' pas encore implémenté (disponibles : {', '.join(sorted(_ITSM_BACKENDS))})."}
    limit = max(1, min(int(args.get("limit", 20)), 100))
    r = await _glpi_request("GET", "Ticket", params={"range": f"0-{limit - 1}"})
    if r.get("error"):
        return r
    tickets = r["data"] if isinstance(r["data"], list) else []
    return {
        "success": True, "system": system, "count": len(tickets),
        "tickets": [
            {"id": t.get("id"), "title": t.get("name"), "status": t.get("status"),
             "urgency": t.get("urgency"), "date": t.get("date")}
            for t in tickets
        ],
    }


async def execute_itsm_ticket_create(args: dict) -> dict:
    """Crée un ticket dans un système ITSM/ticketing connecté (GLPI pour l'instant). Confirme
    toujours le contenu avec l'utilisateur avant d'appeler — action visible pour d'autres
    personnes (technicien assigné, demandeur)."""
    system = (args.get("system") or "glpi").lower()
    if system not in _ITSM_BACKENDS:
        return {"error": f"Système '{system}' pas encore implémenté (disponibles : {', '.join(sorted(_ITSM_BACKENDS))})."}
    title = args.get("title", "").strip()
    description = args.get("description", "").strip()
    if not title:
        return {"error": "Paramètre 'title' requis."}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True,
                "message": f"Créer un ticket {system.upper()} — « {title} » ?\n\n{description[:300]}"}
    urgency = args.get("urgency")  # 1 (très basse) à 5 (très haute), GLPI
    payload = {"input": {"name": title, "content": description}}
    if urgency:
        payload["input"]["urgency"] = int(urgency)
    r = await _glpi_request("POST", "Ticket", json_body=payload)
    if r.get("error"):
        return r
    ticket_id = r["data"].get("id") if isinstance(r["data"], dict) else None
    return {"success": True, "system": system, "ticket_id": ticket_id, "message": f"Ticket créé (#{ticket_id})."}


async def execute_itsm_asset_list(args: dict) -> dict:
    """Liste les postes/matériel enregistrés dans l'inventaire d'un système ITSM (GLPI pour
    l'instant) — complète `pc_hardware_specs`/`net_inventory_list` (données Marvin locales) avec
    la vue « déjà déclarée dans l'outil de gestion de parc »."""
    system = (args.get("system") or "glpi").lower()
    if system not in _ITSM_BACKENDS:
        return {"error": f"Système '{system}' pas encore implémenté (disponibles : {', '.join(sorted(_ITSM_BACKENDS))})."}
    limit = max(1, min(int(args.get("limit", 50)), 200))
    r = await _glpi_request("GET", "Computer", params={"range": f"0-{limit - 1}"})
    if r.get("error"):
        return r
    computers = r["data"] if isinstance(r["data"], list) else []
    return {
        "success": True, "system": system, "count": len(computers),
        "assets": [{"id": c.get("id"), "name": c.get("name"), "serial": c.get("serial")} for c in computers],
    }


async def execute_skill_learning_log(args: dict) -> dict:
    """Introspection : ce que Marvin a appris récemment (créations/améliorations de
    compétences après échec ou succès, consolidations automatiques — y compris la
    consolidation nocturne). Utilise ceci quand l'utilisateur demande ce que Marvin a
    appris, pourquoi une compétence a changé, ou pour vérifier que l'apprentissage marche."""
    import skills as _sk
    skill_name = (args.get("skill") or "").strip() or None
    limit = int(args.get("limit", 10))
    summary = _sk.get_learning_log_for_llm(skill_name=skill_name, limit=limit)
    return {"success": True, "summary": summary, "log": _sk.get_learning_log(limit=limit, skill_name=skill_name)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION OCR — Extraction de texte par vision (llava-phi3)
# ══════════════════════════════════════════════════════════════════════════════

async def execute_logo_generate(args: dict) -> dict:
    """Génère un logo localement (GPU, sd-turbo) à partir d'une description, l'enregistre
    dans data/logos/ et le référence en base pour réutilisation future (logo_list). Né d'un
    échec réel : sans cet outil, le seul recours était d'écrire du code System.Drawing à la
    main via PowerShell -- fragile et lent. Jamais de génération d'image via un shell."""
    name = (args.get("name") or "logo").strip()
    prompt = (args.get("prompt") or args.get("description") or "").strip()
    if not prompt:
        return {"error": "Paramètre 'prompt' requis (description visuelle du logo à générer)."}
    size = int(args.get("size") or 512)

    import local_image as _limg
    import uuid as _uuid
    from config import DATA_DIR as _DATA_DIR
    avail = _limg.is_available()
    if not avail["ok"]:
        return {"error": avail["reason"]}

    slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "logo"
    out_path = str(Path(_DATA_DIR) / "logos" / f"{slug}-{_uuid.uuid4().hex[:8]}.png")

    result = await asyncio.to_thread(_limg.generate_logo_image, prompt, out_path, size)
    if not result.get("success"):
        return {"error": result.get("error", "Échec de la génération d'image.")}

    db.create_logo(name, prompt, result["path"])
    return {
        "success": True,
        "message": f"Logo généré en {result['generation_seconds']}s ({result['device']}) : {result['path']}",
        "path": result["path"],
        "name": name,
    }


async def execute_logo_list(args: dict) -> dict:
    """Liste les logos déjà générés (nom, prompt, chemin) — à consulter avant d'en régénérer
    un pour un client/contexte déjà rencontré, pour réutiliser au lieu de dupliquer."""
    limit = int(args.get("limit") or 50)
    logos = db.list_logos(limit=limit)
    return {
        "success": True,
        "count": len(logos),
        "logos": [{"id": l["id"], "name": l["name"], "prompt": l.get("prompt", ""),
                   "path": l["path"], "created_at": l.get("created_at")} for l in logos],
    }




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


async def execute_email_accounts(args: dict) -> dict:
    """Liste les boîtes mail connectées (multi-comptes). Utile pour savoir lesquelles cibler."""
    accts = _list_email_accounts()
    if not accts:
        return {"success": True, "count": 0, "accounts": [],
                "message": "Aucune boîte mail configurée. Allez dans Paramètres > Email."}
    return {"success": True, "count": len(accts), "accounts": accts,
            "default": accts[0]["username"],
            "message": f"{len(accts)} boîte(s) connectée(s) : " + ", ".join(a["username"] for a in accts)}


async def execute_email_list(args: dict) -> dict:
    """Liste les emails récents de la boîte de réception."""
    cfg = _get_email_cfg(args.get("account"))
    if not cfg:
        return {"error": "Email non configuré. Allez dans Paramètres > Email pour configurer votre boîte."}
    folder = args.get("folder", "INBOX")
    limit = max(1, min(int(args.get("limit", 20)), 50))
    offset = int(args.get("offset", 0))
    try:
        import email_manager as _em
        loop = asyncio.get_running_loop()
        emails = await loop.run_in_executor(None, lambda: _em.fetch_inbox(
            cfg["imap_host"], int(cfg.get("imap_port", 993)),
            cfg["username"], cfg["password"],
            folder=folder, limit=limit, offset=offset,
        ))
        return {"success": True, "folder": folder, "count": len(emails), "emails": emails}
    except Exception as e:
        return {"error": str(e)}


async def execute_email_read(args: dict) -> dict:
    """Lit le contenu complet d'un email par son UID."""
    cfg = _get_email_cfg(args.get("account"))
    if not cfg:
        return {"error": "Email non configuré."}
    uid = str(args.get("uid", "")).strip()
    if not uid:
        return {"error": "Paramètre 'uid' requis."}
    folder = args.get("folder", "INBOX")
    try:
        import email_manager as _em
        loop = asyncio.get_running_loop()
        msg = await loop.run_in_executor(None, lambda: _em.fetch_email(
            cfg["imap_host"], int(cfg.get("imap_port", 993)),
            cfg["username"], cfg["password"],
            uid=uid, folder=folder,
        ))
        return {"success": True, "email": msg}
    except Exception as e:
        return {"error": str(e)}


async def execute_email_search(args: dict) -> dict:
    """Recherche des emails par sujet, expéditeur ou mot-clé."""
    cfg = _get_email_cfg(args.get("account"))
    if not cfg:
        return {"error": "Email non configuré."}
    query = args.get("query", "").strip()
    if not query:
        return {"error": "Paramètre 'query' requis."}
    folder = args.get("folder", "INBOX")
    limit = max(1, min(int(args.get("limit", 20)), 50))
    try:
        import email_manager as _em
        loop = asyncio.get_running_loop()
        emails = await loop.run_in_executor(None, lambda: _em.search_emails(
            cfg["imap_host"], int(cfg.get("imap_port", 993)),
            cfg["username"], cfg["password"],
            query=query, folder=folder, limit=limit,
        ))
        return {"success": True, "query": query, "count": len(emails), "emails": emails}
    except Exception as e:
        return {"error": str(e)}


async def execute_email_send(args: dict) -> dict:
    """Envoie un email via SMTP."""
    cfg = _get_email_cfg(args.get("account"))
    if not cfg:
        return {"error": "Email non configuré."}
    to = args.get("to", "").strip()
    subject = args.get("subject", "").strip()
    body = args.get("body", "").strip()
    # Clarification (anti-erreur) : ne jamais deviner un envoi incomplet → demander
    if not to:
        return {"needsClarification": True, "message": "Il me manque le destinataire. À qui dois-je envoyer ce mail ?"}
    if not subject:
        return {"needsClarification": True, "message": "Quel doit être l'objet de ce mail ?"}
    if not body:
        return {"needsClarification": True, "message": "Que dois-je écrire dans le corps du mail ?"}
    if not args.get("confirmed"):
        return {"requiresConfirmation": True, "message": f"Envoyer l'email à {to} — Objet : {subject} ?\n\n{body[:300]}"}
    cc = args.get("cc", "")
    try:
        import email_manager as _em
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: _em.send_email(
            cfg.get("smtp_host", cfg["imap_host"].replace("imap.", "smtp.")),
            int(cfg.get("smtp_port", 587)),
            cfg["username"], cfg["password"],
            to=to, subject=subject, body=body, cc=cc,
            reply_to=args.get("reply_to", ""),
            in_reply_to=args.get("in_reply_to", ""),
            references=args.get("references", ""),
            auto_submitted=bool(args.get("auto_submitted", False)),
        ))
        return {"success": True, "message": f"Email envoyé à {to}", "detail": result}
    except Exception as e:
        return {"error": str(e)}


async def execute_email_draft_reply(args: dict) -> dict:
    """✨ Rédige par IA la meilleure réponse à un email, en français impeccable (sans fautes).
    Fournir 'uid' (l'email sera lu automatiquement) OU le contenu ('body'/'subject'/'from').
    'instruction' = consigne libre (ex : 'accepte poliment', 'demande un délai d'une semaine')."""
    account = args.get("account")
    original = (args.get("body") or "").strip()
    subject = (args.get("subject") or "").strip()
    sender = (args.get("from") or args.get("from_addr") or "").strip()
    # Lire l'email depuis la boîte si seul l'uid est fourni
    uid = str(args.get("uid", "")).strip()
    if uid and not original:
        cfg = _get_email_cfg(account)
        if not cfg:
            return {"error": "Email non configuré."}
        try:
            import email_manager as _em
            loop = asyncio.get_running_loop()
            msg = await loop.run_in_executor(None, lambda: _em.fetch_email(
                cfg["imap_host"], int(cfg.get("imap_port", 993)),
                cfg["username"], cfg["password"],
                uid=uid, folder=args.get("folder", "INBOX")))
            original = (msg.get("body") or msg.get("text") or "").strip()
            subject = subject or (msg.get("subject") or "")
            sender = sender or (msg.get("from") or msg.get("from_addr") or "")
        except Exception as e:
            return {"error": f"Lecture de l'email impossible : {e}"}
    if not original:
        return {"error": "Aucun contenu à traiter : fournir 'uid' (email à lire) ou 'body'."}

    instruction = (args.get("instruction") or args.get("intent") or "").strip()
    tone = args.get("tone") or "professionnel, clair et courtois"
    lang = args.get("language") or "français"
    signature = args.get("signature") or ""
    prompt = (
        f"Tu es un assistant expert en rédaction d'emails. Rédige LA meilleure réponse à l'email ci-dessous, "
        f"en {lang}, dans un style {tone}, avec une orthographe et une grammaire IRRÉPROCHABLES (zéro faute). "
        f"Structure : formule d'appel adaptée, corps clair et bien tourné, formule de politesse finale. "
        f"Réponds UNIQUEMENT avec le corps de l'email (pas d'objet, pas d'explication, pas de balises).\n\n"
        f"=== EMAIL REÇU ===\nDe : {sender or '(inconnu)'}\nObjet : {subject or '(sans objet)'}\n\n{original[:5000]}\n\n"
    )
    if instruction:
        prompt += f"=== CONSIGNE pour ta réponse ===\n{instruction}\n\n"
    if signature:
        prompt += f"Termine par cette signature :\n{signature}\n\n"
    prompt += "=== TA RÉPONSE (corps de l'email uniquement) ==="
    try:
        draft = await _ollama_generate(prompt, model=args.get("model"), timeout=180)
        draft = (draft or "").strip()
        if not draft:
            return {"error": "L'IA n'a pas produit de réponse. Réessayez."}
        re_subject = subject if subject.lower().startswith("re:") else (f"Re: {subject}" if subject else "Re:")
        return {"success": True, "draft": draft, "to": sender, "subject": re_subject,
                "account": account, "message": "Brouillon de réponse généré."}
    except Exception as e:
        return _net_error(e, "rédaction IA") if "_net_error" in globals() else {"error": str(e)}


async def execute_email_summarize(args: dict) -> dict:
    """📝 Résume un email par IA en français : synthèse, points clés, action attendue.
    Fournir 'uid' (lecture auto) OU le contenu ('body')."""
    account = args.get("account")
    original = (args.get("body") or "").strip()
    subject = (args.get("subject") or "").strip()
    sender = (args.get("from") or args.get("from_addr") or "").strip()
    uid = str(args.get("uid", "")).strip()
    if uid and not original:
        cfg = _get_email_cfg(account)
        if not cfg:
            return {"error": "Email non configuré."}
        try:
            import email_manager as _em
            loop = asyncio.get_running_loop()
            msg = await loop.run_in_executor(None, lambda: _em.fetch_email(
                cfg["imap_host"], int(cfg.get("imap_port", 993)), cfg["username"], cfg["password"],
                uid=uid, folder=args.get("folder", "INBOX")))
            original = (msg.get("body") or msg.get("text") or "").strip()
            subject = subject or (msg.get("subject") or "")
            sender = sender or (msg.get("from") or "")
        except Exception as e:
            return {"error": f"Lecture de l'email impossible : {e}"}
    if not original:
        return {"error": "Aucun contenu à résumer : fournir 'uid' ou 'body'."}
    prompt = (
        "Résume cet email en français, de manière concise et claire. Donne exactement :\n"
        "**Résumé** : 2-3 phrases.\n**Points clés** : 2 à 4 puces.\n"
        "**Action attendue** : ce que je dois faire (ou « Aucune action requise »).\n"
        "N'invente rien, base-toi uniquement sur le contenu.\n\n"
        f"De : {sender or '(inconnu)'}\nObjet : {subject or '(sans objet)'}\n\n{original[:6000]}"
    )
    try:
        summary = await _ollama_generate(prompt, model=args.get("model"), timeout=180)
        return {"success": True, "summary": (summary or "").strip(),
                "subject": subject, "from": sender, "message": "Résumé généré."}
    except Exception as e:
        return _net_error(e, "résumé IA") if "_net_error" in globals() else {"error": str(e)}


async def execute_email_digest(args: dict) -> dict:
    """🧠 Briefing IA de la boîte : scanne les emails récents et les PRIORISE (urgent/à traiter/info).
    account = adresse d'une boîte, ou '__all__' pour toutes."""
    account = args.get("account")
    limit = max(3, min(int(args.get("limit", 15)), 25))
    folder = args.get("folder", "INBOX")
    try:
        import email_manager as _em
        loop = asyncio.get_running_loop()

        def _fetch(cfg):
            ems = _em.fetch_inbox(cfg["imap_host"], int(cfg.get("imap_port", 993)),
                                  cfg["username"], cfg["password"], folder=folder, limit=limit, offset=0)
            for e in ems:
                e["_account"] = cfg["username"]
            return ems

        if account == "__all__":
            emails = []
            for a in _all_email_cfgs():
                try:
                    emails += await loop.run_in_executor(None, lambda a=a: _fetch(a))
                except Exception:
                    continue
        else:
            cfg = _get_email_cfg(account)
            if not cfg:
                return {"error": "Email non configuré."}
            emails = await loop.run_in_executor(None, lambda: _fetch(cfg))

        if not emails:
            return {"success": True, "digest": "Aucun email récent à analyser.", "count": 0}
        emails.sort(key=lambda e: e.get("date") or "", reverse=True)
        emails = emails[:limit]
        lignes = []
        for i, e in enumerate(emails, 1):
            box = f" [{e.get('_account')}]" if account == "__all__" else ""
            lignes.append(f"{i}. De : {e.get('from','?')} | Objet : {e.get('subject','(sans objet)')}{box}")
        prompt = (
            "Tu es mon assistant. Voici la liste de mes emails récents. Fais-moi un BRIEFING en français :\n"
            "- Classe-les par priorité avec une pastille : 🔴 (urgent / à traiter vite), 🟡 (à traiter), ⚪ (info / promo / newsletter).\n"
            "- Pour chaque email important, UNE ligne très courte : qui, de quoi, et l'action suggérée.\n"
            "- Regroupe les ⚪ peu importants en une seule ligne à la fin.\n"
            "- Termine par : « 👉 À TRAITER EN PRIORITÉ : … ».\n"
            "Sois synthétique et concret.\n\n=== EMAILS ===\n" + "\n".join(lignes)
        )
        digest = await _ollama_generate(prompt, model=args.get("model"), timeout=180)
        return {"success": True, "digest": (digest or "").strip(), "count": len(emails),
                "message": f"Briefing de {len(emails)} email(s) généré."}
    except Exception as e:
        return _net_error(e, "briefing IA") if "_net_error" in globals() else {"error": str(e)}


# ─────────────── Assistant email AUTOMATIQUE : 3 modes (v2.41) ───────────────
_AUTO_NEVER_FROM = ["noreply", "no-reply", "no_reply", "do-not-reply", "donotreply",
                    "notification", "notifications", "newsletter", "mailer-daemon",
                    "postmaster", "bounce", "automated", "automatique", "ne-pas-repondre"]
_AUTO_SKIP_KEYWORDS = ["banque", "bank", "mot de passe", "password", "sécurité", "securite",
                       "security", "virement", "carte bancaire", "iban", "rib", "facture impayée",
                       "code de vérification", "verification code", "2fa", "otp", "litige", "juridique"]


def _email_automation_cfg() -> dict:
    """Config de l'assistant email automatique (avec valeurs par défaut sûres)."""
    import json as _json
    cfg = db.get_setting("email_automation")
    if isinstance(cfg, str):
        try:
            cfg = _json.loads(cfg)
        except Exception:
            cfg = None
    if not isinstance(cfg, dict):
        cfg = {}
    profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    return {
        "mode": cfg.get("mode", "manuel"),                    # manuel | brouillon | autonome
        "accounts": cfg.get("accounts") or [],                # sélection explicite recommandée
        "instructions": cfg.get("instructions", ""),
        "tone": cfg.get("tone", "professionnel, clair et courtois"),
        "signature": cfg.get("signature", ""),
        "only_from": [s.lower().strip() for s in (cfg.get("only_from") or []) if s.strip()],
        "never_from": [s.lower().strip() for s in (cfg.get("never_from") or []) if s.strip()],
        "skip_keywords": [s.lower().strip() for s in (cfg.get("skip_keywords") or []) if s.strip()],
        "max_per_run": int(cfg.get("max_per_run", 5)),
        "send_delay_min": max(1, min(int(cfg.get("send_delay_min", 5)), 1440)),
        "scheduler_enabled": bool(cfg.get("scheduler_enabled", False)),
        "interval_min": max(2, min(int(cfg.get("interval_min", 5)), 1440)),
        "profiles": profiles,
    }


def _email_effective_profile(cfg: dict, account: str) -> dict:
    """Fusionne le profil global et les exceptions propres à une boîte."""
    override = cfg.get("profiles", {}).get(account, {})
    if not isinstance(override, dict):
        override = {}
    result = {key: cfg[key] for key in (
        "mode", "instructions", "tone", "signature", "only_from", "never_from",
        "skip_keywords", "max_per_run", "send_delay_min"
    )}
    for key, value in override.items():
        if key in result:
            result[key] = value
    result["only_from"] = [str(item).lower().strip() for item in (result.get("only_from") or []) if str(item).strip()]
    result["never_from"] = [str(item).lower().strip() for item in (result.get("never_from") or []) if str(item).strip()] + _AUTO_NEVER_FROM
    result["skip_keywords"] = [str(item).lower().strip() for item in (result.get("skip_keywords") or []) if str(item).strip()] + _AUTO_SKIP_KEYWORDS
    result["max_per_run"] = max(1, min(int(result.get("max_per_run", 5)), 100))
    result["send_delay_min"] = max(1, min(int(result.get("send_delay_min", 5)), 1440))
    return result


async def execute_email_automation_run(args: dict) -> dict:
    """⚙️ Traite les emails non lus selon le mode configuré :
    - manuel  : ne fait rien.
    - brouillon : prépare des réponses (à valider, rien n'est envoyé).
    - autonome : ENVOIE les réponses automatiquement (selon le cadrage + garde-fous).
    dry_run=true simule sans envoyer (test sûr)."""
    from datetime import datetime as _dt
    cfg = _email_automation_cfg()
    mode = (args.get("mode") or cfg["mode"]).lower()
    dry_run = bool(args.get("dry_run", False))
    if mode == "manuel":
        return {"success": True, "mode": "manuel", "processed": 0, "sent": 0, "drafted": 0,
                "results": [], "message": "Mode manuel : aucune automatisation active."}

    import email_manager as _em
    loop = asyncio.get_running_loop()
    accts = [a for a in _all_email_cfgs() if (not cfg["accounts"] or a["username"] in cfg["accounts"])]
    if not accts:
        return {"error": "Aucune boîte mail configurée pour l'automatisation."}

    seen = set(db.get_setting("email_auto_seen") or [])
    results, sent, drafted_items = [], 0, []
    max_run = cfg["max_per_run"]

    for a in accts:
        if (sent + len(drafted_items)) >= max_run:
            break
        try:
            inbox = await loop.run_in_executor(None, lambda a=a: _em.fetch_inbox(
                a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                folder="INBOX", limit=15, offset=0))
        except Exception as e:
            results.append({"account": a["username"], "action": "erreur", "reason": str(e)})
            continue

        for e in inbox:
            if (sent + len(drafted_items)) >= max_run:   # plafond global (brouillon ET autonome)
                break
            uid = str(e.get("id") or e.get("uid") or "")
            key = f"{a['username']}:{uid}"
            if not uid or key in seen:
                continue
            if e.get("read"):       # on ne traite QUE les non-lus
                continue
            sender = (e.get("from") or "").lower()
            subject = (e.get("subject") or "")
            # ── Garde-fous (anti-erreur) ──
            reason = None
            if any(x in sender for x in cfg["never_from"]):
                reason = "expéditeur automatique/exclu"
            elif any(x in (subject.lower() + " " + sender) for x in cfg["skip_keywords"]):
                reason = "sujet sensible (jamais d'auto-réponse)"
            elif cfg["only_from"] and not any(x in sender for x in cfg["only_from"]):
                reason = "hors liste d'expéditeurs autorisés"
            if reason:
                results.append({"account": a["username"], "from": e.get("from"), "subject": subject,
                                "action": "ignoré", "reason": reason})
                seen.add(key)
                continue
            # ── Rédaction de la réponse (français impeccable) ──
            draft_res = await execute_email_draft_reply({
                "uid": uid, "account": a["username"], "folder": "INBOX",
                "instruction": cfg["instructions"], "tone": cfg["tone"], "signature": cfg["signature"]})
            if draft_res.get("error"):
                results.append({"account": a["username"], "subject": subject, "action": "erreur",
                                "reason": draft_res["error"]})
                continue
            draft, to, re_subj = draft_res["draft"], draft_res["to"], draft_res["subject"]
            if not to or len(draft.strip()) < 15:
                results.append({"account": a["username"], "subject": subject, "action": "ignoré",
                                "reason": "réponse vide ou destinataire manquant"})
                seen.add(key)
                continue

            if mode == "autonome" and not dry_run:
                send_res = await execute_email_send({"to": to, "subject": re_subj, "body": draft,
                                                     "account": a["username"], "confirmed": True})
                if send_res.get("success"):
                    sent += 1
                    results.append({"account": a["username"], "to": to, "subject": re_subj, "action": "envoyé"})
                    seen.add(key)
                else:
                    results.append({"account": a["username"], "to": to, "action": "échec envoi",
                                    "reason": send_res.get("error")})
            else:
                drafted_items.append({"account": a["username"], "to": to, "subject": re_subj,
                                      "body": draft, "from": e.get("from"), "original_subject": subject,
                                      "uid": uid, "created_at": _dt.now().isoformat(timespec="seconds")})
                results.append({"account": a["username"], "to": to, "subject": re_subj,
                                "action": "brouillon préparé" + (" (simulation)" if dry_run else "")})
                seen.add(key)

    db.set_setting("email_auto_seen", list(seen)[-800:])
    if drafted_items and not dry_run:
        existing = db.get_setting("email_pending_drafts") or []
        if isinstance(existing, str):
            import json as _json
            try: existing = _json.loads(existing)
            except Exception: existing = []
        db.set_setting("email_pending_drafts", (existing + drafted_items)[-100:])

    verb = "envoyée(s)" if mode == "autonome" else "préparée(s)"
    n = sent if mode == "autonome" else len(drafted_items)
    return {"success": True, "mode": mode, "dry_run": dry_run, "processed": len(results),
            "sent": sent, "drafted": len(drafted_items), "results": results[:60],
            "message": f"{n} réponse(s) {verb}" + (" (aucun envoi réel — simulation)" if dry_run else "") + "."}


_EMAIL_AUTOMATION_LOCK = asyncio.Lock()


async def execute_email_orchestrator_run(args: dict) -> dict:
    """Orchestrateur multiboîte équitable, idempotent et sans effet de bord en simulation."""
    from datetime import datetime as _dt
    from email.utils import parseaddr
    import email_manager as _em

    if _EMAIL_AUTOMATION_LOCK.locked():
        return {"error": "Une exécution des réponses automatiques est déjà en cours."}
    async with _EMAIL_AUTOMATION_LOCK:
        cfg = _email_automation_cfg()
        dry_run = bool(args.get("dry_run", False))
        forced_mode = (args.get("mode") or "").lower().strip()
        selected = [str(item).lower() for item in cfg.get("accounts", [])]
        if not selected:
            return {"error": "Sélectionne explicitement au moins une boîte pour l'automatisation."}

        accounts = [account for account in _all_email_cfgs()
                    if (account.get("username") or "").lower() in selected]
        if not accounts:
            return {"error": "Aucune des boîtes sélectionnées n'est disponible."}

        loop = asyncio.get_running_loop()

        async def fetch_headers(account):
            if account.get("_auth_error"):
                return account, [], account["_auth_error"]
            try:
                messages = await loop.run_in_executor(None, lambda: _em.fetch_inbox(
                    account["imap_host"], int(account.get("imap_port", 993)),
                    account["username"], account["password"], folder="INBOX", limit=30, offset=0))
                return account, messages, None
            except Exception as exc:
                return account, [], str(exc)

        fetched = await asyncio.gather(*(fetch_headers(account) for account in accounts))
        results = []
        queues = {}
        profiles = {}
        for account, messages, error in fetched:
            username = account["username"]
            profile = _email_effective_profile(cfg, username)
            if forced_mode:
                profile["mode"] = forced_mode
            profiles[username] = profile
            if error:
                results.append({"account": username, "action": "erreur", "reason": error})
            queues[username] = [message for message in messages if not message.get("read")]

        # Round-robin : aucune boîte ne peut monopoliser le passage.
        candidates = []
        per_account = {account["username"]: 0 for account in accounts}
        while any(queues.values()):
            progressed = False
            for account in accounts:
                username = account["username"]
                profile = profiles[username]
                if queues[username] and per_account[username] < profile["max_per_run"]:
                    candidates.append((account, queues[username].pop(0), profile))
                    per_account[username] += 1
                    progressed = True
            if not progressed:
                break

        raw_seen = db.get_setting("email_auto_seen") or []
        if isinstance(raw_seen, str):
            import json as _json
            try:
                raw_seen = _json.loads(raw_seen)
            except Exception:
                raw_seen = []
        seen = set(raw_seen if isinstance(raw_seen, list) else [])
        new_seen = set()
        pending_drafts = []
        pending_outbox = []
        sent = 0

        signatures = db.get_setting("email_signatures") or {}
        if isinstance(signatures, str):
            import json as _json
            try:
                signatures = _json.loads(signatures)
            except Exception:
                signatures = {}
        signatures = signatures if isinstance(signatures, dict) else {}

        for account, header, profile in candidates:
            username = account["username"]
            mode = str(profile.get("mode", "manuel")).lower()
            if mode == "manuel":
                continue
            uid = str(header.get("id") or header.get("uid") or "")
            stable_id = header.get("message_id") or uid
            key = f"{username.lower()}:{stable_id}"
            if not stable_id or key in seen:
                continue
            sender_header = header.get("from") or ""
            sender_address = parseaddr(sender_header)[1].lower() or sender_header.lower()
            subject = header.get("subject") or ""
            reason = None
            auto_submitted = (header.get("auto_submitted") or "").lower()
            precedence = (header.get("precedence") or "").lower()
            if auto_submitted and auto_submitted != "no":
                reason = "message déjà automatique"
            elif header.get("list_id") or precedence in {"bulk", "list", "junk"}:
                reason = "liste de diffusion ou message en masse"
            elif any(item in sender_address for item in profile["never_from"]):
                reason = "expéditeur automatique/exclu"
            elif any(item in (subject.lower() + " " + sender_address) for item in profile["skip_keywords"]):
                reason = "sujet sensible"
            elif mode in {"autonome", "differe"} and not profile["only_from"]:
                reason = "envoi automatique bloqué : liste d'expéditeurs autorisés vide"
            elif profile["only_from"] and not any(item in sender_address for item in profile["only_from"]):
                reason = "hors liste d'expéditeurs autorisés"
            if reason:
                results.append({"account": username, "from": sender_header, "subject": subject,
                                "action": "ignoré", "reason": reason})
                new_seen.add(key)
                continue

            try:
                message = await loop.run_in_executor(None, lambda: _em.fetch_email(
                    account["imap_host"], int(account.get("imap_port", 993)),
                    account["username"], account["password"], uid=uid, folder="INBOX",
                    mark_seen=not dry_run))
            except Exception as exc:
                results.append({"account": username, "subject": subject,
                                "action": "erreur", "reason": str(exc)})
                continue
            signature = profile.get("signature") or signatures.get(username, "")
            draft_result = await execute_email_draft_reply({
                "body": message.get("body", ""), "subject": subject,
                "from": message.get("reply_to") or sender_header,
                "instruction": profile.get("instructions", ""), "tone": profile.get("tone", ""),
                "signature": signature, "account": username,
            })
            if draft_result.get("error"):
                results.append({"account": username, "subject": subject,
                                "action": "erreur", "reason": draft_result["error"]})
                continue
            draft = (draft_result.get("draft") or "").strip()
            to = parseaddr(draft_result.get("to") or sender_header)[1]
            reply_subject = draft_result.get("subject") or (f"Re: {subject}")
            if not to or len(draft) < 15:
                results.append({"account": username, "subject": subject,
                                "action": "ignoré", "reason": "réponse ou destinataire invalide"})
                new_seen.add(key)
                continue

            references = " ".join(filter(None, [message.get("references"), message.get("message_id")])).strip()
            if dry_run:
                action = "envoi simulé" if mode in {"autonome", "differe"} else "brouillon simulé"
                results.append({"account": username, "to": to, "subject": reply_subject, "action": action})
                continue
            if mode == "autonome":
                send_result = await execute_email_send({
                    "to": to, "subject": reply_subject, "body": draft, "account": username,
                    "confirmed": True, "in_reply_to": message.get("message_id", ""),
                    "references": references, "auto_submitted": True,
                })
                if send_result.get("success"):
                    sent += 1
                    new_seen.add(key)
                    results.append({"account": username, "to": to, "subject": reply_subject,
                                    "action": "envoyé"})
                else:
                    results.append({"account": username, "to": to, "subject": reply_subject,
                                    "action": "échec envoi", "reason": send_result.get("error")})
            elif mode == "differe":
                from datetime import timedelta as _timedelta
                import uuid as _uuid
                now = _dt.now()
                pending_outbox.append({
                    "id": _uuid.uuid4().hex,
                    "account": username, "to": to, "subject": reply_subject, "body": draft,
                    "from": sender_header, "original_subject": subject, "uid": uid,
                    "message_id": message.get("message_id", ""), "references": references,
                    "created_at": now.isoformat(timespec="seconds"),
                    "send_after": (now + _timedelta(minutes=profile["send_delay_min"])).isoformat(timespec="seconds"),
                    "status": "pending",
                })
                new_seen.add(key)
                results.append({"account": username, "to": to, "subject": reply_subject,
                                "action": "envoi différé", "delay_min": profile["send_delay_min"]})
            else:
                pending_drafts.append({
                    "account": username, "to": to, "subject": reply_subject, "body": draft,
                    "from": sender_header, "original_subject": subject, "uid": uid,
                    "message_id": message.get("message_id", ""), "references": references,
                    "created_at": _dt.now().isoformat(timespec="seconds"),
                })
                new_seen.add(key)
                results.append({"account": username, "to": to, "subject": reply_subject,
                                "action": "brouillon préparé"})

        if not dry_run:
            db.set_setting("email_auto_seen", list(seen | new_seen)[-2000:])
            if pending_drafts:
                existing = db.get_setting("email_pending_drafts") or []
                if isinstance(existing, str):
                    import json as _json
                    try:
                        existing = _json.loads(existing)
                    except Exception:
                        existing = []
                db.set_setting("email_pending_drafts", ((existing if isinstance(existing, list) else []) + pending_drafts)[-200:])
            if pending_outbox:
                existing = db.get_setting("email_scheduled_outbox") or []
                if not isinstance(existing, list):
                    existing = []
                db.set_setting("email_scheduled_outbox", (existing + pending_outbox)[-200:])

        summary = {
            "at": _dt.now().isoformat(timespec="seconds"), "source": args.get("source", "manual"),
            "dry_run": dry_run, "processed": len(results), "sent": sent,
            "drafted": len(pending_drafts), "queued": len(pending_outbox),
            "errors": sum(1 for item in results if item["action"] in {"erreur", "échec envoi"}),
        }
        if not dry_run:
            history = db.get_setting("email_automation_runs") or []
            if not isinstance(history, list):
                history = []
            db.set_setting("email_automation_runs", (history + [summary])[-100:])
        return {
            "success": True, "dry_run": dry_run, "processed": len(results), "sent": sent,
            "drafted": len(pending_drafts), "queued": len(pending_outbox), "results": results[:100],
            "message": ("Simulation terminée sans aucune modification." if dry_run else
                        f"{sent} réponse(s) envoyée(s), {len(pending_drafts)} brouillon(s), {len(pending_outbox)} envoi(s) différé(s)."),
        }


_EMAIL_OUTBOX_LOCK = asyncio.Lock()


async def execute_email_outbox_flush() -> dict:
    """Envoie uniquement les réponses différées arrivées à échéance."""
    from datetime import datetime as _dt
    if _EMAIL_OUTBOX_LOCK.locked():
        return {"success": True, "sent": 0, "message": "File d'envoi déjà en cours."}
    async with _EMAIL_OUTBOX_LOCK:
        outbox = db.get_setting("email_scheduled_outbox") or []
        if not isinstance(outbox, list):
            outbox = []
        now = _dt.now()
        kept, sent, failed = [], 0, 0
        for item in outbox:
            if item.get("status", "pending") != "pending":
                kept.append(item)
                continue
            try:
                due = _dt.fromisoformat(item.get("send_after", "")) <= now
            except Exception:
                due = False
            if not due:
                kept.append(item)
                continue
            result = await execute_email_send({
                "to": item.get("to", ""), "subject": item.get("subject", ""),
                "body": item.get("body", ""), "account": item.get("account"),
                "confirmed": True, "in_reply_to": item.get("message_id", ""),
                "references": item.get("references", ""), "auto_submitted": True,
            })
            if result.get("success"):
                sent += 1
            else:
                failed += 1
                from datetime import timedelta as _timedelta
                kept.append({**item, "last_error": result.get("error", "Envoi impossible"),
                             "last_attempt_at": now.isoformat(timespec="seconds"),
                             "send_after": (now + _timedelta(minutes=5)).isoformat(timespec="seconds")})
        db.set_setting("email_scheduled_outbox", kept[-200:])
        return {"success": failed == 0, "sent": sent, "failed": failed, "pending": len(kept)}


async def execute_email_to_task(args: dict) -> dict:
    """✅ Transforme un email en TÂCHE actionnable (IA extrait l'action + l'échéance). Fournir 'uid' ou 'body'."""
    account = args.get("account")
    original = (args.get("body") or "").strip()
    subject = (args.get("subject") or "").strip()
    sender = (args.get("from") or "").strip()
    uid = str(args.get("uid", "")).strip()
    if uid and not original:
        cfg = _get_email_cfg(account)
        if not cfg:
            return {"error": "Email non configuré."}
        try:
            import email_manager as _em
            loop = asyncio.get_running_loop()
            msg = await loop.run_in_executor(None, lambda: _em.fetch_email(
                cfg["imap_host"], int(cfg.get("imap_port", 993)), cfg["username"], cfg["password"],
                uid=uid, folder=args.get("folder", "INBOX")))
            original = (msg.get("body") or msg.get("text") or "").strip()
            subject = subject or (msg.get("subject") or "")
            sender = sender or (msg.get("from") or "")
        except Exception as e:
            return {"error": f"Lecture de l'email impossible : {e}"}
    if not original and not subject:
        return {"error": "Aucun contenu : fournir 'uid' ou 'body'."}

    from datetime import date as _date
    today = _date.today().isoformat()
    prompt = (
        "À partir de cet email, définis UNE tâche à faire. Réponds UNIQUEMENT par un objet JSON valide "
        "(aucun texte autour), au format exact :\n"
        '{"title": "...", "description": "...", "priority": "low|medium|high", "due_date": "YYYY-MM-DD ou null"}\n'
        f"- title : court, actionnable, commence par un verbe (français).\n"
        f"- due_date : déduis l'échéance si l'email en mentionne une (aujourd'hui = {today}), sinon null.\n"
        "- priority : selon l'urgence/importance.\n\n"
        f"De : {sender}\nObjet : {subject}\n\n{original[:4000]}"
    )
    try:
        raw = await _ollama_generate(prompt, model=args.get("model"), timeout=180)
    except Exception as e:
        return _net_error(e, "extraction tâche IA") if "_net_error" in globals() else {"error": str(e)}
    # Extraction robuste du JSON
    import json as _json, re as _re2
    data = None
    m = _re2.search(r"\{.*\}", raw or "", _re2.DOTALL)
    if m:
        try:
            data = _json.loads(m.group(0))
        except Exception:
            data = None
    if not isinstance(data, dict):
        data = {"title": (subject or (raw or "").strip()[:80] or "Tâche depuis email")}
    title = str(data.get("title") or subject or "Tâche depuis email").strip()[:200]
    prio = str(data.get("priority") or "medium").lower()
    if prio not in ("low", "medium", "high"):
        prio = "medium"
    due = data.get("due_date")
    if not due or str(due).lower() in ("null", "none", "aucune", "n/a"):
        due = None
    desc = str(data.get("description") or "").strip()
    if subject:
        desc = (desc + f"\n\n— Issu de l'email « {subject} »" + (f" de {sender}" if sender else "")).strip()
    res = await execute_task_create({"title": title, "description": desc, "priority": prio,
                                     "due_date": due, "tags": ["email"]})
    if res.get("error"):
        return res
    return {"success": True, "task": res.get("task"), "title": title, "priority": prio, "due_date": due,
            "message": f"Tâche créée : « {title} »" + (f" (échéance {due})" if due else "")}


async def execute_email_attachment_summary(args: dict) -> dict:
    """📎 Résume par IA une pièce jointe d'un email (PDF, Word, texte). uid + name requis."""
    account = args.get("account")
    uid = str(args.get("uid", "")).strip()
    name = args.get("name", "")
    if not uid:
        return {"error": "Paramètre 'uid' requis."}
    cfg = _get_email_cfg(account)
    if not cfg:
        return {"error": "Email non configuré."}
    import email_manager as _em, tempfile as _tmp, os as _os, uuid as _uuid
    loop = asyncio.get_running_loop()
    try:
        # v2.160 : un uid invalide/mal formé faisait planter la commande IMAP FETCH
        # (exception non rattrapée → 500) au lieu d'un message d'erreur propre.
        att = await loop.run_in_executor(None, lambda: _em.fetch_attachment(
            cfg["imap_host"], int(cfg.get("imap_port", 993)), cfg["username"], cfg["password"],
            uid=uid, name=name, folder=args.get("folder", "INBOX")))
    except Exception as e:
        return {"error": f"Pièce jointe introuvable (uid invalide ou email inaccessible) : {e}"}
    if not att or not att.get("data"):
        return {"error": "Pièce jointe introuvable."}
    fname = att["name"]
    ext = _os.path.splitext(fname)[1].lower()
    path = _os.path.join(_tmp.gettempdir(), f"marvin_att_{_uuid.uuid4().hex[:8]}{ext}")
    try:
        with open(path, "wb") as f:
            f.write(att["data"])
        text = ""
        if ext == ".pdf":
            r = await execute_pdf_read({"path": path, "max_chars": 14000})
            text = r.get("text") or r.get("content") or ""
        elif ext in (".docx",):
            r = await execute_docx_to_text({"path": path, "format": "text"})
            text = r.get("text", "")
        elif ext in (".txt", ".csv", ".md", ".log", ".json"):
            with open(path, "r", encoding="utf-8", errors="replace") as _f:
                text = _f.read(20000)
        else:
            return {"error": f"Type non pris en charge pour le résumé : {ext or fname}. (PDF, Word .docx, texte supportés)"}
        if not (text or "").strip():
            return {"error": f"Impossible d'extraire du texte de « {fname} » (document vide ou scanné)."}
        prompt = (f"Résume en français cette pièce jointe nommée « {fname} ». Donne : **Résumé** (2-4 phrases), "
                  f"**Points clés** (puces), et **À retenir / action** s'il y a lieu. Base-toi uniquement sur le contenu.\n\n{text[:13000]}")
        summary = await _ollama_generate(prompt, model=args.get("model"), timeout=180)
        return {"success": True, "name": fname, "size": att.get("size"), "summary": (summary or "").strip(),
                "message": f"Résumé de « {fname} » généré."}
    except Exception as e:
        return _net_error(e, "résumé pièce jointe") if "_net_error" in globals() else {"error": str(e)}
    finally:
        try:
            _os.remove(path)
        except Exception:
            pass


async def execute_email_watch_check(args: dict) -> dict:
    """🔔 Surveille les emails non lus, détecte les IMPORTANTS par IA et notifie sur le bureau.
    Appelé périodiquement en arrière-plan. force=true ignore le réglage activé/désactivé ; dry_run=true ne notifie pas."""
    import json as _json
    from datetime import datetime as _dt
    cfg = db.get_setting("email_watch")
    if isinstance(cfg, str):
        try: cfg = _json.loads(cfg)
        except Exception: cfg = None
    if not isinstance(cfg, dict):
        cfg = {}
    if not args.get("force") and not cfg.get("enabled"):
        return {"success": True, "checked": 0, "important": 0, "message": "Surveillance désactivée."}
    accounts_filter = cfg.get("accounts") or []
    max_notify = int(cfg.get("max_notify", 5))
    do_notify = not args.get("dry_run", False)

    import email_manager as _em
    loop = asyncio.get_running_loop()
    accts = [a for a in _all_email_cfgs() if (not accounts_filter or a["username"] in accounts_filter)]
    seen = set(db.get_setting("email_watch_seen") or [])
    new_items = []
    for a in accts:
        try:
            inbox = await loop.run_in_executor(None, lambda a=a: _em.fetch_inbox(
                a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                folder="INBOX", limit=15, offset=0))
        except Exception:
            continue
        for e in inbox:
            uid = str(e.get("id") or "")
            key = f"{a['username']}:{uid}"
            if not uid or key in seen or e.get("read"):
                continue
            new_items.append({"account": a["username"], "key": key, "from": e.get("from", ""), "subject": e.get("subject", "")})
    if not new_items:
        return {"success": True, "checked": 0, "important": 0, "message": "Aucun nouvel email non lu."}

    # IA : repérer les importants (1 seul appel)
    listing = "\n".join(f"{i+1}. De: {it['from']} | Objet: {it['subject']}" for i, it in enumerate(new_items[:20]))
    prompt = ("Parmi ces nouveaux emails non lus, lesquels sont VRAIMENT IMPORTANTS (action requise, urgent, "
              "vrai expéditeur attendant une réponse) — par opposition aux non importants (pub, newsletter, "
              "notification automatique, réseaux sociaux) ? Réponds UNIQUEMENT par un JSON : {\"important\": [numéros]}.\n\n" + listing)
    important_idx = set()
    try:
        raw = await _ollama_generate(prompt, model=args.get("model"), timeout=120)
        import re as _re3
        m = _re3.search(r"\{.*\}", raw or "", _re3.DOTALL)
        if m:
            d = _json.loads(m.group(0))
            important_idx = {int(x) for x in d.get("important", []) if str(x).strip().lstrip("-").isdigit()}
    except Exception:
        important_idx = set()

    alerts = db.get_setting("email_watch_alerts") or []
    if isinstance(alerts, str):
        try: alerts = _json.loads(alerts)
        except Exception: alerts = []
    if not isinstance(alerts, list):
        alerts = []
    notified = 0
    for i, it in enumerate(new_items):
        seen.add(it["key"])  # tous marqués vus (pas de re-notification)
        if (i + 1) in important_idx and notified < max_notify:
            if do_notify:
                try:
                    await execute_pc_notify({"title": f"📧 Email important — {it['from'][:40]}",
                                             "message": (it["subject"] or "(sans objet)")[:140]})
                except Exception:
                    pass
                # Alerte aussi sur Telegram (si activé)
                await _telegram_notify(f"🔴 <b>Mail important</b>\nDe : {it['from'][:60]}\n{(it['subject'] or '(sans objet)')[:140]}")
            alerts.insert(0, {"account": it["account"], "from": it["from"], "subject": it["subject"],
                              "at": _dt.now().isoformat(timespec="seconds")})
            notified += 1
    db.set_setting("email_watch_seen", list(seen)[-1000:])
    db.set_setting("email_watch_alerts", alerts[:50])
    return {"success": True, "checked": len(new_items), "important": notified,
            "message": f"{len(new_items)} nouvel(s) email(s) non lu(s), {notified} important(s) signalé(s)."}


def _email_rules() -> list[dict]:
    import json as _json
    r = db.get_setting("email_rules")
    if isinstance(r, str):
        try: r = _json.loads(r)
        except Exception: r = []
    return r if isinstance(r, list) else []


async def execute_email_apply_rules(args: dict) -> dict:
    """🗂️ Applique les règles de classement aux emails récents : déplacer vers un dossier
    ou marquer lu/non lu selon expéditeur/objet. dry_run=true pour simuler."""
    rules = [r for r in _email_rules() if r.get("enabled", True) and (r.get("from_contains") or r.get("subject_contains"))]
    if not rules:
        return {"success": True, "applied": 0, "results": [], "message": "Aucune règle définie."}
    dry_run = bool(args.get("dry_run", False))
    only_account = args.get("account")
    import email_manager as _em
    loop = asyncio.get_running_loop()
    accts = [a for a in _all_email_cfgs() if (not only_account or a["username"] == only_account)]
    results = []
    applied = 0
    for a in accts:
        try:
            inbox = await loop.run_in_executor(None, lambda a=a: _em.fetch_inbox(
                a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                folder="INBOX", limit=int(args.get("limit", 25)), offset=0))
        except Exception as e:
            results.append({"account": a["username"], "action": "erreur", "reason": str(e)})
            continue
        for e in inbox:
            uid = str(e.get("id") or "")
            sender = (e.get("from") or "").lower()
            subject = (e.get("subject") or "").lower()
            for rule in rules:
                if rule.get("account") and rule["account"] != a["username"]:
                    continue
                fc = (rule.get("from_contains") or "").lower().strip()
                sc = (rule.get("subject_contains") or "").lower().strip()
                if fc and fc not in sender:
                    continue
                if sc and sc not in subject:
                    continue
                act = rule.get("action", "move")
                target = rule.get("folder", "")
                label = f"{e.get('subject','(sans objet)')[:40]} → règle « {rule.get('name', act)} »"
                if not dry_run:
                    try:
                        if act == "move" and target:
                            await loop.run_in_executor(None, lambda a=a, uid=uid, target=target: _em.move_email(
                                a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                                uid=uid, dest_folder=target, folder="INBOX"))
                        elif act == "mark_read":
                            await loop.run_in_executor(None, lambda a=a, uid=uid: _em.mark_email(
                                a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                                uid=uid, folder="INBOX", seen=True))
                        elif act == "mark_unread":
                            await loop.run_in_executor(None, lambda a=a, uid=uid: _em.mark_email(
                                a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                                uid=uid, folder="INBOX", seen=False))
                    except Exception as ex:
                        results.append({"account": a["username"], "action": "échec", "detail": label, "reason": str(ex)})
                        break
                results.append({"account": a["username"], "action": act + (" (simulation)" if dry_run else ""),
                                "detail": label, "folder": target})
                applied += 1
                break  # une seule règle par email (la première qui matche)
    return {"success": True, "applied": applied, "dry_run": dry_run, "results": results[:60],
            "message": f"{applied} email(s) classé(s) par règles" + (" (simulation)" if dry_run else "") + "."}


# ─────────────────────── Briefing du jour (assistant) v2.47 ───────────────────────
_FR_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FR_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre"]


async def execute_daily_briefing(args: dict) -> dict:
    """🌅 Génère le briefing du jour : réunit les emails non lus + les tâches en attente
    et produit une synthèse IA priorisée et motivante en français."""
    from datetime import date as _date
    d = _date.today()
    today_fr = f"{_FR_JOURS[d.weekday()]} {d.day} {_FR_MOIS[d.month - 1]} {d.year}"
    # Tâches en attente
    try:
        all_tasks = db.list_tasks(limit=50)
    except Exception:
        all_tasks = []
    pending = [t for t in all_tasks if t.get("status") != "done"]
    # Emails non lus (toutes boîtes)
    import email_manager as _em
    loop = asyncio.get_running_loop()
    unread = []
    for a in _all_email_cfgs():
        try:
            inbox = await loop.run_in_executor(None, lambda a=a: _em.fetch_inbox(
                a["imap_host"], int(a.get("imap_port", 993)), a["username"], a["password"],
                folder="INBOX", limit=12, offset=0))
            unread += [{"from": e.get("from", ""), "subject": e.get("subject", ""), "account": a["username"]}
                       for e in inbox if not e.get("read")]
        except Exception:
            continue
    # Rendez-vous du jour (agenda local)
    try:
        events_today = db.list_events(start=d.strftime("%Y-%m-%d 00:00"),
                                      end=d.strftime("%Y-%m-%d 23:59"), limit=30)
    except Exception:
        events_today = []
    task_lines = "\n".join(
        f"- [{t.get('priority', 'medium')}] {t.get('title', '')}" + (f" (échéance {t['due_date']})" if t.get("due_date") else "")
        for t in pending[:15]) or "(aucune)"
    mail_lines = "\n".join(f"- De {u['from']} : {u['subject']}" for u in unread[:20]) or "(aucun)"
    event_lines = "\n".join(
        f"- {(e.get('start_at') or '')[11:16] or 'journée'} : {e.get('title', '')}" + (f" @ {e['location']}" if e.get("location") else "")
        for e in events_today) or "(aucun)"
    prompt = (
        f"Tu es l'assistant personnel de l'utilisateur. Rédige son BRIEFING DU JOUR en français, "
        f"chaleureux mais concis et actionnable. Nous sommes le {today_fr}.\n\n"
        f"RENDEZ-VOUS DU JOUR ({len(events_today)}) :\n{event_lines}\n\n"
        f"TÂCHES EN ATTENTE ({len(pending)}) :\n{task_lines}\n\n"
        f"EMAILS NON LUS ({len(unread)}) :\n{mail_lines}\n\n"
        "Structure ta réponse :\n"
        "1) Une salutation courte adaptée au moment.\n"
        "2) 📅 AGENDA : rappelle les rendez-vous du jour dans l'ordre (s'il y en a).\n"
        "3) 🔴 PRIORITÉS DU JOUR : les mails vraiment importants à traiter + les tâches urgentes (ignore pubs/newsletters/notifs).\n"
        "4) 🟡 À VOIR : ce qui peut attendre.\n"
        "5) Une phrase de motivation finale.\n"
        "Sois synthétique, va à l'essentiel."
    )
    try:
        briefing = await _ollama_generate(prompt, model=args.get("model"), timeout=180)
    except Exception as e:
        return _net_error(e, "briefing du jour") if "_net_error" in globals() else {"error": str(e)}
    urgent = [t for t in pending if t.get("priority") == "high"]
    return {"success": True, "briefing": (briefing or "").strip(), "date": today_fr,
            "tasks_pending": len(pending), "tasks_urgent": len(urgent), "unread": len(unread),
            "tasks": pending[:15], "events_today": events_today, "message": "Briefing du jour généré."}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION AGENDA — Événements locaux (indépendant de Google Calendar)
# ══════════════════════════════════════════════════════════════════════════════

def _now_iso() -> str:
    from datetime import datetime as _dt
    return _dt.now().strftime("%Y-%m-%d %H:%M")


def _period_range(period: str):
    """Retourne (start_iso, end_iso, label_fr) pour un mot-clé de période."""
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.now()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period = (period or "upcoming").lower().strip()
    if period in ("today", "jour", "aujourd'hui", "aujourdhui"):
        return today0.strftime("%Y-%m-%d 00:00"), today0.strftime("%Y-%m-%d 23:59"), "aujourd'hui"
    if period in ("tomorrow", "demain"):
        t = today0 + _td(days=1)
        return t.strftime("%Y-%m-%d 00:00"), t.strftime("%Y-%m-%d 23:59"), "demain"
    if period in ("week", "semaine", "7days"):
        return today0.strftime("%Y-%m-%d 00:00"), (today0 + _td(days=7)).strftime("%Y-%m-%d 23:59"), "cette semaine"
    if period in ("month", "mois", "30days"):
        return today0.strftime("%Y-%m-%d 00:00"), (today0 + _td(days=31)).strftime("%Y-%m-%d 23:59"), "ce mois-ci"
    if period in ("all", "tout"):
        return None, None, "tous"
    # défaut : à venir (now .. +30 jours)
    return now.strftime("%Y-%m-%d %H:%M"), (today0 + _td(days=30)).strftime("%Y-%m-%d 23:59"), "à venir"


async def _ai_parse_when(text: str, model: str = None) -> dict:
    """Convertit une expression en langage naturel ('rdv dentiste demain 14h30') en
    {title, start_at 'YYYY-MM-DD HH:MM', end_at, all_day} en s'appuyant sur la date du jour."""
    from datetime import date as _date
    d = _date.today()
    today_fr = f"{_FR_JOURS[d.weekday()]} {d.day} {_FR_MOIS[d.month - 1]} {d.year}"
    prompt = (
        f"Nous sommes le {today_fr} (date ISO {d.isoformat()}). "
        f"Analyse cette demande de rendez-vous/événement et renvoie UNIQUEMENT un JSON valide, sans texte autour :\n"
        f'{{"title": "...", "start_at": "YYYY-MM-DD HH:MM", "end_at": "YYYY-MM-DD HH:MM ou null", "all_day": false, "location": ""}}\n'
        f"Règles : si aucune heure n'est précisée mets 09:00 et all_day=false ; "
        f"'demain'=+1 jour, 'après-demain'=+2, un jour de semaine = sa prochaine occurrence. "
        f"Le titre doit être court et propre (sans la date).\n\n"
        f"Demande : « {text} »"
    )
    raw = await _ollama_generate(prompt, model=model, timeout=120)
    import json as _json, re as _re
    m = _re.search(r"\{.*\}", raw or "", _re.DOTALL)
    if not m:
        raise RuntimeError("Impossible d'interpréter la date.")
    return _json.loads(m.group(0))


async def execute_event_create(args: dict) -> dict:
    """Crée un événement dans l'agenda local. Accepte des champs structurés OU un texte
    libre ('natural') interprété par l'IA (ex : « rdv client mardi 14h »)."""
    title = (args.get("title") or "").strip()
    start_at = (args.get("start_at") or "").strip()
    natural = (args.get("natural") or args.get("text") or "").strip()
    end_at = (args.get("end_at") or "").strip() or None
    all_day = bool(args.get("all_day", False))
    location = (args.get("location") or "").strip()
    description = (args.get("description") or "").strip()
    reminder = args.get("reminder_minutes")
    # Interprétation IA si pas de date explicite
    if not start_at and (natural or title):
        try:
            parsed = await _ai_parse_when(natural or title, model=args.get("model"))
            title = title or (parsed.get("title") or "").strip()
            start_at = (parsed.get("start_at") or "").strip()
            end_at = end_at or (parsed.get("end_at") or None)
            all_day = all_day or bool(parsed.get("all_day"))
            location = location or (parsed.get("location") or "").strip()
        except Exception as e:
            return {"error": f"Date non comprise : {e}. Précisez par ex. « réunion 2026-06-20 14:00 »."}
    if not title:
        return {"error": "Titre de l'événement requis."}
    if not start_at:
        return {"error": "Date/heure de début requise (start_at ou texte 'natural')."}
    start_at = start_at.replace("T", " ")[:16]
    if end_at:
        end_at = str(end_at).replace("T", " ")[:16]
    try:
        rem = int(reminder) if reminder not in (None, "") else None
    except Exception:
        rem = None

    # ── Si Google Agenda est connecté → on crée l'événement SUR Google (il apparaît sur
    #    le téléphone + rappel natif), puis on synchronise pour l'afficher dans Marvin.
    #    'local_only=true' force l'agenda local. Repli local automatique si Google échoue.
    if _google_calendar_ready() and not args.get("local_only"):
        try:
            g_start = start_at if all_day else start_at.replace(" ", "T")
            g_end = (end_at.replace(" ", "T") if (end_at and not all_day) else (end_at or "")) if end_at else ""
            gres = await execute_calendar_create({
                "title": title, "start": g_start, "end": g_end,
                "location": location, "description": description, "reminder_minutes": rem,
            })
            if gres.get("success"):
                try:
                    await _sync_google_into_events()
                except Exception:
                    pass
                return {"success": True, "event": gres, "target": "google",
                        "message": f"📅 Créé sur ton Google Agenda : « {title} » le {start_at}"
                                   + (f" (rappel {rem} min)" if rem else "")
                                   + " — visible sur ton téléphone."}
            # sinon : on retombe sur l'agenda local
        except Exception:
            pass

    ev = db.create_event(title=title, start_at=start_at, end_at=end_at, description=description,
                         location=location, all_day=all_day, reminder_minutes=rem,
                         tags=args.get("tags"))
    return {"success": True, "event": ev, "target": "local",
            "message": f"📅 Événement créé : « {title} » le {start_at}" + (f" (rappel {rem} min avant)" if rem else "")}


async def execute_event_list(args: dict) -> dict:
    """Liste les événements de l'agenda. 'period' = today/tomorrow/week/month/upcoming/all,
    ou bornes explicites start/end (YYYY-MM-DD)."""
    start = (args.get("start") or "").strip() or None
    end = (args.get("end") or "").strip() or None
    label = None
    if not start and not end:
        start, end, label = _period_range(args.get("period", "upcoming"))
    limit = int(args.get("limit", 200))
    events = db.list_events(start=start, end=end, limit=limit)
    return {"success": True, "events": events, "count": len(events), "period": label or "personnalisé",
            "message": f"{len(events)} événement(s) {('— ' + label) if label else ''}."}


async def execute_event_update(args: dict) -> dict:
    """Modifie/replanifie un événement (par id). Champs : title, start_at, end_at, location, description, reminder_minutes."""
    eid = (args.get("id") or args.get("event_id") or "").strip()
    if not eid:
        return {"error": "id de l'événement requis."}
    updates = {k: args[k] for k in ("title", "start_at", "end_at", "location", "description", "reminder_minutes", "all_day", "color")
               if k in args and args[k] is not None}
    if "start_at" in updates:
        updates["start_at"] = str(updates["start_at"]).replace("T", " ")[:16]
        updates["reminded"] = False  # on re-notifiera pour la nouvelle heure
    if not updates:
        return {"error": "Aucun champ à modifier."}

    # ── Si l'événement vient de Google → on le modifie SUR Google (sinon le sync écraserait).
    try:
        ev0 = db.get_event(eid)
    except Exception:
        ev0 = None
    if ev0 and ev0.get("source") == "google" and ev0.get("external_id"):
        try:
            gargs = {"event_id": ev0["external_id"]}
            for k_loc, k_g in (("title", "title"), ("description", "description"), ("location", "location")):
                if k_loc in updates:
                    gargs[k_g] = updates[k_loc]
            if "start_at" in updates:
                gargs["start"] = str(updates["start_at"]).replace(" ", "T")
                # Déplacer le début SANS toucher la fin rendrait fin < début (Google refuse) :
                # on conserve la durée d'origine si la fin n'est pas explicitement fournie.
                if not updates.get("end_at"):
                    try:
                        from datetime import datetime as _dt2, timedelta as _td2
                        _os = _dt2.fromisoformat(str(ev0.get("start_at")).replace(" ", "T")[:16])
                        _oe = (_dt2.fromisoformat(str(ev0.get("end_at")).replace(" ", "T")[:16])
                               if ev0.get("end_at") else _os + _td2(hours=1))
                        _ns = _dt2.fromisoformat(str(updates["start_at"]).replace(" ", "T")[:16])
                        gargs["end"] = (_ns + (_oe - _os)).strftime("%Y-%m-%dT%H:%M:%S")
                    except Exception:
                        pass
            if updates.get("end_at"):
                gargs["end"] = str(updates["end_at"]).replace(" ", "T")
            gres = await execute_calendar_update(gargs)
            if gres.get("success"):
                try:
                    await _sync_google_into_events()
                except Exception:
                    pass
                return {"success": True, "event": gres, "target": "google",
                        "message": f"📅 RDV mis à jour sur ton Google Agenda : « {gres.get('title') or ev0.get('title')} »."}
        except Exception:
            pass

    ev = db.update_event(eid, updates)
    if not ev:
        return {"error": "Événement introuvable."}
    return {"success": True, "event": ev, "target": "local", "message": f"📅 Événement mis à jour : « {ev.get('title')} »."}


async def execute_event_delete(args: dict) -> dict:
    """Supprime un événement par id, ou par correspondance de titre si 'title' fourni."""
    eid = (args.get("id") or args.get("event_id") or "").strip()
    title = (args.get("title") or "").strip().lower()
    ev_found = None
    if not eid and title:
        for ev in db.list_events(limit=500):
            if title in (ev.get("title") or "").lower():
                eid = ev["id"]; ev_found = ev
                break
    if not eid:
        return {"error": "Aucun événement correspondant (fournissez 'id' ou 'title')."}
    if ev_found is None:
        try: ev_found = db.get_event(eid)
        except Exception: ev_found = None
    # Action irréversible → confirmation explicite (anti-erreur)
    if not args.get("confirmed"):
        label = (f"« {ev_found['title']} » du {(ev_found.get('start_at') or '')[:16]}"
                 if ev_found else f"id {eid}")
        return {"requiresConfirmation": True, "message": f"Supprimer définitivement l'événement {label} ?"}

    # ── Si l'événement vient de Google → on le supprime SUR Google (sinon le sync le ramène).
    if ev_found and ev_found.get("source") == "google" and ev_found.get("external_id"):
        try:
            gres = await execute_calendar_delete({"event_id": ev_found["external_id"], "confirmed": True})
            if gres.get("success"):
                try:
                    await _sync_google_into_events()
                except Exception:
                    pass
                db.delete_event(eid)  # nettoie la copie locale aussi
                return {"success": True, "target": "google", "message": "🗑️ RDV supprimé de ton Google Agenda."}
        except Exception:
            pass

    db.delete_event(eid)
    return {"success": True, "target": "local", "message": "🗑️ Événement supprimé."}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION AGENDAS CONNECTÉS — Abonnements iCal (Google, Outlook, Apple, tout CalDAV)
# Lecture seule : synchronise les événements externes dans l'agenda local → Marvin
# en est « au courant » dans le briefing, l'agenda et les recherches.
# ══════════════════════════════════════════════════════════════════════════════

def _calendar_subs() -> list:
    subs = db.get_setting("calendar_subscriptions")
    if isinstance(subs, str):
        try:
            import json as _json
            subs = _json.loads(subs)
        except Exception:
            subs = []
    return subs if isinstance(subs, list) else []


def _save_calendar_subs(subs: list):
    db.set_setting("calendar_subscriptions", subs)


def _parse_ics(data: bytes) -> list:
    """Parse un flux iCal et développe les récurrences (RRULE) sur une fenêtre
    [−30 j, +180 j]. Convertit les heures en fuseau local."""
    import icalendar, recurring_ical_events
    from datetime import datetime as _dt, date as _date, timedelta as _td
    cal = icalendar.Calendar.from_ical(data)
    start = _dt.now() - _td(days=30)
    end = _dt.now() + _td(days=180)
    try:
        occurrences = recurring_ical_events.of(cal).between(start, end)
    except Exception:
        # repli : pas d'expansion de récurrence
        occurrences = [c for c in cal.walk("VEVENT")]

    def _fmt(v):
        if v is None:
            return None, False
        d = v.dt if hasattr(v, "dt") else v
        if isinstance(d, _dt):
            if d.tzinfo is not None:
                try: d = d.astimezone()   # → heure locale
                except Exception: pass
            return d.strftime("%Y-%m-%d %H:%M"), False
        if isinstance(d, _date):
            return d.strftime("%Y-%m-%d 00:00"), True   # date pure = journée entière
        return None, False

    out = []
    for ev in occurrences:
        try:
            start_at, all_day = _fmt(ev.get("DTSTART"))
            if not start_at:
                continue
            end_at, _ = _fmt(ev.get("DTEND"))
            out.append({
                "title": str(ev.get("SUMMARY", "(sans titre)")),
                "location": str(ev.get("LOCATION", "") or ""),
                "description": str(ev.get("DESCRIPTION", "") or "")[:500],
                "start_at": start_at, "end_at": end_at, "all_day": all_day,
                "external_id": str(ev.get("UID", "") or ""),
            })
        except Exception:
            continue
    return out


async def _fetch_ics(url: str, timeout: int = 25) -> bytes:
    import httpx
    u = url.strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[len("webcal://"):]
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(u, headers={"User-Agent": "Marvin/1.0 (+calendar-sync)"})
        r.raise_for_status()
        return r.content


async def _sync_subscription(sub: dict) -> dict:
    """Récupère + parse + remplace les événements d'un abonnement. Met à jour sub en place."""
    from datetime import datetime as _dt
    src = f"ics:{sub.get('id')}"
    try:
        data = await _fetch_ics(sub["url"])
        loop = asyncio.get_running_loop()
        events = await loop.run_in_executor(None, _parse_ics, data)
        for e in events:
            e["color"] = sub.get("color") or "#10b981"
        n = db.replace_external_events(src, events)
        sub["last_sync"] = _dt.now().strftime("%Y-%m-%d %H:%M")
        sub["last_error"] = ""
        sub["count"] = n
        return {"success": True, "count": n}
    except Exception as e:
        sub["last_error"] = str(e)[:200]
        return {"error": str(e)[:200]}


async def execute_calendar_subscribe(args: dict) -> dict:
    """Abonne Marvin à un agenda via son lien iCal (.ics / webcal). Le synchronise aussitôt."""
    url = (args.get("url") or "").strip()
    name = (args.get("name") or "").strip() or "Agenda"
    color = (args.get("color") or "#10b981").strip()
    if not url or (".ics" not in url.lower() and "ical" not in url.lower()
                   and not url.lower().startswith(("webcal://", "http"))):
        return {"error": "Lien iCal invalide. Fournissez l'URL .ics (Google : « Adresse secrète au format iCal »)."}
    import uuid as _uuid
    subs = _calendar_subs()
    sub = {"id": _uuid.uuid4().hex[:8], "name": name, "url": url, "color": color,
           "enabled": True, "last_sync": "", "last_error": "", "count": 0}
    r = await _sync_subscription(sub)
    subs.append(sub)
    _save_calendar_subs(subs)
    if r.get("error"):
        return {"error": f"Abonnement ajouté mais synchro échouée : {r['error']}", "subscription": sub}
    return {"success": True, "subscription": sub,
            "message": f"📅 Agenda « {name} » connecté : {r.get('count', 0)} événement(s) importé(s)."}


async def execute_calendar_subscriptions(args: dict) -> dict:
    """Liste les agendas connectés (abonnements iCal) et leur état."""
    subs = _calendar_subs()
    return {"success": True, "subscriptions": subs, "count": len(subs)}


async def execute_calendar_unsubscribe(args: dict) -> dict:
    """Déconnecte un agenda (par id ou nom) et retire ses événements."""
    key = (args.get("id") or args.get("name") or "").strip().lower()
    if not key:
        return {"error": "Fournissez l'id ou le nom de l'agenda à déconnecter."}
    subs = _calendar_subs()
    keep, removed = [], None
    for s in subs:
        if s.get("id", "").lower() == key or (s.get("name", "").lower() == key):
            removed = s
        else:
            keep.append(s)
    if not removed:
        return {"error": "Agenda introuvable."}
    db.delete_events_by_source(f"ics:{removed['id']}")
    _save_calendar_subs(keep)
    return {"success": True, "message": f"🗑️ Agenda « {removed.get('name')} » déconnecté."}


async def _sync_google_into_events() -> dict:
    """Si un compte Google est connecté, importe ses événements dans l'agenda local
    (source='google'), comme un abonnement iCal. Best-effort (ignore si non connecté)."""
    try:
        service = _get_google_calendar_service()
    except Exception:
        return {"connected": False, "count": 0}
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    loop = asyncio.get_running_loop()

    def _list():
        now = _dt.now(_tz.utc)
        res = service.events().list(
            calendarId=_resolve_calendar_id("primary"),
            timeMin=(now - _td(days=30)).isoformat(),
            timeMax=(now + _td(days=180)).isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=500,
        ).execute()
        return res.get("items", [])

    try:
        items = await loop.run_in_executor(None, _list)
    except Exception as e:
        return {"connected": True, "count": 0, "error": str(e)[:150]}

    def _fmt(x):
        if not x:
            return None
        return x.replace("T", " ")[:16]   # garde l'heure murale fournie par Google

    evts = []
    for it in items:
        st, en = it.get("start", {}), it.get("end", {})
        all_day = "date" in st
        evts.append({
            "title": it.get("summary", "(sans titre)"),
            "location": it.get("location", ""),
            "start_at": _fmt(st.get("dateTime") or st.get("date")),
            "end_at": _fmt(en.get("dateTime") or en.get("date")),
            "all_day": all_day, "external_id": it.get("id"), "color": "#4285f4",
        })
    n = db.replace_external_events("google", evts)
    return {"connected": True, "count": n}


async def execute_calendar_sync(args: dict) -> dict:
    """Resynchronise tous les agendas connectés (iCal + Google si connecté)."""
    subs = _calendar_subs()
    only = (args.get("id") or "").strip()
    results, total, ok = [], 0, 0
    for sub in subs:
        if only and sub.get("id") != only:
            continue
        if not sub.get("enabled", True):
            continue
        r = await _sync_subscription(sub)
        if r.get("success"):
            total += r.get("count", 0); ok += 1
        results.append({"name": sub.get("name"), "id": sub.get("id"), **r})
    _save_calendar_subs(subs)
    # Google (si connecté)
    g = await _sync_google_into_events()
    if g.get("connected"):
        total += g.get("count", 0)
        results.append({"name": "Google Agenda", "id": "google", "success": True, "count": g.get("count", 0)})
        if g.get("count"):
            ok += 1
    if not subs and not g.get("connected"):
        return {"success": True, "total_events": 0, "results": [], "message": "Aucun agenda connecté."}
    return {"success": True, "synced": ok, "total_events": total, "results": results,
            "message": f"🔄 {total} événement(s) synchronisé(s) depuis {ok} agenda(s)."}


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





_UNIFIED_SOURCES_DEFAULT = ["documents", "files_name", "files_content", "notes", "tasks", "events", "memory"]
_UNIFIED_SOURCES_ALL = _UNIFIED_SOURCES_DEFAULT + ["emails", "web"]


async def execute_unified_search(args: dict) -> dict:
    """RECHERCHE UNIFIÉE : cherche le même terme PARTOUT à la fois — documents indexés,
    fichiers du PC (nom + contenu), notes, tâches, agenda, mémoire, (emails et web en option).
    Renvoie les résultats groupés par source. Idéal pour « retrouve tout ce qui concerne X »."""
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "Indique ce que tu cherches (paramètre 'query')."}
    scope = args.get("scope") or _UNIFIED_SOURCES_DEFAULT
    if isinstance(scope, str):
        scope = _UNIFIED_SOURCES_ALL if scope == "all" else [scope]
    scope = [s for s in scope if s in _UNIFIED_SOURCES_ALL]
    per = max(1, min(int(args.get("limit", 5)), 15))
    q_low = query.lower()

    async def _documents():
        import vector_store as vs
        hits = await vs.search(query, collections=["documents"], limit=per)
        return [{"name": h["metadata"].get("name", "?"), "snippet": (h.get("text") or "")[:200],
                 "path": h["metadata"].get("path"), "score": round(h.get("score", 0), 3)} for h in hits]

    async def _files_name():
        r = await execute_system_search({"query": query, "max_results": per})
        return [{"name": x.get("name"), "path": x.get("path"), "is_dir": x.get("is_dir"),
                 "size_kb": x.get("size_kb")} for x in (r.get("results") or [])][:per]

    async def _files_content():
        r = await execute_system_search_content({"query": query, "max_results": per})
        return [{"name": x.get("name"), "path": x.get("path"), "snippet": x.get("snippet")}
                for x in (r.get("results") or [])][:per]

    async def _notes():
        rows = db.list_notes(search=query, limit=per)
        return [{"id": n.get("id"), "title": n.get("title"), "snippet": (n.get("content") or "")[:160]} for n in rows]

    async def _tasks():
        out = []
        for t in db.list_tasks(limit=200):
            hay = (str(t.get("title", "")) + " " + str(t.get("description") or "")).lower()
            if q_low in hay:
                out.append({"id": t.get("id"), "title": t.get("title"), "status": t.get("status"),
                            "priority": t.get("priority"), "due_date": t.get("due_date")})
            if len(out) >= per:
                break
        return out

    async def _events():
        out = []
        for e in db.list_events(limit=400):
            hay = (str(e.get("title", "")) + " " + str(e.get("description") or "") + " " + str(e.get("location") or "")).lower()
            if q_low in hay:
                out.append({"id": e.get("id"), "title": e.get("title"), "start_at": e.get("start_at"),
                            "location": e.get("location"), "source": e.get("source")})
            if len(out) >= per:
                break
        return out

    async def _memory():
        import learning
        rec = await learning.recall(query, max_facts=per, max_qa=3)
        items = [{"type": "fait", "text": f} for f in rec.get("facts", [])]
        items += [{"type": "q/r", "text": f"{qa.get('q', '')} → {qa.get('a', '')}"} for qa in rec.get("qa", [])]
        return items[:per]

    async def _emails():
        r = await execute_email_search({"query": query, "account": args.get("account")})
        if r.get("error"):
            return []
        return [{"subject": m.get("subject"), "from": m.get("from") or m.get("from_addr"),
                 "date": m.get("date"), "uid": m.get("uid")} for m in (r.get("emails") or [])][:per]

    async def _web():
        try:
            r = await execute_web_search({"query": query})
        except Exception:
            return []
        return [{"title": x.get("title"), "url": x.get("url"), "snippet": (x.get("snippet") or x.get("description") or "")[:200]}
                for x in (r.get("results") or [])][:per]

    funcs = {"documents": _documents, "files_name": _files_name, "files_content": _files_content,
             "notes": _notes, "tasks": _tasks, "events": _events, "memory": _memory,
             "emails": _emails, "web": _web}
    active = [s for s in scope if s in funcs]
    gathered = await asyncio.gather(*[funcs[s]() for s in active], return_exceptions=True)
    results, errors = {}, {}
    for s, g in zip(active, gathered):
        if isinstance(g, Exception):
            results[s] = []
            errors[s] = str(g)[:120]
        else:
            results[s] = g
    total = sum(len(v) for v in results.values())
    return {"success": True, "query": query, "total": total, "results": results,
            "errors": errors or None,
            "message": f"🔎 {total} résultat(s) pour « {query} » dans {len([s for s in active if results.get(s)])} source(s)."}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION NOTIFICATIONS EXTERNES — Telegram (recevoir les alertes sur le téléphone)
# ══════════════════════════════════════════════════════════════════════════════

def _telegram_cfg() -> dict:
    cfg = db.get_setting("telegram_config")
    if isinstance(cfg, str):
        try:
            import json as _json
            cfg = _json.loads(cfg)
        except Exception:
            cfg = {}
    return cfg if isinstance(cfg, dict) else {}


async def _send_telegram(text: str) -> dict:
    cfg = _telegram_cfg()
    token = (cfg.get("bot_token") or "").strip()
    chat_id = str(cfg.get("chat_id") or "").strip()
    if not token or not chat_id:
        return {"error": "Telegram non configuré (jeton du bot + chat_id requis)."}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:3500], "parse_mode": "HTML",
                      "disable_web_page_preview": True},
            )
        if r.status_code != 200:
            return {"error": f"Telegram {r.status_code}: {r.text[:150]}"}
        return {"success": True}
    except Exception as e:
        return {"error": str(e)[:150]}


async def _telegram_notify(text: str):
    """Envoi best-effort (ne lève jamais) — utilisé par les workers."""
    try:
        if (_telegram_cfg().get("enabled")):
            await _send_telegram(text)
    except Exception:
        pass


async def execute_telegram_send(args: dict) -> dict:
    """Envoie un message sur ton Telegram (alerte, rappel, note). Nécessite la config Telegram."""
    text = (args.get("text") or args.get("message") or "").strip()
    if not text:
        return {"error": "Texte du message requis."}
    r = await _send_telegram(text)
    return r if r.get("error") else {"success": True, "message": "📲 Message envoyé sur Telegram."}


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


# v2.211 — Council v2 : cinq familles cloud, cinq rôles indépendants, critique aveugle puis
# arbitrage. Aucun repli local silencieux : la provenance exposée est celle de l'appel réel.
async def execute_ai_model_council(args: dict) -> dict:
    """Conseil de cinq modèles Ollama Cloud appartenant à cinq familles différentes.

    Le premier tour est indépendant. Un membre critique ensuite les réponses anonymisées,
    puis un autre arbitre l'ensemble dans l'ordre inverse pour réduire le biais de position.
    """
    question = (args.get("question") or args.get("query") or "").strip()
    if not question:
        return {"error": "Paramètre 'question' requis."}
    evidence = (args.get("evidence") or args.get("context") or "").strip()
    panel_size = 5

    import cloud_routing as _cr
    import httpx as _hx
    cloud_enabled, _ = _cr.get_cloud_config()
    if not cloud_enabled:
        return {"error": "Le mode cloud n'est pas activé — Council v2 exige cinq modèles Ollama Cloud."}
    if _cr.is_local_only_lockdown():
        return {"error": "Le mode Hyper local interdit Council Cloud. Passe en mode Normal, Tout cloud ou Ultra débridé."}
    sensitive = _cr.is_sensitive_text(question + "\n" + evidence)
    if sensitive and not _cr.is_ultra_unrestricted():
        return {"error": "Donnée sensible détectée : les cinq avis cloud sont bloqués hors mode Ultra débridé."}

    need = _cr.detect_task(question) or "general"
    candidates = _cr.list_distinct_cloud_models(need)
    if len(candidates) < panel_size:
        return {
            "error": f"Council v2 requiert 5 familles cloud distinctes ; {len(candidates)} seulement sont disponibles.",
            "available_models": candidates,
        }

    roles = (
        ("analyste", "Construis la meilleure solution et explicite les hypothèses décisives."),
        ("critique", "Cherche les erreurs, contre-exemples, risques et hypothèses cachées."),
        ("vérificateur", "Contrôle la solidité factuelle, les preuves et ce qui reste incertain."),
        ("alternatif", "Propose une approche réellement différente et compare ses compromis."),
        ("praticien", "Transforme l'analyse en décision concrète, testable et priorisée."),
    )
    try:
        concurrency = max(1, min(int(db.get_setting("council_concurrency") or 3), panel_size))
    except Exception:
        concurrency = 3
    semaphore = asyncio.Semaphore(concurrency)

    async def _cloud_call(client, model: str, prompt: str, phase: str) -> dict:
        started = time.perf_counter()
        attempts = []
        async with semaphore:
            for attempt in range(1, 3):
                try:
                    response = await client.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": False},
                    )
                    response.raise_for_status()
                    text = (response.json().get("response") or "").strip()
                    if not text:
                        raise RuntimeError("réponse vide")
                    return {
                        "ok": True, "model": model, "family": _cr.model_family(model),
                        "source": "ollama_cloud", "phase": phase, "answer": text,
                        "attempts": attempt, "duration_ms": int((time.perf_counter() - started) * 1000),
                    }
                except Exception as exc:
                    attempts.append(f"{type(exc).__name__}: {str(exc)[:180]}")
                    if isinstance(exc, _hx.TimeoutException):
                        break
                    if attempt == 1:
                        await asyncio.sleep(0.5)
        return {
            "ok": False, "model": model, "family": _cr.model_family(model),
            "source": "ollama_cloud", "phase": phase, "attempts": len(attempts),
            "duration_ms": int((time.perf_counter() - started) * 1000), "errors": attempts,
        }

    context_block = f"\n\nÉLÉMENTS VÉRIFIÉS FOURNIS :\n{evidence[:12000]}" if evidence else ""
    async with _hx.AsyncClient(timeout=_hx.Timeout(150.0, connect=10.0)) as client:
        selected = candidates[:panel_size]
        prompts = []
        for index, ((role, instruction), model) in enumerate(zip(roles, selected)):
            prompts.append((model, (
                f"Tu es le membre {index + 1} d'un conseil, rôle : {role}. {instruction}\n"
                "Travaille indépendamment : ne suppose pas ce que diront les autres. Réponds en français "
                "avec les sections Recommandation, Raisons, Preuves ou vérifications nécessaires, Risques, "
                f"Incertitudes et Confiance (0-100).\n\nQUESTION :\n{question}{context_block}"
            )))
        results = list(await asyncio.gather(*[
            _cloud_call(client, model, prompt, "independent") for model, prompt in prompts
        ]))
        panel_attempt_log = []
        for index, result in enumerate(results):
            result["slot"] = index + 1
            result["role"] = roles[index][0]
            panel_attempt_log.append(dict(result))

        # Un membre défaillant est remplacé par une AUTRE famille disponible. Aucun repli
        # local n'est autorisé, sinon la provenance et la diversité seraient mensongères.
        reserve = candidates[panel_size:]
        for index, result in enumerate(list(results)):
            if result.get("ok"):
                continue
            while reserve:
                replacement = reserve.pop(0)
                retried = await _cloud_call(client, replacement, prompts[index][1], "independent_replacement")
                retried["slot"] = index + 1
                retried["role"] = roles[index][0]
                panel_attempt_log.append(dict(retried))
                results[index] = retried
                if retried.get("ok"):
                    break

        successful = [item for item in results if item.get("ok")]
        if len(successful) != panel_size or len({_cr.model_family(x["model"]) for x in successful}) != panel_size:
            return {
                "error": "Impossible d'obtenir cinq réponses cloud issues de cinq familles distinctes.",
                "attempted": panel_attempt_log,
            }

        anonymous = [
            {"id": chr(65 + i), "answer": item["answer"][:4500]}
            for i, item in enumerate(successful)
        ]
        forward_digest = "\n\n".join(f"[AVIS {x['id']}]\n{x['answer']}" for x in anonymous)
        critic_prompt = (
            "Tu es le contradicteur d'un conseil. Les avis sont anonymisés : ne devine pas les modèles. "
            "Identifie les affirmations non étayées, contradictions, consensus trompeurs et l'avis minoritaire "
            "qui pourrait être juste. Termine par les critères que l'arbitre doit appliquer.\n\n"
            f"QUESTION : {question}\n\n{forward_digest}"
        )
        critique = await _cloud_call(client, successful[3]["model"], critic_prompt, "cross_critique")

        reverse_digest = "\n\n".join(
            f"[AVIS {x['id']}]\n{x['answer']}" for x in reversed(anonymous)
        )
        judge_prompt = (
            "Tu es l'arbitre final. Les cinq avis sont anonymisés et présentés dans un ordre inversé par "
            "rapport au contradicteur. Ne vote pas à la majorité : juge les preuves, le respect des contraintes, "
            "les risques et l'applicabilité. Préserve explicitement un désaccord important au lieu de fabriquer "
            "un consensus. Réponds en français avec : Réponse retenue, Pourquoi, Consensus solide, Désaccords, "
            "Incertitudes, Plan d'action et Confiance globale (0-100).\n\n"
            f"QUESTION : {question}\n\nAVIS :\n{reverse_digest}\n\n"
            f"REVUE CONTRADICTOIRE :\n{critique.get('answer', 'indisponible')[:5000]}"
        )
        judge_order = [successful[0], successful[2], successful[1], successful[4]]
        arbitration = None
        for judge in judge_order:
            attempt = await _cloud_call(client, judge["model"], judge_prompt, "arbitration")
            if attempt.get("ok"):
                arbitration = attempt
                break
        if not arbitration:
            return {"error": "Les cinq avis ont répondu, mais l'arbitrage cloud a échoué.", "panel": successful}

    return {
        "success": True,
        "answer": arbitration["answer"],
        "models_consulted": [item["model"] for item in successful],
        "families": [item["family"] for item in successful],
        "panel_size": panel_size,
        "concurrency": concurrency,
        "individual_answers": successful,
        "panel_attempt_log": panel_attempt_log,
        "critique": critique,
        "arbitration": arbitration,
        "privacy_mode": "ultra_unrestricted" if _cr.is_ultra_unrestricted() else "cloud_non_sensitive",
        "message": "Council v2 terminé : 5 familles cloud, critique croisée et arbitrage traçable.",
    }


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
    """Essaim de cinq chercheurs cloud spécialisés avec recherche web et vérification croisée."""
    question = (args.get("question") or args.get("query") or "").strip()
    try:
        agent_count = int(args.get("agent_count") or 5)
        sources_per_agent = int(args.get("sources_per_agent") or 3)
    except (TypeError, ValueError):
        agent_count, sources_per_agent = 5, 3
    import research_swarm
    return await research_swarm.execute(
        question, agent_count=agent_count, sources_per_agent=sources_per_agent,
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


# v2.145 — « Ultra mode » (GPT-5.6 Sol, juillet 2026) : au lieu d'une seule chaîne de
# raisonnement séquentielle, décompose un objectif en sous-tâches INDÉPENDANTES traitées
# EN PARALLÈLE, puis synthétise. Positionnement HONNÊTE (pas de survente) : contrairement
# à Ultra qui orchestre de vrais sous-agents avec accès aux outils (coordination "dans les
# poids" du modèle), ceci décompose puis fait raisonner des appels LLM en parallèle SANS
# accès aux outils — un vrai gain de rapidité/qualité sur les tâches qui se décomposent en
# angles indépendants (ex. rédiger une politique de sécurité en 3 volets), pas un
# framework d'agents généraliste. Complète `ai_model_council` (même question, plusieurs
# modèles) avec l'axe perpendiculaire (même modèle/plusieurs modèles, sous-questions
# différentes d'un même objectif).
async def execute_ai_subagents_run(args: dict) -> dict:
    """Décompose un objectif en sous-tâches indépendantes, les traite EN PARALLÈLE (raisonnement,
    pas d'accès aux outils), puis synthétise en un résultat cohérent. Pour un objectif qui se
    découpe naturellement en plusieurs angles (ex. « rédige une politique de sécurité couvrant
    accès/incidents/sauvegardes ») — plus rapide et plus complet qu'un seul passage linéaire.
    PAS pour une tâche qui nécessite des outils (fichiers, PC, web) — pour ça, la boucle
    d'agent normale est plus appropriée."""
    goal = (args.get("goal") or args.get("objectif") or "").strip()
    if not goal:
        return {"error": "Paramètre 'goal' requis (l'objectif à décomposer)."}
    subtasks = args.get("subtasks") or []

    if not subtasks:
        decompose_prompt = (
            f"Objectif : {goal}\n\n"
            "Décompose cet objectif en 2 à 5 sous-tâches INDÉPENDANTES (chacune traitable "
            "séparément, sans dépendre du résultat des autres). Réponds UNIQUEMENT par une "
            "liste à puces, une sous-tâche par ligne, formulée comme une consigne claire — "
            "rien d'autre (pas de préambule, pas de numérotation autre que les puces)."
        )
        try:
            raw = (await _ollama_generate(decompose_prompt, model=args.get("model"), timeout=90) or "")
        except Exception:
            raw = ""
        subtasks = [
            line.lstrip("-•* ").strip()
            for line in raw.splitlines()
            if line.strip() and line.lstrip().startswith(("-", "•", "*"))
        ][:5]
    if len(subtasks) < 2:
        return {"error": "Impossible de décomposer cet objectif en sous-tâches indépendantes — utilise la boucle d'agent normale pour une tâche unique."}

    async def _work(subtask: str):
        prompt = (
            f"Objectif global : {goal}\n\n"
            f"Ta sous-tâche (traite UNIQUEMENT celle-ci, en profondeur) : {subtask}\n\n"
            "Réponds de façon complète et autonome à cette sous-tâche."
        )
        try:
            return await _ollama_generate(prompt, model=args.get("model"), timeout=180)
        except Exception as e:
            return f"(échec : {str(e)[:100]})"

    results = await asyncio.gather(*[_work(s) for s in subtasks])

    digest = "\n\n".join(
        f"### Sous-tâche {i+1} : {s}\n{(r or '').strip()}"
        for i, (s, r) in enumerate(zip(subtasks, results)))
    synth_prompt = (
        f"Objectif global : {goal}\n\n"
        f"Voici les résultats de {len(subtasks)} sous-tâches traitées en parallèle :\n\n{digest}\n\n"
        "Fusionne ces résultats en UN document cohérent qui répond à l'objectif global — "
        "structuré, sans répétition entre les parties, transitions naturelles entre les "
        "sections. Ne résume pas superficiellement : intègre le contenu réel de chaque "
        "sous-tâche."
    )
    synthesis = (await _ollama_generate(synth_prompt, model=args.get("model"), timeout=240) or "").strip()

    return {
        "success": True,
        "answer": synthesis,
        "subtasks": subtasks,
        "subtask_results": [{"subtask": s, "result": (r or "")[:2000]} for s, r in zip(subtasks, results)],
        "message": f"{len(subtasks)} sous-tâches traitées en parallèle puis fusionnées.",
    }


# v2.145 — « ChatGPT Work » (tâche longue autonome, juillet 2026) : décompose un objectif en
# checklist (table `tasks` déjà existante, tag `longtask:<slug>`) et programme un job CRON qui
# relance un VRAI tour d'agent (outils complets, pas juste du texte — via `run_agent`, cf.
# `main.py::_long_task_resume_tick`) toutes les 5 min jusqu'à ce que toutes les étapes soient
# faites. Réutilise l'infra cron+tasks déjà existante et testée plutôt que d'inventer un
# nouveau système d'exécution en arrière-plan. Positionnement HONNÊTE (pas de survente) :
# reprise toutes les 5 min, pas un process qui tourne en continu pendant des heures comme
# ChatGPT Work (infra cloud dédiée) — mais un vrai gain : Marvin continue d'avancer après
# avoir répondu, sans qu'on ait à relancer chaque étape soi-même.
async def execute_long_task_start(args: dict) -> dict:
    """Démarre une tâche longue autonome : décompose l'objectif en étapes (visibles dans
    Tâches), avance IMMÉDIATEMENT sur la première avec tes outils normaux, puis programme
    une reprise automatique (toutes les 5 min) jusqu'à ce que tout soit fait. Pour un
    objectif qui prend plusieurs étapes/outils et peut continuer sans supervision constante
    (« occupe-toi de X en tâche de fond », « fais avancer ce projet pendant que je fais
    autre chose »). PAS pour une question simple ou une action en un seul appel d'outil.
    ÉTAPE 1 (sans confirmed) : propose le plan pour validation — ne crée RIEN encore.
    ÉTAPE 2 (avec confirmed=true, mêmes 'goal'/'steps' que le plan proposé) : crée
    réellement les tâches et programme la reprise automatique."""
    goal = (args.get("goal") or "").strip()
    conversation_id = args.get("_conversation_id")
    if not goal:
        return {"error": "Paramètre 'goal' requis."}
    if not conversation_id:
        return {"error": "Cette tâche longue doit être démarrée depuis une conversation active."}

    # v2.151 — "Plan mode" (repris de ChatGPT Work, recherche menée avant implémentation) :
    # un plan proposé puis approuvé avant exécution, plutôt qu'exécuté aveuglément dès la
    # décomposition. Réutilise le même booléen `confirmed` que TOUS les autres outils
    # dangereux de Marvin (pc_run_command, pc_gui_click...) — aucun nouveau concept introduit.
    steps = [s.strip() for s in (args.get("steps") or []) if isinstance(s, str) and s.strip()][:8]
    if not (args.get("confirmed") and steps):
        decompose_prompt = (
            f"Objectif : {goal}\n\n"
            "Décompose en 2 à 8 ÉTAPES concrètes, dans l'ordre logique. IMPORTANT : ces étapes "
            "seront exécutées PAR UN ASSISTANT IA AUTONOME disposant d'outils (fichiers, "
            "commandes système, SSH, web, documents...) — PAS par un humain qui suit un mode "
            "d'emploi. Formule chaque étape comme une action que l'IA peut accomplir elle-même "
            "avec ses outils (ex. « lister les fichiers de X », « vérifier l'espace disque via "
            "une commande système »), jamais une instruction manuelle du type « cliquez sur », "
            "« appuyez sur la touche ». Réponds UNIQUEMENT par une liste à puces, une étape par "
            "ligne — rien d'autre."
        )
        try:
            raw = (await _ollama_generate(decompose_prompt, model=args.get("model"), timeout=90) or "")
        except Exception:
            raw = ""
        steps = [
            line.lstrip("-•* ").strip()
            for line in raw.splitlines()
            if line.strip() and line.lstrip().startswith(("-", "•", "*"))
        ][:8]
        if not steps:
            return {"error": "Impossible de décomposer cet objectif en étapes claires — reformule plus précisément."}

    if not args.get("confirmed"):
        plan_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
        return {
            "requiresConfirmation": True,
            "goal": goal, "steps": steps,
            "message": (f"Plan proposé pour « {goal} » ({len(steps)} étape(s)) :\n{plan_text}\n\n"
                        "Confirme pour démarrer la tâche longue (les mêmes 'steps' seront repris "
                        "tels quels), ou reformule l'objectif pour un plan différent."),
        }

    import re as _re, uuid as _uuid
    slug = _re.sub(r"[^a-z0-9]+", "-", goal.lower())[:40].strip("-") or _uuid.uuid4().hex[:8]
    tag = f"longtask:{slug}"
    created = [db.create_task(title=step, description=f"Étape de la tâche longue : {goal}", tags=[tag])
               for step in steps]

    try:
        db.create_cron_job(
            name=f"Reprise tâche longue : {goal[:60]}",
            tool_name="_long_task_resume",
            args={"conversation_id": conversation_id, "slug": slug, "goal": goal},
            schedule="every 5 minutes",
        )
    except Exception as e:
        return {"error": f"Étapes créées mais échec de la programmation de reprise automatique : {str(e)[:150]}",
                "steps": steps, "tag": tag}

    mission = None
    try:
        import mission_os
        mission = mission_os.create_mission(
            goal=goal,
            conversation_id=str(conversation_id),
            tag=tag,
            steps=steps,
            task_ids=[t["id"] for t in created],
        )
    except Exception:
        mission = None

    return {
        "success": True,
        "goal": goal,
        "steps": steps,
        "tag": tag,
        "task_ids": [t["id"] for t in created],
        "mission_id": mission.get("id") if mission else None,
        "message": (
            f"{len(steps)} étape(s) créée(s) (visibles dans Tâches, tag « {tag} »). "
            "Continue MAINTENANT sur la première étape avec tes outils normaux — la reprise "
            "automatique (toutes les 5 min) prendra le relais pour les étapes restantes."
        ),
    }


async def execute_long_task_status(args: dict) -> dict:
    """Vérifie l'avancement d'une ou de toutes les tâches longues (voir long_task_start)."""
    tag = (args.get("tag") or "").strip()
    all_tasks = db.list_tasks(limit=200)
    relevant = [t for t in all_tasks if any(tg.startswith("longtask:") for tg in (t.get("tags") or []))
                and (not tag or tag in (t.get("tags") or []))]
    if not relevant:
        return {"success": True, "count": 0, "message": "Aucune tâche longue en cours."}
    by_tag: dict[str, list] = {}
    for t in relevant:
        for tg in (t.get("tags") or []):
            if tg.startswith("longtask:"):
                by_tag.setdefault(tg, []).append(t)
    groups = [
        {"tag": tg, "total": len(tasks), "done": sum(1 for t in tasks if t.get("status") == "done"),
         # v2.145 — bug trouvé en testant en réel : sans 'id', le modèle n'a AUCUN moyen de
         # marquer une étape faite (task_update exige l'ID exact) — il inventait le tag ou
         # un numéro de position à la place, échec systématique.
         "steps": [{"id": t["id"], "title": t["title"], "status": t["status"]} for t in tasks]}
        for tg, tasks in by_tag.items()
    ]
    try:
        import mission_os
        for group in groups:
            mission = mission_os.find_active(tag=group["tag"])
            if mission:
                mission_os.sync_steps(mission["id"], [
                    {"id": step["id"], "status": step["status"]} for step in group["steps"]
                ])
                group["mission_id"] = mission["id"]
    except Exception:
        pass
    return {"success": True, "groups": groups, "message": f"{len(groups)} tâche(s) longue(s) trouvée(s)."}


async def execute_long_task_stop(args: dict) -> dict:
    """Arrête la reprise automatique d'une tâche longue (les étapes déjà faites restent, la
    checklist reste consultable — seule la reprise en arrière-plan s'arrête)."""
    tag = (args.get("tag") or "").strip()
    slug = tag.split(":", 1)[-1] if ":" in tag else tag
    if not slug:
        return {"error": "Paramètre 'tag' requis (voir long_task_status pour la liste)."}
    jobs = db.list_cron_jobs()
    stopped = 0
    for j in jobs:
        if j.get("tool_name") == "_long_task_resume" and (j.get("args") or {}).get("slug") == slug:
            db.update_cron_job(j["id"], {"enabled": False})
            stopped += 1
    try:
        import mission_os
        mission = mission_os.find_active(tag=f"longtask:{slug}")
        if mission:
            mission_os.stop_mission(mission["id"], "reprise automatique arrêtée")
    except Exception:
        pass
    return {"success": True, "stopped": stopped,
            "message": (f"{stopped} reprise(s) automatique(s) arrêtée(s)." if stopped
                        else "Aucune reprise automatique trouvée pour ce tag.")}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION VOICE — Transcription audio (faster-whisper)
# ══════════════════════════════════════════════════════════════════════════════

_whisper_model_cache: dict = {}

async def execute_voice_transcribe(args: dict) -> dict:
    """Transcrit un fichier audio local en texte via Whisper (faster-whisper)."""
    audio_path = args.get("audio_path", "").strip()
    model_size = args.get("model", "small")   # tiny, base, small, medium, large-v3
    language = args.get("language", None)    # None = détection auto
    if not audio_path:
        return {"error": "Paramètre 'audio_path' requis."}
    resolved = _resolve_path(audio_path)
    if not os.path.exists(resolved):
        return {"error": f"Fichier introuvable : {resolved}"}

    def _transcribe():
        global _whisper_model_cache
        if model_size not in _whisper_model_cache:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise RuntimeError("faster-whisper non installé. Exécutez : pip install faster-whisper")
            _whisper_model_cache[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
        model = _whisper_model_cache[model_size]
        segments, info = model.transcribe(
            resolved,
            beam_size=5,
            language=language,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, info.language

    try:
        loop = asyncio.get_running_loop()
        text, lang = await loop.run_in_executor(None, _transcribe)
        return {
            "success": True,
            "audio_file": resolved,
            "text": text,
            "language": lang,
            "char_count": len(text),
        }
    except Exception as e:
        return {"error": f"Transcription échouée : {e}"}


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

async def execute_calculator(args: dict) -> dict:
    """Évalue une expression mathématique de façon sécurisée."""
    expr = args.get("expression", "").strip()
    if not expr:
        return {"error": "Paramètre 'expression' requis. Ex: '(12 + 4) * 3 / 2'"}

    # Liste blanche de tokens autorisés : chiffres, opérateurs, fonctions math, constantes
    import math as _math
    import ast as _ast

    _SAFE_NAMES = {
        # constantes
        "pi": _math.pi, "e": _math.e, "inf": _math.inf, "nan": _math.nan,
        "tau": _math.tau,
        # fonctions de base
        "abs": abs, "round": round, "min": min, "max": max,
        "int": int, "float": float,
        # fonctions math
        "sqrt": _math.sqrt, "cbrt": lambda x: x ** (1/3),
        "sin": _math.sin, "cos": _math.cos, "tan": _math.tan,
        "asin": _math.asin, "acos": _math.acos, "atan": _math.atan,
        "atan2": _math.atan2,
        "log": _math.log, "log2": _math.log2, "log10": _math.log10,
        "exp": _math.exp, "pow": _math.pow,
        "floor": _math.floor, "ceil": _math.ceil, "trunc": _math.trunc,
        "factorial": _math.factorial, "gcd": _math.gcd,
        "degrees": _math.degrees, "radians": _math.radians,
        "hypot": _math.hypot, "comb": _math.comb, "perm": _math.perm,
    }

    try:
        # Sécurité : parser l'AST et rejeter tout nœud non-autorisé
        tree = _ast.parse(expr, mode="eval")

        # Nœuds contexte (Load/Store/Del) — toujours inoffensifs, apparaissent dans ast.walk
        _CTX_NODES = tuple(
            getattr(_ast, n) for n in ("Load", "Store", "Del", "AugLoad", "AugStore", "Param")
            if hasattr(_ast, n)
        )

        for node in _ast.walk(tree):
            if isinstance(node, (_ast.Module, _ast.Expr, _ast.Expression)):
                continue
            if isinstance(node, _CTX_NODES):
                continue
            if isinstance(node, (_ast.BinOp, _ast.UnaryOp, _ast.BoolOp,
                                   _ast.Compare, _ast.IfExp)):
                continue
            if isinstance(node, (_ast.Add, _ast.Sub, _ast.Mult, _ast.Div,
                                   _ast.Mod, _ast.Pow, _ast.FloorDiv,
                                   _ast.LShift, _ast.RShift, _ast.BitAnd,
                                   _ast.BitOr, _ast.BitXor, _ast.Invert,
                                   _ast.Not, _ast.UAdd, _ast.USub,
                                   _ast.Eq, _ast.NotEq, _ast.Lt, _ast.LtE,
                                   _ast.Gt, _ast.GtE,
                                   _ast.And, _ast.Or)):
                continue
            if isinstance(node, _ast.Constant):
                if not isinstance(node.value, (int, float, bool, complex)):
                    raise ValueError(f"Constante non autorisée : {node.value!r}")
                continue
            if isinstance(node, _ast.Call):
                # Vérifier que la fonction appelée est dans la whitelist
                if isinstance(node.func, _ast.Name) and node.func.id in _SAFE_NAMES:
                    continue
                raise ValueError(f"Appel de fonction non autorisé : {_ast.unparse(node.func)}")
            if isinstance(node, _ast.Name):
                if node.id in _SAFE_NAMES:
                    continue
                raise ValueError(f"Nom non autorisé : {node.id!r}")
            if isinstance(node, _ast.Tuple):
                continue
            # Arguments de la liste/keywords pour les appels de fonctions
            if isinstance(node, (_ast.arguments, _ast.arg, _ast.keyword)):
                continue
            raise ValueError(f"Expression non autorisée : {type(node).__name__}")

        result = eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, _SAFE_NAMES)

        # Guard against infinite/NaN results
        if isinstance(result, float):
            if _math.isinf(result):
                return {"error": "Résultat infini (division par zéro ou overflow)"}
            if _math.isnan(result):
                return {"error": "Résultat indéfini (NaN)"}

        # Formater le résultat
        if isinstance(result, float):
            if result == int(result) and abs(result) < 1e15:
                formatted = str(int(result))
            else:
                formatted = f"{result:.10g}"
        elif isinstance(result, int):
            # Truncate very large integers to avoid context window bloat
            s = str(result)
            if len(s) > 80:
                formatted = f"{s[:40]}…[{len(s)} chiffres]"
            else:
                formatted = s
        else:
            formatted = str(result)

        # Ensure result is JSON-serializable (large ints can be problematic)
        result_serializable = formatted if isinstance(result, int) and abs(result) > 10**15 else result

        return {
            "success":    True,
            "expression": expr,
            "result":     result_serializable,
            "formatted":  formatted,
        }
    except ZeroDivisionError:
        return {"error": "Division par zéro"}
    except OverflowError:
        return {"error": "Dépassement de capacité (résultat trop grand)"}
    except ValueError as e:
        msg = str(e)
        if "math domain" in msg:
            return {"error": f"Domaine mathématique invalide : {msg}"}
        return {"error": f"Expression non autorisée : {msg}"}
    except Exception as e:
        return {"error": f"Erreur de calcul : {e}"}


async def execute_datetime_info(args: dict) -> dict:
    """Retourne l'heure actuelle, effectue des conversions et calculs de dates."""
    from datetime import datetime, timezone, timedelta
    import zoneinfo

    action   = args.get("action", "now")   # now | convert | diff | add
    tz_name  = args.get("timezone", "Europe/Paris")
    dt_input = args.get("datetime", "")    # ISO 8601 pour convert/diff/add
    dt2      = args.get("datetime2", "")   # pour diff
    delta    = args.get("delta", {})       # pour add : {"days": 5, "hours": 2}

    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
        tz_name = "UTC"

    now_utc = datetime.now(timezone.utc)
    now_tz  = now_utc.astimezone(tz)

    if action == "now":
        return {
            "success":   True,
            "utc":       now_utc.isoformat(),
            "local":     now_tz.isoformat(),
            "timezone":  tz_name,
            "weekday":   now_tz.strftime("%A"),
            "formatted": now_tz.strftime("%d/%m/%Y %H:%M:%S %Z"),
            "unix":      int(now_utc.timestamp()),
        }

    if action == "convert":
        if not dt_input:
            return {"error": "Paramètre 'datetime' requis pour action=convert"}
        try:
            dt = datetime.fromisoformat(dt_input)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            converted = dt.astimezone(tz)
            return {
                "success":   True,
                "original":  dt.isoformat(),
                "converted": converted.isoformat(),
                "timezone":  tz_name,
                "formatted": converted.strftime("%d/%m/%Y %H:%M:%S %Z"),
            }
        except ValueError as e:
            return {"error": f"Format datetime invalide : {e}"}

    if action == "diff":
        if not dt_input or not dt2:
            return {"error": "Paramètres 'datetime' et 'datetime2' requis pour action=diff"}
        try:
            d1 = datetime.fromisoformat(dt_input)
            d2 = datetime.fromisoformat(dt2)
            if d1.tzinfo is None: d1 = d1.replace(tzinfo=timezone.utc)
            if d2.tzinfo is None: d2 = d2.replace(tzinfo=timezone.utc)
            diff = abs(d2 - d1)
            total_s = int(diff.total_seconds())
            return {
                "success":   True,
                "diff_seconds":     total_s,
                "diff_minutes":     round(total_s / 60, 2),
                "diff_hours":       round(total_s / 3600, 2),
                "diff_days":        diff.days,
                "human":            f"{diff.days}j {diff.seconds // 3600}h {(diff.seconds % 3600) // 60}min",
            }
        except ValueError as e:
            return {"error": f"Format datetime invalide : {e}"}

    if action == "add":
        if not dt_input:
            return {"error": "Paramètre 'datetime' requis pour action=add"}
        try:
            dt = datetime.fromisoformat(dt_input)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            td = timedelta(
                days=int(delta.get("days", 0)),
                hours=int(delta.get("hours", 0)),
                minutes=int(delta.get("minutes", 0)),
                seconds=int(delta.get("seconds", 0)),
                weeks=int(delta.get("weeks", 0)),
            )
            result = (dt + td).astimezone(tz)
            return {
                "success":   True,
                "original":  dt.isoformat(),
                "result":    result.isoformat(),
                "formatted": result.strftime("%d/%m/%Y %H:%M:%S %Z"),
            }
        except ValueError as e:
            return {"error": f"Format datetime invalide : {e}"}

    return {"error": f"Action inconnue : {action!r}. Utilisez : now, convert, diff, add"}


async def execute_unit_convert(args: dict) -> dict:
    """Convertit une valeur d'une unité à une autre (longueur, masse, temp., vitesse, surface…)."""
    value_raw = args.get("value")
    from_unit = args.get("from_unit", "").strip().lower()
    to_unit   = args.get("to_unit",   "").strip().lower()

    if value_raw is None:
        return {"error": "Paramètre 'value' requis"}
    try:
        value = float(value_raw)
    except (TypeError, ValueError):
        return {"error": f"Valeur numérique invalide : {value_raw!r}"}

    # Définir toutes les conversions en termes d'une unité de base
    # Format : { alias: (facteur_vers_base, unité_de_base) }
    UNITS: dict[str, tuple[float, str]] = {
        # Longueur (base: mètre)
        "m": (1, "m"), "metre": (1, "m"), "meter": (1, "m"), "metres": (1, "m"), "meters": (1, "m"),
        "km": (1000, "m"), "kilometre": (1000, "m"), "kilometer": (1000, "m"),
        "cm": (0.01, "m"), "centimetre": (0.01, "m"), "centimeter": (0.01, "m"),
        "mm": (0.001, "m"), "millimetre": (0.001, "m"), "millimeter": (0.001, "m"),
        "mile": (1609.344, "m"), "miles": (1609.344, "m"), "mi": (1609.344, "m"),
        "yard": (0.9144, "m"), "yards": (0.9144, "m"), "yd": (0.9144, "m"),
        "foot": (0.3048, "m"), "feet": (0.3048, "m"), "ft": (0.3048, "m"),
        "inch": (0.0254, "m"), "inches": (0.0254, "m"), "in": (0.0254, "m"),
        "nm": (1e-9, "m"), "nanometre": (1e-9, "m"),
        "au": (1.495978707e11, "m"),
        "ly": (9.461e15, "m"),
        # Masse (base: kg)
        "kg": (1, "kg"), "kilogram": (1, "kg"), "kilogramme": (1, "kg"),
        "g": (0.001, "kg"), "gram": (0.001, "kg"), "gramme": (0.001, "kg"),
        "mg": (1e-6, "kg"), "milligram": (1e-6, "kg"),
        "tonne": (1000, "kg"), "t": (1000, "kg"),
        "lb": (0.45359237, "kg"), "pound": (0.45359237, "kg"), "pounds": (0.45359237, "kg"), "lbs": (0.45359237, "kg"),
        "oz": (0.0283495, "kg"), "ounce": (0.0283495, "kg"), "ounces": (0.0283495, "kg"),
        "stone": (6.35029, "kg"),
        # Volume (base: litre)
        "l": (1, "L"), "litre": (1, "L"), "liter": (1, "L"), "litres": (1, "L"), "liters": (1, "L"),
        "ml": (0.001, "L"), "millilitre": (0.001, "L"), "milliliter": (0.001, "L"),
        "cl": (0.01, "L"), "centilitre": (0.01, "L"),
        "dl": (0.1, "L"), "decilitre": (0.1, "L"),
        "m3": (1000, "L"), "m³": (1000, "L"),
        "gallon": (3.78541, "L"), "gallons": (3.78541, "L"), "gal": (3.78541, "L"),
        "pint": (0.473176, "L"), "pints": (0.473176, "L"), "pt": (0.473176, "L"),
        "fl oz": (0.0295735, "L"),
        # Vitesse (base: m/s)
        "m/s": (1, "m/s"), "ms": (1, "m/s"),
        "km/h": (1/3.6, "m/s"), "kmh": (1/3.6, "m/s"), "kph": (1/3.6, "m/s"),
        "mph": (0.44704, "m/s"),
        "knot": (0.514444, "m/s"), "knots": (0.514444, "m/s"), "kt": (0.514444, "m/s"),
        # Surface (base: m²)
        "m2": (1, "m²"), "m²": (1, "m²"),
        "km2": (1e6, "m²"), "km²": (1e6, "m²"),
        "cm2": (1e-4, "m²"), "cm²": (1e-4, "m²"),
        "ha": (1e4, "m²"), "hectare": (1e4, "m²"),
        "acre": (4046.86, "m²"), "acres": (4046.86, "m²"),
        "ft2": (0.092903, "m²"), "sqft": (0.092903, "m²"),
        # Énergie (base: joule)
        "j": (1, "J"), "joule": (1, "J"), "joules": (1, "J"),
        "kj": (1000, "J"), "kilojoule": (1000, "J"),
        "cal": (4.184, "J"), "calorie": (4.184, "J"),
        "kcal": (4184, "J"), "kilocalorie": (4184, "J"),
        "kwh": (3.6e6, "J"), "wh": (3600, "J"),
        "ev": (1.602e-19, "J"),
        # Données numériques (base: octet/byte)
        "b": (1, "o"), "byte": (1, "o"), "bytes": (1, "o"),
        "ko": (1000, "o"), "kb": (1000, "o"), "kilobyte": (1000, "o"),
        "mo": (1e6, "o"), "mb": (1e6, "o"), "megabyte": (1e6, "o"),
        "go": (1e9, "o"), "gb": (1e9, "o"), "gigabyte": (1e9, "o"),
        "to": (1e12, "o"), "tb": (1e12, "o"), "terabyte": (1e12, "o"),
        "kib": (1024, "o"), "mib": (1048576, "o"), "gib": (1073741824, "o"),
    }

    # Températures — traitement spécial (pas linéaire pour certaines)
    TEMP_UNITS = {"c", "celsius", "°c", "f", "fahrenheit", "°f", "k", "kelvin"}

    def _temp_to_celsius(v: float, u: str) -> float:
        if u in ("c", "celsius", "°c"):
            return v
        if u in ("f", "fahrenheit", "°f"):
            return (v - 32) * 5 / 9
        if u in ("k", "kelvin"):
            return v - 273.15
        raise ValueError(f"Unité de température inconnue : {u}")

    def _celsius_to_unit(v: float, u: str) -> float:
        if u in ("c", "celsius", "°c"):
            return v
        if u in ("f", "fahrenheit", "°f"):
            return v * 9 / 5 + 32
        if u in ("k", "kelvin"):
            return v + 273.15
        raise ValueError(f"Unité de température inconnue : {u}")

    if from_unit in TEMP_UNITS or to_unit in TEMP_UNITS:
        try:
            celsius = _temp_to_celsius(value, from_unit)
            result  = _celsius_to_unit(celsius, to_unit)
        except ValueError as e:
            return {"error": str(e)}
        return {
            "success":   True,
            "value":     value,
            "from_unit": from_unit,
            "to_unit":   to_unit,
            "result":    round(result, 6),
            "formatted": f"{value} {from_unit} = {result:.6g} {to_unit}",
        }

    # Conversion linéaire
    if from_unit not in UNITS:
        return {"error": f"Unité source inconnue : '{from_unit}'. Exemples : m, km, kg, lb, L, °C, km/h…"}
    if to_unit not in UNITS:
        return {"error": f"Unité destination inconnue : '{to_unit}'."}

    f_factor, f_base = UNITS[from_unit]
    t_factor, t_base = UNITS[to_unit]
    if f_base != t_base:
        return {"error": f"Unités incompatibles : '{from_unit}' ({f_base}) ≠ '{to_unit}' ({t_base})"}

    result = value * f_factor / t_factor
    return {
        "success":   True,
        "value":     value,
        "from_unit": from_unit,
        "to_unit":   to_unit,
        "result":    round(result, 9),
        "formatted": f"{value} {from_unit} = {result:.6g} {to_unit}",
    }


async def execute_password_generate(args: dict) -> dict:
    """Génère un mot de passe ou PIN sécurisé avec les critères choisis."""
    import secrets
    import string

    length   = max(4, min(int(args.get("length", 16)), 128))
    include  = set(args.get("include", ["letters", "digits", "symbols"]))
    exclude  = str(args.get("exclude", ""))           # caractères à exclure
    count    = max(1, min(int(args.get("count", 1)), 20))   # nombre de mots de passe
    pin_mode = args.get("pin", False)                  # PIN numérique uniquement

    if pin_mode:
        charset = string.digits
    else:
        charset = ""
        if "letters" in include:
            charset += string.ascii_letters
        if "digits" in include:
            charset += string.digits
        if "symbols" in include:
            charset += "!@#$%^&*()-_=+[]{}|;:,.<>?"
        if not charset:
            charset = string.ascii_letters + string.digits

    # Retirer les caractères exclus
    for c in exclude:
        charset = charset.replace(c, "")

    if not charset:
        return {"error": "Aucun caractère disponible après exclusions."}

    passwords = []
    for _ in range(count):
        pwd = "".join(secrets.choice(charset) for _ in range(length))
        # Forcer au moins un caractère de chaque catégorie demandée (sauf PIN)
        if not pin_mode and count == 1:
            tries = 0
            while tries < 50:
                ok = True
                if "letters" in include and not any(c in string.ascii_letters for c in pwd):
                    ok = False
                if "digits" in include and not any(c in string.digits for c in pwd):
                    ok = False
                if "symbols" in include and not any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in pwd):
                    ok = False
                if ok:
                    break
                pwd = "".join(secrets.choice(charset) for _ in range(length))
                tries += 1
        passwords.append(pwd)

    return {
        "success":   True,
        "passwords": passwords,
        "length":    length,
        "charset_size": len(set(charset)),
        "note": f"{'PIN numérique' if pin_mode else f'Mot de passe {length} caractères'} généré avec {len(set(charset))} caractères possibles",
    }


async def execute_translate(args: dict) -> dict:
    """Traduit du texte via MyMemory (gratuit, 1000 req/j sans clé, + clé optionnelle)."""
    import httpx
    import urllib.parse

    text    = args.get("text", "").strip()
    # 'source'/'target' acceptés en alias de 'source_lang'/'target_lang' : sans ça, un appel
    # avec le mauvais nom de paramètre retombe silencieusement sur les défauts (auto→en) au
    # lieu de traduire vers la langue réellement demandée — pas une erreur visible, mais faux.
    source  = (args.get("source_lang") or args.get("source") or "auto").lower()
    target  = (args.get("target_lang") or args.get("target") or "en").lower()

    if not text:
        return {"error": "Paramètre 'text' requis."}
    if not target:
        return {"error": "Paramètre 'target_lang' requis. Ex: 'fr', 'en', 'es'."}

    import credentials_manager as cm
    api_key = cm.get_credential("mymemory_api_key") or ""

    # MyMemory ne supporte pas "auto" comme code source — on détecte la langue
    if source in ("auto", ""):
        try:
            from langdetect import detect as _detect
            source = _detect(text[:200]) or "fr"
        except Exception:
            source = "fr"

    # Si source == target, pas besoin de traduire
    if source.lower() == target.lower():
        return {
            "success":    True,
            "original":   text,
            "translated": text,
            "source_lang": source,
            "target_lang": target,
            "provider":   "local (même langue détectée)",
            "note":       f"Le texte est déjà en '{source}' — aucune traduction nécessaire.",
        }

    # MyMemory attend le format "fr|en" pour langpair
    langpair = f"{source}|{target}"

    # Découper le texte si > 500 chars (limite MyMemory par requête)
    chunks = [text[i:i+500] for i in range(0, len(text), 500)]
    translated_parts = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                params = {
                    "q":        chunk,
                    "langpair": langpair,
                }
                if api_key:
                    params["key"] = api_key

                resp = await client.get(
                    "https://api.mymemory.translated.net/get",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("responseStatus") == 200:
                    translated_parts.append(data["responseData"]["translatedText"])
                else:
                    return {"error": f"Erreur MyMemory : {data.get('responseDetails', 'inconnue')}"}

        translated = " ".join(translated_parts)
        return {
            "success":     True,
            "original":    text,
            "translated":  translated,
            "source_lang": source,
            "target_lang": target,
            "provider":    "MyMemory (mymemory.translated.net)",
        }
    except Exception as e:
        return {"error": f"Traduction échouée : {e}"}


# Cache for weather geocoding (city → lat/lon)
# Same city geocoded → reuse the coords (saves ~200ms per call)
_geocode_cache: dict = {}
_GEOCODE_CACHE_MAX = 100

# Reusable HTTPX client for weather API (HTTP/2, connection pooling)
# Initialized lazily on first call
_weather_client = None
_weather_client_lock = None

async def _get_weather_client():
    """Singleton httpx client with connection pooling for fast repeat calls."""
    global _weather_client, _weather_client_lock
    if _weather_client_lock is None:
        import asyncio as _aio
        _weather_client_lock = _aio.Lock()
    async with _weather_client_lock:
        if _weather_client is None:
            import httpx
            # httpx.Timeout requires all 4 params (connect/read/write/pool) or a single default value
            _weather_client = httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=3.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return _weather_client


async def execute_weather(args: dict) -> dict:
    """Récupère la météo actuelle ou prévisions via Open-Meteo (gratuit, sans clé API). Optimisé pour la rapidité."""
    from datetime import datetime, timezone

    city    = args.get("city", "Paris").strip()
    country = args.get("country", "FR").strip()
    days    = max(1, min(int(args.get("days", 1)), 7))

    cache_key = f"{city.lower()}|{country.lower()}"

    # 1. Géocodage — avec cache
    if cache_key in _geocode_cache:
        loc = _geocode_cache[cache_key]
    else:
        try:
            client = await _get_weather_client()
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 5, "language": "fr", "format": "json"},
            )
            geo.raise_for_status()
            geo_data = geo.json()
        except Exception as e:
            return {"error": f"Géocodage échoué : {e}"}

        results = geo_data.get("results", [])
        if not results:
            return {"error": f"Ville '{city}' non trouvée"}

        loc = next(
            (r for r in results if r.get("country_code", "").upper() == country.upper()),
            results[0]
        )
        # Cache for next time
        if len(_geocode_cache) >= _GEOCODE_CACHE_MAX:
            _geocode_cache.clear()
        _geocode_cache[cache_key] = loc

    lat, lon = loc["latitude"], loc["longitude"]
    city_name = f"{loc.get('name', city)}, {loc.get('country', '')}"

    # 2. Récupérer la météo via Open-Meteo (réutilise le client → plus rapide)
    try:
        client = await _get_weather_client()
        weather = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "forecast_days": days,
                "timezone": "auto",
            },
        )
        weather.raise_for_status()
        wdata = weather.json()
    except Exception as e:
        return {"error": f"API météo échouée : {e}"}

    # Interprétation des codes WMO
    WMO = {
        0: "Ciel dégagé ☀️", 1: "Principalement dégagé 🌤️", 2: "Partiellement nuageux ⛅",
        3: "Couvert ☁️", 45: "Brouillard 🌫️", 48: "Brouillard givrant 🌫️",
        51: "Bruine légère 🌦️", 53: "Bruine modérée 🌦️", 55: "Bruine dense 🌦️",
        61: "Pluie légère 🌧️", 63: "Pluie modérée 🌧️", 65: "Forte pluie 🌧️",
        71: "Légère neige 🌨️", 73: "Neige modérée 🌨️", 75: "Forte neige ❄️",
        77: "Grésil ❄️", 80: "Averses légères 🌦️", 81: "Averses modérées 🌦️",
        82: "Averses violentes ⛈️", 85: "Averses de neige 🌨️", 86: "Fortes averses de neige ❄️",
        95: "Orage ⛈️", 96: "Orage avec grêle ⛈️", 99: "Orage fort avec grêle ⛈️",
    }

    cur = wdata.get("current", {})
    wmo_code = cur.get("weather_code", 0)
    condition = WMO.get(wmo_code, f"Code {wmo_code}")

    current_weather = {
        "city":        city_name,
        "condition":   condition,
        "temperature": cur.get("temperature_2m"),
        "feels_like":  cur.get("apparent_temperature"),
        "humidity":    cur.get("relative_humidity_2m"),
        "wind_speed":  cur.get("wind_speed_10m"),
        "precipitation": cur.get("precipitation"),
    }

    # Prévisions journalières
    daily = wdata.get("daily", {})
    forecasts = []
    if daily:
        dates  = daily.get("time", [])
        maxT   = daily.get("temperature_2m_max", [])
        minT   = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])
        codes  = daily.get("weather_code", [])
        for i in range(min(len(dates), days)):
            forecasts.append({
                "date":        dates[i],
                "condition":   WMO.get(codes[i] if i < len(codes) else 0, "?"),
                "temp_max":    maxT[i] if i < len(maxT) else None,
                "temp_min":    minT[i] if i < len(minT) else None,
                "precipitation": precip[i] if i < len(precip) else None,
            })

    return {
        "success": True,
        "current": current_weather,
        "forecasts": forecasts,
        "source": "Open-Meteo (open-meteo.com)",
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 15 — Outils de traitement de données
# ══════════════════════════════════════════════════════════════════════════════

async def execute_hash_compute(args: dict) -> dict:
    """Calcule le hash cryptographique d'un texte ou fichier."""
    import hashlib as _hashlib

    algorithm = args.get("algorithm", "sha256").lower()
    text      = args.get("text", "")
    file_path = args.get("file_path", "")

    supported = ["md5", "sha1", "sha256", "sha512"]
    if algorithm not in supported:
        return {"error": f"Algorithme non supporté. Utilisez : {', '.join(supported)}"}

    h = _hashlib.new(algorithm)

    if file_path:
        try:
            resolved = _resolve_path(file_path)
            with open(resolved, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            return {
                "success":   True,
                "algorithm": algorithm.upper(),
                "hash":      digest,
                "source":    "file",
                "file":      str(resolved),
            }
        except FileNotFoundError:
            return {"error": f"Fichier introuvable : {file_path}"}
        except Exception as e:
            return {"error": str(e)}
    elif text:
        h.update(text.encode("utf-8"))
        return {
            "success":   True,
            "algorithm": algorithm.upper(),
            "hash":      h.hexdigest(),
            "source":    "text",
        }
    else:
        return {"error": "Fournissez 'text' ou 'file_path'."}


async def execute_base64_tool(args: dict) -> dict:
    """Encode ou décode du Base64."""
    import base64 as _b64

    action = args.get("action", "encode").lower()  # encode | decode
    data   = args.get("data", "")
    url_safe = args.get("url_safe", False)

    if not data:
        return {"error": "Paramètre 'data' requis."}

    try:
        if action == "encode":
            raw = data.encode("utf-8")
            if url_safe:
                result = _b64.urlsafe_b64encode(raw).decode("ascii")
            else:
                result = _b64.b64encode(raw).decode("ascii")
            return {"success": True, "action": "encode", "result": result, "length": len(result)}
        elif action == "decode":
            try:
                if url_safe:
                    decoded = _b64.urlsafe_b64decode(data + "==").decode("utf-8")
                else:
                    decoded = _b64.b64decode(data + "==").decode("utf-8")
            except UnicodeDecodeError:
                decoded = f"<données binaires — {len(_b64.b64decode(data + '=='))} octets>"
            return {"success": True, "action": "decode", "result": decoded}
        else:
            return {"error": "Action invalide. Utilisez 'encode' ou 'decode'."}
    except Exception as e:
        return {"error": str(e)}


async def execute_text_extract(args: dict) -> dict:
    """Extrait des emails, URLs ou numéros de téléphone d'un texte."""
    import re as _re

    text    = args.get("text", "")
    extract = args.get("extract", "all").lower()  # emails | urls | phones | all

    if not text:
        return {"error": "Paramètre 'text' requis."}

    results = {}

    if extract in ("emails", "all"):
        emails = _re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
        results["emails"] = sorted(set(emails))

    if extract in ("urls", "all"):
        urls = _re.findall(
            r"https?://[^\s\"\'\)\]>]+",
            text,
        )
        results["urls"] = sorted(set(u.rstrip(".,;") for u in urls))

    if extract in ("phones", "all"):
        phones = _re.findall(
            r"(?:\+33|0033|0)[1-9](?:[.\- ]?\d{2}){4}"
            r"|(?:\+\d{1,3}[\s\-]?)?\(?\d{3,4}\)?[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}",
            text,
        )
        results["phones"] = sorted(set(phones))

    total = sum(len(v) for v in results.values())
    return {
        "success": True,
        "extracted": extract,
        **results,
        "total_found": total,
    }


async def execute_diff_text(args: dict) -> dict:
    """Compare deux textes et retourne les différences ligne par ligne."""
    import difflib as _difflib

    text_a    = args.get("text_a", "")
    text_b    = args.get("text_b", "")
    mode      = args.get("mode", "unified")  # unified | context | ndiff | ratio
    n_context = int(args.get("context_lines", 3))

    if mode == "ratio":
        ratio = _difflib.SequenceMatcher(None, text_a, text_b).ratio()
        return {
            "success":     True,
            "mode":        "ratio",
            "similarity":  round(ratio * 100, 2),
            "message":     f"Les textes sont similaires à {round(ratio*100,1)} %.",
        }

    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)

    if mode == "unified":
        diff = list(_difflib.unified_diff(lines_a, lines_b, fromfile="texte_a", tofile="texte_b", n=n_context))
    elif mode == "context":
        diff = list(_difflib.context_diff(lines_a, lines_b, fromfile="texte_a", tofile="texte_b", n=n_context))
    else:  # ndiff
        diff = list(_difflib.ndiff(lines_a, lines_b))

    diff_str = "".join(diff)
    added   = diff_str.count("\n+")
    removed = diff_str.count("\n-")

    return {
        "success":      True,
        "mode":         mode,
        "diff":         diff_str or "(Textes identiques)",
        "lines_added":  added,
        "lines_removed": removed,
        "identical":    not bool(diff_str.strip()),
    }




async def execute_qr_generate(args: dict) -> dict:
    """Génère un QR code en PNG depuis un texte ou URL."""
    data        = args.get("data", "").strip()
    output_path = args.get("output_path", "").strip()
    size        = int(args.get("size", 10))          # box_size
    border      = int(args.get("border", 4))
    fg_color    = args.get("fg_color", "black")
    bg_color    = args.get("bg_color", "white")

    if not data:
        return {"error": "Paramètre 'data' requis."}

    try:
        import qrcode as _qr
    except ImportError:
        return {"error": "qrcode non installé. Installez avec : pip install qrcode[pil]"}

    try:
        qr = _qr.QRCode(
            version=1,
            error_correction=_qr.constants.ERROR_CORRECT_L,
            box_size=size,
            border=border,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color=fg_color, back_color=bg_color)

        if not output_path:
            import re as _re2
            desktop = Path(_resolve_path("~/Desktop"))
            safe_name = _re2.sub(r"[^\w\-]", "_", data[:30]).strip("_") or "qrcode"
            out = desktop / f"qr_{safe_name}.png"
        else:
            out = Path(_resolve_path(output_path))

        img.save(str(out))

        return {
            "success":     True,
            "output":      str(out),
            "data":        data,
            "size_px":     list(img.size),
            "size_kb":     round(out.stat().st_size / 1024, 1),
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_json_tool(args: dict) -> dict:
    """Formate, valide, minifie ou interroge (JSONPath) un JSON."""
    import json as _json

    action = args.get("action", "format").lower()  # format | minify | validate | query
    # 'json' accepté en alias de 'data' — le modèle confond parfois les deux noms.
    data   = args.get("data") or args.get("json", "")
    path   = args.get("path", "")  # JSONPath simple : "$.key.subkey[0]"

    if not data:
        return {"error": "Paramètre 'data' (JSON en texte) requis."}

    try:
        parsed = _json.loads(data)
    except _json.JSONDecodeError as e:
        return {"error": f"JSON invalide : {e}", "valid": False}

    if action == "validate":
        return {"success": True, "valid": True, "message": "JSON valide.", "type": type(parsed).__name__}

    if action == "format":
        return {"success": True, "result": _json.dumps(parsed, ensure_ascii=False, indent=2)}

    if action == "minify":
        return {"success": True, "result": _json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))}

    if action == "query":
        if not path:
            return {"error": "Paramètre 'path' requis pour l'action 'query' (ex: 'key.subkey')."}
        # Simple dot-notation traversal (subset of JSONPath)
        keys = path.lstrip("$.").split(".")
        current = parsed
        try:
            for k in keys:
                if k == "": continue
                # Gestion des indices : key[0]
                bracket = k.find("[")
                if bracket >= 0:
                    idx = int(k[bracket+1:-1])
                    k   = k[:bracket]
                    if k: current = current[k]
                    current = current[idx]
                else:
                    current = current[k]
            return {"success": True, "result": _json.dumps(current, ensure_ascii=False, indent=2) if not isinstance(current, (str, int, float, bool)) else current}
        except (KeyError, IndexError, TypeError) as e:
            return {"error": f"Chemin introuvable : {path} — {e}"}

    return {"error": f"Action inconnue : {action}. Utilisez format | minify | validate | query."}


async def execute_markdown_convert(args: dict) -> dict:
    """Convertit du Markdown en HTML ou en texte brut."""
    import re as _re

    text   = args.get("text", "")
    to     = args.get("to", "html").lower()  # html | plain | stats

    if not text:
        return {"error": "Paramètre 'text' requis."}

    if to == "stats":
        headings = len(_re.findall(r"^#{1,6}\s", text, _re.MULTILINE))
        links    = len(_re.findall(r"\[.+?\]\(.+?\)", text))
        images   = len(_re.findall(r"!\[.+?\]\(.+?\)", text))
        code_blocks = len(_re.findall(r"```", text)) // 2
        return {"success": True, "headings": headings, "links": links, "images": images, "code_blocks": code_blocks}

    if to == "plain":
        # Strip markdown markup
        plain = _re.sub(r"#+\s", "", text)
        plain = _re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", plain)
        plain = _re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", plain)
        plain = _re.sub(r"`{1,3}(.+?)`{1,3}", r"\1", plain, flags=_re.DOTALL)
        plain = _re.sub(r"!\[.*?\]\(.*?\)", "", plain)
        plain = _re.sub(r"\[(.+?)\]\(.+?\)", r"\1", plain)
        plain = _re.sub(r"^\s*[-*+]\s", "", plain, flags=_re.MULTILINE)
        plain = _re.sub(r"^\s*\d+\.\s", "", plain, flags=_re.MULTILINE)
        plain = _re.sub(r"---+|===+", "", plain)
        return {"success": True, "format": "plain", "result": plain.strip()}

    # HTML conversion (basic markdown → HTML)
    html = text

    # Code blocks first (to avoid processing inside them)
    blocks = {}
    def save_block(m):
        key = f"__BLOCK_{len(blocks)}__"
        lang = m.group(1) or ""
        code = m.group(2).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        blocks[key] = f'<pre><code class="language-{lang}">{code}</code></pre>'
        return key
    html = _re.sub(r"```(\w*)\n?([\s\S]*?)```", save_block, html)

    # Inline code
    html = _re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    # Headings
    for i in range(6, 0, -1):
        html = _re.sub(r"^#{" + str(i) + r"}\s+(.+)$", rf"<h{i}>\1</h{i}>", html, flags=_re.MULTILINE)
    # Bold & italic
    html = _re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", html)
    html = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = _re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
    html = _re.sub(r"___(.+?)___", r"<strong><em>\1</em></strong>", html)
    html = _re.sub(r"__(.+?)__", r"<strong>\1</strong>", html)
    html = _re.sub(r"_(.+?)_", r"<em>\1</em>", html)
    # Links and images
    html = _re.sub(r"!\[(.+?)\]\((.+?)\)", r'<img src="\2" alt="\1">', html)
    html = _re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', html)
    # Lists
    html = _re.sub(r"^[-*+]\s+(.+)$", r"<li>\1</li>", html, flags=_re.MULTILINE)
    html = _re.sub(r"(<li>.*</li>\n?)+", lambda m: f"<ul>{m.group(0)}</ul>", html)
    # Horizontal rule
    html = _re.sub(r"^---+$", "<hr>", html, flags=_re.MULTILINE)
    # Line breaks → paragraphs (double newline)
    paragraphs = _re.split(r"\n\n+", html)
    html = "\n".join(
        f"<p>{p.strip()}</p>" if not _re.match(r"^<(h\d|ul|ol|li|pre|blockquote|hr)", p.strip()) else p.strip()
        for p in paragraphs if p.strip()
    )
    # Restore code blocks
    for key, val in blocks.items():
        html = html.replace(key, val)

    return {"success": True, "format": "html", "result": html}


async def execute_regex_tool(args: dict) -> dict:
    """Applique une expression régulière à un texte (recherche, extraction, remplacement)."""
    import re as _re

    pattern  = args.get("pattern", "")
    text     = args.get("text", "")
    action   = args.get("action", "findall").lower()  # findall | match | replace | split | test
    replace  = args.get("replace", "")
    flags_str = args.get("flags", "").upper()
    max_results = int(args.get("max_results", 100))

    if not pattern:
        return {"error": "Paramètre 'pattern' requis."}
    if not text and action != "test":
        return {"error": "Paramètre 'text' requis."}

    # Flags
    flags = 0
    if "I" in flags_str: flags |= _re.IGNORECASE
    if "M" in flags_str: flags |= _re.MULTILINE
    if "S" in flags_str: flags |= _re.DOTALL

    try:
        compiled = _re.compile(pattern, flags)
    except _re.error as e:
        return {"error": f"Expression régulière invalide : {e}"}

    try:
        if action == "test":
            match = compiled.search(text)
            return {"success": True, "action": "test", "matches": bool(match), "pattern": pattern}

        if action == "findall":
            matches = compiled.findall(text)[:max_results]
            return {"success": True, "action": "findall", "count": len(matches), "matches": matches}

        if action == "match":
            m = compiled.match(text)
            if not m:
                return {"success": True, "action": "match", "matched": False}
            return {"success": True, "action": "match", "matched": True,
                    "groups": list(m.groups()), "span": list(m.span())}

        if action == "replace":
            result = compiled.sub(replace, text)
            return {"success": True, "action": "replace", "result": result,
                    "replacements": len(compiled.findall(text))}

        if action == "split":
            parts = compiled.split(text)[:max_results]
            return {"success": True, "action": "split", "count": len(parts), "parts": parts}

        return {"error": f"Action inconnue : {action}. Utilisez findall | match | replace | split | test."}
    except Exception as e:
        return {"error": str(e)}


async def execute_csv_analyze(args: dict) -> dict:
    """Analyse un fichier CSV : aperçu, statistiques et valeurs uniques."""
    import csv as _csv, io as _io, statistics as _stats

    path       = args.get("path", "").strip()
    max_rows   = int(args.get("max_rows", 100))    # lignes à charger pour stats
    action     = args.get("action", "summary")     # summary | head | stats | unique
    column     = args.get("column", "")            # pour stats/unique sur une colonne
    delimiter  = args.get("delimiter", ",")

    if not path:
        return {"error": "Paramètre 'path' requis."}

    try:
        resolved = _resolve_path(path)
        with open(resolved, encoding="utf-8-sig", errors="replace") as f:
            raw = f.read(2 * 1024 * 1024)  # 2 MB max

        reader = _csv.DictReader(_io.StringIO(raw), delimiter=delimiter)
        headers = reader.fieldnames or []

        rows = []
        for i, row in enumerate(reader):
            if i >= max_rows: break
            rows.append(dict(row))

        total_rows_approx = raw.count("\n")
        base = {
            "success":      True,
            "file":         str(resolved),
            "columns":      list(headers),
            "column_count": len(headers),
            "rows_loaded":  len(rows),
            "total_rows_approx": total_rows_approx - 1,  # -1 pour l'en-tête
        }

        if action == "head":
            base["preview"] = rows[:10]
            return base

        if action == "unique":
            if not column or column not in headers:
                return {**base, "error": f"Colonne '{column}' introuvable. Colonnes disponibles : {headers}"}
            vals = sorted({r[column] for r in rows if r.get(column) not in ("", None)})
            return {**base, "column": column, "unique_values": vals[:200], "unique_count": len(vals)}

        if action == "stats":
            if not column or column not in headers:
                return {**base, "error": f"Colonne '{column}' introuvable. Colonnes disponibles : {headers}"}
            nums = []
            for r in rows:
                v = r.get(column, "")
                try: nums.append(float(v.replace(",", ".").strip()))
                except: pass
            if not nums:
                return {**base, "column": column, "error": "Aucune valeur numérique dans cette colonne."}
            return {
                **base, "column": column,
                "count":   len(nums),
                "sum":     round(sum(nums), 6),
                "mean":    round(_stats.mean(nums), 6),
                "median":  round(_stats.median(nums), 6),
                "min":     min(nums),
                "max":     max(nums),
                "stdev":   round(_stats.stdev(nums), 6) if len(nums) > 1 else 0,
            }

        # default: summary
        col_stats = {}
        for col in headers:
            vals = [r.get(col, "") for r in rows]
            non_empty = [v for v in vals if v not in ("", None)]
            nums = []
            for v in non_empty:
                try: nums.append(float(str(v).replace(",", ".").strip()))
                except: pass
            col_stats[col] = {
                "non_empty": len(non_empty),
                "empty":     len(vals) - len(non_empty),
                "unique":    len(set(non_empty)),
                "numeric":   len(nums) == len(non_empty) and len(nums) > 0,
            }
            if nums:
                col_stats[col]["min"]  = min(nums)
                col_stats[col]["max"]  = max(nums)
                col_stats[col]["mean"] = round(_stats.mean(nums), 4)

        base["column_analysis"] = col_stats
        base["preview"] = rows[:5]
        return base

    except FileNotFoundError:
        return {"error": f"Fichier introuvable : {path}"}
    except Exception as e:
        return {"error": str(e)}


async def execute_text_stats(args: dict) -> dict:
    """Calcule des statistiques sur un texte : mots, caractères, phrases, temps de lecture."""
    import re as _re, collections as _coll

    text    = args.get("text", "")
    top_n   = int(args.get("top_words", 10))

    if not text:
        return {"error": "Paramètre 'text' requis."}

    # Comptages de base
    chars          = len(text)
    chars_no_space = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    words_list     = _re.findall(r"\b\w+\b", text)
    word_count     = len(words_list)
    sentences      = len(_re.findall(r"[.!?]+", text)) or 1
    paragraphs     = len([p for p in text.split("\n\n") if p.strip()])
    lines          = text.count("\n") + 1

    # Temps de lecture estimé (250 mots/min)
    read_seconds = round(word_count / 250 * 60)
    read_label = f"{read_seconds // 60}m {read_seconds % 60}s" if read_seconds >= 60 else f"{read_seconds}s"

    # Mots les plus fréquents (stopwords basiques FR/EN filtrés)
    stopwords = {
        "le", "la", "les", "de", "du", "des", "et", "en", "un", "une",
        "à", "au", "aux", "que", "qui", "dans", "est", "il", "elle",
        "on", "se", "ce", "je", "tu", "vous", "nous", "ils", "elles",
        "the", "a", "an", "of", "in", "to", "is", "it", "and", "or",
        "for", "that", "this", "with", "are", "was", "be", "as", "at",
    }
    freq = _coll.Counter(
        w.lower() for w in words_list if len(w) > 2 and w.lower() not in stopwords
    )
    top_words = [{"word": w, "count": c} for w, c in freq.most_common(top_n)]

    return {
        "success":        True,
        "characters":     chars,
        "chars_no_space": chars_no_space,
        "words":          word_count,
        "sentences":      sentences,
        "paragraphs":     paragraphs,
        "lines":          lines,
        "avg_word_length": round(sum(len(w) for w in words_list) / max(1, word_count), 1),
        "avg_words_per_sentence": round(word_count / sentences, 1),
        "reading_time":   read_label,
        "top_words":      top_words,
    }


async def execute_ip_info(args: dict) -> dict:
    """Retourne la géolocalisation et les infos d'une adresse IP (ip-api.com, gratuit)."""
    import urllib.request as _req, json as _json

    ip = args.get("ip", "").strip()
    # IP vide = IP publique de la machine
    target = ip if ip else ""

    try:
        url = f"http://ip-api.com/json/{target}?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
        with _req.urlopen(url, timeout=8) as resp:
            data = _json.loads(resp.read().decode())

        if data.get("status") != "success":
            return {"error": data.get("message", "IP introuvable ou réservée")}

        return {
            "success":      True,
            "ip":           data.get("query"),
            "country":      data.get("country"),
            "country_code": data.get("countryCode"),
            "region":       data.get("regionName"),
            "city":         data.get("city"),
            "postal_code":  data.get("zip"),
            "latitude":     data.get("lat"),
            "longitude":    data.get("lon"),
            "timezone":     data.get("timezone"),
            "isp":          data.get("isp"),
            "org":          data.get("org"),
            "asn":          data.get("as"),
        }
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 16 — Documents, Archives & Utilitaires couleur
# ══════════════════════════════════════════════════════════════════════════════



# ───────────────────────── PDF & Image toolkit (v2.34) ─────────────────────────









def _file_large_finder_scan(root: Path, top: int, threshold: float) -> tuple[list, int]:
    """Scan bloquant (os.walk) — appelé via asyncio.to_thread, jamais directement dans l'event loop."""
    import heapq
    # Tas borné : on ne garde JAMAIS plus de `top` fichiers en mémoire (anti-OOM sur gros disques)
    heap = []  # min-heap de (taille, chemin)
    scanned = 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d.lower() not in ("$recycle.bin", "system volume information")]
        for fn in fns:
            try:
                fp = os.path.join(dp, fn)
                sz = os.path.getsize(fp)
                scanned += 1
                if sz >= threshold:
                    if len(heap) < top:
                        heapq.heappush(heap, (sz, fp))
                    elif sz > heap[0][0]:
                        heapq.heapreplace(heap, (sz, fp))
            except Exception:
                continue
    return sorted(heap, reverse=True), scanned


async def execute_file_large_finder(args: dict) -> dict:
    """Trouve les plus gros fichiers d'un dossier (récursif) — pour repérer ce qui prend de la place."""
    directory = args.get("directory") or args.get("path") or _HOME
    try:
        root = Path(_resolve_path(directory))
        if not root.exists():
            return {"error": f"Dossier introuvable : {root}"}
        top = max(1, min(int(args.get("top", 20)), 500))
        threshold = float(args.get("min_mb", 0)) * 1024 * 1024
        # v2.160 : le scan récursif (os.walk) peut prendre plusieurs minutes sur un gros
        # dossier (mesuré 145s sur le home réel de l'utilisateur, 132 Go) — déporté sur un
        # thread pour ne pas geler tout le backend pendant ce temps (même classe de bug que
        # v2.96/v2.152 : jamais de blocage synchrone dans une fonction async).
        items, scanned = await asyncio.to_thread(_file_large_finder_scan, root, top, threshold)
        total = sum(s for s, _ in items)
        return {"success": True, "directory": str(root), "count": len(items),
                "total_human": _fmt_bytes(total),
                "files": [{"path": p, "size_bytes": s, "size_human": _fmt_bytes(s)} for s, p in items],
                "message": f"{len(items)} plus gros fichiers ({_fmt_bytes(total)})"}
    except Exception as e:
        return {"error": str(e)}


def _system_cleanup_scan(candidates: list, cutoff: float, do_delete: bool) -> dict:
    """Scan bloquant (os.walk + éventuelle suppression) — appelé via asyncio.to_thread,
    jamais directement dans l'event loop (Temp peut contenir énormément de petits
    fichiers, même risque que file_large_finder v2.160)."""
    report = []
    grand_total = 0; grand_files = 0; freed = 0; freed_files = 0
    for d in candidates:
        dtotal = 0; dfiles = 0
        for dp, dns, fns in os.walk(d):
            for fn in fns:
                fp = os.path.join(dp, fn)
                try:
                    st = os.stat(fp)
                    dtotal += st.st_size; dfiles += 1
                    if do_delete and st.st_mtime < cutoff:
                        try:
                            os.remove(fp); freed += st.st_size; freed_files += 1
                        except Exception:
                            pass
                except Exception:
                    continue
        grand_total += dtotal; grand_files += dfiles
        report.append({"dir": d, "size_human": _fmt_bytes(dtotal), "files": dfiles})
    return {"report": report, "grand_total": grand_total, "grand_files": grand_files,
            "freed": freed, "freed_files": freed_files}


async def execute_system_cleanup(args: dict) -> dict:
    """Analyse (et, si delete=true, vide) les fichiers temporaires pour libérer de l'espace.
    Sans delete=true : rapport seulement (aucune suppression). delete=true est une action sensible."""
    import tempfile
    try:
        candidates = []
        seen = set()
        for d in [tempfile.gettempdir(),
                  os.environ.get("TEMP"), os.environ.get("TMP"),
                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp"),
                  os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Temp")]:
            if d and os.path.isdir(d):
                rd = os.path.normcase(os.path.abspath(d))
                if rd not in seen:
                    seen.add(rd); candidates.append(d)
        min_age_days = float(args.get("min_age_days", 1))
        cutoff = time.time() - min_age_days * 86400
        do_delete = bool(args.get("delete", False))
        scan = await asyncio.to_thread(_system_cleanup_scan, candidates, cutoff, do_delete)
        grand_total, grand_files = scan["grand_total"], scan["grand_files"]
        freed, freed_files = scan["freed"], scan["freed_files"]
        res = {"success": True, "locations": scan["report"],
               "reclaimable_human": _fmt_bytes(grand_total), "total_files": grand_files,
               "deleted": do_delete}
        if do_delete:
            res["freed_human"] = _fmt_bytes(freed); res["freed_files"] = freed_files
            res["message"] = f"Nettoyage : {_fmt_bytes(freed)} libérés ({freed_files} fichiers supprimés, > {min_age_days} j)"
        else:
            res["message"] = f"{_fmt_bytes(grand_total)} potentiellement récupérables dans {len(candidates)} dossiers temp. Relancez avec delete=true pour nettoyer."
        return res
    except Exception as e:
        return {"error": str(e)}


# ───────────────────────── PDF avancé & lot d'images (v2.35) ─────────────────────





# ════════════════ PDF render/OCR/forms, PPTX, conversions, IA (v2.36) ════════════
async def _ollama_generate(prompt: str, model: str = None, images: list = None, timeout: int = 180) -> str:
    """Appel texte (ou vision) à Ollama /api/generate, AVEC robustesse :
    - 1 essai primaire (timeout complet) + 1 retry primaire SEULEMENT si l'échec n'est pas
      un timeout (v2.137 — un timeout sur un gros prompt est structurel, pas transitoire) ;
    - repli sur un modèle plus léger (chat) avec un timeout réduit si le primaire échoue.
    Retourne la réponse brute.

    v2.122 — passe par `cloud_routing.resolve_model()` : c'est le point d'entrée UNIQUE
    utilisé par 13+ outils (document_generate, email_*, text_summarize, document_ask...) et,
    indirectement, par `skills.py` (upgrade_skill/suggest_skills, injecté comme callback) —
    un seul endroit à corriger pour que TOUS ces appels bénéficient du même routage
    cloud/sensibilité que la boucle de chat principale, au lieu de tomber systématiquement
    en local sans jamais consulter le réglage Ollama Cloud de l'utilisateur. Les images
    (OCR/vision) forcent toujours le local (cf. docstring de `resolve_model`)."""
    import httpx, asyncio as _aio
    import cloud_routing as _cr
    primary = _cr.resolve_model(model, profile="agent", text_for_sensitivity=prompt, has_images=bool(images))
    if _cr.is_cloud_only_mode():
        need = "vision" if images else (_cr.detect_task(prompt) or "general")
        try:
            light = _cr.require_cloud_model(need, exclude=frozenset({primary}))
        except _cr.CloudOnlyModelUnavailable:
            light = None
    else:
        try:
            light = MODEL_PROFILES.get("chat", {}).get("model") or "qwen2.5:3b"
        except Exception:
            light = "qwen2.5:3b"
    # v2.137 — trouvé en corrigeant la lenteur de /api/skills/suggest (timeout 5 min dépassé,
    # backend resté sain — pas un hang, juste un budget de temps catastrophique) : l'ancien
    # schéma retentait le modèle PRIMAIRE 3× AU TIMEOUT COMPLET avant même d'essayer le repli
    # léger — pire cas 3×240s = 12 minutes rien que pour le primaire. Un timeout n'est presque
    # jamais un blip réseau transitoire pour un GROS prompt (comme les 120 messages analysés
    # par suggest_skills) : la génération est structurellement lente, pas temporairement en
    # panne — réessayer IDENTIQUE échoue de la même façon. Seules les erreurs non-timeout
    # (connexion refusée, 5xx ponctuel) bénéficient vraiment d'un retry rapide. Nouveau schéma :
    # 1 essai primaire au timeout complet, 1 SEUL retry primaire UNIQUEMENT si l'échec n'était
    # PAS un timeout, puis repli léger avec un timeout RÉDUIT (modèle plus petit = plus rapide,
    # pas besoin du budget complet). Pire cas : timeout + timeout_léger, au lieu de 4×timeout.
    light_timeout = max(30, min(timeout, 60))
    has_light_fallback = bool(light) and light != primary

    async def _call(mdl: str, to: int):
        payload = {"model": mdl, "prompt": prompt, "stream": False}
        if images:
            payload["images"] = images
        async with httpx.AsyncClient(timeout=to) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()

    last_err = None
    # 1) Essai primaire, timeout complet.
    try:
        return await _call(primary, timeout)
    except Exception as e:
        last_err = e
        # 2) Retry primaire — SEULEMENT si l'échec n'était pas un timeout (connexion, 5xx
        #    ponctuel) : réessayer un timeout identique à l'identique échouerait pareil.
        if not isinstance(e, httpx.TimeoutException):
            await _aio.sleep(1)
            try:
                return await _call(primary, timeout)
            except Exception as e2:
                last_err = e2
    # 3) Repli sur le modèle léger, timeout réduit (petit modèle = rapide).
    if has_light_fallback:
        try:
            return await _call(light, light_timeout)
        except Exception as e3:
            last_err = e3
    raise last_err if last_err else RuntimeError("Ollama indisponible")


documents_domain.configure_generation(
    text_generator=_ollama_generate,
    generated_dir=Path(__file__).resolve().parent.parent / "data" / "documents_generes",
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
    generated_dir=Path(__file__).resolve().parent.parent / "data" / "documents_generes",
)
execute_document_index = document_knowledge_domain.index
execute_document_ask = document_knowledge_domain.ask
execute_document_list = document_knowledge_domain.list_documents
execute_document_forget = document_knowledge_domain.forget
execute_document_refine_section = document_knowledge_domain.refine_section








async def execute_pptx_create(args: dict) -> dict:
    """Crée une présentation PowerPoint (.pptx) : diapo de titre + diapos à puces."""
    slides = args.get("slides") or []
    if isinstance(slides, str):
        try:
            slides = json.loads(slides)
        except Exception:
            return {"error": "'slides' doit être une liste d'objets {title, bullets}."}
    if not slides and not args.get("title"):
        return {"error": "Fournir 'title' et/ou 'slides' (liste de {title, bullets})."}
    try:
        from pptx import Presentation
        from pptx.util import Pt
        prs = Presentation()
        # Diapo de titre
        if args.get("title"):
            s = prs.slides.add_slide(prs.slide_layouts[0])
            s.shapes.title.text = args["title"]
            if args.get("subtitle") and len(s.placeholders) > 1:
                s.placeholders[1].text = args["subtitle"]
        # Diapos de contenu
        for sl in slides:
            if isinstance(sl, str):
                sl = {"title": sl, "bullets": []}
            s = prs.slides.add_slide(prs.slide_layouts[1])
            s.shapes.title.text = sl.get("title", "")
            bullets = sl.get("bullets") or sl.get("points") or []
            if isinstance(bullets, str):
                bullets = [b.strip() for b in bullets.split("\n") if b.strip()]
            if bullets and len(s.placeholders) > 1:
                tf = s.placeholders[1].text_frame
                tf.text = str(bullets[0])
                for b in bullets[1:]:
                    p = tf.add_paragraph(); p.text = str(b)
        out = _resolve_path(args.get("output_path", "").strip() or str(Path(_HOME) / "Desktop" / "presentation.pptx"))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        prs.save(out)
        n_slides = len(slides) + (1 if args.get("title") else 0)
        return {"success": True, "path": out, "destination": out, "slides": n_slides,
                "message": f"Présentation créée ({n_slides} diapos) → {out}"}
    except Exception as e:
        return {"error": str(e)}


async def execute_pptx_read(args: dict) -> dict:
    """Extrait le texte de toutes les diapos d'un fichier PowerPoint (.pptx)."""
    path = args.get("path", "").strip()
    if not path:
        return {"error": "Paramètre 'path' requis."}
    try:
        from pptx import Presentation
        rp = Path(_resolve_path(path))
        if not rp.exists():
            return {"error": f"Fichier introuvable : {rp}"}
        prs = Presentation(str(rp))
        out = []
        for i, slide in enumerate(prs.slides):
            parts = []
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text_frame.text.strip():
                    parts.append(shape.text_frame.text.strip())
            out.append({"slide": i + 1, "text": "\n".join(parts)})
        full = "\n\n".join(f"--- Diapo {s['slide']} ---\n{s['text']}" for s in out)
        return {"success": True, "slides": len(out), "content": out, "text": full[:6000],
                "message": f"{len(out)} diapo(s) lue(s)"}
    except Exception as e:
        return {"error": str(e)}




async def execute_docx_to_text(args: dict) -> dict:
    """Extrait le texte d'un document Word (.docx), en texte brut ou Markdown (titres, listes, tableaux)."""
    path = args.get("path", "").strip()
    if not path:
        return {"error": "Paramètre 'path' requis."}
    as_md = (args.get("format", "markdown").lower() == "markdown")
    try:
        from docx import Document
        rp = Path(_resolve_path(path))
        if not rp.exists():
            return {"error": f"Fichier introuvable : {rp}"}
        doc = Document(str(rp))
        lines = []
        for para in doc.paragraphs:
            t = para.text.strip()
            if not t:
                lines.append("")
                continue
            style = (para.style.name or "").lower() if para.style else ""
            if as_md and style.startswith("heading"):
                try:
                    lvl = int(style.replace("heading", "").strip() or 1)
                except Exception:
                    lvl = 1
                lines.append("#" * min(lvl, 6) + " " + t)
            elif as_md and ("list" in style or "bullet" in style):
                lines.append("- " + t)
            else:
                lines.append(t)
        # Tableaux
        for tbl in doc.tables:
            if as_md and tbl.rows:
                hdr = [c.text.strip() for c in tbl.rows[0].cells]
                lines.append("\n| " + " | ".join(hdr) + " |")
                lines.append("| " + " | ".join("---" for _ in hdr) + " |")
                for row in tbl.rows[1:]:
                    lines.append("| " + " | ".join(c.text.strip() for c in row.cells) + " |")
            else:
                for row in tbl.rows:
                    lines.append(" | ".join(c.text.strip() for c in row.cells))
        text = "\n".join(lines).strip()
        saved = None
        if args.get("output_path"):
            saved = _resolve_path(args["output_path"])
            Path(saved).parent.mkdir(parents=True, exist_ok=True)
            Path(saved).write_text(text, encoding="utf-8")
        return {"success": True, "text": text[:8000], "truncated": len(text) > 8000,
                "paragraphs": len(doc.paragraphs), "tables": len(doc.tables), "path": saved,
                "message": f"Word extrait ({len(doc.paragraphs)} paragraphes, {len(doc.tables)} tableau(x))"}
    except Exception as e:
        return {"error": str(e)}


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





async def execute_csv_to_chart(args: dict) -> dict:
    """📊 Génère un graphique (PNG) directement à partir d'un fichier CSV.
    chart_type: bar|line|pie. label_column = colonne des étiquettes ; value_columns auto-détectées si absentes."""
    path = args.get("path", "").strip()
    if not path:
        return {"error": "Paramètre 'path' requis."}
    try:
        import csv as _csv
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        rp = Path(_resolve_path(path))
        if not rp.exists():
            return {"error": f"Fichier introuvable : {rp}"}
        with open(rp, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(2048); f.seek(0)
            try:
                delim = _csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except Exception:
                delim = ","
            rows = [r for r in _csv.reader(f, delimiter=delim) if any(c.strip() for c in r)]
        if len(rows) < 2:
            return {"error": "CSV insuffisant (il faut un en-tête + des données)."}
        header = rows[0]
        data = rows[1:200]  # borné
        label_col = int(args.get("label_column", 0))

        def _num(v):
            try:
                return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
            except Exception:
                return None

        # colonnes de valeurs : spécifiées, sinon auto-détection des colonnes numériques
        if args.get("value_columns"):
            vc = args["value_columns"]
            value_cols = [int(x) for x in (vc if isinstance(vc, list) else str(vc).split(","))]
        else:
            value_cols = []
            for ci in range(len(header)):
                if ci == label_col:
                    continue
                col_vals = [_num(r[ci]) for r in data if len(r) > ci]
                if col_vals and sum(1 for v in col_vals if v is not None) >= max(1, len(col_vals) // 2):
                    value_cols.append(ci)
        if not value_cols:
            return {"error": "Aucune colonne numérique détectée à tracer."}

        labels = [r[label_col] if len(r) > label_col else "" for r in data]
        chart_type = (args.get("chart_type") or "bar").lower()
        title = args.get("title") or rp.stem
        plt.figure(figsize=(11, 6))
        plt.rcParams.update({"font.size": 10})

        if chart_type == "pie":
            ci = value_cols[0]
            vals = [(_num(r[ci]) or 0) for r in data if len(r) > ci]
            plt.pie(vals, labels=labels[:len(vals)], autopct="%1.1f%%", startangle=90)
            plt.axis("equal")
        else:
            import numpy as _np
            x = _np.arange(len(labels))
            nseries = len(value_cols)
            width = 0.8 / max(1, nseries) if chart_type == "bar" else None
            for si, ci in enumerate(value_cols):
                vals = [(_num(r[ci]) if len(r) > ci else None) for r in data]
                vals = [v if v is not None else 0 for v in vals]
                name = header[ci] if ci < len(header) else f"Col {ci}"
                if chart_type == "line":
                    plt.plot(x, vals, marker="o", label=name)
                else:  # bar
                    plt.bar(x + si * width - 0.4 + width / 2, vals, width=width, label=name)
            plt.xticks(x, labels, rotation=45, ha="right")
            if nseries > 1:
                plt.legend()
            plt.grid(axis="y", alpha=0.3)
        plt.title(title)
        plt.tight_layout()
        out = _resolve_path(args.get("output_path", "").strip() or str(rp.with_suffix(".png")))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out, dpi=120, bbox_inches="tight")
        plt.close()
        return {"success": True, "path": out, "destination": out, "chart_type": chart_type,
                "series": len(value_cols), "points": len(labels),
                "message": f"Graphique {chart_type} généré ({len(value_cols)} série(s), {len(labels)} points) → {out}"}
    except Exception as e:
        return {"error": str(e)}




async def execute_url_analyze(args: dict) -> dict:
    """Analyse une URL : titre, meta description, statut HTTP, serveur et temps de réponse."""
    url = args.get("url", "").strip()
    if not url:
        return {"error": "Paramètre 'url' requis."}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    import re as _re, time as _t2
    try:
        def _fetch():
            import urllib.request as _ureq
            hdrs = {"User-Agent": "Mozilla/5.0 (compatible; MarvinBot/2.9)"}
            req = _ureq.Request(url, headers=hdrs, method="GET")
            t0 = _t2.time()
            with _ureq.urlopen(req, timeout=10) as resp:
                elapsed = round((_t2.time() - t0) * 1000)
                status = resp.status
                rh = dict(resp.headers)
                ct = rh.get("Content-Type", "")
                body = resp.read(60_000).decode("utf-8", errors="replace") if "html" in ct else ""
                return status, rh, body, elapsed
        loop = asyncio.get_running_loop()
        status, rh, body, elapsed = await loop.run_in_executor(None, _fetch)
        title = ""
        tm = _re.search(r"<title[^>]*>([^<]{1,200})</title>", body, _re.I)
        if tm:
            title = _re.sub(r"\s+", " ", tm.group(1)).strip()
        desc = ""
        dm = _re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{1,500})["\']', body, _re.I)
        if not dm:
            dm = _re.search(r'<meta[^>]+content=["\']([^"\']{1,500})["\'][^>]+name=["\']description["\']', body, _re.I)
        if dm:
            desc = _re.sub(r"\s+", " ", dm.group(1)).strip()
        canon = ""
        cm = _re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', body, _re.I)
        if cm:
            canon = cm.group(1).strip()
        return {
            "success":          True,
            "url":              url,
            "status":           status,
            "response_time_ms": elapsed,
            "title":            title,
            "description":      desc,
            "canonical":        canon,
            "content_type":     rh.get("Content-Type", ""),
            "server":           rh.get("Server", ""),
            "content_length":   rh.get("Content-Length", ""),
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_zip_list(args: dict) -> dict:
    """Liste le contenu d'une archive ZIP sans l'extraire."""
    path = args.get("path", "").strip()
    if not path:
        return {"error": "Paramètre 'path' requis."}
    try:
        import zipfile as _zf
        resolved = _resolve_path(path)
        if not os.path.exists(resolved):
            return {"error": f"Archive introuvable : {resolved}"}
        entries = []; total_size = 0; comp_size = 0
        with _zf.ZipFile(resolved, "r") as zf:
            for info in zf.infolist():
                entries.append({
                    "name":       info.filename,
                    "size":       info.file_size,
                    "compressed": info.compress_size,
                    "is_dir":     info.filename.endswith("/"),
                    "date":       f"{info.date_time[0]}-{info.date_time[1]:02d}-{info.date_time[2]:02d}",
                })
                total_size += info.file_size
                comp_size  += info.compress_size
        ratio = f"{round((1 - comp_size / total_size) * 100, 1)}%" if total_size > 0 else "0%"
        return {
            "success":            True,
            "archive":            str(resolved),
            "entries_count":      len(entries),
            "total_size_kb":      round(total_size / 1024, 1),
            "compressed_size_kb": round(comp_size  / 1024, 1),
            "compression_ratio":  ratio,
            "entries":            entries[:200],
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_color_tool(args: dict) -> dict:
    """Convertit des couleurs entre HEX, RGB et HSL, et calcule la couleur complémentaire."""
    color = args.get("color", "").strip()
    if not color:
        return {"error": "Paramètre 'color' requis. Exemple : #FF5733 ou rgb(255,87,51) ou hsl(11,100%,60%)"}
    import colorsys as _cs, re as _re
    try:
        def _hex_to_rgb(h):
            h = h.lstrip("#")
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        if color.startswith("#"):
            r, g, b = _hex_to_rgb(color)
        elif color.lower().startswith("rgb"):
            nums = _re.findall(r"\d+", color)
            r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
        elif color.lower().startswith("hsl"):
            nums = _re.findall(r"[\d.]+", color)
            h_deg, s_pct, l_pct = float(nums[0]), float(nums[1]), float(nums[2])
            r_, g_, b_ = _cs.hls_to_rgb(h_deg / 360, l_pct / 100, s_pct / 100)
            r, g, b = round(r_ * 255), round(g_ * 255), round(b_ * 255)
        else:
            return {"error": f"Format non reconnu : {color}. Utilisez #RRGGBB, rgb(r,g,b) ou hsl(h,s%,l%)"}

        h, lum, s = _cs.rgb_to_hls(r / 255, g / 255, b / 255)
        h_deg2 = round(h * 360, 1); s_pct2 = round(s * 100, 1); l_pct2 = round(lum * 100, 1)
        hex_out = f"#{r:02X}{g:02X}{b:02X}"

        # Complementary colour
        h_comp = (h + 0.5) % 1.0
        rc, gc, bc = _cs.hls_to_rgb(h_comp, lum, s)
        complementary = f"#{round(rc*255):02X}{round(gc*255):02X}{round(bc*255):02X}"

        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return {
            "success":       True,
            "input":         color,
            "hex":           hex_out,
            "rgb":           {"r": r, "g": g, "b": b},
            "rgb_str":       f"rgb({r},{g},{b})",
            "hsl":           {"h": h_deg2, "s": s_pct2, "l": l_pct2},
            "hsl_str":       f"hsl({h_deg2},{s_pct2}%,{l_pct2}%)",
            "complementary": complementary,
            "luminance":     round(luminance, 3),
            "brightness":    "clair" if luminance > 0.5 else "sombre",
        }
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 17 — SQLite, Git & Fichiers avancés
# ══════════════════════════════════════════════════════════════════════════════

async def execute_sqlite_query(args: dict) -> dict:
    """Exécute une requête SQL sur une base SQLite locale."""
    db_path  = args.get("db_path", "").strip()
    query    = args.get("query", "").strip()
    max_rows = int(args.get("max_rows", 100))
    confirmed = args.get("confirmed", False)

    if not db_path:
        return {"error": "Paramètre 'db_path' requis."}
    if not query:
        return {"error": "Paramètre 'query' requis."}

    resolved = _resolve_path(db_path)
    if not os.path.exists(resolved):
        return {"error": f"Base de données introuvable : {resolved}"}

    # Les requêtes d'écriture (INSERT/UPDATE/DELETE/DROP/CREATE) nécessitent confirmation
    is_write = any(
        query.strip().upper().startswith(kw)
        for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "REPLACE", "TRUNCATE")
    )
    if is_write and not confirmed:
        preview = query[:200]
        return {
            "requiresConfirmation": True,
            "message": f"Exécuter cette requête d'écriture sur {os.path.basename(resolved)} ?\n{preview}",
        }

    import sqlite3 as _sq
    try:
        def _run():
            conn = _sq.connect(resolved)
            conn.row_factory = _sq.Row
            cur = conn.cursor()
            cur.execute(query)
            if is_write:
                conn.commit()
                rows_affected = cur.rowcount
                conn.close()
                return {"write": True, "rows_affected": rows_affected}
            cols = [d[0] for d in (cur.description or [])]
            rows = [dict(zip(cols, r)) for r in cur.fetchmany(max_rows)]
            # Convert non-serializable types
            for row in rows:
                for k, v in row.items():
                    if isinstance(v, bytes):
                        row[k] = f"<bytes:{len(v)}>"
            total = cur.fetchall()  # consume remainder for count
            conn.close()
            return {"cols": cols, "rows": rows, "rows_count": len(rows), "has_more": len(total) > 0}
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run)
        if result.get("write"):
            return {"success": True, "write": True, "rows_affected": result["rows_affected"]}
        return {
            "success":    True,
            "db":         os.path.basename(resolved),
            "query":      query[:200],
            "columns":    result["cols"],
            "rows":       result["rows"],
            "rows_count": result["rows_count"],
            "truncated":  result["has_more"],
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_sqlite_tables(args: dict) -> dict:
    """Liste les tables et leur schéma dans une base SQLite."""
    db_path = args.get("db_path", "").strip()
    if not db_path:
        return {"error": "Paramètre 'db_path' requis."}
    resolved = _resolve_path(db_path)
    if not os.path.exists(resolved):
        return {"error": f"Base de données introuvable : {resolved}"}
    import sqlite3 as _sq
    try:
        def _run():
            conn = _sq.connect(resolved)
            cur = conn.cursor()
            cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name;")
            tables = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]
            schema = {}
            for t in tables:
                cur.execute(f"PRAGMA table_info('{t['name']}');")
                schema[t["name"]] = [
                    {"col": r[1], "type": r[2], "notnull": bool(r[3]), "pk": bool(r[5])}
                    for r in cur.fetchall()
                ]
            conn.close()
            return tables, schema
        loop = asyncio.get_running_loop()
        tables, schema = await loop.run_in_executor(None, _run)
        stat = Path(resolved).stat()
        return {
            "success":    True,
            "db":         os.path.basename(resolved),
            "size_kb":    round(stat.st_size / 1024, 1),
            "table_count": len(tables),
            "tables":     tables,
            "schema":     schema,
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_git_info(args: dict) -> dict:
    """Retourne les informations Git d'un dépôt : branche, statut, derniers commits."""
    path = args.get("path", ".").strip() or "."
    action = args.get("action", "status")  # status | log | branches | diff

    resolved = _resolve_path(path)
    if not os.path.exists(resolved):
        return {"error": f"Dossier introuvable : {resolved}"}

    try:
        def _git(cmd: list) -> str:
            result = subprocess.run(
                ["git", "-C", resolved] + cmd,
                capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
            )
            return result.stdout.strip(), result.returncode

        if action == "status":
            out, rc = await asyncio.to_thread(_git, ["status", "--short", "--branch"])
            if rc != 0:
                return {"error": "Ce dossier n'est pas un dépôt Git ou git n'est pas installé."}
            lines = out.splitlines()
            branch_line = lines[0] if lines else ""
            changes = [l for l in lines[1:] if l.strip()]
            branch = branch_line.replace("## ", "").split("...")[0] if branch_line.startswith("## ") else branch_line
            return {
                "success":  True,
                "repo":     resolved,
                "branch":   branch,
                "changes_count": len(changes),
                "changes":  changes[:50],
                "clean":    len(changes) == 0,
            }
        elif action == "log":
            count = int(args.get("count", 10))
            out, rc = await asyncio.to_thread(_git, ["log", f"--max-count={count}", "--oneline", "--no-color"])
            if rc != 0:
                return {"error": "Impossible d'accéder au log Git."}
            commits = []
            for line in out.splitlines():
                if line.strip():
                    parts = line.split(" ", 1)
                    commits.append({"hash": parts[0], "message": parts[1] if len(parts) > 1 else ""})
            return {"success": True, "repo": resolved, "commits": commits, "count": len(commits)}
        elif action == "branches":
            out, rc = await asyncio.to_thread(_git, ["branch", "-a", "--no-color"])
            if rc != 0:
                return {"error": "Impossible de lister les branches."}
            branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
            current = next((b.lstrip("* ") for b in out.splitlines() if b.startswith("*")), "")
            return {"success": True, "repo": resolved, "current": current, "branches": branches}
        elif action == "diff":
            out, rc = await asyncio.to_thread(_git, ["diff", "--stat", "--no-color"])
            return {"success": True, "repo": resolved, "diff_stat": out or "(aucune modification)"}
        else:
            return {"error": f"Action inconnue : {action}. Valeurs : status, log, branches, diff"}
    except FileNotFoundError:
        return {"error": "git n'est pas installé ou introuvable dans PATH."}
    except Exception as e:
        return {"error": str(e)}


async def execute_bulk_rename(args: dict) -> dict:
    """Renomme en masse des fichiers dans un dossier selon un motif de recherche/remplacement."""
    folder   = args.get("folder", "").strip()
    pattern  = args.get("pattern", "").strip()  # regex ou texte à trouver dans le nom
    replace  = args.get("replace", "")          # texte de remplacement
    glob_pat = args.get("glob", "*")            # filtre de fichiers ex: "*.jpg"
    dry_run  = args.get("dry_run", True)        # True = simuler seulement
    confirmed = args.get("confirmed", False)

    if not folder:
        return {"error": "Paramètre 'folder' requis."}
    if not pattern:
        return {"error": "Paramètre 'pattern' requis."}

    resolved = Path(_resolve_path(folder))
    if not resolved.exists():
        return {"error": f"Dossier introuvable : {resolved}"}

    import re as _re, fnmatch as _fn
    try:
        files = [f for f in resolved.iterdir() if f.is_file()]
        if glob_pat != "*":
            files = [f for f in files if _fn.fnmatch(f.name, glob_pat)]

        renames = []
        for f in files:
            new_name = _re.sub(pattern, replace, f.name)
            if new_name != f.name:
                renames.append({"old": f.name, "new": new_name, "old_path": str(f), "new_path": str(f.parent / new_name)})

        if not renames:
            return {"success": True, "message": "Aucun fichier ne correspond au motif.", "renamed": 0}

        if dry_run and not confirmed:
            return {
                "requiresConfirmation": True,
                "message": f"Renommer {len(renames)} fichier(s) dans {resolved.name} ?\nExemple : {renames[0]['old']} → {renames[0]['new']}",
                "preview": renames[:10],
            }

        # Execute rename
        done = []; errors = []
        for r in renames:
            try:
                os.rename(r["old_path"], r["new_path"])
                done.append(r)
            except Exception as e:
                errors.append({"file": r["old"], "error": str(e)})
        return {
            "success": True,
            "folder": str(resolved),
            "renamed": len(done),
            "errors": errors,
            "files": done[:50],
        }
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 18 — Outils composés & productivité
# ══════════════════════════════════════════════════════════════════════════════

async def execute_screen_ocr(args: dict) -> dict:
    """
    Capture l'écran et en extrait le texte via l'IA vision (llava) ou pytesseract.
    Méthode 1 (recommandée) : Ollama + llava-phi3 (no extra install needed).
    Méthode 2 (fallback)     : pytesseract si installé + tesseract binary.
    """
    region   = args.get("region", None)    # [x, y, w, h] ou None = écran entier
    save     = args.get("save", False)     # True = sauvegarder le screenshot
    method   = args.get("method", "auto")  # auto | vision | tesseract
    prompt   = args.get("prompt", "Extrais tout le texte visible dans cette image. Retourne uniquement le texte brut.")

    try:
        import mss as _mss
        from PIL import Image as PILImg
        import io as _io, tempfile as _tmp

        with _mss.mss() as sct:
            if region and len(region) == 4:
                x, y, w, h = region
                mon = {"left": x, "top": y, "width": w, "height": h}
            else:
                mon = sct.monitors[0]  # Virtual screen (all monitors combined)
            shot = sct.grab(mon)
            img  = PILImg.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        screen_size = list(shot.size)

        # Reduce size for faster OCR (max 1920px)
        max_dim = 1920
        if max(img.size) > max_dim:
            ratio    = max_dim / max(img.size)
            img      = img.resize((int(img.width * ratio), int(img.height * ratio)), PILImg.LANCZOS)

        # Save to temp PNG
        tmp = _tmp.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(tmp.name, "PNG")
        tmp.close()
        tmp_path = tmp.name

        text = ""
        ocr_method_used = "none"

        # Method 1: Ollama vision (llava-phi3)
        if method in ("auto", "vision"):
            try:
                result = await execute_ocr_extract({"image_path": tmp_path, "prompt": prompt})
                if result.get("text") and not result.get("error"):
                    text = result["text"].strip()
                    ocr_method_used = "vision (llava)"
            except Exception:
                pass

        # Method 2: pytesseract fallback
        if not text and method in ("auto", "tesseract"):
            try:
                import pytesseract
                lang = args.get("lang", "fra+eng")
                try:
                    text = pytesseract.image_to_string(img, lang=lang, config="--oem 3 --psm 6").strip()
                except Exception:
                    text = pytesseract.image_to_string(img, config="--oem 3 --psm 6").strip()
                if text:
                    ocr_method_used = "tesseract"
            except Exception:
                pass

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        result = {
            "success":     True,
            "text":        text,
            "text_length": len(text),
            "screen_size": screen_size,
            "method":      ocr_method_used,
        }

        if save:
            saved_path = Path(_SYSTEM_PATHS["desktop"]) / f"screen_ocr_{int(time.time())}.png"
            PILImg.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX").save(str(saved_path))
            result["saved_to"] = str(saved_path)

        if not text:
            result["warning"] = "Aucun texte extrait. Installez Tesseract ou assurez-vous que llava-phi3 est disponible dans Ollama."

        return result

    except ImportError as e:
        return {"error": f"Dépendance manquante : {e}. Installez 'mss' avec : pip install mss"}
    except Exception as e:
        return {"error": str(e)}


async def execute_file_batch_read(args: dict) -> dict:
    """Lit plusieurs fichiers texte en une seule requête et retourne leur contenu agrégé."""
    paths       = args.get("paths", [])
    max_per_file = int(args.get("max_chars_per_file", 5000))
    encoding    = args.get("encoding", "utf-8")

    if not paths:
        return {"error": "Paramètre 'paths' requis (liste de chemins de fichiers)."}
    if isinstance(paths, str):
        paths = [p.strip() for p in paths.split(",") if p.strip()]

    results = []
    total_chars = 0
    for raw_path in paths[:20]:  # max 20 fichiers
        resolved = _resolve_path(raw_path.strip())
        entry = {"path": resolved, "success": False}
        try:
            with open(resolved, encoding=encoding, errors="replace") as f:
                content = f.read(max_per_file)
            entry.update({
                "success":   True,
                "content":   content,
                "chars":     len(content),
                "truncated": len(content) >= max_per_file,
            })
            total_chars += len(content)
        except FileNotFoundError:
            entry["error"] = "Fichier introuvable"
        except Exception as e:
            entry["error"] = str(e)
        results.append(entry)

    return {
        "success":     True,
        "files_read":  sum(1 for r in results if r.get("success")),
        "files_error": sum(1 for r in results if r.get("error")),
        "total_chars": total_chars,
        "files":       results,
    }


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


async def execute_text_join(args: dict) -> dict:
    """Fusionne plusieurs textes avec un séparateur (jointure de lignes, CSV → texte, etc.)."""
    texts     = args.get("texts", [])
    separator = args.get("separator", "\n")
    prefix    = args.get("prefix", "")
    suffix    = args.get("suffix", "")
    dedupe    = args.get("dedupe", False)       # supprimer les doublons

    if not texts:
        return {"error": "Paramètre 'texts' requis (liste de chaînes)."}
    if isinstance(texts, str):
        texts = [texts]

    if dedupe:
        seen = set(); unique = []
        for t in texts:
            if t not in seen:
                seen.add(t); unique.append(t)
        texts = unique

    result = separator.join(f"{prefix}{t}{suffix}" for t in texts)
    return {
        "success":     True,
        "result":      result,
        "items":       len(texts),
        "total_chars": len(result),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 19 — Exécution de code Python (sandboxée)
# ══════════════════════════════════════════════════════════════════════════════

# v2.142 — liste de modules/appels sensibles pour l'analyse STRUCTURELLE (AST) du code
# avant exécution. Remplace l'ancienne liste noire par SOUS-CHAÎNE (v2.36-2.106), trouvée
# contournable en auditant le code pour la comparaison "meilleur que le payant" (v2.141) :
# `getattr(os, 'sys'+'tem')(...)` ne contient AUCUNE des chaînes interdites d'origine, et
# `os` était de toute façon importé SANS CONDITION dans l'espace de noms — le denylist
# n'aurait jamais empêché grand-chose. L'AST voit la structure réelle (Import/Call), pas
# le texte brut : impossible à déguiser par concaténation de chaînes ou obfuscation.
_CODE_FORBIDDEN_MODULES = {
    "os", "subprocess", "socket", "shutil", "ctypes", "sys",
    "multiprocessing", "threading", "urllib", "http", "ftplib", "smtplib",
    "importlib", "pickle", "winreg", "psutil",
}
_CODE_FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open", "input"}


def _scan_code_ast(code: str) -> list[str]:
    """Retourne les motifs sensibles trouvés (imports/appels) par analyse AST, ou
    ["Erreur de syntaxe : ..."] si le code ne parse pas. Best-effort mais structurel :
    un `import os` ou `eval(...)` est détecté quelle que soit la façon dont le module
    est ensuite utilisé — contrairement à un test de sous-chaîne, contourner la
    DÉTECTION DE L'IMPORT LUI-MÊME ne sert à rien puisque sans l'import, le nom
    n'existe simplement pas dans l'espace de noms du sous-processus."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Erreur de syntaxe : {e}"]
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _CODE_FORBIDDEN_MODULES:
                    found.add(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _CODE_FORBIDDEN_MODULES:
                found.add(f"from {node.module or '?'} import ...")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name in _CODE_FORBIDDEN_CALLS:
                found.add(f"appel à {name}(...)")
    return sorted(found)


_CODE_RESULT_MARKER = "___MARVIN_RESULT___"


async def execute_code_python(args: dict) -> dict:
    """
    Exécute un extrait de code Python dans un SOUS-PROCESSUS isolé (v2.142 — l'ancienne
    version tournait par exec() DANS le process du backend, avec `os` toujours disponible :
    un vrai isolement de processus, pas juste un espace de noms restreint). Idéal pour :
    calculs de données, statistiques, transformations, GRAPHIQUES (matplotlib) — tout
    fichier écrit dans le dossier de travail (image, CSV...) est automatiquement détecté
    et renvoyé, cliquable dans le chat (comme un Code Interpreter). Les imports sensibles
    (os, subprocess, réseau, fichiers via open()...) demandent confirmation explicite.
    """
    code = (args.get("code") or "").strip()
    timeout = max(1, min(int(args.get("timeout", 15)), 60))
    confirmed = bool(args.get("confirmed", False))

    if not code:
        return {"error": "Paramètre 'code' requis."}

    risks = _scan_code_ast(code)
    if risks and not confirmed:
        return {
            "requiresConfirmation": True,
            "message": f"Ce code utilise des fonctionnalités sensibles ({', '.join(risks[:4])}). Exécuter quand même ?",
            "risks": risks,
        }

    import uuid as _uuid
    import glob as _glob

    run_id = _uuid.uuid4().hex[:12]
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "code_outputs", run_id))
    os.makedirs(out_dir, exist_ok=True)
    script_path = os.path.join(out_dir, "_script.py")
    # Capture best-effort d'une variable `result`/`output` si le code en définit une —
    # imprimée avec un marqueur unique, extrait du stdout après coup (le sous-processus
    # ne partage pas de mémoire avec le backend, donc pas d'autre moyen de la récupérer).
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
        f.write(
            "\ntry:\n"
            "    _mv_r = locals().get('result', locals().get('output'))\n"
            "    if _mv_r is not None:\n"
            f"        print({_CODE_RESULT_MARKER!r} + repr(_mv_r)[:2000])\n"
            "except Exception:\n"
            "    pass\n"
        )

    env = dict(os.environ)
    env["MPLBACKEND"] = "Agg"  # graphiques sans affichage (sous-processus headless)
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", script_path,
            cwd=out_dir, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": f"Timeout dépassé ({timeout}s). Simplifiez le code ou augmentez le timeout."}
    except Exception as e:
        return {"error": f"Échec de lancement du sous-processus : {str(e)[:200]}"}

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")

    result_val = None
    clean_lines = []
    for line in stdout.splitlines():
        if line.startswith(_CODE_RESULT_MARKER):
            result_val = line[len(_CODE_RESULT_MARKER):][:2000]
        else:
            clean_lines.append(line)
    stdout_clean = "\n".join(clean_lines)

    # Fichiers écrits par le code (graphiques, CSV exportés...) — glob du dossier de
    # travail dédié à cette exécution, en excluant le script lui-même. `path`/`files`
    # sont détectés côté frontend par EXTENSION (GeneratedFileCard, v2.128/v2.142),
    # donc rien à câbler côté LLM : un simple plt.savefig("chart.png") suffit.
    generated = [
        os.path.abspath(p) for p in sorted(_glob.glob(os.path.join(out_dir, "*")))
        if os.path.isfile(p) and os.path.basename(p) != "_script.py"
    ]

    resp = {
        "success":    proc.returncode == 0,
        "stdout":     stdout_clean[:4000] or "(aucune sortie)",
        "stderr":     stderr[:1500] if stderr else "",
        "result":     result_val,
        "returncode": proc.returncode,
    }
    if generated:
        resp["files"] = generated
        if len(generated) == 1:
            resp["path"] = generated[0]
            resp["message"] = f"Fichier généré : {os.path.basename(generated[0])}"
    if proc.returncode != 0 and not resp["stderr"]:
        resp["error"] = "Le script a échoué (code de retour non nul) sans message d'erreur."
    return resp


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













def _file_duplicate_finder_scan(resolved: Path, min_size: int, max_files: int) -> dict:
    """Scan bloquant (os.walk + hash MD5) — appelé via asyncio.to_thread, jamais
    directement dans l'event loop (même risque que file_large_finder v2.160 : un gros
    dossier peut prendre plusieurs dizaines de secondes)."""
    import hashlib as _hl
    # 1. Group by size (fast pre-filter)
    size_map = {}
    scanned = 0
    for root, dirs, files in os.walk(str(resolved)):
        dirs[:] = [d for d in dirs if d not in ('$RECYCLE.BIN', 'System Volume Information', 'node_modules', '.git')]
        for fname in files:
            if scanned >= max_files:
                break
            fpath = os.path.join(root, fname)
            try:
                sz = os.path.getsize(fpath)
                if sz >= min_size:
                    size_map.setdefault(sz, []).append(fpath)
                    scanned += 1
            except Exception:
                pass
        if scanned >= max_files:
            break

    # 2. For sizes with >1 file, compute hash
    duplicates = []
    total_wasted = 0
    for sz, paths in size_map.items():
        if len(paths) < 2:
            continue
        hash_map = {}
        for p in paths:
            try:
                h = _hl.md5()
                with open(p, "rb") as f:
                    # Hash first 64KB for speed (good enough for dedup detection)
                    h.update(f.read(65536))
                hash_map.setdefault(h.hexdigest(), []).append(p)
            except Exception:
                pass
        for hsh, dups in hash_map.items():
            if len(dups) > 1:
                duplicates.append({
                    "size_kb": round(sz/1024, 1),
                    "count": len(dups),
                    "files": dups,
                })
                total_wasted += sz * (len(dups) - 1)

    duplicates.sort(key=lambda d: d["size_kb"] * d["count"], reverse=True)
    return {"scanned": scanned, "duplicates": duplicates, "total_wasted": total_wasted}


async def execute_file_duplicate_finder(args: dict) -> dict:
    """
    Trouve les fichiers en double dans un dossier (par taille puis hash MD5).
    Utile pour le nettoyage de disque. Ne supprime rien.
    """
    path = args.get("path", "").strip()
    if not path:
        return {"error": "Paramètre 'path' requis."}
    resolved = Path(_resolve_path(path))
    if not resolved.exists():
        return {"error": f"Dossier introuvable : {resolved}"}
    min_size = int(args.get("min_size_kb", 10)) * 1024  # ignore tiny files
    max_files = int(args.get("max_files", 5000))

    try:
        scan = await asyncio.to_thread(_file_duplicate_finder_scan, resolved, min_size, max_files)
        duplicates = scan["duplicates"]
        return {
            "success": True,
            "root": str(resolved),
            "scanned": scan["scanned"],
            "duplicate_groups": len(duplicates),
            "wasted_space_mb": round(scan["total_wasted"]/1024**2, 1),
            "duplicates": duplicates[:50],
            "hint": "Hash sur les 64 premiers Ko (rapide). Vérifiez avant toute suppression.",
        }
    except Exception as e:
        return {"error": str(e)}


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

async def execute_system_self_test(args: dict) -> dict:
    """
    🩺 Auto-diagnostic : Marvin teste un échantillon de ses propres outils (sûrs,
    lecture seule) et rapporte leur état + latence. include_web=true ajoute les
    outils réseau. Permet de vérifier en un appel que tout fonctionne.
    """
    category = (args.get("category") or "").lower().strip()
    include_web = bool(args.get("include_web", False))
    SAFE = [
        ("calcul", "calculator", {"expression": "2+2"}),
        ("date", "datetime_info", {}),
        ("conversion", "unit_convert", {"value": 1, "from_unit": "km", "to_unit": "m"}),
        ("crypto", "hash_compute", {"text": "x", "algorithm": "md5"}),
        ("texte", "json_tool", {"data": "{}", "operation": "format"}),
        ("système", "pc_system_info", {}),
        ("disque", "win_disk_info", {}),
        ("système", "win_uptime", {}),
        ("devis", "billing_catalog_list", {}),
        ("base IT", "it_kb_list", {}),
        ("base IT", "it_kb_recommend", {"need": "antivirus pme"}),
        ("mémoire", "memory_list", {}),
        ("notes", "note_list", {}),
        ("tâches", "task_list", {}),
        ("chemins", "pc_get_real_paths", {}),
        ("documentation", "doc_intervention_list", {}),
        # v2.106 — élargissement (couverture ~18→46 outils) pour un vrai audit,
        # à charge d'exclure explicitement tout ce qui a un effet de bord (écriture,
        # e-mail, réseau destructif, tweak système…).
        ("réseau", "ip_info", {}),
        ("réseau", "net_ping", {"host": "127.0.0.1", "count": 1}),
        ("système", "pc_process_list", {}),
        ("système", "pc_window_list", {}),
        ("système", "pc_installed_software", {}),
        ("système", "win_services_list", {}),
        ("système", "win_startup_programs", {}),
        ("système", "win_users_list", {}),
        ("système", "pc_gpu_status", {}),
        ("système", "pc_hardware_specs", {}),
        ("système", "win_update_status", {}),
        ("outils", "password_generate", {}),
        ("outils", "base64_tool", {"data": "test", "action": "encode"}),
        ("outils", "color_tool", {"color": "#ffffff"}),
        ("outils", "regex_tool", {"pattern": "a+", "text": "aaa", "action": "findall"}),
        ("outils", "text_stats", {"text": "Bonjour le monde."}),
        ("outils", "diff_text", {"text_a": "a", "text_b": "b"}),
        ("outils", "pc_clipboard_get", {}),
        ("agenda", "calendar_list", {}),
        ("email", "email_accounts", {}),
        ("mémoire", "memory_search", {"query": "test"}),
        ("recherche", "search_semantic", {"query": "test"}),
        ("devis", "billing_client_list", {}),
        ("devis", "billing_quote_list", {}),
        ("devis", "billing_invoice_list", {}),
        ("documentation", "doc_template_list", {}),
        ("ssh", "ssh_list", {}),
    ]
    if include_web:
        SAFE += [
            ("web", "web_search", {"query": "test", "max_results": 2}),
            ("météo", "weather", {"city": "Paris"}),
        ]
    results = []
    for cat, name, a in SAFE:
        if category and category not in cat.lower() and category not in name:
            continue
        fn = TOOLS_REGISTRY.get(name)
        if not fn:
            results.append({"tool": name, "category": cat, "status": "absent"})
            continue
        t0 = time.time()
        try:
            r = await fn(a)
            ok = not (isinstance(r, dict) and r.get("error"))
            results.append({"tool": name, "category": cat,
                            "status": "ok" if ok else "erreur",
                            "detail": "" if ok else str(r.get("error"))[:90],
                            "ms": int((time.time() - t0) * 1000)})
        except Exception as e:
            results.append({"tool": name, "category": cat, "status": "crash",
                            "detail": str(e)[:90], "ms": int((time.time() - t0) * 1000)})
    ok = sum(1 for r in results if r["status"] == "ok")
    failed = [r for r in results if r["status"] != "ok"]
    return {
        "success": True,
        "registry_total": len(TOOLS_REGISTRY),
        "tested": len(results), "ok": ok, "failed": len(failed),
        "failures": failed,
        "results": results,
        "summary": (f"✅ {ok}/{len(results)} outils testés OK (sur {len(TOOLS_REGISTRY)} au total)."
                    if not failed else
                    f"⚠️ {ok}/{len(results)} OK — {len(failed)} à vérifier : "
                    + ", ".join(f['tool'] for f in failed)),
    }


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
execute_pc_browse = pc_control_domain.execute_pc_browse
execute_pc_clipboard_get = pc_control_domain.execute_pc_clipboard_get
execute_pc_clipboard_set = pc_control_domain.execute_pc_clipboard_set
execute_pc_get_real_paths = pc_control_domain.execute_pc_get_real_paths
execute_pc_gui_click = pc_control_domain.execute_pc_gui_click
execute_pc_gui_read = pc_control_domain.execute_pc_gui_read
execute_pc_gui_type = pc_control_domain.execute_pc_gui_type
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

windows_settings_domain.configure(
    run_powershell=execute_pc_run_powershell,
    registry_get=execute_registry_get,
)
execute_os_power_plan = windows_settings_domain.execute_os_power_plan
execute_os_dark_mode = windows_settings_domain.execute_os_dark_mode
execute_os_firewall = windows_settings_domain.execute_os_firewall
execute_os_network_adapters = windows_settings_domain.execute_os_network_adapters
execute_os_hibernation = windows_settings_domain.execute_os_hibernation

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

execute_web_browse = web_domain.execute_web_browse
execute_web_browser_open = web_domain.execute_web_browser_open
execute_web_deep_research = web_domain.execute_web_deep_research
execute_web_research = web_domain.execute_web_research
execute_web_search = web_domain.execute_web_search

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


# REGISTRE DES OUTILS
# ══════════════════════════════════════════════════════════════════════════════

TOOLS_REGISTRY: dict[str, Any] = {
    "quiz_generate": execute_quiz_generate,
    "quiz_next":     execute_quiz_next,
    "quiz_answer":   execute_quiz_answer,
    "quiz_stats":    execute_quiz_stats,
    "system_self_test": execute_system_self_test,
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
    "pc_system_info": execute_pc_system_info,
    "pc_screenshot": execute_pc_screenshot,
    "pc_window_list": execute_pc_window_list,
    "pc_window_focus": execute_pc_window_focus,
    "pc_gui_read": execute_pc_gui_read,
    "pc_gui_click": execute_pc_gui_click,
    "pc_gui_type": execute_pc_gui_type,
    "vm_lab_install": execute_vm_lab_install,
    "pc_notify": execute_pc_notify,
    "pc_pull_ollama_model": execute_pc_pull_ollama_model,
    "pc_clipboard_get": execute_pc_clipboard_get,
    "pc_clipboard_set": execute_pc_clipboard_set,
    "pc_process_list": execute_pc_process_list,
    "pc_process_kill": execute_pc_process_kill,
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
            },
        },
    }


TOOLS_SPEC = [
    _t("system_self_test",
       "Auto-diagnostic : Marvin teste un échantillon de ses propres outils et rapporte ceux qui fonctionnent ou non (+ latence). include_web=true teste aussi les outils réseau. Pour répondre à 'est-ce que tout fonctionne ?'.",
       {"category":    {"type": "string", "description": "Filtrer par catégorie/outil (optionnel)"},
        "include_web": {"type": "boolean", "description": "Inclure les outils réseau (web, météo)"}}, []),
    _t("file_list", "Liste les fichiers et dossiers dans un répertoire.",
       {"path": {"type": "string", "description": "Chemin du répertoire à lister"},
        "show_hidden": {"type": "boolean", "description": "Afficher les fichiers cachés"}},
       ["path"]),

    _t("file_info", "Retourne les métadonnées détaillées d'un fichier ou dossier (taille, dates, hash MD5 optionnel).",
       {"path": {"type": "string", "description": "Chemin du fichier ou dossier"},
        "hash": {"type": "boolean", "description": "Calculer le MD5 du fichier (défaut : false)"}},
       ["path"]),

    _t("file_read", "Lit le contenu d'un fichier (TXT, PDF, Word DOCX, Excel XLSX, CSV, Markdown, code source...).",
       {"path": {"type": "string", "description": "Chemin du fichier à lire"}},
       ["path"]),

    _t("file_write", "Écrit du contenu dans un fichier texte ou markdown. Crée le fichier s'il n'existe pas.",
       {"path": {"type": "string", "description": "Chemin du fichier à écrire"},
        "content": {"type": "string", "description": "Contenu à écrire"},
        "append": {"type": "boolean", "description": "Ajouter au fichier existant (true) ou écraser (false, défaut)"},
        "mode": {"type": "string", "enum": ["overwrite", "append"], "description": "Mode d'écriture : 'overwrite' (défaut) ou 'append'"}},
       ["path", "content"]),

    _t("file_delete", "Supprime un fichier ou un dossier (demande confirmation).",
       {"path": {"type": "string", "description": "Chemin à supprimer"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
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
        "size": {"type": "integer", "description": "Taille en pixels, carré (défaut 512)"}},
       ["name", "prompt"]),

    _t("logo_list", "Liste les logos déjà générés localement (nom, description, chemin) — à consulter AVANT logo_generate pour réutiliser un logo existant plutôt que d'en régénérer un nouveau pour le même client/contexte.",
       {"limit": {"type": "integer", "description": "Nombre max à lister (défaut 50)"}},
       []),

    _t("file_create_docx", "Crée un vrai document Word (.docx) PROFESSIONNEL : page de titre, **gras**/*italique*/`code`, tableaux markdown (| a | b |), citations (> ), blocs de code, en-tête/pied de page personnalisables, sommaire auto, bloc signature. Pour un document STRUCTURÉ/officiel (rapport, procédure, devis, présentation) sans identité document déjà connue (voir document_identity_set), demande d'abord auteur/organisation/en-tête à l'utilisateur plutôt que de deviner.",
       {"path": {"type": "string", "description": "Chemin du fichier Word à créer (.docx)"},
        "title": {"type": "string", "description": "Titre principal du document"},
        "subtitle": {"type": "string", "description": "Sous-titre (optionnel)"},
        "content": {"type": "string", "description": "Contenu markdown : # titres, **gras**, *italique*, - listes, tableaux | a | b |, > citations, ``` code, ![légende](chemin) pour embarquer une vraie image (ex. une capture d'écran)"},
        "author": {"type": "string", "description": "Auteur du document (sinon : identité document par défaut, sinon 'Marvin')"},
        "accent": {"type": "string", "description": "Couleur d'accent hex (défaut #c9a84c)"},
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
       ["path", "title", "content"]),

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
    _t("file_find", "Trouve des fichiers par nom/motif glob. Utilise l'index Windows Search (très rapide ~50ms) ou os.walk en fallback. Pour chercher sur TOUT le PC, omettez 'path' ou utilisez path='all'.",
       {"pattern":      {"type": "string",  "description": "Motif : *.pdf, rapport*, *2024*, ou simplement un nom. Supporte * et ?"},
        "path":         {"type": "string",  "description": "Dossier de recherche, ou 'all' pour tout le PC (défaut : tout le PC via l'index Windows)"},
        "max_results":  {"type": "integer", "description": "Limite de résultats (défaut 100)"},
        "include_dirs": {"type": "boolean", "description": "Inclure les dossiers dans les résultats (défaut false)"}},
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
    _t("pc_open_file", "Ouvre un fichier ou dossier dans son application par défaut.",
       {"path": {"type": "string", "description": "Chemin du fichier à ouvrir"}},
       ["path"]),

    _t("pc_browse", "Explore un dossier Windows (sous-dossiers + fichiers avec taille/date) et donne les accès rapides (Bureau, Documents, lecteurs). Pour naviguer l'arborescence sans connaître le chemin exact.",
       {"path": {"type": "string", "description": "Dossier à explorer (vide = Accueil)"},
        "show_hidden": {"type": "boolean", "description": "Afficher les éléments cachés"}},
       []),
    _t("pc_reveal", "Ouvre l'Explorateur Windows sur l'emplacement d'un fichier/dossier (le met en surbrillance).",
       {"path": {"type": "string", "description": "Chemin du fichier/dossier à révéler"}},
       ["path"]),

    _t("pc_app_launch", "Lance une application Windows installée par son nom (Chrome, Word, Spotify, etc.). Résout via PATH, registre App Paths et menu Démarrer → lance n'importe quelle app installée.",
       {"app_name": {"type": "string", "description": "Nom de l'application à lancer"}},
       ["app_name"]),

    _t("pc_run_command", "Exécute une commande système Windows (demande confirmation).",
       {"command": {"type": "string", "description": "Commande shell à exécuter"},
        "timeout": {"type": "integer", "description": "Délai max en secondes"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       ["command"]),

    _t("pc_run_powershell", "Exécute un script ou une commande PowerShell Windows et retourne la sortie (demande confirmation).",
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
    _t("winget_install", "Installe un logiciel en silencieux via Winget (demande confirmation).",
       {"id":        {"type": "string",  "description": "ID exact du paquet (ex: 7zip.7zip) — préférable"},
        "query":     {"type": "string",  "description": "À défaut d'ID, nom approximatif (moins fiable)"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       []),
    _t("winget_upgrade", "Met à jour un paquet précis (id) ou TOUS les paquets (all=true) via Winget (demande confirmation).",
       {"id":        {"type": "string",  "description": "ID du paquet à mettre à jour"},
        "all":       {"type": "boolean", "description": "true = mettre à jour TOUS les paquets"},
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur"}},
       []),
    _t("winget_uninstall", "Désinstalle un logiciel en silencieux via Winget (demande confirmation).",
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

    _t("csv_analyze", "Analyse un fichier CSV : aperçu, statistiques par colonne, valeurs uniques.",
       {"path":      {"type": "string",  "description": "Chemin du fichier CSV"},
        "action":    {"type": "string",  "enum": ["summary", "head", "stats", "unique"],
                      "description": "Action : summary (défaut), head (5 premières lignes), stats (stats numériques colonne), unique (valeurs uniques colonne)"},
        "column":    {"type": "string",  "description": "Colonne cible pour stats ou unique"},
        "max_rows":  {"type": "integer", "description": "Nombre max de lignes à charger (défaut 100)"},
        "delimiter": {"type": "string",  "description": "Séparateur (défaut ',')"}},
       ["path"]),

    _t("pc_system_info", "Retourne les informations techniques du PC : CPU, RAM, disques, uptime.",
       {}, []),

    _t("pc_screenshot", "Prend une capture d'écran du bureau Windows. Avec embed=true, retourne l'image base64 pour l'afficher dans le chat.",
       {"output_path": {"type": "string", "description": "Chemin de sauvegarde PNG (optionnel, défaut : Bureau)"},
        "embed": {"type": "boolean", "description": "Si true, retourner l'image base64 dans la réponse (pour affichage dans le chat)"}},
       []),

    _t("pc_window_list", "Liste toutes les fenêtres ouvertes sur le bureau.",
       {}, []),

    _t("pc_window_focus", "Met une fenêtre au premier plan par son titre.",
       {"search": {"type": "string", "description": "Texte à rechercher dans le titre de la fenêtre"}},
       ["search"]),

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

    _t("web_search", "Effectue une recherche web (DuckDuckGo gratuit mais sujet à un anti-bot occasionnel, ou SearXNG auto-hébergé/Brave/Google/SerpAPI si configurés — priorité à SearXNG en mode auto, gratuit et illimité).",
       {"query": {"type": "string", "description": "Requête de recherche"},
        "provider": {"type": "string", "enum": ["auto", "searxng", "duckduckgo", "brave", "google", "serpapi"], "description": "Moteur de recherche (auto = meilleur disponible, SearXNG en premier si configuré)"},
        "max_results": {"type": "integer", "description": "Nombre de résultats (défaut 8)"}},
       ["query"]),

    _t("web_browse", "Récupère et extrait le texte principal d'une page web depuis une URL. Retourne titre, description et contenu texte.",
       {"url": {"type": "string", "description": "URL de la page à visiter"},
        "max_chars": {"type": "integer", "description": "Limite de caractères à retourner (défaut 25000, max 60000)"}},
       ["url"]),

    _t("infographic_create", "Crée un graphique PNG. Types : bar, horizontal_bar, pie, donut, line, area, multi_line, scatter, radar, grouped_bar, stacked_bar. Pour les multi-séries (grouped/stacked/multi_line/radar), fournir 'series' = [{name, values}].",
       {"chart_type": {"type": "string", "enum": ["bar", "horizontal_bar", "pie", "donut", "line", "area", "multi_line", "scatter", "radar", "grouped_bar", "stacked_bar"], "description": "Type de graphique"},
        "title": {"type": "string", "description": "Titre du graphique"},
        "labels": {"type": "array", "items": {"type": "string"}, "description": "Étiquettes (axe / catégories)"},
        "values": {"type": "array", "items": {"type": "number"}, "description": "Valeurs (mono-série)"},
        "series": {"type": "array", "description": "Multi-séries : [{\"name\":\"2024\",\"values\":[...]}, …]"},
        "x_values": {"type": "array", "items": {"type": "number"}, "description": "Abscisses pour scatter"},
        "theme": {"type": "string", "enum": ["dark", "light"], "description": "Thème (défaut sombre)"},
        "output_path": {"type": "string", "description": "Chemin de sauvegarde PNG (défaut : Bureau)"},
        "subtitle": {"type": "string", "description": "Sous-titre optionnel"},
        "colors": {"type": "array", "items": {"type": "string"}, "description": "Couleurs HEX optionnelles"}},
       ["title", "labels"]),

    _t("file_create_xlsx", "Crée un fichier Excel (.xlsx) avec titres, en-têtes et données.",
       {"path": {"type": "string", "description": "Chemin du fichier Excel"},
        "title": {"type": "string", "description": "Titre du tableau"},
        "headers": {"type": "array", "items": {"type": "string"}, "description": "En-têtes des colonnes"},
        "rows": {"type": "array", "items": {"type": "array"}, "description": "Lignes de données (tableau de tableaux)"},
        "sheet_name": {"type": "string", "description": "Nom de la feuille"}},
       ["headers", "rows"]),

    _t("file_create_pdf", "Crée un PDF PROFESSIONNEL (sans Word) : page de titre, **gras**/*italique*/`code`, tableaux markdown stylés, citations, blocs de code, liens, en-tête/pied de page personnalisables, sommaire auto. Pour un document STRUCTURÉ/officiel (rapport, procédure, devis, présentation) sans identité document déjà connue (voir document_identity_set), demande d'abord auteur/organisation/en-tête à l'utilisateur plutôt que de deviner.",
       {"path": {"type": "string", "description": "Chemin du PDF à créer"},
        "title": {"type": "string", "description": "Titre du document"},
        "subtitle": {"type": "string", "description": "Sous-titre (optionnel)"},
        "content": {"type": "string", "description": "Contenu markdown : # titres, **gras**, *italique*, - listes, tableaux | a | b |, > citations, [lien](url), ![légende](chemin) pour embarquer une vraie image (ex. une capture d'écran)"},
        "author": {"type": "string", "description": "Auteur (sinon : identité document par défaut, sinon 'Marvin')"},
        "accent": {"type": "string", "description": "Couleur d'accent hex (défaut #c9a84c)"},
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
        "urgency": {"type": "number", "description": "Urgence GLPI 1 (très basse) à 5 (très haute)"}},
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
    _t("ocr_extract", "Extrait le texte visible dans une image (OCR par IA, utilise llava-phi3).",
       {"image_path": {"type": "string", "description": "Chemin vers le fichier image (PNG, JPG, etc.)"},
        "prompt": {"type": "string", "description": "Instruction personnalisée pour l'extraction (optionnel)"},
        "model": {"type": "string", "description": "Modèle vision Ollama à utiliser (défaut : llava-phi3)"}},
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
        "confirmed": {"type": "boolean", "description": "Confirmation de l'utilisateur (obligatoire avant envoi)"}},
       ["to", "subject", "body"]),

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
        "dry_run": {"type": "boolean", "description": "true = simulation sans envoi réel (recommandé pour tester)"}},
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
        "reminder_minutes": {"type": "integer", "description": "Rappel X minutes avant (notification + rappel Google)"},
        "local_only": {"type": "boolean", "description": "Forcer l'agenda LOCAL même si Google est connecté"}},
       []),
    _t("event_list", "Liste les rendez-vous de l'agenda. Pour « mon agenda », « mes rendez-vous », « quels RDV cette semaine ».",
       {"period": {"type": "string", "description": "today / tomorrow / week / month / upcoming / all"},
        "start": {"type": "string", "description": "Borne début YYYY-MM-DD (optionnel)"},
        "end": {"type": "string", "description": "Borne fin YYYY-MM-DD (optionnel)"}},
       []),
    _t("event_update", "Modifie ou replanifie un événement existant (par id).",
       {"id": {"type": "string", "description": "Identifiant de l'événement"},
        "title": {"type": "string"}, "start_at": {"type": "string"}, "end_at": {"type": "string"},
        "location": {"type": "string"}, "reminder_minutes": {"type": "integer"}},
       ["id"]),
    _t("event_delete", "Supprime un événement de l'agenda (par id, ou par titre approchant).",
       {"id": {"type": "string", "description": "Identifiant de l'événement"},
        "title": {"type": "string", "description": "Ou titre à rechercher"}},
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
        "author": {"type": "string", "description": "Auteur (sinon déduit ou « Marvin »)"},
        "pdf": {"type": "boolean", "description": "Aussi exporter en PDF"},
        "mode": {"type": "string", "description": "rapide (1 passe, défaut) ou detaille (section par section, plus complet mais plus lent)"},
        "use_documents": {"type": "boolean", "description": "Enrichir avec les documents indexés"},
        "client": {"type": "string", "description": "Nom du client (apparaît sur la page de titre)"},
        "reference": {"type": "string", "description": "Référence du document"},
        "include_header": {"type": "boolean", "description": "Inclure l'en-tête configuré (défaut oui)"},
        "sign": {"type": "boolean", "description": "Ajouter un bloc signature à la fin"},
        "lieu": {"type": "string", "description": "Lieu pour la signature (« Fait à … »)"}},
       []),

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
    _t("web_research", "Cherche la réponse sur INTERNET avec un vrai navigateur (contourne les blocages anti-bot), lit les meilleurs résultats et mémorise la réponse. Pour « cherche sur le web », « trouve en ligne », quand une info manque.",
       {"query": {"type": "string", "description": "La question / les mots-clés à rechercher"}},
       ["query"]),
    _t("ai_model_council",
       "COUNCIL V2 : consulte exactement CINQ modèles Ollama Cloud de CINQ familles différentes, "
       "avec cinq rôles indépendants, une critique aveugle et un arbitrage final traçable. À appeler "
       "obligatoirement si l'utilisateur dit « mode Council », « Model Council » ou demande cinq "
       "modèles. Pour une recherche web, effectue d'abord la recherche puis passe les faits vérifiés "
       "dans evidence. Ne jamais l'utiliser spontanément pour une question simple.",
       {"question": {"type": "string", "description": "La question à poser à plusieurs modèles"},
        "evidence": {"type": "string", "description": "Faits ou sources déjà vérifiés à soumettre aux cinq modèles (optionnel)"}},
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
       "RESEARCH SWARM : lance 3 à 5 cellules de recherche web spécialisées avec des familles "
       "Ollama Cloud distinctes, puis effectue une contradiction, une vérification croisée et "
       "une synthèse sourcée. À utiliser uniquement si l'utilisateur sélectionne explicitement "
       "Research Swarm ou demande un essaim de recherche sur un sujet complexe et non sensible.",
       {"question": {"type": "string", "description": "Question de recherche complexe"},
        "agent_count": {"type": "integer", "minimum": 3, "maximum": 5,
                        "description": "Nombre de cellules de recherche, défaut 5"},
        "sources_per_agent": {"type": "integer", "minimum": 1, "maximum": 5,
                              "description": "Sources maximum par cellule, défaut 3"}},
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
       "rapport structuré avec citations numérotées. PREND PLUSIEURS MINUTES — à utiliser UNIQUEMENT "
       "quand l'utilisateur demande explicitement une recherche approfondie/exhaustive/un rapport "
       "détaillé (« fais une recherche approfondie sur... », « fais-moi un rapport complet sur... »), "
       "jamais pour une question simple (utiliser web_research à la place, bien plus rapide).",
       {"query": {"type": "string", "description": "Le sujet à rechercher en profondeur"},
        "max_rounds": {"type": "integer", "description": "Nombre max de passes de recherche (1-6, défaut 4)"}},
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
    _t("calculator", "Évalue une expression mathématique (arithmétique, trigonométrie, logarithmes, factorielle, etc.).",
       {"expression": {"type": "string", "description": "Expression à évaluer. Exemples : '(12 + 4) * 3 / 2', 'sqrt(144)', 'sin(pi/2)', 'factorial(10)'"}},
       ["expression"]),

    _t("datetime_info",
       "Retourne la date/heure actuelle, convertit entre fuseaux horaires, calcule des différences ou ajoute un delta à une date.",
       {"action":    {"type": "string", "enum": ["now", "convert", "diff", "add"],
                      "description": "Action : now=heure actuelle, convert=changer fuseau, diff=durée entre deux dates, add=ajouter un delta"},
        "timezone":  {"type": "string", "description": "Nom du fuseau horaire IANA (ex: Europe/Paris, America/New_York). Défaut : Europe/Paris"},
        "datetime":  {"type": "string", "description": "Date/heure ISO 8601 (requis pour convert, diff, add). Ex: '2025-06-01T14:30:00'"},
        "datetime2": {"type": "string", "description": "Deuxième date/heure ISO 8601 (requis pour action=diff)"},
        "delta":     {"type": "object", "description": "Durée à ajouter (action=add). Ex: {\"days\": 5, \"hours\": 2, \"minutes\": 30}"}},
       []),

    _t("weather", "Récupère la météo actuelle et les prévisions (jusqu'à 7 jours) via Open-Meteo (gratuit, sans clé API).",
       {"city":    {"type": "string", "description": "Nom de la ville (ex: Paris, Lyon, Toulouse)"},
        "country": {"type": "string", "description": "Code pays ISO 2 lettres (ex: FR, BE, CH). Aide à disambiguïser."},
        "days":    {"type": "integer", "description": "Nombre de jours de prévisions (1 à 7, défaut : 1)"}},
       ["city"]),

    _t("translate", "Traduit du texte dans n'importe quelle langue via MyMemory (gratuit, sans clé, 1000 req/j).",
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
       {"length":  {"type": "integer", "description": "Longueur du mot de passe (défaut 16, max 128)"},
        "count":   {"type": "integer", "description": "Nombre de mots de passe à générer (défaut 1, max 20)"},
        "include": {"type": "array",   "items": {"type": "string"},
                    "description": "Catégories incluses : ['letters', 'digits', 'symbols']. Défaut : les trois."},
        "exclude": {"type": "string",  "description": "Caractères à exclure (ex: 'Il1O0' pour éviter confusions)"},
        "pin":     {"type": "boolean", "description": "Mode PIN numérique uniquement (défaut false)"}},
       []),

    # ── Section 15 — traitement de données ────────────────────────────────────
    _t("hash_compute", "Calcule le hash cryptographique (MD5/SHA1/SHA256/SHA512) d'un texte ou fichier.",
       {"text":      {"type": "string", "description": "Texte à hacher"},
        "file_path": {"type": "string", "description": "Chemin du fichier à hacher"},
        "algorithm": {"type": "string", "enum": ["md5", "sha1", "sha256", "sha512"],
                      "description": "Algorithme (défaut : sha256)"}},
       []),

    _t("base64_tool", "Encode ou décode en Base64 (standard ou URL-safe).",
       {"data":     {"type": "string",  "description": "Texte à encoder ou chaîne Base64 à décoder"},
        "action":   {"type": "string",  "enum": ["encode", "decode"], "description": "Action (défaut : encode)"},
        "url_safe": {"type": "boolean", "description": "Utiliser le variant URL-safe (défaut false)"}},
       ["data"]),

    _t("text_extract", "Extrait des emails, URLs et numéros de téléphone d'un texte.",
       {"text":    {"type": "string", "description": "Texte source à analyser"},
        "extract": {"type": "string", "enum": ["emails", "urls", "phones", "all"],
                    "description": "Type à extraire (défaut : all)"}},
       ["text"]),

    _t("diff_text", "Compare deux textes et affiche les différences (unified diff ou ratio de similarité).",
       {"text_a":        {"type": "string", "description": "Premier texte"},
        "text_b":        {"type": "string", "description": "Second texte"},
        "mode":          {"type": "string", "enum": ["unified", "context", "ndiff", "ratio"],
                          "description": "Mode de diff (défaut : unified)"},
        "context_lines": {"type": "integer", "description": "Lignes de contexte (défaut 3)"}},
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
       {"data":        {"type": "string",  "description": "Texte ou URL à encoder dans le QR code"},
        "output_path": {"type": "string",  "description": "Chemin du fichier PNG de sortie (défaut : Bureau)"},
        "size":        {"type": "integer", "description": "Taille des modules en pixels (défaut 10)"},
        "border":      {"type": "integer", "description": "Bordure blanche autour (défaut 4 modules)"},
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
        "top_words": {"type": "integer", "description": "Nombre de mots fréquents à retourner (défaut 10)"}},
       ["text"]),

    _t("ip_info", "Retourne la géolocalisation et les infos réseau d'une adresse IP publique (ip-api.com, gratuit).",
       {"ip": {"type": "string", "description": "Adresse IP à analyser (vide = IP publique de la machine)"}},
       []),

    _t("markdown_convert", "Convertit du Markdown en HTML, texte brut ou retourne des statistiques (titres, liens, blocs de code).",
       {"text":   {"type": "string", "description": "Contenu Markdown à convertir"},
        "to":     {"type": "string", "enum": ["html", "plain", "stats"],
                   "description": "Format cible : html (défaut), plain (texte brut), stats"}},
       ["text"]),

    _t("regex_tool", "Applique une expression régulière à un texte : recherche, extraction, remplacement ou validation.",
       {"pattern":     {"type": "string", "description": "Expression régulière"},
        "text":        {"type": "string", "description": "Texte cible"},
        "action":      {"type": "string", "enum": ["findall", "match", "replace", "split", "test"],
                        "description": "Action (défaut : findall)"},
        "replace":     {"type": "string", "description": "Texte de remplacement (pour action replace)"},
        "flags":       {"type": "string", "description": "Flags : I (insensible à la casse), M (multiline), S (dot-all)"},
        "max_results": {"type": "integer", "description": "Limite de résultats (défaut 100)"}},
       ["pattern"]),
    # ── Section 16 ──────────────────────────────────────────────────────────
    _t("pdf_read", "Extrait le texte d'un fichier PDF page par page.",
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
       {"directory": {"type": "string", "description": "Dossier à analyser (défaut : dossier personnel)"},
        "top": {"type": "integer", "description": "Nombre de fichiers à retourner (défaut 20)"},
        "min_mb": {"type": "number", "description": "Taille minimale en Mo à considérer"}},
       []),
    _t("system_cleanup", "Analyse les fichiers temporaires et l'espace récupérable. delete=true vide les temp (action sensible, fichiers anciens uniquement).",
       {"delete": {"type": "boolean", "description": "true = supprimer réellement (sinon rapport seul)"},
        "min_age_days": {"type": "number", "description": "Âge minimal des fichiers à supprimer en jours (défaut 1)"}},
       []),
    _t("pptx_create", "Crée une présentation PowerPoint (.pptx) : diapo de titre + diapos à puces.",
       {"title": {"type": "string", "description": "Titre de la présentation (diapo de couverture)"},
        "subtitle": {"type": "string", "description": "Sous-titre de couverture"},
        "slides": {"type": "array", "items": {"type": "object"},
                   "description": "Diapos : [{title, bullets:[...]}, …]"},
        "output_path": {"type": "string", "description": "Fichier .pptx de sortie (défaut : Bureau)"}},
       []),
    _t("pptx_read", "Extrait le texte de toutes les diapos d'un PowerPoint (.pptx).",
       {"path": {"type": "string", "description": "Fichier .pptx"}},
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
       {"path": {"type": "string", "description": "Fichier .docx"},
        "format": {"type": "string", "enum": ["markdown", "text"], "description": "Format de sortie (défaut markdown)"},
        "output_path": {"type": "string", "description": "Fichier texte de sortie (optionnel)"}},
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
       {"path": {"type": "string", "description": "Fichier CSV source"},
        "chart_type": {"type": "string", "enum": ["bar","line","pie"], "description": "Type de graphique"},
        "label_column": {"type": "integer", "description": "Index de la colonne des étiquettes (défaut 0)"},
        "value_columns": {"type": "string", "description": "Indices des colonnes de valeurs, ex '1,2' (auto si absent)"},
        "title": {"type": "string", "description": "Titre du graphique"},
        "output_path": {"type": "string", "description": "Image PNG de sortie"}},
       ["path"]),
    _t("xlsx_read", "Lit un fichier Excel (.xlsx) et retourne le contenu d'une feuille.",
       {"path":     {"type": "string", "description": "Chemin du fichier Excel (.xlsx)"},
        "sheet":    {"type": "string", "description": "Nom de la feuille (défaut : première feuille active)"},
        "action":   {"type": "string", "enum": ["read", "sheets", "summary"],
                     "description": "read = données, sheets = liste des onglets, summary = dimensions (défaut : read)"},
        "max_rows": {"type": "integer", "description": "Nombre max de lignes à retourner (défaut 50)"}},
       ["path"]),
    _t("url_analyze", "Analyse une URL : titre, meta description, statut HTTP, serveur et temps de réponse.",
       {"url": {"type": "string", "description": "URL à analyser (avec ou sans https://)"}},
       ["url"]),
    _t("zip_list", "Liste le contenu d'une archive ZIP sans l'extraire.",
       {"path": {"type": "string", "description": "Chemin de l'archive ZIP"}},
       ["path"]),
    _t("color_tool", "Convertit une couleur entre HEX, RGB et HSL, et calcule la couleur complémentaire.",
       {"color": {"type": "string",
                  "description": "Couleur à convertir. Formats acceptés : #RRGGBB (#FF5733), rgb(r,g,b) (rgb(255,87,51)) ou hsl(h,s%,l%)"}},
       ["color"]),
    # ── Section 17 ──────────────────────────────────────────────────────────
    _t("sqlite_query", "Exécute une requête SQL (SELECT ou écriture avec confirmation) sur une base SQLite locale.",
       {"db_path":   {"type": "string",  "description": "Chemin du fichier .db ou .sqlite"},
        "query":     {"type": "string",  "description": "Requête SQL à exécuter"},
        "max_rows":  {"type": "integer", "description": "Nombre max de lignes retournées (défaut 100)"},
        "confirmed": {"type": "boolean", "description": "Requis pour les requêtes d'écriture (INSERT/UPDATE/DELETE…)"}},
       ["db_path", "query"]),
    _t("sqlite_tables", "Liste les tables et leur schéma dans une base SQLite.",
       {"db_path": {"type": "string", "description": "Chemin du fichier SQLite (.db, .sqlite)"}},
       ["db_path"]),
    _t("git_info", "Retourne des informations sur un dépôt Git : branche, statut, commits, branches.",
       {"path":   {"type": "string", "description": "Chemin du dépôt (défaut : dossier courant)"},
        "action": {"type": "string", "enum": ["status", "log", "branches", "diff"],
                   "description": "status = fichiers modifiés, log = historique, branches = liste, diff = statistiques"},
        "count":  {"type": "integer", "description": "Nombre de commits pour l'action 'log' (défaut 10)"}},
       []),
    _t("bulk_rename", "Renomme en masse des fichiers d'un dossier selon un motif regex (avec confirmation et mode dry_run).",
       {"folder":   {"type": "string", "description": "Dossier contenant les fichiers"},
        "pattern":  {"type": "string", "description": "Expression régulière à trouver dans le nom de fichier"},
        "replace":  {"type": "string", "description": "Texte de remplacement (peut utiliser des groupes de capture)"},
        "glob":     {"type": "string", "description": "Filtre de fichiers ex: *.jpg (défaut: *)"},
        "dry_run":  {"type": "boolean", "description": "Si true, simule seulement et demande confirmation (défaut : true)"},
        "confirmed":{"type": "boolean", "description": "Requis pour exécuter le renommage réel"}},
       ["folder", "pattern"]),
    # ── Section 18 ──────────────────────────────────────────────────────────
    _t("screen_ocr", "Capture l'écran et en extrait le texte via OCR (pytesseract). Combine screenshot + OCR en un seul appel.",
       {"lang":  {"type": "string", "description": "Langue OCR (défaut : fra+eng). Exemples : eng, fra, deu"},
        "region":{"type": "array",  "description": "Région [x, y, largeur, hauteur] ou null pour tout l'écran"},
        "save":  {"type": "boolean","description": "Sauvegarder le screenshot sur le Bureau (défaut : false)"}},
       []),
    _t("file_batch_read", "Lit plusieurs fichiers texte en une seule requête et retourne leur contenu agrégé.",
       {"paths":              {"type": "array",   "description": "Liste des chemins de fichiers à lire"},
        "max_chars_per_file": {"type": "integer", "description": "Limite de caractères par fichier (défaut 5000)"},
        "encoding":           {"type": "string",  "description": "Encodage (défaut utf-8)"}},
       ["paths"]),
    _t("clipboard_append", "Ajoute du texte au contenu actuel du presse-papiers (append) sans écraser ce qui est déjà dedans.",
       {"text":      {"type": "string", "description": "Texte à ajouter au presse-papiers"},
        "separator": {"type": "string", "description": "Séparateur entre l'ancien et le nouveau contenu (défaut : saut de ligne)"}},
       ["text"]),
    _t("text_join", "Fusionne une liste de textes avec un séparateur personnalisé (jointure, concaténation, déduplication).",
       {"texts":     {"type": "array",   "description": "Liste des textes à fusionner"},
        "separator": {"type": "string",  "description": "Séparateur entre les textes (défaut : saut de ligne)"},
        "prefix":    {"type": "string",  "description": "Préfixe ajouté à chaque élément"},
        "suffix":    {"type": "string",  "description": "Suffixe ajouté à chaque élément"},
        "dedupe":    {"type": "boolean", "description": "Supprimer les doublons avant la fusion (défaut : false)"}},
       ["texts"]),
    # ── Section 19 ──────────────────────────────────────────────────────────
    _t("code_python",
       "Exécute un extrait de code Python dans un SOUS-PROCESSUS isolé (vrai « Code Interpreter »). "
       "Idéal pour : calculs de données, statistiques, transformations, et GRAPHIQUES — un simple "
       "plt.savefig('nom.png') suffit, l'image est automatiquement détectée et affichée cliquable "
       "dans le chat (pas besoin de chemin spécial). Bibliothèques disponibles : json, math, re, "
       "datetime, collections, statistics, random, numpy/pandas/matplotlib (si installés) — utilise "
       "un simple 'import'. Imprime le résultat avec print() pour le voir, ou définis une variable "
       "'result'/'output' pour qu'elle apparaisse dans le champ 'result'. "
       "os/subprocess/réseau/fichiers (open) demandent une confirmation explicite.",
       {"code":      {"type": "string",  "description": "Code Python à exécuter"},
        "timeout":   {"type": "integer", "description": "Délai max en secondes (1–60, défaut 15)"},
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
       {"path": {"type": "string", "description": "Dossier à analyser"},
        "min_size_kb": {"type": "integer", "description": "Taille minimale en Ko (défaut 10)"},
        "max_files": {"type": "integer", "description": "Limite de fichiers scannés (défaut 5000)"}},
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
