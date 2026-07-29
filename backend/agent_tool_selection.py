"""Selection bornee et explicable des outils exposes au LLM."""
from __future__ import annotations

import cloud_routing as _cr
import database as db
from tools import TOOLS_SPEC
from tool_capability_ranking import build_catalog, rank_capabilities

_ALWAYS_INCLUDE = {
    "pc_get_real_paths",
    "memory_save", "memory_list",
    "datetime_info",
}

# Repli BORNÉ quand aucun mot-clé métier ne matche : un petit jeu d'outils
# polyvalents, AU LIEU des ~245 specs (qui font un prompt énorme → réponse de
# plusieurs minutes, surtout sur petit GPU). Les noms inexistants sont ignorés.
_COMMON_TOOLS = {
    "web_search", "web_browse", "datetime_info", "weather",
    "task_create", "task_list", "task_update",
    "note_create", "note_list",
    "event_create", "event_list", "daily_briefing",
    "email_list", "email_digest",
    "system_search", "file_find", "pc_system_info",
    "translate", "calculator", "text_summarize",
}

# Mapping keyword → tools relevant for that keyword
# When user message contains these words, we include the matching tools
_KEYWORD_TOOLS = {
    # v2.183 — Génération de logo locale (GPU) : sans cette entrée, logo_generate/logo_list
    # sont enregistrés mais INVISIBLES sur les profils filtrés chat/agent (leçon répétée
    # cette session, cf. v2.93/v2.113 — un outil hors _KEYWORD_TOOLS n'est jamais proposé).
    ("logo", "logotype", "icône de marque", "icone de marque"):
        {"logo_generate", "logo_list"},

    # v2.184 — journal des vrais bugs (exceptions + traceback), pour un audit après usage
    # intensif sans supervision.
    ("journal des bugs", "liste les bugs", "quels bugs", "bug log", "erreurs recentes",
     "erreurs récentes", "qu'est ce qui a plante", "qu'est-ce qui a planté",
     "qu'est ce qui a bug", "qu'est-ce qui a buggé"):
        {"bug_log_list"},

    # v2.183 — changer le format d'un document déjà généré (docx<->pdf), sans le regénérer.
    ("plutot en word", "plutôt en word", "plutot en pdf", "plutôt en pdf", "convertis en word",
     "convertis en pdf", "convertir en word", "convertir en pdf", "en format word",
     "en format pdf", "change le format", "changer le format"):
        {"document_convert_format", "file_convert_docx_to_pdf"},

    # Météo
    ("météo", "meteo", "temps", "température", "temperature", "pluie", "neige",
     "vent", "prévision", "previsions", "il fait", "il pleut", "demain", "weather"):
        {"weather"},

    # Recherche web
    ("web", "internet", "searxng", "cherche sur", "recherche en ligne",
     "actualité", "news", "actu", "info", "trouve en ligne", "sur le net", "sur le web",
     "renseigne-toi", "renseigne toi"):
        {"web_search", "web_browse", "web_research"},

    # v2.142 — Recherche APPROFONDIE (« Deep Research ») : groupe de mots-clés SÉPARÉ et
    # plus restrictif que la recherche web générale ci-dessus — outil volontairement lent
    # (plusieurs minutes), ne doit apparaître que sur une demande explicite de profondeur/
    # exhaustivité, jamais sur "cherche sur le web" tout court.
    ("recherche approfondie", "recherche exhaustive", "recherche detaillee",
     "recherche détaillée", "rapport de recherche", "rapport complet sur",
     "rapport detaille sur", "rapport détaillé sur", "deep research", "enquete complete",
     "enquête complète", "analyse approfondie du web", "fouille le web"):
        {"web_deep_research"},

    # v2.142 — Conseil de plusieurs modèles IA (« Model Council ») : signal explicite
    # uniquement, jamais déclenché par défaut (coût de plusieurs appels LLM en parallèle).
    ("plusieurs ia", "plusieurs modeles", "plusieurs modèles", "conseil de modeles",
     "conseil de modèles", "demande a plusieurs", "demande à plusieurs",
     "differents modeles", "différents modèles", "model council", "deuxieme avis",
     "deuxième avis", "second avis", "autre ia", "autre modele", "autre modèle"):
        {"ai_model_council"},

    # v2.145 — Décomposition en sous-tâches parallèles (« Ultra mode »)
    ("plusieurs angles", "sous plusieurs angles", "decompose", "décompose",
     "sous-taches", "sous-tâches", "en parallele", "en parallèle", "plusieurs volets",
     "differents aspects", "différents aspects"):
        {"ai_subagents_run"},

    # v2.145 — Tâche longue autonome (« ChatGPT Work »)
    ("tache de fond", "tâche de fond", "en arriere-plan", "en arrière-plan",
     "pendant que je fais autre chose", "occupe-toi de", "occupe toi de",
     "fais avancer ce projet", "tache longue", "tâche longue", "sans supervision"):
        {"long_task_start", "long_task_status", "long_task_stop"},

    # v2.122 — Fraîcheur de l'information (règle d'or #8) : signaux qu'une réponse "de
    # mémoire" risque d'être périmée (version, actualité, disponibilité, événement récent) —
    # déclenche la recherche web même sans mention explicite de "web"/"internet".
    ("derniere version", "dernière version", "nouvelle version", "quoi de neuf",
     "encore d'actualite", "toujours d'actualite", "encore disponible", "existe encore",
     "vient de sortir", "recemment sorti", "récemment sorti", "sorti recemment",
     "en ce moment", "actuellement", "a jour", "à jour", "obsolete", "obsolète",
     "depuis quand", "cette annee", "cette année"):
        {"web_search", "web_research"},

    # Lire une page web
    ("url", "site", "page web", "lien", "http", "navigateur", "ouvre le site"):
        {"web_browse", "url_analyze", "web_browser_open", "web_research"},

    # Fichiers
    ("fichier", "dossier", "bureau", "documents", "downloads", "téléchargement",
     "fichiers", "dossiers"):
        {"system_search", "file_find", "file_list", "file_info", "file_read",
         "file_write", "file_delete", "file_rename", "file_move", "file_copy",
         "file_create_folder", "file_search_text", "pc_get_real_paths"},

    # Recherche dans fichiers
    ("trouve", "cherche", "où est", "ou est", "ou se trouve", "trouver", "*.pdf",
     "*.docx", "*.xlsx"):
        {"system_search", "system_search_content", "file_find", "file_search_text"},

    # Logiciels installés / inventaire logiciel
    ("logiciel installé", "logiciels installés", "logiciels installer", "inventaire logiciel",
     "liste des programmes", "programmes installés", "quels logiciels", "applications installées",
     "liste logiciels", "logiciels sur ce pc", "logiciels du pc"):
        {"pc_installed_software", "win_system_report", "pc_system_info"},

    # Installer / mettre à jour / désinstaller un logiciel (Winget) — bug réel corrigé
    # v2.113 : aucune entrée ne routait ici avant, le LLM tombait parfois sur du routage
    # sémantique fragile (marche pour "vlc" + "winget" explicite, échoue pour un nom moins
    # connu comme "victoria") → il "documentait" une installation (document_generate) au
    # lieu d'installer réellement. Stem court "instal" (pas "installe") pour matcher aussi
    # "install"/"installation" sans le "e" final — repéré en reproduisant le bug exact avec
    # le message original de l'utilisateur ("install le logiciel victoria", sans "e").
    # Matche aussi "installés"/"installer un inventaire" (substring) mais sans risque : ça
    # ne fait qu'AJOUTER winget_* à l'ensemble déjà proposé, jamais retirer pc_installed_software.
    ("instal", "télécharge et installe", "telecharge et installe",
     "mets à jour", "mets a jour", "met à jour", "met a jour", "mettre à jour", "mettre a jour",
     "désinstal", "desinstal", "winget"):
        {"winget_search", "winget_install", "winget_upgrade", "winget_uninstall",
         "winget_list_upgrades", "winget_list_installed"},

    # Recherche unifiée (tout à la fois)
    ("cherche partout", "recherche partout", "retrouve tout", "trouve tout ce qui", "tout ce qui concerne",
     "partout où", "dans tout", "recherche globale", "cherche dans tout"):
        {"unified_search", "system_search", "system_search_content", "document_ask"},

    # Recherche par CONTENU (fouiller le contenu des documents du PC)
    ("qui parle de", "qui contient", "où j'ai écrit", "ou j'ai ecrit", "le document sur",
     "le fichier où", "le fichier ou", "retrouve le document", "fouille", "fouiller",
     "dans le contenu", "à l'intérieur des fichiers", "le document qui mentionne",
     "cherche dans mes fichiers", "le contrat avec", "le devis de"):
        {"system_search_content", "system_search", "file_search_text", "document_ask"},

    # Documents Word/PDF/Excel
    ("word", "docx", "rédige un doc", "crée un doc", "lettre"):
        {"file_create_docx", "file_convert_docx_to_pdf", "pdf_read", "pdf_info",
         "docx_to_text", "text_summarize", "document_identity_set"},
    ("pdf", "convertis"):
        {"pdf_read", "pdf_info", "file_create_pdf", "file_convert_docx_to_pdf",
         "pdf_merge", "pdf_split", "pdf_rotate", "images_to_pdf",
         "pdf_watermark", "pdf_protect", "pdf_extract_images",
         "pdf_to_images", "pdf_ocr", "pdf_form_fields", "pdf_fill_form",
         "pdf_compress", "pdf_add_page_numbers", "document_identity_set"},
    ("compresse le pdf", "compresser le pdf", "allège le pdf", "réduis le pdf", "poids du pdf",
     "numérote le pdf", "numéro de page", "numéros de page", "pagination du pdf", "ajoute les pages"):
        {"pdf_compress", "pdf_add_page_numbers", "pdf_info"},
    # Synthèse vocale (text-to-speech)
    ("synthèse vocale", "synthese vocale", "lis à voix haute", "lis a voix haute", "voix off",
     "text to speech", "tts", "fais parler", "génère un audio", "transforme en audio",
     "transforme en voix", "voix off", "dis à voix haute", "narration"):
        {"text_to_speech"},
    # Graphique depuis des données
    ("graphique du csv", "graphique depuis", "trace le csv", "diagramme du csv", "camembert",
     "histogramme du csv", "graphe des données", "visualise les données", "courbe du csv"):
        {"csv_to_chart", "infographic_create", "csv_analyze"},
    ("fusionne les pdf", "fusionner pdf", "assemble les pdf", "combine les pdf",
     "découpe le pdf", "decouper le pdf", "sépare le pdf", "extraire des pages",
     "pivote le pdf", "tourne le pdf", "images en pdf", "photos en pdf",
     "filigrane sur le pdf", "protège le pdf", "protege le pdf", "mot de passe pdf",
     "chiffre le pdf", "extraire les images du pdf", "confidentiel pdf",
     "pdf scanné", "pdf scanne", "ocr du pdf", "ocr pdf", "texte du pdf scanné",
     "pdf en images", "pages du pdf en png", "remplis le formulaire", "champs du formulaire",
     "formulaire pdf"):
        {"pdf_merge", "pdf_split", "pdf_rotate", "images_to_pdf", "pdf_info",
         "pdf_watermark", "pdf_protect", "pdf_extract_images",
         "pdf_to_images", "pdf_ocr", "pdf_form_fields", "pdf_fill_form"},
    # Briefing du jour
    ("ma journée", "ma journee", "briefing du jour", "fais le point", "point du jour",
     "que dois-je faire aujourd", "résumé de ma journée", "mon programme", "quoi de neuf"):
        {"daily_briefing", "task_list", "email_digest", "event_list"},
    # Agenda / rendez-vous
    ("rendez-vous", "rendez vous", "rdv", "agenda", "planifie", "planifier", "agender",
     "mon planning", "mes rendez", "réunion", "reunion", "ajoute un événement",
     "ajoute un evenement", "note dans l'agenda", "quels rdv", "quel rendez"):
        {"event_create", "event_list", "event_update", "event_delete", "daily_briefing",
         "calendar_subscriptions", "calendar_sync"},
    # Telegram (alertes téléphone)
    ("telegram", "préviens-moi sur mon téléphone", "envoie sur mon téléphone",
     "envoie-moi un message", "notifie-moi sur telegram"):
        {"telegram_send"},
    # Génération de documentation (notes → Word)
    ("rédige", "redige", "génère un document", "genere un document", "fais-moi un rapport",
     "fais moi un rapport", "rapport d'intervention", "dossier professionnel", "dossier pro",
     "document word", "fichier word", "rédaction", "mets en forme un document",
     "procédure technique", "cahier des charges", "compte-rendu", "compte rendu",
     "génère une doc", "rédige une doc"):
        {"document_generate"},
    # v2.175 — documentation à partir des captures d'écran attachées au chat
    ("mes captures", "mes screenshots", "mes screens", "compile mes captures",
     "documente mon travail", "documentation de mon travail", "captures d'écran",
     "captures d ecran", "capture d'écran", "capture d ecran", "screenshot", "screenshots"):
        {"screenshot_list", "doc_generate_from_screenshots"},
    # Affiner une section d'un document généré
    ("développe la partie", "developpe la partie", "développe la section", "complète la section",
     "complete la section", "approfondis", "étoffe", "etoffe", "raccourcis la section",
     "reformule la partie", "ajoute un tableau dans", "affine la section", "détaille la partie"):
        {"document_refine_section", "document_generate"},
    # Documents (RAG : parle à tes documents)
    ("parle à mes documents", "parle a mes documents", "dans mes documents", "mes documents",
     "indexe", "indexer", "que dit le contrat", "que dit le document", "selon le document",
     "selon le pdf", "cherche dans le", "interroge", "pose une question au document",
     "apprends ce dossier", "lis ce document et", "base de connaissance", "ma documentation"):
        {"document_index", "document_ask", "document_list", "document_forget", "system_search_content"},
    # Agendas connectés (abonnements iCal / Google / Outlook)
    ("connecte mon agenda", "connecter mon agenda", "connecte mon calendrier",
     "abonne", "abonnement", "ical", "lien ics", "agenda google", "calendrier google",
     "agenda outlook", "synchronise mon agenda", "synchroniser l'agenda", "mets à jour mes agendas",
     "agendas connectés", "agenda externe"):
        {"calendar_subscribe", "calendar_subscriptions", "calendar_unsubscribe", "calendar_sync",
         "event_list", "daily_briefing"},

    # PowerPoint
    ("powerpoint", "pptx", "présentation", "presentation", "diaporama", "diapo",
     "slides", "slide", "deck", "support de présentation"):
        {"pptx_create", "pptx_read"},
    # Conversions bureautiques
    ("csv en excel", "csv vers excel", "convertis le csv", "excel en csv", "xlsx en csv",
     "convertis le word", "word en texte", "docx en texte", "extrais le texte du word",
     "docx en markdown", "word en markdown"):
        {"csv_to_xlsx", "xlsx_to_csv", "docx_to_text", "file_create_xlsx"},
    # Résumé / synthèse IA
    ("résume", "resume", "résumé", "synthèse", "synthese", "synthétise", "tl;dr", "tldr",
     "points clés", "points d'action", "fais-moi un résumé", "résume ce document"):
        {"text_summarize", "pdf_read", "docx_to_text"},
    ("excel", "xlsx", "tableau", "tableur", "csv"):
        {"file_create_xlsx", "xlsx_read", "csv_analyze", "csv_to_xlsx", "xlsx_to_csv", "csv_to_chart"},

    # Agenda (local prioritaire + Google si demandé)
    ("calendrier", "agenda", "rendez-vous", "événement", "evenement", "rdv", "réunion"):
        {"event_create", "event_list", "event_update", "event_delete",
         "calendar_list", "calendar_create", "calendar_update", "calendar_delete"},

    # Emails
    ("email", "mail", "courriel", "gmail", "outlook", "boîte de réception", "envoie un mail",
     "boîte mail", "boite mail", "mes mails", "quelle boîte", "quels comptes mail",
     "réponds au mail", "reponds au mail", "réponse au mail", "rédige une réponse",
     "redige une reponse", "répondre à ce mail", "repondre a ce mail", "brouillon de réponse",
     "résume ce mail", "resume ce mail", "résume l'email", "résume mes mails",
     "briefing", "brief mes mails", "que dois-je traiter", "mails importants",
     "trie mes mails", "priorise mes mails", "fais le point sur mes mails",
     "réponse automatique", "reponse automatique", "mode autonome", "automatise mes mails",
     "traite mes mails", "réponds automatiquement", "prépare les réponses",
     "crée une tâche depuis", "transforme ce mail en tâche", "tâche depuis ce mail", "email en tâche",
     "pièce jointe", "piece jointe", "résume le pdf reçu", "résume la pièce jointe", "attachment",
     "surveille mes mails", "mails importants", "notifie", "notification", "alerte mail", "préviens-moi",
     "règle de classement", "classe mes mails", "trie automatiquement", "range mes mails", "filtre mail"):
        {"email_accounts", "email_list", "email_read", "email_search", "email_send",
         "email_draft_reply", "email_summarize", "email_digest", "email_automation_run", "email_to_task",
         "email_attachment_summary", "email_watch_check", "email_apply_rules"},

    # Calcul / maths
    ("calcul", "calculer", "calcule", "combien", "+ * -", "sqrt", "math",
     "racine", "factoriel", "puissance"):
        {"calculator"},

    # Date / heure
    ("date", "heure", "fuseau", "timezone", "tokyo", "new york", "maintenant",
     "aujourd'hui", "demain", "hier"):
        {"datetime_info"},

    # Traduction
    ("traduit", "traduis", "traduction", "translate", "anglais", "espagnol",
     "allemand", "italien", "chin…1062 tokens truncated…mps a pris",
     "chronologie de la conversation"):
        {"pc_conversation_trace"},

    # Inventaire réseau persistant (v2.139)
    ("inventaire réseau", "inventaire du réseau", "appareils du réseau", "appareils connectés",
     "quels appareils sont sur le réseau"):
        {"net_inventory_scan", "net_inventory_list", "net_inventory_annotate"},

    # Connecteurs ITSM/ticketing (v2.139)
    ("glpi", "ticket", "tickets", "ouvre un ticket", "crée un ticket", "gestion de parc",
     "itsm"):
        {"itsm_ticket_list", "itsm_ticket_create", "itsm_asset_list"},

    # Capture d'écran
    ("capture", "screenshot", "écran", "ocr"):
        {"pc_screenshot", "screen_ocr", "ocr_extract"},

    # Agent GUI local — clic/frappe dans une fenêtre (v2.149)
    ("clique sur", "clique dans", "clic sur", "coche la case", "remplis le champ",
     "tape dans le champ", "appuie sur le bouton", "clique le bouton", "clic dans la fenetre",
     "clic dans la fenêtre"):
        {"pc_gui_read", "pc_gui_click", "pc_gui_type"},

    # Réseau
    ("ping", "réseau", "wifi", "ip", "dns", "traceroute", "scan de port", "whois",
     "nmap", "scan réseau", "certificat", "tls", "ssl", "https", "sweep", "sous-réseau",
     "subnet", "adresse mac", "bannière", "port ouvert", "site web accessible", "connectivité"):
        {"net_ping", "net_port_scan", "net_dns_lookup", "net_traceroute",
         "net_whois", "net_scan_local", "ip_info", "win_network_config",
         "net_nmap_scan", "net_service_detect", "net_http_probe", "net_tls_check",
         "net_tls_check_bulk", "net_subnet_calc",
         "net_subnet_sweep", "net_route_diagnostics"},

    # SNMP + topologie réseau (v2.155)
    ("snmp", "topologie", "topologie réseau", "schéma réseau", "diagramme réseau",
     "diagramme de topologie", "interfaces du switch", "interfaces du routeur"):
        {"net_snmp_query", "net_topology_diagram"},

    # Fiches de révision / quiz (v2.155)
    ("fiche de révision", "fiches de révision", "quiz", "révise", "réviser", "flashcard",
     "flashcards", "teste-moi", "teste moi", "prépare mon examen", "prépare ma certification",
     "préparer ma certification", "réviser ma certification", "réviser pour"):
        {"quiz_generate", "quiz_next", "quiz_answer", "quiz_stats"},

    # Inventaire matériel
    ("caractéristiques matérielles", "caractéristique matérielle", "specs du pc", "specs pc",
     "spécifications matérielles", "carte mère", "quel processeur", "quelle carte graphique",
     "config du pc", "configuration matérielle", "fiche technique pc", "inventaire matériel",
     "numéro de série", "n° de série", "modèle du pc", "pilotes officiels", "drivers officiels"):
        {"pc_hardware_specs", "win_system_report"},

    # GPU / changement de carte graphique
    ("gpu", "carte graphique", "changé de carte", "changement de carte", "nouvelle carte graphique",
     "j'ai changé de gpu", "quel gpu", "vram", "directml", "carte amd", "carte nvidia",
     "génération vidéo", "video locale", "vidéo locale"):
        {"pc_gpu_status", "pc_hardware_specs"},

    # Apprentissage / introspection des compétences
    ("qu'as-tu appris", "qu'est-ce que tu as appris", "qu'as tu appris", "as-tu appris",
     "historique d'apprentissage", "journal d'apprentissage", "learning log",
     "pourquoi as-tu changé", "pourquoi as tu changé cette compétence", "comment tu t'améliores",
     "apprentissage nocturne", "consolidation nocturne", "que t'a appris cet échec"):
        {"skill_learning_log"},

    # Windows+ (raccourcis panneaux Windows)
    ("god mode", "panneau de configuration", "ouvre les paramètres", "ouvre le gestionnaire de tâches",
     "gestionnaire des tâches", "ouvre services", "services windows", "ouvre le pare-feu",
     "observateur d'événements", "planificateur de tâches", "gestion des disques",
     "gestionnaire de périphériques", "nettoyage de disque", "moniteur de ressources",
     "ouvre le dossier temp", "dossier de démarrage", "programmes et fonctionnalités",
     "connexions réseau", "propriétés système", "msconfig"):
        {"win_quick_launch", "win_quick_launch_list"},

    # SSH
    ("ssh", "serveur distant", "serveur", "ssh connect", "sftp", "transfert fichier",
     "uploader sur le serveur", "télécharger du serveur", "mes serveurs", "parc serveurs"):
        {"ssh_list", "ssh_connection_save", "ssh_exec", "ssh_exec_multi", "ssh_upload", "ssh_download",
         "ssh_list_dir", "ssh_server_info", "ssh_write_and_run"},

    # Drive / OneDrive
    ("drive", "google drive", "onedrive", "cloud"):
        {"google_drive_list", "google_drive_read", "google_drive_upload",
         "onedrive_list", "onedrive_read", "onedrive_upload"},

    # Tâches / notes / mémoire
    ("tâche", "tache", "todo", "à faire", "rappel"):
        {"task_create", "task_list", "task_update", "task_delete"},
    ("note", "noter", "rappel-toi"):
        {"note_create", "note_list", "note_update", "note_delete"},
    ("souvenir", "mémorise", "memorise", "rappelle-toi", "n'oublie pas"):
        {"memory_save", "memory_list", "memory_delete", "memory_search"},

    # Code Python
    ("code workspace", "coding mission", "mission de code", "test forge", "code forge",
     "projet de code", "workspace de code"):
        {"code_workspace_start", "code_workspace_status", "code_workspace_control",
         "ai_code_forge", "ai_test_forge"},
    ("code python", "script python", "execute python", "analyse avec python"):
        {"code_python"},

    # Couleurs
    ("couleur", "color", "hex", "rgb", "hsl"):
        {"color_tool"},

    # QR Code
    ("qr code", "qrcode", "qr"):
        {"qr_generate"},

    # Images
    ("image", "photo", "redimensionne", "resize", "rogne", "rogner", "crop", "recadre",
     "pivote l'image", "tourne l'image", "retourne l'image", "miroir", "flip",
     "compresse l'image", "compresser l'image", "réduis le poids", "allège l'image",
     "par lot", "en lot", "toutes les images", "lot d'images", "dossier d'images",
     "traite les images", "traiter les images", "batch"):
        {"image_info", "image_resize", "image_crop", "image_rotate", "image_compress",
         "image_batch", "images_to_pdf", "ocr_extract"},

    # SQLite / Git / archives
    ("sqlite", "base de données", "requête sql"):
        {"sqlite_query", "sqlite_tables"},
    ("git", "dépôt", "commit", "branche"):
        {"git_info"},
    ("zip", "archive", "extrait"):
        {"file_compress", "file_extract", "zip_list"},

    # Renommage
    ("renomme", "renommer", "renommage en masse"):
        {"file_rename", "bulk_rename"},

    # JSON / regex / texte
    ("json", "formate le json"):
        {"json_tool"},
    ("regex", "expression régulière", "regexp"):
        {"regex_tool"},
    ("markdown",):
        {"markdown_convert"},
    ("compte les mots", "statistiques texte", "longueur du texte"):
        {"text_stats", "text_extract"},

    # Vidéo / infographie
    ("infographie", "graphique"):
        {"infographic_create"},

    # v2.145 — Mini-appli web (« ChatGPT Sites »)
    ("dashboard", "mini-appli", "mini appli", "page web", "interface web",
     "appli web", "application web", "site interactif", "prototype web",
     "page de suivi", "outil interactif", "webapp"):
        {"webapp_create"},

    # Édition vidéo / GIF (v2.32)
    ("vidéo", "video", "gif", "mp4", "avi", "mkv", "mov", "webm",
     "convertis en gif", "convertir en gif", "découpe la vidéo", "decoupe la video",
     "trim", "compresse la vidéo", "compresse la video", "compresser",
     "filigrane", "watermark", "ralenti", "accéléré", "accelere",
     "extrait les images", "extraire les images", "miniature", "thumbnail",
     "enregistre l'écran", "screen record", "capture vidéo", "optimise le gif",
     "redimensionne la vidéo", "vitesse de la vidéo"):
        {"video_info", "video_to_gif", "gif_to_video", "video_trim",
         "video_compress", "video_resize", "video_extract_frames", "video_speed",
         "video_watermark", "gif_optimize", "screen_record_gif",
         "infographic_create", "system_search", "file_find"},

    # Voix
    ("transcription", "transcris", "voix", "whisper", "sous-titre"):
        {"voice_transcribe"},

    # Boîte à outils audio (ffmpeg)
    ("audio", "son", "mp3", "wav", "ogg", "flac", "aac", "m4a", "musique", "piste audio",
     "extrais l'audio", "extraire l'audio", "extrais le son", "convertis l'audio",
     "convertir en mp3", "convertir en wav", "découpe l'audio", "coupe l'audio",
     "fusionne l'audio", "monte le son", "baisse le son", "volume", "normalise l'audio",
     "infos audio", "bitrate", "débit audio"):
        {"audio_info", "audio_extract", "audio_convert", "audio_trim",
         "audio_merge", "audio_volume", "voice_transcribe", "text_to_speech"},

    # Auto-diagnostic
    ("auto-diagnostic", "autodiagnostic", "self test", "self-test", "teste tes outils",
     "vérifie tes outils", "verifie tes outils", "est-ce que tout fonctionne",
     "tout fonctionne", "santé des outils", "diagnostic des outils", "tes fonctions marchent"):
        {"system_self_test"},

    # Devis / Facturation IT (commercial)
    ("devis", "facture", "facturation", "facturer", "proposition commerciale", "client it",
     "tarif", "tarifs", "prix de vente", "marge", "catalogue", "prestation", "prestations",
     "comparer les prix", "comparer les offres", "prix du marché", "prix marché",
     "combien facturer", "combien vendre", "encaissement", "impayé", "impayés",
     "chiffre d'affaires", "mrr", "arr", "tco", "rentabilité", "rentable"):
        {"billing_market_research", "billing_price_recommendation", "billing_generate_proposal",
         "billing_tco_analysis", "billing_invoice_create", "billing_invoice_list",
         "billing_invoice_mark_paid", "billing_revenue_dashboard", "billing_catalog_enrich",
         "billing_analyze_need", "billing_quote_create", "billing_quote_list",
         "billing_client_list", "billing_catalog_list", "billing_tier_breakdown",
         "billing_product_reviews", "billing_seed_trade", "web_search"},

    # Documentation technique IT
    ("documentation", "rapport d'intervention", "rapport intervention", "procédure",
     "runbook", "post-mortem", "postmortem", "cause racine", "rca", "demande de changement",
     "change request", "plan de reprise", "pra", "pca", "fiche client", "schéma réseau",
     "documenter", "compte rendu", "onboarding", "offboarding", "arrivée collaborateur",
     "départ collaborateur", "fiche d'intervention", "maintenance préventive"):
        {"doc_generate_report", "doc_generate_procedure", "doc_generate_runbook",
         "doc_generate_postmortem", "doc_generate_change", "doc_generate_onboarding",
         "doc_generate_recovery_plan", "doc_generate_maintenance", "doc_generate_client_sheet",
         "doc_generate_schema", "doc_analyze_input", "doc_intervention_create",
         "doc_intervention_list", "doc_knowledge_search"},

    # Métier / catalogue par métier (devis utilisable hors IT)
    ("métier", "metier", "plomberie", "plombier", "électricité", "electricien", "électricien",
     "peinture", "peintre", "menuiserie", "menuisier", "jardinage", "paysagiste", "ménage",
     "menage", "coiffure", "esthétique", "photographe", "comptable", "comptabilité",
     "artisan", "btp", "bâtiment", "prestations types", "catalogue métier"):
        {"billing_seed_trade", "billing_catalog_list", "billing_analyze_need",
         "billing_quote_create", "billing_client_create"},

    # Prix d'un produit / achat / budget (le plus important : ne jamais refuser)
    ("prix", "prix de", "les prix", "combien coûte", "combien coute", "ça coûte",
     "ca coute", "coûte combien", "coute combien", "coût de", "cout de", "coût d'",
     "tarif de", "acheter", "achat", "à vendre", "prix moyen", "entrée de gamme",
     "entré de gamme", "milieu de gamme", "haut de gamme", "moins de", "pas cher",
     "le moins cher", "budget", "à partir de", "fourchette de prix", "ça vaut",
     "ca vaut", "ça coûte combien", "pc", "ordinateur", "portable", "laptop",
     "macbook", "serveur", "écran", "imprimante", "disque dur", "ssd", "barrette",
     "carte graphique", "processeur", "switch", "routeur", "nas"):
        {"billing_market_research", "billing_find_products", "billing_product_reviews",
         "billing_price_recommendation", "it_kb_recommend", "web_search"},

    # Avis produits / comparatif
    ("avis", "avis client", "note", "notes", "étoiles", "review", "reviews", "fiable",
     "fiabilité", "réputation", "le meilleur", "lequel choisir", "comparatif", "vaut-il"):
        {"billing_product_reviews", "billing_market_research", "billing_find_products",
         "it_kb_recommend", "web_search"},

    # Base de connaissances IT : recommandation d'outils/logiciels
    ("quel outil", "quel logiciel", "recommande", "recommandation", "conseille", "conseil",
     "antivirus", "sauvegarde", "backup", "supervision", "monitoring", "pare-feu", "firewall",
     "virtualisation", "hyperviseur", "accès distant", "prise en main", "rmm", "edr",
     "gestionnaire de mot de passe", "outil pour", "logiciel pour", "solution pour",
     "diagnostic", "clonage", "imagerie", "scanner réseau", "vpn"):
        {"it_kb_recommend", "it_kb_search", "it_kb_list", "it_kb_add",
         "billing_product_reviews", "web_search"},
}


_strip_accents = _cr.strip_accents


# Index précalculé (normalisé UNE fois au chargement, pas à chaque message) : évite de
# refaire le NFKD sur ~400 mots-clés à chaque tour de chat.
_KEYWORD_TOOLS_NORM = [
    (tuple(_strip_accents(k) for k in keywords), tools)
    for keywords, tools in _KEYWORD_TOOLS.items()
]
_CAPABILITY_CATALOG = build_catalog(TOOLS_SPEC)


async def filter_relevant_tools(messages: list[dict], profile_name: str) -> list:
    """
    Réduit l'ensemble des outils envoyés au LLM en fonction du message utilisateur.
    → Contexte système plus court → réponse beaucoup plus rapide.

    Stratégie :
    - Toujours inclure les outils universels (mémoire, paths, datetime)
    - Inclure les outils correspondant aux mots-clés du dernier message
    - Si aucun mot-clé match → fallback sur le top 20 (les plus utilisés)
    """
    # Extraire le texte du dernier message utilisateur
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if not last_user:
        return TOOLS_SPEC  # Pas de message → tout envoyer par sécurité

    content = last_user.get("content", "")
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    text_raw = (content or "")
    text = text_raw.lower()
    text_norm = _strip_accents(text)   # « caracteristiques » doit matcher « caractéristiques »

    # 1) Mots-clés (rapide, fiable pour les formulations connues) — insensible aux accents.
    relevant = set(_ALWAYS_INCLUDE)
    keyword_hits = set()
    for keywords, tools in _KEYWORD_TOOLS_NORM:
        if any(k in text_norm for k in keywords):
            keyword_hits.update(tools)
    relevant |= keyword_hits

    # 2) Contrats lexicaux : signal portable dérivé des noms, descriptions et paramètres
    #    des 344 outils. Il couvre les paraphrases même sans Ollama/Qdrant.
    lexical_ranked = rank_capabilities(text_raw, _CAPABILITY_CATALOG)
    lexical = {name for name, _score in lexical_ranked}
    relevant |= lexical

    # 3) Sémantique + appris (comprend les paraphrases, s'améliore avec l'usage).
    #    Best-effort : si l'embedding/Qdrant échoue, on garde juste les mots-clés.
    semantic = set()
    try:
        import tool_router
        routed = await tool_router.route_tools(text_raw)
        semantic = (routed.get("semantic", set()) | routed.get("learned", set()))
    except Exception:
        pass
    relevant |= semantic

    # 4) Toujours rien de spécifique → repli BORNÉ sur un petit jeu polyvalent.
    #    ⚠️ NE JAMAIS renvoyer les ~245 specs (prompt énorme → réponse très lente).
    if len(relevant) <= len(_ALWAYS_INCLUDE):
        relevant |= _COMMON_TOOLS

    # N'envoyer que des outils RÉELLEMENT existants
    names = {s.get("function", {}).get("name") for s in TOOLS_SPEC}
    relevant &= names

    # 5) Plafond selon le MODE de performance (max_tools) : sur petite machine on envoie peu
    #    d'outils (rapide) ; sur machine puissante, beaucoup (meilleure sélection). On garde
    #    PRIORITAIREMENT l'essentiel + les correspondances mots-clés, puis on complète.
    # v2.107 — le profil analysis envoyait TOUS les outils (~294) sans filtrage : sur un
    # catalogue aussi large, le LLM peut halluciner un nom d'outil plausible mais inexistant
    # au lieu d'utiliser le bon (constaté : "HWMonitor" inventé au lieu de pc_hardware_specs).
    # On applique désormais le même filtrage mots-clés+sémantique que chat/agent, mais avec
    # un plafond bien plus large (le profil analysis pairé à un modèle puissant peut gérer
    # plus de contexte) — garde la qualité/couverture tout en réduisant le bruit du catalogue.
    try:
        max_tools = int(db.get_setting("max_tools") or 28)
    except Exception:
        max_tools = 28
    if profile_name == "analysis":
        max_tools = max(max_tools, 90)
    if len(relevant) > max_tools:
        ordered: list[str] = []
        for group in (
            set(_ALWAYS_INCLUDE) & names,
            keyword_hits & names,
            lexical & names,
            semantic & names,
            relevant,
        ):
            # Les ensembles Python dépendent du hash seed du processus. Le tri garantit
            # qu'un redémarrage ne change pas silencieusement les outils retenus au plafond.
            for t in sorted(group):
                if t in relevant and t not in ordered:
                    ordered.append(t)
        relevant = set(ordered[:max_tools])

    return [s for s in TOOLS_SPEC if s.get("function", {}).get("name") in relevant]
