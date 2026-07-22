"""Routage deterministe des profils et modeles de l'agent Marvin.

Ce module isole l'inventaire Ollama, la detection du profil de travail et les
facades de confidentialite. Il ne depend ni de FastAPI, ni des outils, ni de la
boucle agentique, afin de rester testable sans demarrer Marvin.
"""
from __future__ import annotations

import httpx

import cloud_routing as _cr
from config import AUTO_MODE_FALLBACKS, MODEL_PROFILES, OLLAMA_URL

_ACTION_KEYWORDS = {
    # Fichiers & documents
    "trouve tous les", "cherche tous les", "trouve les fichiers", "cherche les fichiers",
    "trouve le fichier", "trouve le dossier", "cherche le fichier", "cherche le dossier",
    "ou est", "où est", "ou se trouve", "où se trouve",
    "*.pdf", "*.docx", "*.xlsx", "*.log", "*.txt", "*.py",
    "créé", "cree", "crée", "créer", "creer", "fichier", "dossier", "bureau",
    "documents", "ouvre", "ouvrir", "lance", "lancer", "cherche", "recherche",
    "liste", "affiche", "montre", "infographie", "graphique", "excel", "word",
    "pdf", "docx", "capture", "screenshot", "copie", "copier", "déplace",
    "deplace", "supprime", "supprimer", "renomme", "renommer", "écris", "ecris",
    "écrire", "ecrire", "télécharge", "telecharge", "drive", "onedrive",
    # PC & processus
    "commande", "processus", "presse-papiers", "clipboard", "fenêtre", "fenetre",
    "notification", "notifie", "application", "programme",
    # Communication & Calendrier
    "outlook", "gmail", "email", "courriel", "mail", "calendrier", "calendar",
    "planifie", "planifier", "rappel", "rendez-vous", "réunion", "meeting",
    "agenda", "événement", "evenement", "crée un événement", "ajoute au calendrier",
    "envoie", "envoyer", "inbox", "boîte",
    "reçu", "reçu", "expéditeur", "expediteur", "destinataire", "objet",
    # Notes & tâches & mémoire
    "note", "tâche", "tache", "mémorise", "memorise", "souvenir",
    # Web & cloud
    "web", "navigue", "internet", "site", "url", "lien",
    # Réseau
    "ping", "réseau", "reseau", "network", "scan", "port", "dns", "traceroute",
    "whois", "ip", "wifi", "connexion", "connecte",
    # SSH
    "ssh", "serveur", "serveur distant", "terminal",
    # OCR & IA
    "ocr", "extrais", "extraire le texte", "capture d'écran ocr", "image", "photo",
    # Voice & audio
    "transcris", "transcription", "audio", "enregistrement", "whisper", "mp3", "wav", "ogg",
    # Archives
    "zip", "tar", "archive", "compresse",
    # Calcul & date & météo
    "calcule", "calculator", "calculer", "math", "sqrt", "sin", "cos", "log", "factorielle",
    "heure", "date", "fuseau", "timezone", "maintenant", "aujourd", "demain", "hier",
    "météo", "meteo", "temps", "température", "pluie", "neige", "vent", "prévisions", "previsions",
    # Traduction
    "traduis", "traduction", "traduire", "translate", "en anglais", "en français", "en espagnol",
    "en allemand", "en chinois", "en japonais", "en arabe", "en russe", "en portugais",
    # Conversion & sécurité
    "convertis", "conversion", "convertir", "km en", "kg en", "celsius", "fahrenheit",
    "miles", "pounds", "litres", "gallons", "mo en", "go en",
    "mot de passe", "password", "mdp", "pin", "génère un mdp", "securise",
    # Traitement de données
    "hash", "sha256", "md5", "sha512", "empreinte", "intégrité", "checksum",
    "base64", "encode", "decode", "encodage",
    "extrait les emails", "extraire les urls", "extraire les numéros",
    "compare ces textes", "différence entre", "diff",
    "qr code", "qrcode", "qr", "flashcode",
    "redimensionne", "redimensionner", "resize", "convertis l'image", "convertir image",
    "infos de l'image", "métadonnées image", "exif",
    "json", "formate le json", "valide le json", "minifie",
    # CSV & PowerShell
    "csv", "analyse ce csv", "statistiques csv", "données csv", "colonnes csv",
    "powershell", "script ps1", "cmdlet", "get-", "set-", "new-", "remove-",
    "invoke-", "write-host", "write-output",
    # Stats texte & IP
    "compte les mots", "nombre de mots", "statistiques texte", "temps de lecture",
    "mots fréquents", "longueur du texte",
    "adresse ip", "géolocalisation", "geolocalis", "whois ip", "ip publique",
    "localisation ip", "pays de l'ip",
    # Section 16 — Documents, Archives & Couleurs
    "lis ce pdf", "lire le pdf", "extraire le texte du pdf", "pages du pdf",
    "métadonnées pdf", "infos du pdf", "auteur du pdf", "pages du fichier",
    "lis ce excel", "lire le xlsx", "feuilles excel", "colonnes excel",
    "analyse une url", "infos de l'url", "titre de la page", "statut http",
    "vérifie ce site", "temps de réponse", "meta description",
    "contenu du zip", "lister le zip", "archive zip",
    "convertis cette couleur", "hex en rgb", "rgb en hex", "hsl", "couleur complémentaire",
    "teinte", "saturation", "luminosité couleur",
    # Section 17 — SQLite, Git & Fichiers avancés
    "sqlite", "base de données", "requête sql", "tables sqlite", "interroge la base",
    "query sql", "select from", "insert into", "update table",
    "dépôt git", "branche git", "commits git", "statut git", "log git",
    "git status", "git log", "git branch",
    "renomme tous les fichiers", "renommage en masse", "bulk rename", "regex fichiers",
    # Section 18-19 — Outils composés & code
    "capture l'écran et extrais", "ocr écran", "lis le texte à l'écran",
    "lis plusieurs fichiers", "lecture de fichiers", "batch read",
    "fusionne ces textes", "joins ces lignes", "concatène",
    "exécute ce code", "lance ce script python", "calcule en python",
    "code python", "script python", "analyse avec python",
}

# Mots-clés déclenchant le profil "analysis" (modèle 14b, réponse longue)
_ANALYSIS_KEYWORDS = {
    "analyse", "rédige", "redige", "rapport", "résumé", "resume", "synthèse",
    "synthese", "explique en détail", "explique en detail", "compare", "évalue",
    "evalue", "dissertation", "lettre de motivation", "courrier", "contrat",
    "essai", "approfond", "développe", "developpe", "stratégie",
    "strategie", "documentation complète", "documentation complete",
    # Common educational/explanation requests
    "explique-moi", "explique moi", "qu'est-ce que", "qu est ce que",
    "comment fonctionne", "pourquoi", "détaillé", "detaille",
    "en profondeur", "complet", "exhaustif", "argumente",
}

# Cache des modèles disponibles dans Ollama (mis à jour au démarrage)
_available_models_cache: set[str] = set()


async def refresh_model_cache() -> set[str]:
    """Interroge Ollama pour lister les modèles installés et met à jour le cache."""
    global _available_models_cache
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                data = r.json()
                names: set[str] = {m["name"] for m in data.get("models", [])}
                # Ajouter aussi les noms de base sans tag (ex: "qwen2.5:7b" → "qwen2.5")
                bases: set[str] = {n.split(":")[0] for n in names}
                _available_models_cache = names | bases
    except Exception:
        pass
    return _available_models_cache


def is_model_available(name: str) -> bool:
    """Vérifie si un modèle est dans le cache (vrai si cache vide → on suppose dispo)."""
    if not _available_models_cache:
        return True
    return name in _available_models_cache or name.split(":")[0] in _available_models_cache


def pick_available(preferred: str, fallbacks: list[str]) -> str:
    """Retourne le premier modèle disponible de la liste (preferred en tête)."""
    for name in [preferred, *fallbacks]:
        if is_model_available(name):
            return name
    return preferred  # last resort


# ══════════════════════════════════════════════════════════════════════════════
# v2.119 — Ollama Cloud : routage local/cloud par SENSIBILITÉ, pas par profil
# ══════════════════════════════════════════════════════════════════════════════
# Demande explicite de l'utilisateur : « rester sur du purement local peut être pertinent
# quand on manipule des données sensibles comme mail, mots de passe et autre, mais pour
# optimiser Marvin l'option Ollama Cloud est très utile ». Les profils "agent"/"chat" gèrent
# TOUT mélangé (météo autant qu'emails/SSH) — épingler un profil entier sur le cloud enverrait
# aussi les emails/mots de passe/sorties SSH chez Ollama Cloud. Le routage se fait donc au
# niveau de la REQUÊTE (mots-clés + outils réellement en jeu), pas du profil : toute donnée
# sensible détectée force le modèle local, cloud seulement pour le reste. Deux couches :
#   1. Au début du tour : mots-clés sensibles dans le dernier message + tool_calls déjà
#      présents dans l'historique récent de la conversation (un "résume-moi ça" après un
#      email déjà chargé en contexte doit rester local aussi).
#   2. PENDANT la boucle d'outils : si un outil sensible est appelé alors qu'on est sur un
#      modèle cloud (ex. l'agent décide d'appeler email_read sans que "email" soit dans le
#      message initial), bascule immédiate en local AVANT que le résultat de l'outil ne soit
#      envoyé au modèle cloud au tour suivant.
# v2.122 — les primitives partagées (mots-clés sensibles, lecture des réglages cloud,
# Hyper sécurisé, Ultra débridé) vivent désormais dans `cloud_routing.py`, réutilisé aussi
# par `tools.py::_ollama_generate` (13+ outils qui appellent Ollama en interne — document_
# generate, email_*, text_summarize... — ignoraient jusqu'ici complètement le routage
# cloud/sensibilité de la boucle de chat principale). `agent.py` ne peut pas être importé
# par `tools.py` (import circulaire : agent.py importe déjà TOOLS_REGISTRY/TOOLS_SPEC
# depuis tools.py), d'où l'extraction dans un module séparé sans dépendance vers l'un ou
# l'autre.
SENSITIVE_TOOL_PREFIXES = _cr.SENSITIVE_TOOL_PREFIXES


def is_sensitive_request(messages: list[dict], text_norm: str) -> bool:
    """Détecte une donnée sensible dans la requête ou son historique récent.

    Le caller applique ensuite la politique de confidentialité active. En particulier,
    Ultra débridé peut explicitement autoriser le cloud; ce détecteur ne décide pas du mode.
    ``text_norm`` est déjà normalisé (accents retirés) par l'appelant.
    """
    if any(_cr.strip_accents(k) in text_norm for k in _cr.SENSITIVE_KEYWORDS):
        return True
    for m in messages[-8:]:
        # Le contenu récent compte aussi : « résume ça » après la lecture d'un email ou
        # le collage d'un secret ne doit pas repartir au cloud par simple anaphore.
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", "")) for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if _cr.is_sensitive_text(str(content or "")):
            return True
        for tc in (m.get("tool_calls") or []):
            if not isinstance(tc, dict):
                continue
            name = (tc.get("function") or {}).get("name") or tc.get("toolName") or ""
            if _cr.is_sensitive_tool(name):
                return True
    return False


is_sensitive_tool = _cr.is_sensitive_tool
is_cloud_model = _cr.is_cloud_model
get_cloud_config = _cr.get_cloud_config
is_local_only_lockdown = _cr.is_local_only_lockdown
is_ultra_unrestricted = _cr.is_ultra_unrestricted


def detect_profile(messages: list[dict]) -> tuple[str, str, float]:
    """
    Analyse le contexte et retourne (profile_name, model_name, temperature).

    Ordre de détection :
      1. Images présentes  → vision
      2. Mots-clés analyse → analysis (14b)
      3. Mots-clés action  → agent   (7b tool calling)
      4. Message court     → chat    (3b rapide)
      5. Défaut            → agent
    """
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if not last_user:
        p = MODEL_PROFILES["agent"]
        return "agent", pick_available(p["model"], AUTO_MODE_FALLBACKS), p["temperature"]

    # ── 1. Images présentes → Vision ──────────────────────────────────────────
    content = last_user.get("content", "")
    images  = last_user.get("images", [])
    has_images = bool(images)
    if isinstance(content, list):
        has_images = has_images or any(
            part.get("type") in ("image_url", "image") for part in content
        )

    if has_images:
        p = MODEL_PROFILES["vision"]
        model = pick_available(p["model"], ["llava:7b", "llava", *AUTO_MODE_FALLBACKS])
        return "vision", model, p["temperature"]

    # ── Extraire le texte brut ─────────────────────────────────────────────────
    if isinstance(content, str):
        text = content.lower()
    elif isinstance(content, list):
        text = " ".join(
            part.get("text", "") for part in content if part.get("type") == "text"
        ).lower()
    else:
        text = ""

    word_count = len(text.split())

    # ── 2. Mots-clés d'action PRIORITAIRES → Agent (tool calling) ───────────────
    # Use multi-word action phrases or high-specificity single words only,
    # to avoid routing pure text analysis requests to the agent profile.
    has_action = any(k in text for k in _ACTION_KEYWORDS)
    has_analysis = any(k in text for k in _ANALYSIS_KEYWORDS)

    # If BOTH action and analysis keywords match, the action keywords must be
    # genuinely tool-related (not just content words like "texte", "lien").
    # Route to agent only when there are clear tool indicators.
    _STRONG_ACTION = {
        # Files & system - specific enough to not false-positive
        "fichier", "dossier", "bureau", "screenshot", "capture d'ecran",
        "ping ", "dns lookup", "traceroute",
        "ssh", "email", "gmail", "outlook", "calendrier", "calendar", "agenda",
        "drive", "onedrive", "processus", "presse-papiers", "clipboard",
        "powershell", "commande shell",
        "mon pdf", "mon docx", "mon excel", "mon csv", "analyse ce csv",
        "analyse le csv", "liste les fichiers", "liste mes fichiers",
        "liste mes taches", "liste mes notes", "liste mes mails",
        "mes emails", "mes rendez", "mes evenements",
        "wifi", "reseau local", "scan de port", "scan de ports",
        "lien url", "cette url", "ce site",
        "ma tache", "ma tâche", "cette note",
        "hash sha", "sha256", "base64", "qr code", "mot de passe",
        "sqlite", "code python", "git status", "git log",
        "ce zip", "ce fichier zip", "redimensionne", "convertis l'image",
        # High-confidence action verbs (not content words)
        "recherche dans", "cherche dans", "trouve le fichier",
        "ouvre le fichier", "écris dans", "supprime le fichier",
    }

    # If a strong action keyword is present, definitely use agent profile
    has_strong_action = any(k in text for k in _STRONG_ACTION)

    if has_strong_action:
        p = MODEL_PROFILES["agent"]
        model = pick_available(p["model"], AUTO_MODE_FALLBACKS)
        return "agent", model, p["temperature"]

    # If only weak action keywords (like "texte", "lien") with analysis keywords,
    # prefer the analysis profile for better quality
    if has_analysis or word_count > 80:
        p = MODEL_PROFILES["analysis"]
        model = pick_available(p["model"], ["qwen2.5:7b", *AUTO_MODE_FALLBACKS])
        return "analysis", model, p["temperature"]

    if has_action:
        p = MODEL_PROFILES["agent"]
        model = pick_available(p["model"], AUTO_MODE_FALLBACKS)
        return "agent", model, p["temperature"]

    # ── 4. Message court et conversationnel → Chat léger ─────────────────────
    if word_count <= 12:
        p = MODEL_PROFILES["chat"]
        model = pick_available(p["model"], ["qwen2.5:3b", "llama3.2:3b", *AUTO_MODE_FALLBACKS])
        return "chat", model, p["temperature"]

    # ── 5. Défaut → Agent ─────────────────────────────────────────────────────
    p = MODEL_PROFILES["agent"]
    model = pick_available(p["model"], AUTO_MODE_FALLBACKS)
    return "agent", model, p["temperature"]
