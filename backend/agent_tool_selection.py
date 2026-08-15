"""Selection bornee et explicable des outils exposes au LLM."""
from __future__ import annotations

import re
from functools import lru_cache

import cloud_routing as _cr
import database as db
import tool_availability
from tools import TOOLS_SPEC
from tool_capability_ranking import build_catalog, rank_capabilities

_TOOL_FOLLOWUP_RE = re.compile(
    r"^\s*(?:oui|non|vas[- ]?y|fais[- ]?le|continue|reprends|réessaie|reessaie|"
    r"tu\s+as\s+les?\s+outils?|utilise\s+(?:donc\s+)?les?\s+outils?|"
    r"pourtant|ça\s+ne\s+marche\s+pas|ca\s+ne\s+marche\s+pas)\b",
    re.IGNORECASE,
)
_EXPLICIT_PPTX_CREATE_RE = re.compile(
    r"\b(?:cr[ée]e|cr[ée]er|fais|faire|g[ée]n[èe]re|g[ée]n[ée]rer|veux|souhaite)\w*\b"
    r".{0,100}\b(?:powerpoint|pptx|fichier\s+\.pptx)\b|"
    r"\b(?:powerpoint|pptx|fichier\s+\.pptx)\b.{0,100}"
    r"\b(?:cr[ée]e|fais|g[ée]n[èe]re|veux|souhaite)\w*\b",
    re.IGNORECASE,
)
_NO_PPTX_CREATION_RE = re.compile(
    r"\b(?:sans\s+(?:cr[ée]er|g[ée]n[ée]rer)|ne\s+cr[ée]e\s+pas|"
    r"n['’]\s*enregistre\s+pas)\b",
    re.IGNORECASE,
)
_PPTX_REDESIGN_RE = re.compile(
    r"\b(?:refais|refaire|am[ée]liore|embellis|redesign|design|plus\s+(?:joli|beau))\w*\b"
    r".{0,140}\b(?:pr[ée]sentation|powerpoint|pptx|diaporama|cela|ça|ca)\b|"
    r"\b(?:pr[ée]sentation|powerpoint|pptx|diaporama)\b.{0,140}"
    r"\b(?:refais|am[ée]liore|embellis|design|joli|beau)\w*\b",
    re.IGNORECASE,
)

_ALWAYS_INCLUDE = {
    "pc_get_real_paths",
    "memory_save", "memory_list",
    "datetime_info",
    "tool_search",
}

# Repli BORNÉ quand aucun mot-clé métier ne matche : un petit jeu d'outils
# polyvalents, AU LIEU des ~245 specs (qui font un prompt énorme → réponse de
# plusieurs minutes, surtout sur petit GPU). Les noms inexistants sont ignorés.
_COMMON_TOOLS = {
    "web_search", "web_browse", "web_site_crawl", "datetime_info", "weather",
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
    # Organisation native de la barre latérale Marvin. Le mot « dossier » seul reste
    # volontairement géré par les outils fichiers ; « projet » ou « conversation »
    # apporte le signal métier qui distingue l'espace logique d'un dossier Windows.
    ("barre laterale", "barre latérale", "projet marvin", "nouveau projet",
     "cree un projet", "crée un projet", "renomme le projet", "instructions du projet",
     "deplace cette discussion", "déplace cette discussion", "deplace la conversation",
     "déplace la conversation", "range cette discussion", "classe cette conversation",
     "conversation sans projet", "discussions sans projet", "archive cette conversation",
     "epingle cette conversation", "épingle cette conversation"):
        {"project_list", "project_create", "project_update", "project_delete",
         "conversation_list", "conversation_search", "conversation_move",
         "conversation_move_many", "conversation_update"},

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
        {"web_search", "web_browse", "web_site_crawl", "web_research"},

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
        {"web_browse", "web_site_crawl", "url_analyze", "web_browser_open", "web_research",
         "computer_control"},

    # Contrôle interactif du poste : le runtime unifié observe et vérifie chaque effet.
    ("clique", "clic", "souris", "clavier", "remplis le formulaire", "utilise l'application",
     "pilote le pc", "contrôle le pc", "controle le pc", "navigue dans le navigateur",
     "interagis avec", "fenêtre windows", "fenetre windows"):
        {"computer_control", "pc_window_list", "pc_gui_read", "pc_screenshot"},

    # Opérations Windows typées : l'opérateur compile vers les exécuteurs connus et
    # vérifie l'effet. computer_control reste réservé aux gestes visuels ci-dessus.
    ("processus actifs", "liste les processus", "arrête le processus", "arrete le processus",
     "ferme l'application", "ferme le logiciel", "lance l'application", "ouvre l'application",
     "lance le programme", "ouvre le logiciel", "démarre l'application", "demarre l'application",
     "démarre le programme", "demarre le programme", "démarre l'outil", "demarre l'outil",
     "exécute le binaire", "execute le binaire", "lance l'exécutable", "lance l'executable",
     "active l'application", "lance le bloc-notes", "ouvre le bloc-notes",
     "services windows", "liste les services",
     "configuration réseau", "configuration reseau", "état du pare-feu", "etat du pare-feu",
     "logiciels installés", "logiciels installes", "crée le dossier", "cree le dossier",
     "renomme le fichier", "copie le fichier"):
        {"windows_task"},

    # Fichiers
    ("fichier", "dossier", "bureau", "documents", "downloads", "téléchargement",
     "fichiers", "dossiers"):
        {"system_search", "file_find", "file_list", "file_info", "file_read",
         "file_write", "file_delete", "file_rename", "file_move", "file_copy",
         "file_create_folder", "file_search_text", "pc_get_real_paths", "windows_task"},

    # Inventaire non mutant des fichiers et sous-dossiers volumineux. Une demande mixte
    # conserve les outils d'exploration généraux mais ne dépend pas d'un détour par
    # tool_search pour obtenir le classement des tailles cumulées.
    ("plus gros fichier", "plus gros fichiers", "fichier le plus gros",
     "fichiers les plus gros", "fichier volumineux", "fichiers volumineux",
     "fichier ou dossier les plus gros", "fichiers ou dossiers les plus gros",
     "dossier ou fichier les plus gros", "dossiers ou fichiers les plus gros",
     "fichiers qui prennent le plus de place", "fichiers qui occupent le plus"):
        {"file_large_finder"},

    # Recherche dans fichiers
    ("trouve", "cherche", "où est", "ou est", "ou se trouve", "trouver", "*.pdf",
     "*.docx", "*.xlsx"):
        {"system_search", "system_search_content", "file_find", "file_search_text"},

    # Logiciels installés / inventaire logiciel
    ("logiciel installé", "logiciels installés", "logiciels installer", "inventaire logiciel",
     "liste des programmes", "programmes installés", "quels logiciels", "applications installées",
     "est installé", "est installe", "sont installés", "sont installes",
     "programmes présents", "programmes presents", "liste logiciels", "logiciels sur ce pc",
     "logiciels du pc"):
        {"pc_installed_software", "winget_list_installed", "win_system_report",
         "pc_system_info", "windows_task"},

    # État des mises à jour : lecture Winget dédiée, sans lancer d'installation.
    ("mise à jour disponible", "mise a jour disponible", "mises à jour disponibles",
     "mises a jour disponibles", "état des mises à jour", "etat des mises a jour",
     "liste les mises à jour", "liste les mises a jour", "dernière version installée",
     "derniere version installee"):
        {"winget_list_upgrades", "winget_list_installed"},

    # Les actions Winget mutuellement exclusives sont composées après l'union K+L+S par
    # ``_software_intent_boundary``. Ne jamais réintroduire ici une règle par famille :
    # elle exposerait notamment la désinstallation sur une demande d'installation.

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
    ("extraire les images", "extrait les images", "images du site", "photos du site",
     "télécharge les images", "telecharge les images", "récupère les images",
     "recupere les images", "médias du site", "medias du site"):
        {"web_media_extract"},
    ("inspiré de leur design", "inspire de leur design", "identité graphique du site",
     "identite graphique du site", "charte graphique du site", "design graphique du site"):
        {"web_media_extract", "pptx_create"},
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
    ("email", "emails", "mail", "courriel", "gmail", "outlook", "boîte de réception", "envoie un mail",
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
     "ca vaut", "ça coûte combien", "ordinateur", "portable", "laptop",
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
_VISUAL_CONTROL_TERMS_NORM = tuple(
    _strip_accents(term)
    for term in (
        "clique", "clic", "souris", "clavier", "remplis le formulaire",
        "pilote le pc", "contrôle le pc", "controle le pc", "interagis avec",
        "fenêtre windows", "fenetre windows", "capture d'écran", "screenshot",
        "navigue dans le navigateur", "ouvre chrome", "ouvre edge", "ouvre firefox",
        "ouvre le navigateur", "ouvre le site", "page web", "va sur le site",
        "bouton", "réservation", "reservation",
    )
)
_CAPABILITY_CATALOG = build_catalog(TOOLS_SPEC)

_SOFTWARE_ACTION_TOOLS = {
    "winget_search",
    "winget_install",
    "winget_upgrade",
    "winget_uninstall",
    "winget_list_upgrades",
    "winget_list_installed",
    "pc_installed_software",
    "win_quick_launch",
    "win_quick_launch_list",
}
_SOFTWARE_INTENT_ALLOWED = {
    "software.search": {"winget_search"},
    "software.install": {"winget_install"},
    "software.inventory": {"winget_list_installed", "pc_installed_software"},
    "software.updates_check": {"winget_list_upgrades"},
    "software.upgrade": {"winget_upgrade"},
    "software.uninstall": {"winget_uninstall"},
    "software.manual_panel": {"win_quick_launch", "win_quick_launch_list"},
    "software.ambiguous": {
        "winget_search", "winget_list_installed", "winget_list_upgrades",
        "pc_installed_software",
    },
}
_SOFTWARE_DEVELOPMENT_CONTEXT = (
    "pip ", "pip3 ", "npm ", "pnpm ", "yarn ", "cargo ", "poetry ",
    "dependance python", "dependances python", "package python", "paquet python",
    "dependance node", "dependances node", "node_modules",
)
_FILESYSTEM_MUTATION_TOOLS = {
    "file_write", "file_delete", "file_rename", "file_move", "file_copy",
    "file_create_folder", "windows_task",
}
_FILESYSTEM_MUTATION_TERMS_NORM = tuple(
    _strip_accents(term)
    for term in (
        "supprime", "efface", "nettoie", "déplace", "deplace", "renomme",
        "copie", "crée", "cree", "écris", "ecris", "modifie",
    )
)


@lru_cache(maxsize=4096)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Compile une seule fois chaque motif interne de frontière de mot."""

    escaped = re.escape(keyword).replace(r"\ ", r"\s+")
    left = r"(?<![a-z0-9])" if keyword[0].isalnum() else ""
    right = r"(?![a-z0-9])" if keyword[-1].isalnum() else ""
    return re.compile(left + escaped + right)


def _within_one_edit(left: str, right: str) -> bool:
    """Distance d'édition <= 1, sans matrice ni tolérance non bornée."""

    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_index = long_index = differences = 0
    while short_index < len(shorter) and long_index < len(longer):
        if shorter[short_index] == longer[long_index]:
            short_index += 1
            long_index += 1
            continue
        differences += 1
        if differences > 1:
            return False
        long_index += 1
    return True


def _prefix_keyword_present(prefix: str, text: str) -> bool:
    """Préfixe explicite, avec une seule faute tolérée sur un radical long."""

    if len(prefix) < 7 or not prefix.isalnum():
        return False
    for token in re.findall(r"[a-z0-9]+", text):
        # Formes adjectivales non ambiguës de « installé » : elles décrivent
        # l'inventaire existant et ne doivent jamais déclencher une mutation.
        if prefix == "install" and token in {"installes", "installee", "installees"}:
            continue
        if token.startswith(prefix):
            return True
        if len(token) >= len(prefix) - 1:
            candidate = token[: len(prefix)]
            if _within_one_edit(prefix, candidate):
                return True
    return False


def _keyword_present(keyword: str, text: str) -> bool:
    """Matche un terme metier complet, jamais une sous-chaine accidentelle.

    Les anciens ``keyword in text`` faisaient par exemple correspondre ``ip`` dans
    ``multiplie`` et exposaient toute la suite reseau pour un calcul. Les bornes ne
    sont ajoutees qu'aux extremites alphanumeriques afin de conserver les marqueurs
    ponctues historiques tels que ``+ * -``.
    """

    normalized = str(keyword or "").strip()
    if not normalized:
        return False
    if normalized.endswith("*"):
        return _prefix_keyword_present(normalized[:-1], text)
    return _keyword_pattern(normalized).search(text) is not None


def _software_intent_boundary(text: str) -> str | None:
    """Classifie une action logicielle explicite sans examiner les candidats obtenus.

    La classification est indépendante de K/L/S. Une intention reconnue ferme ensuite la
    famille Winget sur le contrat terminal correspondant. Une demande ambiguë ne conserve
    que des outils de lecture; les confirmations restent une barrière supplémentaire, jamais
    une justification pour présenter une mutation contradictoire.
    """

    normalized = str(text or "").strip()
    if not normalized:
        return None
    if any(marker in normalized for marker in _SOFTWARE_DEVELOPMENT_CONTEXT):
        return None
    if any(
        _keyword_present(marker, normalized)
        for marker in (
            "document", "fichier", "dossier", "projet", "code source",
            "tableur", "presentation", "base de donnees",
        )
    ) and any(
        _keyword_present(marker, normalized)
        for marker in ("mets a jour", "met a jour", "mettre a jour")
    ):
        return None

    manual_panel = (
        "programmes et fonctionnalites", "panneau de desinstallation",
        "applications et fonctionnalites", "ouvrir appwiz", "ouvre appwiz",
    )
    if any(_keyword_present(marker, normalized) for marker in manual_panel):
        return "software.manual_panel"

    if _prefix_keyword_present("desinstall", normalized) or any(
        _keyword_present(marker, normalized)
        for marker in (
            "retire le logiciel", "retire l'application", "retire le programme",
            "supprime le logiciel", "uninstall",
        )
    ) or re.search(r"\bretire\s+.+\s+de\s+ce\s+pc\b", normalized):
        return "software.uninstall"

    update_subject = any(
        _keyword_present(marker, normalized)
        for marker in (
            "mise a jour", "mises a jour", "version obsolete", "versions obsoletes",
            "logiciel obsolete", "logiciels obsoletes", "upgrade",
        )
    ) or bool(re.search(r"\blogiciels?\b.{0,32}\bobsoletes?\b", normalized))
    read_signal = any(
        _keyword_present(marker, normalized)
        for marker in ("liste", "affiche", "verifie", "quelles", "quels", "disponible", "disponibles")
    )
    if update_subject and read_signal:
        return "software.updates_check"
    if any(
        _keyword_present(marker, normalized)
        for marker in (
            "mets a jour", "met a jour", "mais a jour", "mettre a jour",
            "applique les mises a jour", "actualise le logiciel",
        )
    ) or re.search(r"\b(?:mets?|mais)\b.{0,64}\ba\s+jour\b", normalized):
        return "software.upgrade"

    inventory = (
        "logiciel installe", "logiciels installes", "programmes installes",
        "applications installees", "inventaire logiciel", "liste des programmes",
        "est deja installe", "est installe", "logiciels sur ce pc",
    )
    if any(_keyword_present(marker, normalized) for marker in inventory):
        return "software.inventory"

    search_action = any(
        _keyword_present(marker, normalized)
        for marker in ("cherche", "recherche", "trouve", "quel paquet")
    )
    software_subject = any(
        _keyword_present(marker, normalized)
        for marker in ("winget", "catalogue", "logiciel", "application", "programme", "paquet")
    )
    if search_action and software_subject:
        return "software.search"

    if _prefix_keyword_present("install", normalized) or any(
        _keyword_present(marker, normalized)
        for marker in ("telecharge et installe", "ajoute le logiciel", "ajoute l'application")
    ):
        return "software.install"

    if _keyword_present("winget", normalized) or any(
        _keyword_present(marker, normalized)
        for marker in ("gerer mes logiciels", "gere mes logiciels", "gestion des logiciels")
    ):
        return "software.ambiguous"
    return None


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
    if _TOOL_FOLLOWUP_RE.search(text_raw):
        previous_user = next(
            (
                item
                for item in reversed(messages[:-1])
                if item.get("role") == "user" and item.get("content")
            ),
            None,
        )
        if previous_user:
            previous_content = previous_user.get("content", "")
            if isinstance(previous_content, list):
                previous_content = " ".join(
                    part.get("text", "")
                    for part in previous_content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            text_raw = f"{previous_content}\nSuivi utilisateur : {text_raw}"
    text = text_raw.lower()
    text_norm = _strip_accents(text)   # « caracteristiques » doit matcher « caractéristiques »

    # 1) Mots-clés (rapide, fiable pour les formulations connues) — insensible aux accents.
    relevant = set(_ALWAYS_INCLUDE)
    keyword_hits = set()
    for keywords, tools in _KEYWORD_TOOLS_NORM:
        if any(_keyword_present(k, text_norm) for k in keywords):
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

    # Frontière d'action après l'union K+L+S : une couche de rappel peut proposer un outil
    # voisin, mais ne peut pas remettre une mutation contradictoire dans le sous-ensemble.
    software_intent_priority: set[str] = set()
    software_intent = _software_intent_boundary(text_norm)
    if software_intent:
        allowed_software = _SOFTWARE_INTENT_ALLOWED[software_intent]
        software_intent_priority = set(allowed_software)
        relevant.difference_update(_SOFTWARE_ACTION_TOOLS)
        relevant.update(allowed_software)
        keyword_hits.difference_update(_SOFTWARE_ACTION_TOOLS)
        keyword_hits.update(allowed_software)

    # Une demande d'inventaire des fichiers volumineux est en lecture seule. Les mots
    # génériques « fichier/dossier » ne doivent pas laisser des mutations voisines prendre
    # un slot, sauf si l'utilisateur exprime aussi explicitement une action mutante.
    if (
        "file_large_finder" in keyword_hits
        and not any(_keyword_present(term, text_norm) for term in _FILESYSTEM_MUTATION_TERMS_NORM)
    ):
        relevant.difference_update(_FILESYSTEM_MUTATION_TOOLS)
        keyword_hits.difference_update(_FILESYSTEM_MUTATION_TOOLS)

    # Un outil visuel de 24 paramètres ne concurrence pas l'opérateur système typé
    # lorsque la demande ne contient aucun geste visuel. Il reste découvrable par
    # tool_search et réapparaît dès qu'un signal UI explicite est présent.
    visual_control_requested = any(
        _keyword_present(term, text_norm) for term in _VISUAL_CONTROL_TERMS_NORM
    )
    if not visual_control_requested and "windows_task" in relevant:
        relevant.discard("computer_control")

    # Un livrable Office explicite doit passer par son outil documentaire dédié.
    # Test Forge vérifie du code mais n'est pas un moteur de documents.
    if (
        (_EXPLICIT_PPTX_CREATE_RE.search(text_raw) or _PPTX_REDESIGN_RE.search(text_raw))
        and not _NO_PPTX_CREATION_RE.search(text_raw)
    ):
        relevant.add("pptx_create")
        relevant.difference_update({
            "ai_test_forge",
            "ai_code_forge",
            "code_python",
            "code_workspace_start",
        })
    elif _NO_PPTX_CREATION_RE.search(text_raw):
        relevant.discard("pptx_create")

    # 4) Toujours rien de spécifique → repli BORNÉ sur un petit jeu polyvalent.
    #    ⚠️ NE JAMAIS renvoyer les ~245 specs (prompt énorme → réponse très lente).
    if len(relevant) <= len(_ALWAYS_INCLUDE):
        relevant |= _COMMON_TOOLS

    # N'envoyer que des outils RÉELLEMENT existants
    names = {s.get("function", {}).get("name") for s in TOOLS_SPEC}
    relevant &= names

    # Un outil indisponible reste connu via ``tool_search`` mais ne consomme pas
    # un slot de classement. Une demande métier explicite conserve toutefois
    # l'outil afin qu'il retourne son diagnostic réel plutôt qu'une incapacité
    # inventée par le modèle.
    try:
        snapshot = await tool_availability.get_snapshot()
        availability = tool_availability.availability_map(names, snapshot)
        unavailable = {
            name for name, state in availability.items()
            if not state.get("rankable", True)
        }
    except tool_availability.ToolDependencyInventoryError:
        # The versioned gate prevents this in a valid installation. If an AV or
        # damaged deployment removes the manifest at runtime, retain Marvin's
        # previous functional selection instead of breaking every conversation.
        unavailable = set()
    explicit_names = {
        name for name in names
        if name and (
            _keyword_present(name, text_norm)
            or _keyword_present(name.replace("_", " "), text_norm)
        )
    }
    explicitly_required = (keyword_hits | explicit_names) & unavailable
    relevant = (relevant - unavailable) | explicitly_required
    if unavailable:
        relevant.add("tool_search")

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
            software_intent_priority & names,
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
