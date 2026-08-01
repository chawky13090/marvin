"""
SecretaryAI Backend — Configuration centralisée.
Tous les chemins et paramètres sont définis ici.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Chemins ─────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = str(DATA_DIR / "secretary.db")
QDRANT_PATH = str(DATA_DIR / "qdrant")
RERANKER_CACHE_DIR = str(DATA_DIR / "reranker_cache")  # v2.115 — modèle cross-encoder local (flashrank)

# Créer les répertoires de données si nécessaire
DATA_DIR.mkdir(exist_ok=True)
(DATA_DIR / "qdrant").mkdir(exist_ok=True)

# ── Ollama ───────────────────────────────────────────────────────────────────
# Use 127.0.0.1 instead of localhost to avoid Windows IPv6 resolution delay (~2s)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b")   # modèle par défaut (agent)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

# ── Profils de modèles (routing automatique) ─────────────────────────────────
# Chaque profil définit le meilleur modèle pour un type de tâche.
# Le mode "auto" sélectionne le profil en fonction du message de l'utilisateur.
MODEL_PROFILES: dict = {
    "agent": {
        "model":       "qwen2.5:7b",
        "temperature": 0.1,     # très bas → tool calling déterministe, zéro hallucination
        "label":       "🤖 Agent",
        "tools":       True,
        "description": "Tâches avec outils, actions sur le PC",
    },
    "chat": {
        "model":       "qwen2.5:3b",
        "temperature": 0.4,     # bas pour réduire les hallucinations sur tool calling
        "label":       "💬 Chat",
        "tools":       True,    # qwen2.5:3b supporte le tool calling — activé pour gérer météo/horaire/recherche
        "description": "Réponses rapides, questions simples (avec outils légers)",
    },
    "analysis": {
        "model":       "qwen2.5:14b",
        "temperature": 0.15,
        "label":       "🔍 Analyse",
        "tools":       True,
        "description": "Analyse approfondie, rédaction longue, documents",
    },
    "vision": {
        "model":       "qwen3.5:2b",
        "temperature": 0.3,
        "label":       "👁️ Vision",
        "tools":       False,
        "description": "Analyse et description d'images",
    },
}

# Ordre de fallback si le modèle préféré n'est pas installé
AUTO_MODE_FALLBACKS = ["qwen2.5:7b", "qwen2.5:3b", "qwen3:8b", "hermes3:8b", "llama3.2:3b"]

# ── Serveur ──────────────────────────────────────────────────────────────────
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8005"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:3000")

# ── Agent ────────────────────────────────────────────────────────────────────
MAX_TOOL_STEPS = 10         # max itérations d'appel d'outils par réponse
MAX_CONTEXT_MESSAGES = 16   # messages récents envoyés à Ollama (augmenté pour mieux suivre le contexte)

# ══════════════════════════════════════════════════════════════════════════════
# Niveaux de permission
# ══════════════════════════════════════════════════════════════════════════════
PERMISSION_SECURE   = 1   # Lecture seule — aucune modification du système
PERMISSION_STANDARD = 2   # Écriture autorisée, confirmation pour les actions dangereuses
PERMISSION_EXPERT   = 3   # Accès total, aucune confirmation requise

DEFAULT_PERMISSION_LEVEL = PERMISSION_STANDARD

# Outils bloqués au niveau Sécurisé (1) — toute action d'écriture/système
SECURE_BLOCKED_TOOLS: set[str] = {
    "file_write",
    "file_delete",
    "file_move",
    "file_rename",
    "file_copy",
    "file_create_folder",
    "file_create_docx",
    "file_convert_docx_to_pdf",
    "file_create_xlsx",
    "file_create_pdf",
    "pc_run_command",
    "pc_run_powershell",
    "pc_run_elevated",  # exécution EN ADMINISTRATEUR — jamais en niveau Sécurisé
    "pc_process_kill",
    "pc_clipboard_set",
    "pc_open_file",
    "google_drive_upload",
    "onedrive_upload",
    "infographic_create",  # crée un fichier sur le disque
    "file_compress",       # crée un fichier sur le disque
    "file_extract",        # extrait des fichiers sur le disque
    # Manipulation PDF/image & maintenance (écrivent sur le disque)
    "pdf_merge", "pdf_split", "pdf_rotate", "images_to_pdf",
    "pdf_watermark", "pdf_protect", "pdf_extract_images",
    "image_crop", "image_rotate", "image_compress", "image_batch",
    "system_cleanup",
    # Audio (écrivent un fichier sur le disque)
    "audio_extract", "audio_convert", "audio_trim", "audio_merge", "audio_volume",
    # Bureautique & rendu (écrivent un fichier sur le disque)
    "pdf_to_images", "pdf_fill_form", "pptx_create", "csv_to_xlsx", "xlsx_to_csv",
    "text_to_speech", "pdf_compress", "pdf_add_page_numbers", "csv_to_chart",
    # Email (envoi = action externe irréversible)
    "email_send",
    # SSH (exécution distante = action externe potentiellement irréversible)
    "ssh_exec",
    "ssh_write_and_run",
    "code_workspace_start",
    "code_workspace_control",
    "winget_install",
    "winget_upgrade",
    "winget_uninstall",
    "tweak_debloat_remove",
    "system_restore_point",
    "catharsis_clean",
    "pc_pull_ollama_model",  # télécharge plusieurs Go et écrit sur le disque, sans confirmation jusqu'ici
}

# ── Outils nécessitant une confirmation manuelle (niveau Standard = 2) ────────
DANGEROUS_TOOLS: set[str] = {
    "file_delete",
    "pc_run_command",
    "pc_run_powershell",  # le contenu vient du LLM : preuve UI obligatoire
    "pc_run_elevated",  # exécution EN ADMINISTRATEUR — toujours confirmée
    "pc_process_kill",
    "task_delete",
    "note_delete",
    "event_delete",     # suppression d'un événement d'agenda (irréversible)
      "memory_delete",    # suppression de mémoire à long terme
      "project_delete",   # suppression d'un espace logique persistant
    "email_send",       # envoi d'email irréversible
    "email_automation_run",  # peut envoyer des emails automatiquement (mode autonome)
    "ssh_exec",         # commande distante potentiellement destructrice
    "ssh_exec_multi",   # commande sur plusieurs serveurs
    "ssh_upload",       # écriture de fichier sur un serveur distant
    "ssh_write_and_run",  # écriture + exécution d'un script sur un serveur distant
    "system_cleanup",   # suppression de fichiers temporaires (delete=true)
    "bulk_rename",      # mutation groupée de noms, avec manifeste de rollback
    "itsm_ticket_create",  # crée un ticket visible dans un système externe (GLPI...)
    "pc_gui_click",      # v2.149 — clic réel dans une fenêtre (UI Automation)
    "pc_gui_type",       # v2.149 — écriture réelle dans un champ (UI Automation)
    "vm_lab_install",    # recrée une VM Hyper-V de test et installe son OS
    "code_workspace_start",  # crée dépôt/worktree et peut lancer un job Auto
    "code_workspace_control",  # reprend ou annule un job Auto persistant
    "long_task_start",   # v2.151 — "Plan mode" : démarrage réel après validation du plan
    "winget_install",
    "winget_upgrade",
    "winget_uninstall",
    "tweak_debloat_remove",
    "system_restore_point",
    "catharsis_clean",
    "pc_pull_ollama_model",  # télécharge plusieurs Go et écrit sur le disque, sans confirmation jusqu'ici
}

# Outils mixtes lecture/mutation. Les actions listées restent des lectures sûres; toute
# autre action suit les politiques DANGEROUS + SECURE_BLOCKED sans rendre le statut
# indisponible en mode Sécurisé.
CONDITIONAL_TOOL_SAFE_ACTIONS: dict[str, frozenset[str]] = {
    "computer_control": frozenset(
        {"observe", "verify", "screenshot", "list_windows", "wait"}
    ),
    "tweak_telemetry": frozenset({"status"}),
    "tweak_network_harden": frozenset({"status"}),
    "os_power_plan": frozenset({"get", "status"}),
    "os_dark_mode": frozenset({"get", "status"}),
    "os_firewall": frozenset({"status"}),
    "os_hibernation": frozenset({"status"}),
    "os_network_adapters": frozenset({"list", "status"}),
}
