export const SYSTEM_CATEGORIES = [
  {
    id: 'fichiers', label: 'Fichiers', icon: '📁', color: '#22c55e',
    description: 'Explorateur complet + listez, lisez, écrivez, copiez, déplacez et cherchez des fichiers.',
    tools: [
      {
        id: 'file_manager', custom: 'fileManager', icon: '🗂️', name: 'Explorateur de fichiers',
        description: 'Naviguez dans toute l\'arborescence Windows et agissez directement : ouvrir, renommer, couper/copier/coller, supprimer, propriétés, nouveau dossier.',
        params: [],
      },
      {
        id: 'file_list', icon: '📁', name: 'Lister un dossier',
        description: 'Affiche le contenu d\'un répertoire avec taille, type et date de chaque fichier.',
        params: [
          { name: 'path',        label: 'Chemin du dossier',        type: 'path',    required: true, placeholder: 'Bureau' },
          { name: 'show_hidden', label: 'Afficher les fichiers cachés', type: 'checkbox', defaultValue: false },
        ],
      },
      {
        id: 'file_info', icon: 'ℹ️', name: 'Informations fichier',
        description: 'Métadonnées détaillées d\'un fichier ou dossier : taille, dates, hash MD5 optionnel.',
        tips: ['Retourne taille, date de création, modification, accès', 'L\'option MD5 peut être lente sur les gros fichiers'],
        params: [
          { name: 'path', label: 'Chemin du fichier ou dossier', type: 'path', required: true },
          { name: 'hash', label: 'Calculer le MD5', type: 'checkbox', defaultValue: false },
        ],
      },
      {
        id: 'file_read', icon: '👁️', name: 'Lire un fichier',
        description: 'Lit le contenu d\'un fichier texte, PDF, Word, Excel ou CSV.',
        tips: ['Supporte .txt, .md, .pdf, .docx, .xlsx, .csv, .json, .py, .js...'],
        params: [
          { name: 'path', label: 'Chemin du fichier', type: 'path', required: true, placeholder: 'Bureau\\fichier.txt' },
        ],
      },
      {
        id: 'file_write', icon: '✏️', name: 'Écrire dans un fichier',
        description: 'Crée ou écrase / ajoute du texte dans un fichier.',
        params: [
          { name: 'path',    label: 'Chemin du fichier', type: 'path',     required: true },
          { name: 'content', label: 'Contenu',           type: 'textarea', required: true },
          { name: 'mode',    label: 'Mode',              type: 'select',   options: [
            { value: 'overwrite', label: '♻️ Écraser' },
            { value: 'append',    label: '➕ Ajouter à la fin' },
          ]},
        ],
      },
      {
        id: 'file_search_text', icon: '🔍', name: 'Rechercher dans les fichiers',
        description: 'Cherche une chaîne de texte dans un dossier entier (récursif optionnel).',
        tips: ['Supporte les expressions régulières', 'Retourne le fichier, la ligne et le contexte'],
        params: [
          { name: 'path',      label: 'Dossier de recherche', type: 'path', required: true, placeholder: 'Documents' },
          { name: 'query',     label: 'Texte à chercher',     type: 'text', required: true },
          { name: 'recursive', label: 'Sous-dossiers inclus', type: 'checkbox', defaultValue: true },
        ],
      },
      {
        id: 'system_search', icon: '🚀', name: 'Recherche système (rapide)',
        description: 'Recherche INSTANTANÉE sur tout le PC via l\'index Windows Search (~50ms). Trouve fichiers et dossiers indexés.',
        tips: [
          'Tape juste le mot — pas besoin de wildcards',
          'Filtrez par type : folder, pdf, docx, xlsx, image',
          'Seuls les dossiers indexés sont trouvés (Bureau, Documents, Téléchargements…)',
        ],
        params: [
          { name: 'query',     label: 'Recherche', type: 'text', required: true, placeholder: 'abdou, rapport 2024, photo…' },
          { name: 'file_type', label: 'Type', type: 'select', options: [
            { value: 'all',    label: '🔍 Tout' },
            { value: 'folder', label: '📁 Dossiers seulement' },
            { value: 'file',   label: '📄 Fichiers seulement' },
            { value: 'pdf',    label: '📕 PDF' },
            { value: 'docx',   label: '📝 Word' },
            { value: 'xlsx',   label: '📗 Excel/CSV' },
            { value: 'image',  label: '🖼️ Images' },
          ]},
          { name: 'max_results', label: 'Max résultats', type: 'number', defaultValue: 30 },
        ],
      },
      {
        id: 'file_find', icon: '🔭', name: 'Trouver des fichiers (avancé)',
        description: 'Trouve des fichiers par nom ou motif glob (*.pdf, rapport*, *.log). Plus lent que system_search mais fonctionne hors index.',
        tips: ['Pour une recherche RAPIDE sur tout le PC, préférez system_search', '*.pdf = tous les PDFs', 'path="all" = recherche partout via l\'index'],
        params: [
          { name: 'pattern',     label: 'Motif (glob)',       type: 'text',   required: true, placeholder: '*.pdf  ou  rapport*  ou  *abdou*' },
          { name: 'path',        label: 'Dossier de départ',  type: 'path',   required: false, placeholder: 'vide ou "all" = tout le PC (index Windows)' },
          { name: 'max_results', label: 'Max résultats',      type: 'number', defaultValue: 100 },
          { name: 'include_dirs', label: 'Inclure les dossiers', type: 'checkbox', defaultValue: false },
          { name: 'use_index',   label: 'Utiliser l\'index Windows (rapide)', type: 'checkbox', defaultValue: true },
        ],
      },
      {
        id: 'file_copy', icon: '📋', name: 'Copier',
        description: 'Copie un fichier ou dossier vers un nouvel emplacement.',
        params: [
          { name: 'source',      label: 'Source',      type: 'path', required: true },
          { name: 'destination', label: 'Destination', type: 'path', required: true },
        ],
      },
      {
        id: 'file_move', icon: '📦', name: 'Déplacer',
        description: 'Déplace un fichier ou dossier (coupe-colle).',
        params: [
          { name: 'source',      label: 'Source',      type: 'path', required: true },
          { name: 'destination', label: 'Destination', type: 'path', required: true },
        ],
      },
      {
        id: 'file_rename', icon: '🏷️', name: 'Renommer',
        description: 'Renomme un fichier ou dossier.',
        params: [
          { name: 'source',   label: 'Chemin actuel', type: 'path', required: true },
          { name: 'new_name', label: 'Nouveau nom',   type: 'text', required: true, placeholder: 'nouveau_nom.docx' },
        ],
      },
      {
        id: 'file_create_folder', icon: '📂', name: 'Créer un dossier',
        description: 'Crée un dossier (et tous les parents si nécessaire).',
        params: [
          { name: 'path', label: 'Chemin du dossier', type: 'path', required: true, placeholder: 'Bureau\\MonDossier' },
        ],
      },
      {
        id: 'file_delete', icon: '🗑️', name: 'Supprimer un fichier / dossier',
        description: 'Supprime définitivement un fichier ou un dossier. Demande une confirmation avant d\'agir.',
        tips: ['⚠️ Action irréversible', 'Les dossiers sont supprimés avec tout leur contenu', 'Une confirmation sera demandée'],
        params: [
          { name: 'path', label: 'Chemin à supprimer', type: 'path', required: true },
        ],
      },
    ],
  },
  {
    id: 'pc', label: 'PC & Système', icon: '🖥️', color: '#8b5cf6',
    description: 'Contrôlez votre Windows : processus, commandes, captures, presse-papiers.',
    tools: [
      {
        id: 'pc_get_real_paths', icon: '🗺️', name: 'Arborescence du PC',
        description: 'Découvre tous les vrais chemins Windows (Bureau, Documents, AppData…) et liste leur contenu.',
        tips: ['Appelé automatiquement au 1er message de chaque conversation', 'Utile pour diagnostiquer des problèmes de chemin'],
        params: [],
      },
      {
        id: 'pc_system_info', icon: '💻', name: 'Informations système',
        description: 'CPU, RAM, disque, OS, réseau et uptime en un coup d\'œil.',
        params: [],
      },
      {
        id: 'system_cleanup', icon: '🧹', name: 'Nettoyer le disque',
        description: 'Analyse les fichiers temporaires et l\'espace récupérable. Sans suppression par défaut. Version rapide — pour un nettoyage détaillé par catégorie (cache navigateurs, vignettes, corbeille…), voir PC & Système → onglet Nettoyage.',
        tips: ['Lancez d\'abord sans cocher pour voir l\'espace récupérable', 'Cochez "Supprimer" pour nettoyer réellement (fichiers anciens uniquement)', 'Action sensible : demande confirmation', '💡 Pour un nettoyage plus fin (par catégorie, façon CCleaner) : PC & Système → Nettoyage'],
        params: [
          { name: 'delete',       label: '⚠️ Supprimer réellement', type: 'checkbox' },
          { name: 'min_age_days', label: 'Âge minimal des fichiers (jours)', type: 'number', defaultValue: 1 },
        ],
      },
      {
        id: 'file_large_finder', icon: '📦', name: 'Plus gros fichiers',
        description: 'Trouve les fichiers qui occupent le plus d\'espace dans un dossier (récursif).',
        tips: ['Idéal pour repérer ce qui sature le disque', 'Laissez vide pour analyser le dossier personnel'],
        params: [
          { name: 'directory', label: 'Dossier à analyser', type: 'path', placeholder: 'Dossier personnel (défaut)' },
          { name: 'top',       label: 'Nombre de résultats', type: 'number', defaultValue: 20 },
          { name: 'min_mb',    label: 'Taille minimale (Mo)', type: 'number', placeholder: 'ex: 10' },
        ],
      },
      {
        id: 'pc_screenshot', icon: '📸', name: 'Capture d\'écran',
        description: 'Prend une capture plein écran et la sauvegarde en PNG.',
        params: [
          { name: 'path', label: 'Chemin de sauvegarde (.png)', type: 'path', placeholder: 'Bureau (défaut)' },
        ],
      },
      {
        id: 'pc_process_list', icon: '⚙️', name: 'Processus actifs',
        description: 'Liste tous les processus en cours avec consommation CPU et RAM.',
        params: [
          { name: 'sort_by', label: 'Trier par', type: 'select', options: [
            { value: 'cpu',    label: '🔥 CPU' },
            { value: 'memory', label: '💾 Mémoire' },
            { value: 'name',   label: '🔤 Nom' },
          ]},
        ],
      },
      {
        id: 'pc_clipboard_get', icon: '📋', name: 'Lire le presse-papiers',
        description: 'Lit le texte actuellement dans le presse-papiers.',
        params: [],
      },
      {
        id: 'pc_clipboard_set', icon: '📋', name: 'Écrire dans le presse-papiers',
        description: 'Copie un texte dans le presse-papiers Windows.',
        params: [
          { name: 'text', label: 'Texte à copier', type: 'textarea', required: true },
        ],
      },
      {
        id: 'pc_open_file', icon: '🚀', name: 'Ouvrir un fichier / app',
        description: 'Ouvre un fichier avec son application par défaut, ou lance une application par nom.',
        tips: ['Exemples : chrome, notepad, calc, explorer', 'Ou un chemin complet vers un fichier'],
        params: [
          { name: 'path', label: 'Fichier ou application', type: 'path', required: true, placeholder: 'chrome  |  notepad  |  C:\\fichier.pdf' },
        ],
      },
      {
        id: 'pc_app_launch', icon: '🎯', name: 'Lancer une application',
        description: 'Ouvre une application Windows installée par son nom commun.',
        tips: ['chrome, firefox, notepad, word, excel, vlc, spotify, discord, teams…', 'Utilise des alias courants automatiquement'],
        params: [
          { name: 'app_name', label: 'Nom de l\'application', type: 'text', required: true, placeholder: 'chrome  |  spotify  |  word' },
        ],
      },
      {
        id: 'pc_notify', icon: '🔔', name: 'Envoyer une notification',
        description: 'Affiche une notification Windows (bulle en bas à droite de l\'écran).',
        tips: ['Apparaît dans le centre de notifications Windows', 'Utile pour des rappels ou alertes'],
        params: [
          { name: 'title',   label: 'Titre',   type: 'text',     required: true, placeholder: 'Rappel Marvin' },
          { name: 'message', label: 'Message', type: 'textarea', required: true, placeholder: 'N\'oublie pas la réunion à 14h !' },
        ],
      },
      {
        id: 'pc_window_list', icon: '🪟', name: 'Fenêtres ouvertes',
        description: 'Liste toutes les fenêtres actuellement ouvertes sur le bureau Windows.',
        tips: ['Retourne le titre et l\'application de chaque fenêtre', 'Utile pour voir ce qui tourne en arrière-plan'],
        params: [],
      },
      {
        id: 'pc_run_powershell', icon: '⚡', name: 'Script PowerShell',
        description: 'Exécute n\'importe quel script ou cmdlet PowerShell et retourne la sortie.',
        tips: [
          'Exemples : Get-Process, Get-Date, Get-ChildItem',
          'Supporte les scripts multi-lignes',
          'Les commandes dangereuses demandent une confirmation',
        ],
        params: [
          { name: 'script',    label: 'Script PowerShell', type: 'textarea', required: true, placeholder: 'Get-Date\nGet-Process | Select-Object -First 5' },
          { name: 'timeout',   label: 'Délai max (s)',     type: 'number',   defaultValue: 30 },
          { name: 'confirmed', label: 'Confirmer l\'exécution', type: 'checkbox', defaultValue: false },
        ],
      },
    ],
  },
  {
    id: 'reseau', label: 'Réseau', icon: '🌐', color: '#38bdf8',
    description: 'Diagnostiquez votre réseau : ping, ports, DNS, traceroute, scan local.',
    tools: [
      {
        id: 'net_ping', icon: '📡', name: 'Ping',
        description: 'Teste la connectivité vers une IP ou un nom d\'hôte.',
        tips: ['Retourne le temps de réponse et les statistiques', '8.8.8.8 = DNS Google, 1.1.1.1 = Cloudflare'],
        params: [
          { name: 'host',  label: 'Hôte / IP',           type: 'text',   required: true, placeholder: '8.8.8.8 ou google.com' },
          { name: 'count', label: 'Nombre de paquets',   type: 'number', defaultValue: 4, min: 1, max: 20 },
        ],
      },
      {
        id: 'net_port_scan', icon: '🔭', name: 'Scanner les ports',
        description: 'Détecte les ports TCP ouverts sur un hôte.',
        tips: ['Ports communs : 80 (HTTP), 443 (HTTPS), 22 (SSH), 3389 (RDP)', 'Plage possible : "20-80"'],
        params: [
          { name: 'host',    label: 'Hôte / IP',           type: 'text',   required: true, placeholder: '192.168.1.1 ou exemple.com' },
          { name: 'ports',   label: 'Ports (CSV ou plage)', type: 'text',   placeholder: '22,80,443,3389,8080' },
          { name: 'timeout', label: 'Timeout/port (sec)',   type: 'number', defaultValue: 1.0, min: 0.1, max: 10 },
        ],
      },
      {
        id: 'net_dns_lookup', icon: '🔍', name: 'Résolution DNS',
        description: 'Résout un nom de domaine en IP (ou reverse lookup d\'une IP en nom).',
        tips: ['Inclut aussi la sortie nslookup', 'Fonctionne aussi en reverse : entrez une IP'],
        params: [
          { name: 'host', label: 'Domaine ou IP', type: 'text', required: true, placeholder: 'google.com ou 8.8.8.8' },
        ],
      },
      {
        id: 'net_traceroute', icon: '🗺️', name: 'Traceroute',
        description: 'Affiche tous les sauts réseau entre ce PC et la destination.',
        tips: ['Peut prendre 30-60 secondes', 'Utile pour détecter les ralentissements réseau'],
        params: [
          { name: 'host',     label: 'Hôte / IP',        type: 'text',   required: true, placeholder: 'google.com' },
          { name: 'max_hops', label: 'Sauts maximum',    type: 'number', defaultValue: 15, min: 3, max: 30 },
        ],
      },
      {
        id: 'net_scan_local', icon: '🏠', name: 'Scanner le réseau local',
        description: 'Détecte tous les appareils connectés au réseau local via ARP.',
        tips: ['Retourne IP + adresse MAC de chaque appareil', 'Identifie smartphones, TV, NAS, etc.'],
        params: [],
      },
      {
        id: 'net_whois', icon: '📋', name: 'WHOIS',
        description: 'Obtient les informations d\'enregistrement d\'un domaine ou d\'une IP.',
        tips: ['Registrant, serveurs DNS, dates de création/expiration', 'Fonctionne sur domaines et IPs publiques'],
        params: [
          { name: 'host', label: 'Domaine ou IP', type: 'text', required: true, placeholder: 'exemple.com ou 142.250.0.1' },
        ],
      },
    ],
  },
  {
    id: 'ssh', label: 'SSH', icon: '🔗', color: '#10b981',
    description: 'Exécutez des commandes sur vos serveurs distants via SSH (connexions configurées dans l\'onglet SSH).',
    tools: [
      {
        id: 'ssh_list', icon: '📋', name: 'Lister les connexions SSH',
        description: 'Affiche toutes les connexions SSH sauvegardées dans Marvin.',
        tips: ['Gérez les connexions dans l\'onglet SSH du menu'],
        params: [],
      },
      {
        id: 'ssh_exec', icon: '⚡', name: 'Exécuter une commande SSH',
        description: 'Lance une commande sur un serveur distant via SSH. Demande confirmation avant exécution.',
        tips: ['⚠️ Les commandes distantes peuvent être irréversibles', 'Récupérez l\'ID via "Lister les connexions SSH"', 'Timeout maximum : 120 secondes'],
        params: [
          { name: 'connection_id', label: 'ID de connexion', type: 'text',   required: true, placeholder: 'ex: 1 (depuis ssh_list)' },
          { name: 'command',       label: 'Commande',        type: 'textarea', required: true, placeholder: 'ls -la /var/log' },
          { name: 'timeout',       label: 'Timeout (secondes)', type: 'number', defaultValue: 30, min: 5, max: 120 },
        ],
      },
      {
        id: 'ssh_exec_multi', icon: '🖧', name: 'Commande multi-serveurs',
        description: 'Exécute la même commande sur plusieurs serveurs en parallèle (administration de parc).',
        tips: ['Séparez les IDs par des virgules', 'Idéal pour patcher/auditer plusieurs serveurs'],
        params: [
          { name: 'connection_ids', label: 'IDs de connexions', type: 'tags', required: true, placeholder: '1, 2, 3' },
          { name: 'command',        label: 'Commande',          type: 'textarea', required: true, placeholder: 'uptime' },
        ],
      },
      {
        id: 'ssh_server_info', icon: '🩺', name: 'Diagnostic serveur',
        description: 'État rapide d\'un serveur : OS, uptime, RAM, disque, charge.',
        tips: ['Lecture seule — aucun risque'],
        params: [{ name: 'connection_id', label: 'ID de connexion', type: 'text', required: true, placeholder: '1' }],
      },
      {
        id: 'ssh_list_dir', icon: '📂', name: 'Lister un dossier distant',
        description: 'Affiche le contenu d\'un dossier sur le serveur (SFTP).',
        params: [
          { name: 'connection_id', label: 'ID de connexion', type: 'text', required: true, placeholder: '1' },
          { name: 'remote_path',   label: 'Dossier distant',  type: 'text', placeholder: '/var/www (défaut: ~)' },
        ],
      },
      {
        id: 'ssh_upload', icon: '📤', name: 'Envoyer un fichier (SFTP)',
        description: 'Transfère un fichier local vers le serveur.',
        params: [
          { name: 'connection_id', label: 'ID de connexion', type: 'text', required: true, placeholder: '1' },
          { name: 'local_path',    label: 'Fichier local',    type: 'path', required: true },
          { name: 'remote_path',   label: 'Destination distante', type: 'text', required: true, placeholder: '/tmp/fichier.txt' },
        ],
      },
      {
        id: 'ssh_download', icon: '📥', name: 'Télécharger un fichier (SFTP)',
        description: 'Récupère un fichier du serveur vers le PC.',
        params: [
          { name: 'connection_id', label: 'ID de connexion', type: 'text', required: true, placeholder: '1' },
          { name: 'remote_path',   label: 'Fichier distant',  type: 'text', required: true, placeholder: '/var/log/syslog' },
          { name: 'local_path',    label: 'Destination locale', type: 'path', placeholder: 'Téléchargements (défaut)' },
        ],
      },
    ],
  },
  {
    id: 'archives', label: 'Archives', icon: '🗜️', color: '#f59e0b',
    description: 'Compressez et extrayez des archives ZIP et TAR sans quitter Marvin.',
    tools: [
      {
        id: 'file_compress', icon: '🗜️', name: 'Créer une archive ZIP',
        description: 'Compresse un ou plusieurs fichiers/dossiers en une archive ZIP.',
        tips: [
          'Séparez plusieurs chemins par des virgules',
          'Si omis, l\'archive est créée sur le Bureau',
          'Supporte la compression de dossiers entiers',
        ],
        params: [
          { name: 'sources',     label: 'Fichiers / Dossiers à compresser', type: 'tags', required: true,
            placeholder: 'Bureau\\rapport, Bureau\\images' },
          { name: 'output_path', label: 'Chemin de l\'archive ZIP de sortie', type: 'path',
            placeholder: 'Bureau (défaut)' },
        ],
      },
      {
        id: 'file_extract', icon: '📦', name: 'Extraire une archive',
        description: 'Décompresse une archive ZIP, TAR.GZ ou TGZ vers un dossier.',
        tips: [
          'Supporte .zip, .tar, .tar.gz, .tgz, .tar.bz2',
          'Si omis, extraction dans le même dossier que l\'archive',
          'Crée automatiquement le dossier de destination',
        ],
        params: [
          { name: 'archive_path', label: 'Chemin de l\'archive', type: 'path', required: true,
            placeholder: 'Bureau\\fichiers.zip' },
          { name: 'dest_path',    label: 'Dossier de destination', type: 'path',
            placeholder: 'Même dossier que l\'archive (défaut)' },
        ],
      },
    ],
  },
  {
    id: 'utilitaires', label: 'Utilitaires', icon: '🧰', color: '#06b6d4',
    description: 'Calculs, dates, heures, météo, traduction, conversion et générateur de mots de passe.',
    tools: [
      {
        id: 'calculator', icon: '🧮', name: 'Calculateur',
        description: 'Évalue une expression mathématique — arithmétique, trigonométrie, logarithmes, factorielles et bien plus.',
        tips: [
          'Exemples : (12 + 4) * 3 / 2  →  24',
          'sqrt(144)  →  12',
          'sin(pi/2)  →  1',
          'factorial(10)  →  3628800',
          'log2(1024)  →  10',
        ],
        params: [
          { name: 'expression', label: 'Expression', type: 'text', required: true,
            placeholder: '(12 + 4) * 3 / sqrt(9)' },
        ],
      },
      {
        id: 'datetime_info', icon: '🕐', name: 'Date & Heure',
        description: 'Heure actuelle, conversion de fuseau horaire, différence entre deux dates, ou ajout d\'une durée.',
        tips: [
          'action=now → heure actuelle dans le fuseau indiqué',
          'action=diff → durée entre deux dates ISO',
          'action=add avec delta {"days":7} → date +7 jours',
        ],
        params: [
          { name: 'action', label: 'Action', type: 'select', options: [
            { value: 'now',     label: '🕐 Heure actuelle' },
            { value: 'convert', label: '🔄 Convertir fuseau horaire' },
            { value: 'diff',    label: '📏 Différence entre deux dates' },
            { value: 'add',     label: '➕ Ajouter une durée' },
          ]},
          { name: 'timezone',  label: 'Fuseau horaire', type: 'text', placeholder: 'Europe/Paris' },
          { name: 'datetime',  label: 'Date/heure 1 (ISO 8601)', type: 'text', placeholder: '2025-06-01T14:30:00' },
          { name: 'datetime2', label: 'Date/heure 2 (pour diff)', type: 'text', placeholder: '2025-07-01T14:30:00' },
          { name: 'delta',     label: 'Delta (JSON) (pour add)', type: 'text', placeholder: '{"days":5,"hours":2}' },
        ],
      },
      {
        id: 'weather', icon: '🌤️', name: 'Météo',
        description: 'Météo actuelle et prévisions jusqu\'à 7 jours via Open-Meteo (gratuit, sans clé API).',
        tips: [
          'Aucune configuration requise — fonctionne directement',
          'Couvre toutes les villes du monde',
          'Données : température, humidité, vent, précipitations',
        ],
        params: [
          { name: 'city',    label: 'Ville', type: 'text', required: true, placeholder: 'Paris' },
          { name: 'country', label: 'Pays (code ISO 2 lettres)', type: 'text', placeholder: 'FR' },
          { name: 'days',    label: 'Jours de prévisions (1-7)', type: 'number', defaultValue: 1, min: 1, max: 7 },
        ],
      },
      {
        id: 'translate', icon: '🌍', name: 'Traducteur',
        description: 'Traduit du texte dans plus de 100 langues via MyMemory (gratuit, aucune configuration).',
        tips: [
          'Aucune clé API requise — fonctionne directement',
          'Langues : fr, en, es, de, it, pt, ar, zh, ja, ru, nl, pl…',
          'Détection automatique de la langue source si laissé vide',
          '1000 requêtes/jour gratuites (suffisant pour un usage quotidien)',
        ],
        params: [
          { name: 'text',        label: 'Texte à traduire', type: 'textarea', required: true, placeholder: 'Bonjour, comment allez-vous ?' },
          { name: 'target_lang', label: 'Langue cible',     type: 'select', required: true, options: [
            { value: 'en', label: '🇬🇧 Anglais' },
            { value: 'fr', label: '🇫🇷 Français' },
            { value: 'es', label: '🇪🇸 Espagnol' },
            { value: 'de', label: '🇩🇪 Allemand' },
            { value: 'it', label: '🇮🇹 Italien' },
            { value: 'pt', label: '🇵🇹 Portugais' },
            { value: 'ar', label: '🇸🇦 Arabe' },
            { value: 'zh', label: '🇨🇳 Chinois' },
            { value: 'ja', label: '🇯🇵 Japonais' },
            { value: 'ru', label: '🇷🇺 Russe' },
            { value: 'nl', label: '🇳🇱 Néerlandais' },
            { value: 'pl', label: '🇵🇱 Polonais' },
            { value: 'tr', label: '🇹🇷 Turc' },
            { value: 'ko', label: '🇰🇷 Coréen' },
          ]},
          { name: 'source_lang', label: 'Langue source', type: 'text', placeholder: 'auto (détection automatique)' },
        ],
      },
      {
        id: 'unit_convert', icon: '📐', name: 'Convertisseur d\'unités',
        description: 'Convertit entre toutes les unités : longueur, masse, volume, vitesse, surface, énergie, données, température.',
        tips: [
          'Longueur : m, km, cm, mm, mile, yard, ft, inch',
          'Masse : kg, g, lb, oz, tonne',
          'Température : °C, °F, K',
          'Volume : L, ml, cl, gallon, pint',
          'Vitesse : km/h, m/s, mph, knot',
          'Données : GB, MB, KB, GiB, MiB',
        ],
        params: [
          { name: 'value',     label: 'Valeur', type: 'number', required: true, placeholder: '100' },
          { name: 'from_unit', label: 'Unité source',      type: 'text', required: true, placeholder: 'km' },
          { name: 'to_unit',   label: 'Unité destination', type: 'text', required: true, placeholder: 'mile' },
        ],
      },
      {
        id: 'password_generate', icon: '🔐', name: 'Générateur de mots de passe',
        description: 'Génère des mots de passe ou PINs sécurisés avec critères configurables.',
        tips: [
          'Activez "PIN" pour générer un code numérique uniquement',
          'Excluez les caractères ambigus : Il1O0',
          'Générez jusqu\'à 20 mots de passe en une fois',
          'Utilise secrets.choice() — cryptographiquement sécurisé',
        ],
        params: [
          { name: 'length', label: 'Longueur', type: 'number', defaultValue: 16, min: 4, max: 128 },
          { name: 'count',  label: 'Nombre de mots de passe', type: 'number', defaultValue: 1, min: 1, max: 20 },
          { name: 'exclude', label: 'Caractères à exclure', type: 'text', placeholder: 'Il1O0 (éviter confusions)' },
          { name: 'pin',    label: 'Mode PIN numérique', type: 'checkbox', defaultValue: false },
        ],
      },
    ],
  },
];
