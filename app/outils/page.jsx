'use client';
import { useState, useCallback, useEffect, useMemo, useRef, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { LoadingRow } from '@/components/ui/Spinner';
import PrettyResult from '@/components/chat/PrettyResult';
import { useToast } from '@/components/ui/Toast';

import { BACKEND_URL } from '@/lib/backend';

// ══════════════════════════════════════════════════════════════════════════════
// Catalogue des outils par catégorie
// ══════════════════════════════════════════════════════════════════════════════

const CATEGORIES = [
  // ─────────────────────────────────────────────────────── INFOGRAPHIE
  {
    id: 'infographie', label: 'Infographie', icon: '📊', color: '#f97316',
    description: 'Créez des graphiques et visualisations de données en PNG.',
    tools: [
      {
        id: 'infographic_create', icon: '📊', name: 'Créer un graphique',
        description: 'Génère un graphique PNG (barres, camembert, ligne) à partir de données brutes.',
        tips: ['Séparez labels et valeurs par des virgules', 'Le fichier est créé sur votre Bureau par défaut', 'Les valeurs doivent être numériques'],
        params: [
          { name: 'title',       label: 'Titre',                   type: 'text',    required: true,  placeholder: 'Ventes 2024' },
          { name: 'chart_type',  label: 'Type de graphique',       type: 'select',  required: true,  options: [
            { value: 'bar',            label: '📊 Barres verticales' },
            { value: 'horizontal_bar', label: '📊 Barres horizontales' },
            { value: 'pie',            label: '🥧 Camembert' },
            { value: 'donut',          label: '🍩 Anneau (donut)' },
            { value: 'line',           label: '📈 Ligne' },
            { value: 'area',           label: '🏔️ Aire' },
            { value: 'multi_line',     label: '📉 Multi-lignes (series)' },
            { value: 'grouped_bar',    label: '📊 Barres groupées (series)' },
            { value: 'stacked_bar',    label: '📚 Barres empilées (series)' },
            { value: 'scatter',        label: '✴️ Nuage de points' },
            { value: 'radar',          label: '🕸️ Radar (series)' },
          ]},
          { name: 'labels',      label: 'Étiquettes',              type: 'tags',    required: true,  placeholder: 'Jan, Fév, Mar, Avr' },
          { name: 'values',      label: 'Valeurs (mono-série)',    type: 'numbers', placeholder: '100, 200, 150, 300' },
          { name: 'series',      label: 'Séries (multi) — JSON',   type: 'jsonarray', placeholder: '[{"name":"2024","values":[100,200,150]},{"name":"2025","values":[120,210,180]}]' },
          { name: 'subtitle',    label: 'Sous-titre',              type: 'text',    placeholder: 'optionnel' },
          { name: 'theme',       label: 'Thème',                   type: 'select',  options: [{ value: 'dark', label: '🌙 Sombre' }, { value: 'light', label: '☀️ Clair' }] },
          { name: 'output_path', label: 'Chemin de sortie',        type: 'path',    placeholder: 'Bureau (défaut)' },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── DOCUMENTS
  {
    id: 'documents', label: 'Documents', icon: '📄', color: '#3b82f6',
    description: 'Créez et convertissez des fichiers Word, PDF et Excel.',
    tools: [
      {
        id: 'file_create_docx', icon: '📝', name: 'Créer un Word (.docx)',
        description: 'Génère un document Microsoft Word avec support Markdown (titres, listes, séparateurs).',
        tips: ['# Titre 1,  ## Titre 2', '**gras**, *italique*, `code`', '- listes · 1. numérotées', 'Tableaux : | Col A | Col B |', '> citation · ``` bloc de code'],
        params: [
          { name: 'path',     label: 'Chemin du fichier (.docx)', type: 'path',     required: true,  placeholder: 'Cliquez sur Parcourir…' },
          { name: 'title',    label: 'Titre du document',         type: 'text',     required: true,  placeholder: 'Mon rapport' },
          { name: 'subtitle', label: 'Sous-titre (optionnel)',    type: 'text',     placeholder: 'Sous-titre ou résumé' },
          { name: 'content',  label: 'Contenu (Markdown enrichi)',type: 'textarea', required: true,  placeholder: '# Introduction\n\nTexte avec **gras**.\n\n| Produit | Prix |\n|---------|------|\n| A | 10€ |' },
          { name: 'author',   label: 'Auteur',                    type: 'text',     placeholder: 'Marvin', defaultValue: 'Marvin' },
          { name: 'accent',   label: "Couleur d'accent",          type: 'text',     placeholder: '#4f8cff' },
        ],
      },
      {
        id: 'file_create_pdf', icon: '📕', name: 'Créer un PDF',
        description: 'Génère un PDF professionnel directement — aucun logiciel nécessaire (ReportLab).',
        tips: ['Pas besoin de Word', '**gras**, *italique*, `code`, [liens](url)', 'Tableaux markdown stylés', 'Numéros de page automatiques'],
        params: [
          { name: 'path',     label: 'Chemin du fichier (.pdf)', type: 'path',     required: true,  placeholder: 'Cliquez sur Parcourir…' },
          { name: 'title',    label: 'Titre',                    type: 'text',     required: true },
          { name: 'subtitle', label: 'Sous-titre (optionnel)',   type: 'text',     placeholder: 'Sous-titre ou résumé' },
          { name: 'content',  label: 'Contenu (Markdown enrichi)',type: 'textarea', required: true },
          { name: 'author',   label: 'Auteur',                   type: 'text',     placeholder: 'Marvin', defaultValue: 'Marvin' },
          { name: 'accent',   label: "Couleur d'accent",         type: 'text',     placeholder: '#4f8cff' },
        ],
      },
      {
        id: 'file_create_xlsx', icon: '📗', name: 'Créer un Excel (.xlsx)',
        description: 'Crée un tableur Excel avec en-têtes et données (openpyxl).',
        tips: ['Séparez les en-têtes par des virgules', 'Les lignes sont en JSON : [["val1","val2"], ...]'],
        params: [
          { name: 'path',    label: 'Chemin (.xlsx)',       type: 'path',      placeholder: 'Bureau (défaut)' },
          { name: 'title',   label: 'Nom de la feuille',   type: 'text',      required: true, placeholder: 'Données 2024' },
          { name: 'headers', label: 'En-têtes (CSV)',      type: 'tags',      required: true, placeholder: 'Nom, Prénom, Age, Email' },
          { name: 'rows',    label: 'Données (JSON)',      type: 'jsonarray', placeholder: '[["Jean","Dupont",30,"j@mail.fr"]]' },
        ],
      },
      {
        id: 'file_convert_docx_to_pdf', icon: '🔄', name: 'Word → PDF',
        description: 'Convertit un .docx existant en PDF (docx2pdf).',
        tips: ['Le fichier Word doit exister sur le disque', 'Microsoft Word doit être installé'],
        params: [
          { name: 'path',       label: 'Fichier Word source (.docx)', type: 'path', required: true },
          { name: 'output_dir', label: 'Dossier destination',         type: 'path', placeholder: 'Même dossier (défaut)' },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── FICHIERS
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

  // ─────────────────────────────────────────────────────── WEB
  {
    id: 'web', label: 'Web', icon: '🌐', color: '#06b6d4',
    description: 'Recherchez sur Internet et lisez des pages web.',
    tools: [
      {
        id: 'web_search', icon: '🔍', name: 'Recherche web',
        description: 'Effectue une recherche DuckDuckGo et retourne titres, URLs et extraits. Aucune clé API requise.',
        tips: ['Utilise DuckDuckGo par défaut (gratuit)', 'Retourne jusqu\'à 20 résultats', 'Compatible Brave/SerpAPI via les paramètres'],
        params: [
          { name: 'query',       label: 'Requête',               type: 'text',   required: true, placeholder: 'Ollama modèles locaux 2024' },
          { name: 'num_results', label: 'Nombre de résultats',   type: 'number', defaultValue: 5, min: 1, max: 20 },
        ],
      },
      {
        id: 'web_browse', icon: '🌐', name: 'Lire une page web',
        description: 'Charge une page web et extrait son contenu texte (via BeautifulSoup).',
        tips: ['Retourne le texte brut lisible', 'Utile pour documentation, articles, wiki'],
        params: [
          { name: 'url', label: 'URL de la page', type: 'url', required: true, placeholder: 'https://example.com/article' },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── PC
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

  // ─────────────────────────────────────────────────────── CALENDRIER
  {
    id: 'calendar', label: 'Calendrier', icon: '📅', color: '#3b82f6',
    description: 'Consultez et créez des événements Google Calendar (OAuth Google requis).',
    tools: [
      {
        id: 'calendar_list', icon: '📅', name: 'Voir les événements',
        description: 'Liste les prochains événements Google Calendar.',
        requiresAuth: 'google',
        tips: ['OAuth Google requis dans Paramètres > Connexions', 'Affiche les N prochains jours'],
        params: [
          { name: 'days',        label: 'Nombre de jours',    type: 'number', defaultValue: 7,  min: 1, max: 90 },
          { name: 'max_results', label: 'Événements max',     type: 'number', defaultValue: 20, min: 1, max: 50 },
          { name: 'calendar_id', label: 'Calendrier (optionnel)', type: 'text', placeholder: 'primary (défaut)' },
        ],
      },
      {
        id: 'calendar_create', icon: '➕', name: 'Créer un événement',
        description: 'Ajoute un événement dans Google Calendar.',
        requiresAuth: 'google',
        tips: ['Format date+heure : 2025-12-25T14:00:00', 'Format journée entière : 2025-12-25', 'Durée par défaut : 1 heure'],
        params: [
          { name: 'title',       label: 'Titre',            type: 'text',     required: true },
          { name: 'start',       label: 'Début',            type: 'text',     required: true, placeholder: '2025-12-25T14:00:00 ou 2025-12-25' },
          { name: 'end',         label: 'Fin (optionnel)',   type: 'text',     placeholder: '2025-12-25T15:00:00 ou 2025-12-26' },
          { name: 'location',    label: 'Lieu',             type: 'text',     placeholder: 'Paris, 75001' },
          { name: 'description', label: 'Description',      type: 'textarea', placeholder: 'Notes ou ordre du jour…' },
          { name: 'calendar_id', label: 'Calendrier',       type: 'text',     placeholder: 'primary (défaut)' },
        ],
      },
      {
        id: 'calendar_update', icon: '✏️', name: 'Modifier un événement',
        description: 'Met à jour le titre, l\'horaire, le lieu ou la description d\'un événement Google Calendar.',
        requiresAuth: 'google',
        tips: ['Récupérez l\'ID avec calendar_list', 'Laissez vides les champs à ne pas modifier'],
        params: [
          { name: 'event_id',    label: 'ID de l\'événement', type: 'text', required: true, placeholder: 'abc123xyz...' },
          { name: 'title',       label: 'Nouveau titre',       type: 'text', placeholder: 'Réunion d\'équipe' },
          { name: 'start',       label: 'Nouveau début',       type: 'text', placeholder: '2025-06-15T09:00:00' },
          { name: 'end',         label: 'Nouvelle fin',        type: 'text', placeholder: '2025-06-15T10:00:00' },
          { name: 'location',    label: 'Lieu',                type: 'text', placeholder: 'Paris, France' },
          { name: 'description', label: 'Description',         type: 'textarea', placeholder: 'Notes...' },
          { name: 'calendar_id', label: 'Calendrier',          type: 'text', placeholder: 'primary (défaut)' },
        ],
      },
      {
        id: 'calendar_delete', icon: '🗑️', name: 'Supprimer un événement',
        description: 'Supprime définitivement un événement Google Calendar par son ID.',
        requiresAuth: 'google',
        tips: ['Récupérez l\'ID dans calendar_list', 'L\'action est irréversible — une confirmation est demandée'],
        params: [
          { name: 'event_id',    label: 'ID de l\'événement', type: 'text', required: true, placeholder: 'abc123xyz...' },
          { name: 'calendar_id', label: 'Calendrier',          type: 'text', placeholder: 'primary (défaut)' },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── CLOUD
  {
    id: 'cloud', label: 'Cloud', icon: '☁️', color: '#ec4899',
    description: 'Google Drive et OneDrive — listez, lisez et uploadez.',
    tools: [
      {
        id: 'google_drive_list', icon: '🔴', name: 'Lister Google Drive',
        description: 'Liste les fichiers et dossiers dans Google Drive.',
        requiresAuth: 'google',
        params: [
          { name: 'folder_id', label: 'ID du dossier (optionnel)', type: 'text', placeholder: 'root' },
        ],
      },
      {
        id: 'google_drive_read', icon: '🔴', name: 'Lire un fichier Drive',
        description: 'Télécharge et lit le contenu d\'un fichier Google Drive.',
        requiresAuth: 'google',
        params: [
          { name: 'file_id', label: 'ID du fichier', type: 'text', required: true },
        ],
      },
      {
        id: 'google_drive_upload', icon: '🔴', name: 'Uploader vers Drive',
        description: 'Envoie un fichier local vers Google Drive.',
        requiresAuth: 'google',
        params: [
          { name: 'path',      label: 'Fichier local',          type: 'path', required: true },
          { name: 'folder_id', label: 'Dossier cible (optionnel)', type: 'text' },
        ],
      },
      {
        id: 'onedrive_list', icon: '🔵', name: 'Lister OneDrive',
        description: 'Liste les fichiers et dossiers dans OneDrive.',
        requiresAuth: 'microsoft',
        params: [
          { name: 'folder_path', label: 'Chemin du dossier', type: 'text', placeholder: '/ (racine)' },
        ],
      },
      {
        id: 'onedrive_read', icon: '🔵', name: 'Lire un fichier OneDrive',
        description: 'Télécharge et lit un fichier OneDrive.',
        requiresAuth: 'microsoft',
        params: [
          { name: 'file_id', label: 'ID du fichier', type: 'text', required: true },
        ],
      },
      {
        id: 'onedrive_upload', icon: '🔵', name: 'Uploader vers OneDrive',
        description: 'Envoie un fichier local vers OneDrive.',
        requiresAuth: 'microsoft',
        params: [
          { name: 'path', label: 'Fichier local', type: 'path', required: true },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── TÂCHES
  {
    id: 'taches', label: 'Tâches & Notes', icon: '✅', color: '#eab308',
    description: 'Gérez vos tâches et prenez des notes persistantes.',
    tools: [
      {
        id: 'task_create', icon: '✅', name: 'Créer une tâche',
        description: 'Crée une tâche avec titre, priorité et date d\'échéance.',
        params: [
          { name: 'title',       label: 'Titre',         type: 'text',     required: true },
          { name: 'description', label: 'Description',   type: 'textarea' },
          { name: 'due_date',    label: 'Échéance',      type: 'date' },
          { name: 'priority',    label: 'Priorité',      type: 'select', options: [
            { value: 'low',    label: '🟢 Faible' },
            { value: 'medium', label: '🟡 Moyenne' },
            { value: 'high',   label: '🔴 Haute' },
          ]},
        ],
      },
      {
        id: 'task_list', icon: '📋', name: 'Lister les tâches',
        description: 'Affiche toutes les tâches enregistrées, filtrables par statut.',
        params: [
          { name: 'status', label: 'Statut', type: 'select', options: [
            { value: 'all',         label: '📋 Toutes' },
            { value: 'pending',     label: '⏳ En attente' },
            { value: 'in_progress', label: '▶️ En cours' },
            { value: 'done',        label: '✅ Terminées' },
          ]},
        ],
      },
      {
        id: 'note_create', icon: '📝', name: 'Créer une note',
        description: 'Crée une note avec contenu et tags pour la retrouver facilement.',
        params: [
          { name: 'title',   label: 'Titre',                    type: 'text',     required: true },
          { name: 'content', label: 'Contenu',                  type: 'textarea', required: true },
          { name: 'tags',    label: 'Tags (séparés par virgule)', type: 'text',   placeholder: 'travail, urgent, projet' },
        ],
      },
      {
        id: 'note_list', icon: '📚', name: 'Lister les notes',
        description: 'Affiche toutes les notes, avec filtre optionnel par tag.',
        params: [
          { name: 'tag', label: 'Filtrer par tag (optionnel)', type: 'text' },
        ],
      },
      {
        id: 'task_update', icon: '✏️', name: 'Modifier une tâche',
        description: 'Met à jour le statut, la priorité ou le titre d\'une tâche existante.',
        tips: ['Obtenez l\'ID d\'une tâche via "Lister les tâches"'],
        params: [
          { name: 'id',     label: 'ID de la tâche', type: 'text', required: true },
          { name: 'status', label: 'Statut',          type: 'select', options: [
            { value: 'pending',     label: '⏳ En attente' },
            { value: 'in_progress', label: '▶️ En cours' },
            { value: 'done',        label: '✅ Terminée' },
          ]},
          { name: 'priority', label: 'Priorité', type: 'select', options: [
            { value: 'low',    label: '🟢 Faible' },
            { value: 'medium', label: '🟡 Moyenne' },
            { value: 'high',   label: '🔴 Haute' },
          ]},
          { name: 'title', label: 'Nouveau titre (optionnel)', type: 'text' },
        ],
      },
      {
        id: 'task_delete', icon: '🗑️', name: 'Supprimer une tâche',
        description: 'Supprime une tâche définitivement. Demande confirmation.',
        params: [
          { name: 'id', label: 'ID de la tâche', type: 'text', required: true },
        ],
      },
      {
        id: 'note_update', icon: '✏️', name: 'Modifier une note',
        description: 'Met à jour le contenu ou les tags d\'une note existante.',
        tips: ['Obtenez l\'ID d\'une note via "Lister les notes"'],
        params: [
          { name: 'id',      label: 'ID de la note',  type: 'text',     required: true },
          { name: 'title',   label: 'Nouveau titre',   type: 'text' },
          { name: 'content', label: 'Nouveau contenu', type: 'textarea' },
          { name: 'tags',    label: 'Tags',            type: 'text', placeholder: 'travail, urgent' },
        ],
      },
      {
        id: 'note_delete', icon: '🗑️', name: 'Supprimer une note',
        description: 'Supprime une note définitivement. Demande confirmation.',
        params: [
          { name: 'id', label: 'ID de la note', type: 'text', required: true },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── MÉMOIRE
  {
    id: 'memoire', label: 'Mémoire & IA', icon: '🧠', color: '#a78bfa',
    description: 'Gérez la mémoire personnalisée de Marvin et la recherche sémantique.',
    tools: [
      {
        id: 'memory_save', icon: '💾', name: 'Mémoriser une information',
        description: 'Sauvegarde une préférence ou fait dans la mémoire longue durée de Marvin.',
        tips: ['Ces infos sont injectées dans chaque conversation', 'Ex: préférences, habitudes, infos perso'],
        params: [
          { name: 'content', label: 'Information à mémoriser', type: 'textarea', required: true,
            placeholder: 'Je préfère les réponses courtes et directes en français.' },
        ],
      },
      {
        id: 'memory_list', icon: '📚', name: 'Lister les mémoires',
        description: 'Affiche toutes les informations mémorisées par Marvin.',
        params: [],
      },
      {
        id: 'memory_search', icon: '🔍', name: 'Rechercher dans les mémoires',
        description: 'Recherche sémantique dans les mémoires enregistrées.',
        params: [
          { name: 'query', label: 'Requête', type: 'text', required: true },
        ],
      },
      {
        id: 'memory_delete', icon: '🗑️', name: 'Supprimer une mémoire',
        description: 'Efface définitivement une information mémorisée. Demande confirmation.',
        tips: ['Obtenez l\'ID via "Lister les mémoires"'],
        params: [
          { name: 'id', label: 'ID de la mémoire', type: 'text', required: true },
        ],
      },
      {
        id: 'search_semantic', icon: '🔮', name: 'Recherche sémantique',
        description: 'Recherche dans les documents indexés par sens (vectorielle via Qdrant).',
        tips: ['Posez une question en langage naturel', 'Fonctionne sur les fichiers indexés'],
        params: [
          { name: 'query', label: 'Question', type: 'text', required: true, placeholder: 'Quelle est ma config réseau ?' },
          { name: 'limit', label: 'Nombre de résultats', type: 'number', defaultValue: 5, min: 1, max: 20 },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── RÉSEAU
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

  // ─────────────────────────────────────────────────────── OCR
  {
    id: 'ocr', label: 'OCR & Vision', icon: '👁️', color: '#a78bfa',
    description: 'Extrayez du texte à partir d\'images grâce à l\'IA vision (llava-phi3).',
    tools: [
      {
        id: 'ocr_extract', icon: '🔬', name: 'Extraire le texte d\'une image',
        description: 'Utilise llava-phi3 (IA vision locale) pour lire et retranscrire le texte visible dans n\'importe quelle image.',
        tips: [
          'Supporte PNG, JPG, BMP, WEBP…',
          'Idéal pour captures d\'écran, photos de documents, tickets de caisse',
          'Entièrement local — aucune donnée envoyée sur Internet',
          'llava-phi3 doit être disponible dans Ollama',
        ],
        params: [
          { name: 'image_path', label: 'Chemin de l\'image', type: 'path', required: true,
            placeholder: 'Bureau\\capture.png' },
          { name: 'prompt',     label: 'Instruction OCR (optionnel)', type: 'textarea',
            placeholder: 'Extrais tout le texte présent dans cette image.' },
          { name: 'model',      label: 'Modèle vision', type: 'select', options: [
            { value: 'llava-phi3',   label: '👁️ llava-phi3 (rapide, 4GB)' },
            { value: 'llava:13b',    label: '👁️ llava:13b (précis, 8GB)' },
            { value: 'llava:7b',     label: '👁️ llava:7b (équilibré)' },
          ]},
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── EMAIL
  {
    id: 'email', label: 'Email', icon: '📧', color: '#3b82f6',
    description: 'Lisez et envoyez des emails via IMAP/SMTP. Configurez d\'abord votre boîte dans Paramètres > Email.',
    tools: [
      {
        id: 'email_list', icon: '📬', name: 'Lire la boîte mail',
        description: 'Liste les emails récents d\'un dossier IMAP (INBOX par défaut).',
        tips: ['Config requise dans Paramètres > Email', 'Supporte INBOX, Sent, Drafts, Spam…'],
        params: [
          { name: 'folder', label: 'Dossier IMAP', type: 'text', placeholder: 'INBOX (défaut)' },
          { name: 'limit',  label: 'Nombre d\'emails', type: 'number', defaultValue: 20, min: 1, max: 50 },
          { name: 'offset', label: 'Décalage (pagination)', type: 'number', defaultValue: 0, min: 0 },
        ],
      },
      {
        id: 'email_read', icon: '📖', name: 'Lire un email',
        description: 'Affiche le contenu complet d\'un email par son UID.',
        tips: ['Récupérez l\'UID via "Lire la boîte mail"'],
        params: [
          { name: 'uid',    label: 'UID de l\'email', type: 'text', required: true, placeholder: 'ex: 1234' },
          { name: 'folder', label: 'Dossier IMAP',    type: 'text', placeholder: 'INBOX (défaut)' },
        ],
      },
      {
        id: 'email_search', icon: '🔍', name: 'Chercher des emails',
        description: 'Recherche des emails par sujet, expéditeur ou mot-clé.',
        params: [
          { name: 'query',  label: 'Terme de recherche', type: 'text',   required: true, placeholder: 'facture, rapport…' },
          { name: 'folder', label: 'Dossier IMAP',       type: 'text',   placeholder: 'INBOX (défaut)' },
          { name: 'limit',  label: 'Résultats max',      type: 'number', defaultValue: 20 },
        ],
      },
      {
        id: 'email_send', icon: '📤', name: 'Envoyer un email',
        description: 'Envoie un email via SMTP. Une confirmation sera demandée avant l\'envoi.',
        tips: ['⚠️ Action irréversible', 'Vérifiez l\'adresse destinataire avant d\'envoyer', 'Config SMTP requise dans Paramètres > Email'],
        params: [
          { name: 'to',      label: 'Destinataire',    type: 'text',     required: true, placeholder: 'contact@exemple.com' },
          { name: 'subject', label: 'Objet',           type: 'text',     required: true },
          { name: 'body',    label: 'Corps du message', type: 'textarea', required: true },
          { name: 'cc',      label: 'CC (optionnel)',  type: 'text',     placeholder: 'copie@exemple.com' },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── SSH
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

  // ─────────────────────────────────────────────────────── ARCHIVES
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

  // ─────────────────────────────────────────────────────── VOIX
  {
    id: 'voix', label: 'Voix & Audio', icon: '🎙️', color: '#ec4899',
    description: 'Transcrivez des fichiers audio en texte avec Whisper (IA locale, sans internet).',
    tools: [
      {
        id: 'voice_transcribe', icon: '🎙️', name: 'Transcrire un fichier audio',
        description: 'Convertit un fichier audio (MP3, WAV, OGG, WEBM…) en texte grâce à Whisper, entièrement en local.',
        tips: [
          'Supporte MP3, WAV, OGG, WEBM, MP4, FLAC…',
          'Détection automatique de la langue si non spécifiée',
          'Le modèle "base" est chargé au premier appel (~5 secondes)',
          'Entièrement local — aucune donnée envoyée sur Internet',
        ],
        params: [
          { name: 'audio_path', label: 'Chemin du fichier audio', type: 'path', required: true,
            placeholder: 'Bureau\\enregistrement.mp3' },
          { name: 'model', label: 'Modèle Whisper', type: 'select', options: [
            { value: 'base',     label: '⚡ base (rapide, 74MB)' },
            { value: 'small',    label: '🔍 small (précis, 244MB)' },
            { value: 'medium',   label: '🎯 medium (très précis, 769MB)' },
            { value: 'large-v3', label: '🏆 large-v3 (meilleur, 1.5GB)' },
            { value: 'tiny',     label: '⚡ tiny (ultra-rapide, 39MB)' },
          ]},
          { name: 'language', label: 'Langue (optionnel)', type: 'text',
            placeholder: 'fr, en, es… (détection auto si vide)' },
        ],
      },
      {
        id: 'audio_info', icon: 'ℹ️', name: 'Infos audio',
        description: 'Durée, débit, fréquence d\'échantillonnage et nombre de canaux d\'un fichier audio.',
        params: [
          { name: 'path', label: 'Fichier audio', type: 'path', required: true, placeholder: 'C:\\...\\son.mp3' },
        ],
      },
      {
        id: 'audio_extract', icon: '🎬', name: 'Extraire l\'audio d\'une vidéo',
        description: 'Récupère la piste audio d\'une vidéo et l\'enregistre en MP3, WAV, AAC…',
        tips: ['Idéal pour extraire la musique ou la voix d\'une vidéo', 'WAV/FLAC = sans perte, MP3/AAC = compressé'],
        params: [
          { name: 'path',    label: 'Vidéo source', type: 'path', required: true },
          { name: 'format',  label: 'Format audio', type: 'select', options: [
            { value: 'mp3',  label: '🎵 MP3' }, { value: 'wav', label: '💿 WAV (sans perte)' },
            { value: 'aac',  label: '📱 AAC' }, { value: 'flac', label: '🏆 FLAC (sans perte)' },
            { value: 'ogg',  label: '🔊 OGG' }, { value: 'opus', label: '⚡ Opus' },
          ]},
          { name: 'bitrate', label: 'Débit', type: 'text', placeholder: '192k (défaut)' },
          { name: 'output_path', label: 'Fichier de sortie', type: 'path', placeholder: 'Même nom (défaut)' },
        ],
      },
      {
        id: 'audio_convert', icon: '🔄', name: 'Convertir un audio',
        description: 'Convertit un fichier audio d\'un format à un autre (MP3, WAV, OGG, FLAC, AAC, Opus).',
        tips: ['Change aussi la fréquence d\'échantillonnage si besoin', 'WAV/FLAC ignorent le débit (sans perte)'],
        params: [
          { name: 'path',   label: 'Fichier source', type: 'path', required: true },
          { name: 'format', label: 'Format cible', type: 'select', options: [
            { value: 'mp3',  label: '🎵 MP3' }, { value: 'wav', label: '💿 WAV' },
            { value: 'ogg',  label: '🔊 OGG' }, { value: 'flac', label: '🏆 FLAC' },
            { value: 'aac',  label: '📱 AAC' }, { value: 'opus', label: '⚡ Opus' },
          ]},
          { name: 'bitrate',     label: 'Débit', type: 'text', placeholder: '192k' },
          { name: 'sample_rate', label: 'Fréquence (Hz)', type: 'number', placeholder: '44100' },
          { name: 'output_path', label: 'Fichier de sortie', type: 'path' },
        ],
      },
      {
        id: 'audio_trim', icon: '✂️', name: 'Découper un audio',
        description: 'Extrait un segment d\'un fichier audio (début/fin ou début + durée, en secondes).',
        tips: ['Renseignez "fin" OU "durée"', 'Ex : début 30, durée 15 → extrait de 30s à 45s'],
        params: [
          { name: 'path',     label: 'Fichier source', type: 'path', required: true },
          { name: 'start',    label: 'Début (s)', type: 'number', defaultValue: 0 },
          { name: 'end',      label: 'Fin (s)', type: 'number', placeholder: 'ou durée' },
          { name: 'duration', label: 'Durée (s)', type: 'number', placeholder: 'ou fin' },
          { name: 'output_path', label: 'Fichier de sortie', type: 'path' },
        ],
      },
      {
        id: 'audio_merge', icon: '🔗', name: 'Fusionner des audios',
        description: 'Met bout à bout plusieurs fichiers audio (même de formats différents).',
        tips: ['Séparez les chemins par des virgules', 'L\'ordre de la liste = l\'ordre de lecture'],
        params: [
          { name: 'paths',  label: 'Fichiers (séparés par virgules)', type: 'tags', required: true, placeholder: 'C:\\...\\1.mp3, C:\\...\\2.mp3' },
          { name: 'format', label: 'Format de sortie', type: 'select', options: [
            { value: 'mp3', label: '🎵 MP3' }, { value: 'wav', label: '💿 WAV' },
            { value: 'flac', label: '🏆 FLAC' }, { value: 'aac', label: '📱 AAC' },
          ]},
          { name: 'output_path', label: 'Fichier de sortie', type: 'path' },
        ],
      },
      {
        id: 'audio_volume', icon: '🔊', name: 'Volume / Normaliser',
        description: 'Augmente ou baisse le volume (facteur ou gain dB) ou normalise le niveau sonore.',
        tips: ['Facteur 1.5 = +50% ; gain +6 dB = ~2× plus fort', 'Cochez "normaliser" pour un niveau homogène (EBU R128)'],
        params: [
          { name: 'factor',    label: 'Facteur (ex 1.5)', type: 'number', placeholder: '1.5' },
          { name: 'gain_db',   label: 'Ou gain (dB, ex 6 / -6)', type: 'number', placeholder: '6' },
          { name: 'normalize', label: 'Normaliser le niveau', type: 'checkbox' },
          { name: 'path',      label: 'Fichier source', type: 'path', required: true },
          { name: 'output_path', label: 'Fichier de sortie', type: 'path' },
        ],
      },
      {
        id: 'text_to_speech', icon: '🗣️', name: 'Synthèse vocale (texte → MP3)',
        description: 'Transforme un texte en fichier audio MP3 avec une voix neurale réaliste (français ou anglais).',
        tips: ['Plusieurs voix disponibles', 'Vitesse : +10% (plus rapide), -10% (plus lent)', 'Nécessite une connexion internet (voix Microsoft)'],
        params: [
          { name: 'text',  label: 'Texte à lire', type: 'textarea', required: true, placeholder: 'Bonjour, je suis Marvin…' },
          { name: 'voice', label: 'Voix', type: 'select', options: [
            { value: 'denise',   label: '👩 Denise (FR, naturelle)' },
            { value: 'henri',    label: '👨 Henri (FR, pro)' },
            { value: 'eloise',   label: '👩 Eloïse (FR, douce)' },
            { value: 'remy',     label: '👨 Rémy (FR, multilingue)' },
            { value: 'vivienne', label: '👩 Vivienne (FR, multilingue)' },
            { value: 'thierry',  label: '👨 Thierry (Québec)' },
            { value: 'sylvie',   label: '👩 Sylvie (Québec)' },
            { value: 'en-femme', label: '🇬🇧 Aria (anglais, F)' },
            { value: 'en-homme', label: '🇬🇧 Guy (anglais, H)' },
          ]},
          { name: 'rate',  label: 'Vitesse', type: 'text', placeholder: '+0% (ex: +10%, -10%)' },
          { name: 'pitch', label: 'Hauteur', type: 'text', placeholder: '+0Hz (ex: +5Hz)' },
          { name: 'output_path', label: 'Fichier .mp3 de sortie', type: 'path', placeholder: 'Bureau (défaut)' },
        ],
      },
    ],
  },

  // ─────────────────────────────────────────────────────── UTILITAIRES
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

  // ─────────────────────────────────────────────────────── TRAITEMENT DE DONNÉES
  {
    id: 'donnees', label: 'Données & Docs', icon: '🔧', color: '#f59e0b',
    description: 'Hash, Base64, JSON, CSV, PDF, Excel, ZIP, images, QR code, couleur, URL, SQLite, Git et traitement de données.',
    tools: [
      {
        id: 'markdown_convert', icon: '📄', name: 'Convertir Markdown',
        description: 'Convertit du Markdown en HTML propre ou en texte brut sans markup.',
        tips: ['Mode "stats" retourne les comptages de titres, liens et blocs de code', 'Supporte : titres, listes, liens, images, code, bold, italic'],
        params: [
          { name: 'text', label: 'Contenu Markdown', type: 'textarea', required: true, placeholder: '# Titre\n\n**Texte** en gras...' },
          { name: 'to', label: 'Format cible', type: 'select', options: [
            { value: 'html',  label: '🌐 HTML' },
            { value: 'plain', label: '📝 Texte brut' },
            { value: 'stats', label: '📊 Statistiques' },
          ]},
        ],
      },
      {
        id: 'regex_tool', icon: '🔤', name: 'Regex — Expressions régulières',
        description: 'Applique une regex à un texte : recherche, extraction, remplacement ou test de correspondance.',
        tips: [
          'findall : retourne toutes les correspondances',
          'replace : remplace toutes les occurrences',
          'Flags : I = insensible à la casse, M = multiline, S = dot-all',
        ],
        params: [
          { name: 'pattern', label: 'Expression régulière', type: 'text', required: true, placeholder: '\\b\\w{5,}\\b' },
          { name: 'text',    label: 'Texte cible',          type: 'textarea', required: true },
          { name: 'action',  label: 'Action', type: 'select', options: [
            { value: 'findall', label: '🔍 Trouver toutes les occurrences' },
            { value: 'test',    label: '✅ Tester (true/false)' },
            { value: 'replace', label: '✏️ Remplacer' },
            { value: 'match',   label: '🎯 Match en début de chaîne' },
            { value: 'split',   label: '✂️ Découper' },
          ]},
          { name: 'replace', label: 'Remplacement (pour "replace")', type: 'text', placeholder: '' },
          { name: 'flags',   label: 'Flags (ex: IM)', type: 'text', placeholder: 'I, M, S' },
        ],
      },
      {
        id: 'text_stats', icon: '📝', name: 'Statistiques texte',
        description: 'Analyse un texte : mots, caractères, phrases, temps de lecture et mots les plus fréquents.',
        tips: ['Collez n\'importe quel texte pour l\'analyser', 'Le temps de lecture est estimé à 250 mots/minute'],
        params: [
          { name: 'text',      label: 'Texte à analyser', type: 'textarea', required: true, placeholder: 'Collez votre texte ici…' },
          { name: 'top_words', label: 'Mots fréquents à afficher', type: 'number', defaultValue: 10 },
        ],
      },
      {
        id: 'ip_info', icon: '🌍', name: 'Infos IP & Géoloc',
        description: 'Retourne la géolocalisation et les infos réseau d\'une adresse IP publique (ip-api.com).',
        tips: ['Laissez vide pour analyser votre propre IP publique', 'Retourne pays, ville, ISP, ASN, coordonnées GPS'],
        params: [
          { name: 'ip', label: 'Adresse IP (optionnel)', type: 'text', placeholder: 'Ex: 8.8.8.8 — vide = votre IP' },
        ],
      },
      {
        id: 'csv_analyze', icon: '📊', name: 'Analyser un CSV',
        description: 'Charge un fichier CSV et calcule des statistiques, aperçu ou valeurs uniques par colonne.',
        tips: [
          'Action "summary" : aperçu global de toutes les colonnes',
          'Action "stats" + column : moyenne, min, max, écart-type d\'une colonne numérique',
          'Action "unique" + column : liste les valeurs distinctes',
        ],
        params: [
          { name: 'path',      label: 'Chemin du fichier CSV', type: 'path', required: true, placeholder: 'Bureau\\data.csv' },
          { name: 'action',    label: 'Action', type: 'select', options: [
            { value: 'summary', label: '📋 Résumé global' },
            { value: 'head',    label: '👁️ Aperçu (5 premières lignes)' },
            { value: 'stats',   label: '📊 Statistiques (colonne numérique)' },
            { value: 'unique',  label: '🔍 Valeurs uniques (colonne)' },
          ]},
          { name: 'column',    label: 'Colonne (pour stats/unique)', type: 'text', placeholder: 'ex: price' },
          { name: 'max_rows',  label: 'Lignes max à analyser',       type: 'number', defaultValue: 100 },
          { name: 'delimiter', label: 'Séparateur',                  type: 'text', placeholder: ', (défaut)' },
        ],
      },
      {
        id: 'hash_compute', icon: '🔏', name: 'Calculer un hash',
        description: 'Calcule le hash cryptographique (MD5/SHA256/SHA512) d\'un texte ou d\'un fichier.',
        tips: ['SHA256 recommandé pour l\'intégrité', 'Fournissez soit du texte, soit un chemin de fichier'],
        params: [
          { name: 'algorithm', label: 'Algorithme', type: 'select', options: [
            { value: 'sha256', label: '🔒 SHA-256' },
            { value: 'sha512', label: '🔒 SHA-512' },
            { value: 'md5',   label: '🔑 MD5' },
            { value: 'sha1',  label: '🔑 SHA-1' },
          ]},
          { name: 'text',      label: 'Texte',           type: 'textarea', placeholder: 'Texte à hacher...' },
          { name: 'file_path', label: 'Ou chemin fichier', type: 'path',   placeholder: 'Bureau\\fichier.zip' },
        ],
      },
      {
        id: 'base64_tool', icon: '🔢', name: 'Base64 Encode/Decode',
        description: 'Encode du texte en Base64 ou décode une chaîne Base64.',
        tips: ['Encode: texte → Base64', 'Decode: Base64 → texte', 'URL-safe remplace + par - et / par _'],
        params: [
          { name: 'action',   label: 'Action', type: 'select', options: [
            { value: 'encode', label: '⬆️ Encoder' },
            { value: 'decode', label: '⬇️ Décoder' },
          ]},
          { name: 'data',     label: 'Données', type: 'textarea', required: true, placeholder: 'Texte ou chaîne Base64...' },
          { name: 'url_safe', label: 'Mode URL-safe', type: 'checkbox', defaultValue: false },
        ],
      },
      {
        id: 'text_extract', icon: '🔎', name: 'Extraire du texte',
        description: 'Extrait automatiquement les emails, URLs et numéros de téléphone d\'un texte.',
        tips: ['Idéal pour analyser des emails ou documents', 'Extrait les 3 types en même temps avec "all"'],
        params: [
          { name: 'text', label: 'Texte source', type: 'textarea', required: true, placeholder: 'Collez votre texte ici...' },
          { name: 'extract', label: 'Type à extraire', type: 'select', options: [
            { value: 'all',    label: '🔍 Tout (emails + URLs + téléphones)' },
            { value: 'emails', label: '📧 Emails uniquement' },
            { value: 'urls',   label: '🔗 URLs uniquement' },
            { value: 'phones', label: '📞 Téléphones uniquement' },
          ]},
        ],
      },
      {
        id: 'diff_text', icon: '↔️', name: 'Comparer deux textes',
        description: 'Affiche les différences ligne par ligne entre deux textes (unified diff ou ratio de similarité).',
        tips: ['Mode "ratio" retourne un % de similarité', 'Mode "ndiff" montre chaque caractère modifié'],
        params: [
          { name: 'text_a', label: 'Texte A (original)', type: 'textarea', required: true, placeholder: 'Premier texte...' },
          { name: 'text_b', label: 'Texte B (modifié)',  type: 'textarea', required: true, placeholder: 'Second texte...' },
          { name: 'mode', label: 'Mode', type: 'select', options: [
            { value: 'unified', label: '📄 Unified diff' },
            { value: 'ratio',   label: '📊 Ratio de similarité' },
            { value: 'ndiff',   label: '🔍 NDiff détaillé' },
          ]},
        ],
      },
      {
        id: 'json_tool', icon: '📋', name: 'Outil JSON',
        description: 'Formate, minifie, valide ou interroge un JSON avec une notation pointée.',
        tips: ['Action "query" + path "user.address.city" pour accéder à une valeur', '"format" pour indenter proprement'],
        params: [
          { name: 'data', label: 'JSON', type: 'textarea', required: true, placeholder: '{"key": "value"}' },
          { name: 'action', label: 'Action', type: 'select', options: [
            { value: 'format',   label: '💅 Formater (indenter)' },
            { value: 'validate', label: '✅ Valider' },
            { value: 'minify',   label: '📦 Minifier' },
            { value: 'query',    label: '🔍 Interroger (dot-path)' },
          ]},
          { name: 'path', label: 'Chemin (pour query)', type: 'text', placeholder: 'user.address.city' },
        ],
      },
      {
        id: 'qr_generate', icon: '📱', name: 'Générer un QR Code',
        description: 'Génère un QR code PNG depuis un texte ou une URL.',
        tips: ['Le fichier PNG est sauvegardé sur le Bureau par défaut', 'Fonctionne avec URLs, textes, contacts vCard...'],
        params: [
          { name: 'data',        label: 'Contenu du QR Code', type: 'text', required: true, placeholder: 'https://example.com' },
          { name: 'output_path', label: 'Chemin de sortie',   type: 'path', placeholder: 'Bureau (défaut)' },
          { name: 'size',        label: 'Taille des modules', type: 'number', defaultValue: 10, min: 5, max: 30 },
        ],
      },
      {
        id: 'image_info', icon: '🖼️', name: 'Infos image',
        description: 'Retourne les métadonnées d\'une image : dimensions, format, taille, données EXIF.',
        tips: ['Fonctionne avec JPEG, PNG, WEBP, BMP, GIF...', 'Les données EXIF incluent date de prise, appareil, GPS'],
        params: [
          { name: 'path', label: 'Chemin de l\'image', type: 'path', required: true, placeholder: 'Bureau\\photo.jpg' },
        ],
      },
      {
        id: 'image_resize', icon: '🖼️', name: 'Redimensionner image',
        description: 'Redimensionne ou convertit une image en JPEG, PNG ou WEBP via Pillow.',
        tips: ['Laissez l\'un vide pour conserver le ratio automatiquement', 'Convertit aussi les formats (ex: PNG → WEBP)'],
        params: [
          { name: 'path',        label: 'Image source',   type: 'path',   required: true },
          { name: 'width',       label: 'Largeur (px)',   type: 'number', placeholder: 'ex: 1920' },
          { name: 'height',      label: 'Hauteur (px)',   type: 'number', placeholder: 'ex: 1080' },
          { name: 'output_path', label: 'Fichier sortie', type: 'path',   placeholder: 'Même dossier _resized (défaut)' },
          { name: 'format',      label: 'Format de sortie', type: 'select', options: [
            { value: '',      label: '🔄 Même format' },
            { value: 'JPEG',  label: '📷 JPEG' },
            { value: 'PNG',   label: '🖼️ PNG' },
            { value: 'WEBP',  label: '⚡ WEBP' },
          ]},
          { name: 'quality', label: 'Qualité (JPEG/WEBP)', type: 'number', defaultValue: 85, min: 1, max: 95 },
        ],
      },
      {
        id: 'image_crop', icon: '✂️', name: 'Rogner une image',
        description: 'Recadre une image selon un ratio centré (1:1, 16:9…) ou une boîte précise en pixels.',
        tips: ['Le plus simple : indiquez un ratio comme 1:1 (carré) ou 16:9', 'Sinon précisez gauche/haut/droite/bas en pixels'],
        params: [
          { name: 'path',        label: 'Image source', type: 'path', required: true },
          { name: 'aspect',      label: 'Ratio centré (optionnel)', type: 'select', options: [
            { value: '',     label: '— Boîte manuelle —' },
            { value: '1:1',  label: '⬛ Carré 1:1' },
            { value: '16:9', label: '🖥️ 16:9' },
            { value: '4:3',  label: '🖼️ 4:3' },
            { value: '3:2',  label: '📷 3:2' },
            { value: '9:16', label: '📱 9:16 (vertical)' },
          ]},
          { name: 'left',   label: 'Gauche (px)', type: 'number', placeholder: 'si boîte manuelle' },
          { name: 'top',    label: 'Haut (px)',   type: 'number' },
          { name: 'right',  label: 'Droite (px)', type: 'number' },
          { name: 'bottom', label: 'Bas (px)',    type: 'number' },
          { name: 'output_path', label: 'Fichier sortie', type: 'path', placeholder: '_crop (défaut)' },
        ],
      },
      {
        id: 'image_rotate', icon: '🔄', name: 'Pivoter / retourner image',
        description: 'Fait pivoter une image d\'un angle (sens horaire) et/ou la retourne en miroir.',
        tips: ['90, 180 ou 270° pour les rotations courantes', 'Le miroir horizontal inverse gauche/droite'],
        params: [
          { name: 'path',  label: 'Image source', type: 'path', required: true },
          { name: 'angle', label: 'Angle horaire (°)', type: 'number', placeholder: 'ex: 90' },
          { name: 'flip',  label: 'Miroir', type: 'select', options: [
            { value: '',           label: '— Aucun —' },
            { value: 'horizontal', label: '↔️ Horizontal' },
            { value: 'vertical',   label: '↕️ Vertical' },
          ]},
          { name: 'output_path', label: 'Fichier sortie', type: 'path', placeholder: '_rot (défaut)' },
        ],
      },
      {
        id: 'image_compress', icon: '🗜️', name: 'Compresser une image',
        description: 'Réduit le poids d\'une image vers une taille cible (Ko) ou une qualité fixe (JPEG/WEBP).',
        tips: ['Poids cible : Marvin ajuste la qualité automatiquement', 'Idéal pour alléger des photos avant envoi'],
        params: [
          { name: 'path',      label: 'Image source', type: 'path', required: true },
          { name: 'target_kb', label: 'Poids cible (Ko)', type: 'number', placeholder: 'ex: 200' },
          { name: 'quality',   label: 'Ou qualité fixe (1-100)', type: 'number', placeholder: 'défaut 80' },
          { name: 'format',    label: 'Format', type: 'select', options: [
            { value: 'JPEG', label: '📷 JPEG' },
            { value: 'WEBP', label: '⚡ WEBP' },
          ]},
          { name: 'output_path', label: 'Fichier sortie', type: 'path', placeholder: '_compresse (défaut)' },
        ],
      },
      {
        id: 'image_batch', icon: '🗂️', name: 'Traiter des images en lot',
        description: 'Applique une même opération à toutes les images d\'un dossier : convertir, redimensionner, compresser, pivoter ou filigraner.',
        tips: ['Traite tout un dossier d\'un coup', 'Le résultat va dans un dossier "_traite" (l\'original n\'est pas modifié)'],
        params: [
          { name: 'directory', label: 'Dossier d\'images', type: 'path', required: true },
          { name: 'operation', label: 'Opération', type: 'select', options: [
            { value: 'convert',   label: '🔄 Convertir le format' },
            { value: 'resize',    label: '📐 Redimensionner' },
            { value: 'compress',  label: '🗜️ Compresser' },
            { value: 'rotate',    label: '🔁 Pivoter / retourner' },
            { value: 'watermark', label: '💧 Filigrane texte' },
          ]},
          { name: 'format',    label: 'Format (convert : JPEG/PNG/WEBP)', type: 'text', placeholder: 'JPEG' },
          { name: 'width',     label: 'Largeur (resize)', type: 'number' },
          { name: 'height',    label: 'Hauteur (resize)', type: 'number' },
          { name: 'target_kb', label: 'Poids cible Ko (compress)', type: 'number' },
          { name: 'angle',     label: 'Angle (rotate)', type: 'number' },
          { name: 'flip',      label: 'Miroir (rotate)', type: 'select', options: [
            { value: '', label: '— Aucun —' }, { value: 'horizontal', label: '↔️ Horizontal' }, { value: 'vertical', label: '↕️ Vertical' },
          ]},
          { name: 'text',      label: 'Texte (watermark)', type: 'text', placeholder: '@MonNom' },
          { name: 'recursive', label: 'Inclure les sous-dossiers', type: 'checkbox' },
          { name: 'output_dir', label: 'Dossier de sortie', type: 'path', placeholder: '_traite (défaut)' },
        ],
      },
      {
        id: 'pdf_read', icon: '📕', name: 'Lire un PDF',
        description: 'Extrait le texte d\'un fichier PDF page par page.',
        tips: ['Spécifiez "1-3" pour lire les pages 1 à 3', 'Laissez vide pour tout lire', 'max_chars limite la taille de la réponse'],
        params: [
          { name: 'path',      label: 'Chemin du PDF',  type: 'path',   required: true, placeholder: 'Documents\\document.pdf' },
          { name: 'pages',     label: 'Pages (ex: 1-3 ou 2)', type: 'text', placeholder: 'Vide = tout' },
          { name: 'max_chars', label: 'Max caractères', type: 'number', defaultValue: 4000 },
        ],
      },
      {
        id: 'pdf_info', icon: '📕', name: 'Infos PDF',
        description: 'Retourne les métadonnées d\'un PDF : titre, auteur, pages, taille, chiffrement.',
        tips: ['Ne lit pas le contenu, juste les métadonnées', 'Rapide même pour les gros PDFs'],
        params: [
          { name: 'path', label: 'Chemin du PDF', type: 'path', required: true, placeholder: 'Documents\\document.pdf' },
        ],
      },
      {
        id: 'pdf_merge', icon: '📑', name: 'Fusionner des PDF',
        description: 'Combine plusieurs fichiers PDF en un seul, dans l\'ordre indiqué.',
        tips: ['Ajoutez au moins 2 PDF, un chemin par ligne', 'L\'ordre de la liste = l\'ordre des pages'],
        params: [
          { name: 'sources',     label: 'PDF à fusionner (séparés par des virgules)', type: 'tags', required: true, placeholder: 'C:\\...\\a.pdf, C:\\...\\b.pdf' },
          { name: 'output_path', label: 'PDF de sortie', type: 'path', placeholder: 'Bureau/fusion.pdf (défaut)' },
        ],
      },
      {
        id: 'pdf_split', icon: '✂️', name: 'Découper un PDF',
        description: 'Sépare un PDF : une page par fichier, ou extrait des pages précises dans un seul fichier.',
        tips: ['Pages "1-3,5" extrait ces pages dans un fichier', 'Cochez "une page par fichier" pour tout éclater'],
        params: [
          { name: 'path',       label: 'PDF source', type: 'path', required: true },
          { name: 'pages',      label: 'Pages à extraire (ex: 1-3,5)', type: 'text', placeholder: 'Vide = toutes' },
          { name: 'per_page',   label: 'Une page par fichier', type: 'checkbox' },
          { name: 'output_dir', label: 'Dossier de sortie', type: 'path', placeholder: 'Dossier du PDF (défaut)' },
        ],
      },
      {
        id: 'pdf_rotate', icon: '🔄', name: 'Pivoter un PDF',
        description: 'Fait pivoter tout ou partie des pages d\'un PDF (90, 180 ou 270°).',
        tips: ['Laissez "pages" vide pour pivoter tout le document', 'Utile pour redresser des scans'],
        params: [
          { name: 'path',  label: 'PDF source', type: 'path', required: true },
          { name: 'angle', label: 'Angle', type: 'select', options: [
            { value: '90',  label: '↻ 90°' },
            { value: '180', label: '⟲ 180°' },
            { value: '270', label: '↺ 270°' },
          ]},
          { name: 'pages',       label: 'Pages (ex: 1,3-4)', type: 'text', placeholder: 'Vide = toutes' },
          { name: 'output_path', label: 'PDF de sortie', type: 'path', placeholder: '_pivote (défaut)' },
        ],
      },
      {
        id: 'images_to_pdf', icon: '🖼️', name: 'Images → PDF',
        description: 'Assemble plusieurs images (JPG, PNG…) en un seul PDF, une image par page.',
        tips: ['Parfait pour regrouper des photos ou scans', 'L\'ordre de la liste = l\'ordre des pages'],
        params: [
          { name: 'sources',     label: 'Images (séparées par des virgules)', type: 'tags', required: true, placeholder: 'C:\\...\\1.jpg, C:\\...\\2.jpg' },
          { name: 'output_path', label: 'PDF de sortie', type: 'path', placeholder: 'Bureau/images.pdf (défaut)' },
          { name: 'dpi',         label: 'Résolution (DPI)', type: 'number', defaultValue: 150 },
        ],
      },
      {
        id: 'pdf_watermark', icon: '💧', name: 'Filigrane sur PDF',
        description: 'Appose un filigrane texte en diagonale sur chaque page (ex : CONFIDENTIEL, BROUILLON).',
        tips: ['Parfait pour marquer un document confidentiel', 'Opacité basse = filigrane discret'],
        params: [
          { name: 'path',      label: 'PDF source', type: 'path', required: true },
          { name: 'text',      label: 'Texte du filigrane', type: 'text', required: true, placeholder: 'CONFIDENTIEL' },
          { name: 'opacity',   label: 'Opacité (0-1)', type: 'number', placeholder: '0.12' },
          { name: 'font_size', label: 'Taille police', type: 'number', placeholder: 'auto' },
          { name: 'output_path', label: 'PDF de sortie', type: 'path', placeholder: '_filigrane (défaut)' },
        ],
      },
      {
        id: 'pdf_protect', icon: '🔒', name: 'Protéger un PDF',
        description: 'Chiffre un PDF avec un mot de passe (AES-256) — il faudra le mot de passe pour l\'ouvrir.',
        tips: ['Notez bien le mot de passe : sans lui, le PDF est illisible', 'Le mot de passe propriétaire restreint l\'impression/copie'],
        params: [
          { name: 'path',           label: 'PDF source', type: 'path', required: true },
          { name: 'password',       label: 'Mot de passe d\'ouverture', type: 'text', required: true },
          { name: 'owner_password', label: 'Mot de passe propriétaire (optionnel)', type: 'text' },
          { name: 'output_path',    label: 'PDF de sortie', type: 'path', placeholder: '_protege (défaut)' },
        ],
      },
      {
        id: 'pdf_extract_images', icon: '🖼️', name: 'Extraire images d\'un PDF',
        description: 'Récupère toutes les images intégrées d\'un PDF et les enregistre dans un dossier.',
        tips: ['Utile pour récupérer des photos d\'un document', 'Les images sont nommées par page'],
        params: [
          { name: 'path',       label: 'PDF source', type: 'path', required: true },
          { name: 'output_dir', label: 'Dossier de sortie', type: 'path', placeholder: '<pdf>_images (défaut)' },
        ],
      },
      {
        id: 'pdf_to_images', icon: '🖨️', name: 'PDF → images PNG',
        description: 'Convertit chaque page d\'un PDF en image PNG (rendu haute qualité).',
        tips: ['Laissez "pages" vide pour tout convertir', 'Augmentez le DPI pour plus de netteté (150 = standard, 300 = impression)'],
        params: [
          { name: 'path',       label: 'PDF source', type: 'path', required: true },
          { name: 'pages',      label: 'Pages (ex: 1-3,5)', type: 'text', placeholder: 'Vide = toutes' },
          { name: 'dpi',        label: 'Résolution (DPI)', type: 'number', defaultValue: 150 },
          { name: 'output_dir', label: 'Dossier de sortie', type: 'path', placeholder: '<pdf>_pages (défaut)' },
        ],
      },
      {
        id: 'pdf_ocr', icon: '🔎', name: 'OCR d\'un PDF (même scanné)',
        description: 'Extrait le texte d\'un PDF. Utilise le texte intégré si présent, sinon reconnaît le texte des pages scannées par IA (vision).',
        tips: ['Fonctionne sur les PDF scannés (images)', 'L\'OCR par IA utilise le GPU — limitez le nombre de pages', 'Indiquez un fichier .txt de sortie pour sauvegarder'],
        params: [
          { name: 'path',        label: 'PDF source', type: 'path', required: true },
          { name: 'pages',       label: 'Pages (ex: 1-3)', type: 'text', placeholder: 'Vide = toutes' },
          { name: 'max_pages',   label: 'Pages max à traiter', type: 'number', defaultValue: 15 },
          { name: 'output_path', label: 'Fichier .txt de sortie', type: 'path', placeholder: 'Optionnel' },
        ],
      },
      {
        id: 'pdf_form_fields', icon: '📋', name: 'Champs d\'un formulaire PDF',
        description: 'Liste les champs remplissables (AcroForm) d\'un formulaire PDF.',
        tips: ['À lancer avant "Remplir un formulaire" pour connaître les noms des champs'],
        params: [
          { name: 'path', label: 'PDF formulaire', type: 'path', required: true },
        ],
      },
      {
        id: 'pdf_fill_form', icon: '✍️', name: 'Remplir un formulaire PDF',
        description: 'Remplit les champs d\'un formulaire PDF à partir d\'un objet JSON {champ: valeur}.',
        tips: ['Utilisez "Champs d\'un formulaire" pour obtenir les noms exacts', 'Exemple : {"nom":"Dupont","date":"05/06/2026"}'],
        params: [
          { name: 'path',        label: 'PDF formulaire', type: 'path', required: true },
          { name: 'data',        label: 'Données (JSON {champ: valeur})', type: 'textarea', required: true, placeholder: '{"nom": "Dupont", "ville": "Paris"}' },
          { name: 'output_path', label: 'PDF de sortie', type: 'path', placeholder: '_rempli (défaut)' },
        ],
      },
      {
        id: 'pptx_create', icon: '📊', name: 'Créer une présentation (.pptx)',
        description: 'Génère un diaporama PowerPoint : diapo de titre + diapos à puces.',
        tips: ['Diapos au format JSON : [{"title":"...","bullets":["...","..."]}]', 'Idéal pour un support de réunion rapide'],
        params: [
          { name: 'title',       label: 'Titre (diapo de couverture)', type: 'text', placeholder: 'Rapport Q2 2026' },
          { name: 'subtitle',    label: 'Sous-titre', type: 'text' },
          { name: 'slides',      label: 'Diapos (JSON)', type: 'textarea', placeholder: '[{"title":"Résultats","bullets":["CA +12%","3 clients"]}]' },
          { name: 'output_path', label: 'Fichier .pptx de sortie', type: 'path', placeholder: 'Bureau (défaut)' },
        ],
      },
      {
        id: 'pptx_read', icon: '📑', name: 'Lire une présentation (.pptx)',
        description: 'Extrait le texte de toutes les diapositives d\'un fichier PowerPoint.',
        params: [
          { name: 'path', label: 'Fichier .pptx', type: 'path', required: true },
        ],
      },
      {
        id: 'csv_to_xlsx', icon: '📈', name: 'CSV → Excel',
        description: 'Convertit un fichier CSV en classeur Excel (.xlsx) avec en-têtes en gras.',
        tips: ['Le séparateur est détecté automatiquement (, ; tab |)'],
        params: [
          { name: 'path',        label: 'Fichier CSV', type: 'path', required: true },
          { name: 'delimiter',   label: 'Séparateur (auto si vide)', type: 'text', placeholder: ', ; tab |' },
          { name: 'output_path', label: 'Fichier .xlsx de sortie', type: 'path' },
        ],
      },
      {
        id: 'xlsx_to_csv', icon: '📉', name: 'Excel → CSV',
        description: 'Convertit une feuille d\'un classeur Excel (.xlsx) en fichier CSV.',
        params: [
          { name: 'path',        label: 'Fichier Excel', type: 'path', required: true },
          { name: 'sheet',       label: 'Feuille (défaut : active)', type: 'text' },
          { name: 'delimiter',   label: 'Séparateur de sortie', type: 'text', placeholder: ',' },
          { name: 'output_path', label: 'Fichier .csv de sortie', type: 'path' },
        ],
      },
      {
        id: 'docx_to_text', icon: '📃', name: 'Word → texte / Markdown',
        description: 'Extrait le texte d\'un document Word (.docx) en texte brut ou en Markdown (titres, listes, tableaux).',
        params: [
          { name: 'path',        label: 'Fichier Word (.docx)', type: 'path', required: true },
          { name: 'format',      label: 'Format', type: 'select', options: [
            { value: 'markdown', label: '📝 Markdown' },
            { value: 'text',     label: '📄 Texte brut' },
          ]},
          { name: 'output_path', label: 'Fichier texte de sortie', type: 'path', placeholder: 'Optionnel' },
        ],
      },
      {
        id: 'text_summarize', icon: '🧠', name: 'Résumer (IA)',
        description: 'Résume un texte collé OU un document (txt/pdf/docx) grâce à l\'IA locale. Plusieurs styles disponibles.',
        tips: ['Collez du texte OU indiquez un chemin de document', 'Utilise le GPU/Ollama', 'Style "action" = extrait les tâches et décisions'],
        params: [
          { name: 'text',     label: 'Texte à résumer', type: 'textarea', placeholder: 'Collez le texte ici… (ou utilisez un chemin ci-dessous)' },
          { name: 'path',     label: 'Ou document (txt/pdf/docx)', type: 'path', placeholder: 'C:\\...\\rapport.pdf' },
          { name: 'style',    label: 'Style', type: 'select', options: [
            { value: 'bref',     label: '⚡ Bref (3-4 phrases)' },
            { value: 'détaillé', label: '📖 Détaillé' },
            { value: 'puces',    label: '• En puces' },
            { value: 'action',  label: '✅ Points d\'action' },
          ]},
          { name: 'language', label: 'Langue', type: 'text', placeholder: 'français' },
        ],
      },
      {
        id: 'pdf_compress', icon: '🗜️', name: 'Compresser un PDF',
        description: 'Réduit le poids d\'un fichier PDF (recompression des flux). Ne produit jamais un fichier plus gros.',
        tips: ['Très efficace sur les PDF non optimisés', 'Si le PDF est déjà optimal, l\'original est conservé'],
        params: [
          { name: 'path',        label: 'PDF source', type: 'path', required: true },
          { name: 'output_path', label: 'PDF de sortie', type: 'path', placeholder: '_compresse (défaut)' },
        ],
      },
      {
        id: 'pdf_add_page_numbers', icon: '#️⃣', name: 'Numéroter un PDF',
        description: 'Ajoute une numérotation de pages (ou un texte de pied/en-tête) sur chaque page d\'un PDF.',
        tips: ['Modèle : {n} = numéro, {total} = nombre total', 'Ex : "Page {n} / {total}"'],
        params: [
          { name: 'path',         label: 'PDF source', type: 'path', required: true },
          { name: 'format',       label: 'Modèle', type: 'text', placeholder: 'Page {n} / {total}' },
          { name: 'position',     label: 'Position', type: 'select', options: [
            { value: 'bottom-center', label: '⬇️ Bas centre' },
            { value: 'bottom-right',  label: '↘️ Bas droite' },
            { value: 'bottom-left',   label: '↙️ Bas gauche' },
            { value: 'top-center',    label: '⬆️ Haut centre' },
            { value: 'top-right',     label: '↗️ Haut droite' },
            { value: 'top-left',      label: '↖️ Haut gauche' },
          ]},
          { name: 'start_number', label: 'Numéro de départ', type: 'number', defaultValue: 1 },
          { name: 'font_size',    label: 'Taille police', type: 'number', defaultValue: 9 },
          { name: 'output_path',  label: 'PDF de sortie', type: 'path', placeholder: '_numerote (défaut)' },
        ],
      },
      {
        id: 'csv_to_chart', icon: '📊', name: 'CSV → Graphique',
        description: 'Génère un graphique (PNG) directement à partir d\'un fichier CSV. Colonnes numériques détectées automatiquement.',
        tips: ['Histogramme, courbe ou camembert', 'La 1ère colonne sert d\'étiquettes par défaut'],
        params: [
          { name: 'path',        label: 'Fichier CSV', type: 'path', required: true },
          { name: 'chart_type',  label: 'Type', type: 'select', options: [
            { value: 'bar',  label: '📊 Histogramme' },
            { value: 'line', label: '📈 Courbe' },
            { value: 'pie',  label: '🥧 Camembert' },
          ]},
          { name: 'title',         label: 'Titre', type: 'text', placeholder: 'Titre du graphique' },
          { name: 'label_column',  label: 'Colonne étiquettes (index)', type: 'number', defaultValue: 0 },
          { name: 'value_columns', label: 'Colonnes valeurs (ex: 1,2)', type: 'text', placeholder: 'Auto si vide' },
          { name: 'output_path',   label: 'Image PNG de sortie', type: 'path' },
        ],
      },
      {
        id: 'xlsx_read', icon: '📗', name: 'Lire un Excel',
        description: 'Lit un fichier Excel (.xlsx) et retourne les données d\'une feuille.',
        tips: ['Action "sheets" pour lister les onglets', '"summary" pour les dimensions sans charger les données', '"read" pour les lignes'],
        params: [
          { name: 'path',     label: 'Chemin du fichier Excel', type: 'path',   required: true, placeholder: 'Documents\\fichier.xlsx' },
          { name: 'action',   label: 'Action', type: 'select', options: [
            { value: 'read',    label: '📊 Lire les données' },
            { value: 'sheets',  label: '📋 Lister les feuilles' },
            { value: 'summary', label: 'ℹ️ Résumé (dimensions)' },
          ]},
          { name: 'sheet',    label: 'Feuille (défaut: première)', type: 'text', placeholder: 'Nom de la feuille' },
          { name: 'max_rows', label: 'Lignes max', type: 'number', defaultValue: 50 },
        ],
      },
      {
        id: 'url_analyze', icon: '🔗', name: 'Analyser une URL',
        description: 'Analyse une URL : titre, meta description, statut HTTP, serveur et temps de réponse.',
        tips: ['Idéal pour vérifier si un site est actif', 'Retourne aussi le titre et la description SEO'],
        params: [
          { name: 'url', label: 'URL', type: 'text', required: true, placeholder: 'https://example.com' },
        ],
      },
      {
        id: 'zip_list', icon: '🗜️', name: 'Lister un ZIP',
        description: 'Liste le contenu d\'une archive ZIP sans l\'extraire.',
        tips: ['Affiche le nom, la taille et la date de chaque fichier', 'Calcule le taux de compression'],
        params: [
          { name: 'path', label: 'Chemin de l\'archive ZIP', type: 'path', required: true, placeholder: 'Documents\\archive.zip' },
        ],
      },
      {
        id: 'color_tool', icon: '🎨', name: 'Outil Couleur',
        description: 'Convertit une couleur entre HEX, RGB et HSL, et calcule la couleur complémentaire.',
        tips: ['Accepte #RRGGBB, rgb(r,g,b) ou hsl(h,s%,l%)', 'Retourne aussi la luminosité et la couleur complémentaire'],
        params: [
          { name: 'color', label: 'Couleur', type: 'text', required: true, placeholder: '#3B82F6 ou rgb(59,130,246)' },
        ],
      },
      {
        id: 'sqlite_tables', icon: '🗃️', name: 'Tables SQLite',
        description: 'Liste les tables et leur schéma dans une base de données SQLite.',
        tips: ['Retourne le nom, le type et les colonnes de chaque table', 'Supporte .db et .sqlite'],
        params: [
          { name: 'db_path', label: 'Chemin de la base SQLite', type: 'path', required: true, placeholder: 'Documents\\base.db' },
        ],
      },
      {
        id: 'sqlite_query', icon: '🗃️', name: 'Requête SQLite',
        description: 'Exécute une requête SQL (SELECT ou écriture avec confirmation) sur une base SQLite.',
        tips: ['SELECT, INSERT, UPDATE, DELETE supportés', 'Les requêtes d\'écriture demandent confirmation', 'Retourne jusqu\'à 100 lignes'],
        params: [
          { name: 'db_path',  label: 'Chemin SQLite',  type: 'path',     required: true },
          { name: 'query',    label: 'Requête SQL',    type: 'textarea', required: true, placeholder: 'SELECT * FROM users LIMIT 10' },
          { name: 'max_rows', label: 'Max lignes',     type: 'number',   defaultValue: 100 },
        ],
      },
      {
        id: 'git_info', icon: '🌿', name: 'Infos Git',
        description: 'Retourne des informations sur un dépôt Git : branche, statut, historique des commits.',
        tips: ['status = fichiers modifiés', 'log = derniers commits', 'branches = liste des branches'],
        params: [
          { name: 'path',   label: 'Chemin du dépôt', type: 'path',   required: false, placeholder: 'Dossier du projet' },
          { name: 'action', label: 'Action', type: 'select', options: [
            { value: 'status',   label: '📋 Statut (fichiers modifiés)' },
            { value: 'log',      label: '📜 Historique des commits' },
            { value: 'branches', label: '🌿 Branches' },
            { value: 'diff',     label: '↔️ Diff statistiques' },
          ]},
          { name: 'count', label: 'Nombre de commits (log)', type: 'number', defaultValue: 10 },
        ],
      },
      {
        id: 'bulk_rename', icon: '✏️', name: 'Renommage en masse',
        description: 'Renomme en masse des fichiers dans un dossier selon un motif regex.',
        tips: ['Mode dry_run = prévisualiser avant d\'exécuter', 'Utilisez des groupes de capture : photo_(\\d+) → image_$1', 'Filtrez par extension avec le champ glob'],
        params: [
          { name: 'folder',  label: 'Dossier source',  type: 'path',   required: true },
          { name: 'pattern', label: 'Regex (recherche)', type: 'text',  required: true, placeholder: '^photo_' },
          { name: 'replace', label: 'Remplacement',    type: 'text',   placeholder: 'image_' },
          { name: 'glob',    label: 'Filtre fichiers', type: 'text',   placeholder: '*.jpg (défaut: *)' },
          { name: 'dry_run', label: 'Mode aperçu (dry_run)', type: 'checkbox', defaultValue: true },
        ],
      },
      {
        id: 'screen_ocr', icon: '🖥️', name: 'OCR Écran',
        description: 'Capture l\'écran et en extrait le texte par OCR (pytesseract). Sans argument = écran entier.',
        tips: ['Sans argument = tout l\'écran', '"lang" : fra, eng, fra+eng, etc.', 'save=true enregistre le screenshot sur le Bureau'],
        params: [
          { name: 'lang', label: 'Langue OCR',    type: 'text',     placeholder: 'fra+eng (défaut)' },
          { name: 'save', label: 'Enregistrer screenshot', type: 'checkbox', defaultValue: false },
        ],
      },
      {
        id: 'file_batch_read', icon: '📚', name: 'Lecture de fichiers (lot)',
        description: 'Lit plusieurs fichiers texte en une seule requête. Utile pour analyser plusieurs fichiers.',
        tips: ['Séparez les chemins par des virgules', 'Max 20 fichiers par requête', 'Limite max_chars_per_file pour éviter les réponses trop longues'],
        params: [
          { name: 'paths',              label: 'Chemins (séparés par virgule)', type: 'textarea', required: true, placeholder: 'C:\\file1.txt, C:\\file2.txt' },
          { name: 'max_chars_per_file', label: 'Max caractères par fichier',     type: 'number',   defaultValue: 5000 },
        ],
      },
      {
        id: 'code_python', icon: '🐍', name: 'Exécuter du Python',
        description: 'Exécute un extrait de code Python et retourne stdout, les variables et les erreurs.',
        tips: ['Variables "result" ou "output" sont capturées automatiquement', 'Bibliothèques disponibles : math, statistics, re, datetime, json, numpy (si installé)', 'Timeout max : 60s'],
        params: [
          { name: 'code',    label: 'Code Python', type: 'textarea', required: true, placeholder: 'result = sum(range(1, 101))\nprint(f"Somme 1-100 = {result}")' },
          { name: 'timeout', label: 'Timeout (secondes)', type: 'number', defaultValue: 15, min: 1, max: 60 },
        ],
      },
      {
        id: 'text_join', icon: '🔗', name: 'Joindre des textes',
        description: 'Fusionne une liste de textes avec un séparateur personnalisé. Supporte déduplication.',
        tips: ['Séparateur peut être "\\n", ", ", " | ", etc.', 'dedupe = supprimer les doublons', 'prefix/suffix = ajouter un entourage à chaque item'],
        params: [
          { name: 'texts',     label: 'Textes (JSON Array)',   type: 'jsonarray', required: true, placeholder: '["texte1","texte2","texte3"]' },
          { name: 'separator', label: 'Séparateur',             type: 'text',     defaultValue: '\n' },
          { name: 'prefix',    label: 'Préfixe (optionnel)',    type: 'text',     placeholder: '- ' },
          { name: 'suffix',    label: 'Suffixe (optionnel)',    type: 'text',     placeholder: '' },
          { name: 'dedupe',    label: 'Supprimer doublons',     type: 'checkbox', defaultValue: false },
        ],
      },
    ],
  },
];

// ── v2.157 — outils manquants au catalogue codé en dur ────────────────────────
// Trouvé en auditant (pas en devinant) : ce catalogue est entièrement statique et avait
// dérivé du vrai TOOLS_REGISTRY backend (141 listés ici contre 327 réels — recherche de
// "topologie" ne trouvait même pas net_topology_diagram, pourtant fonctionnel). Plutôt que
// de tout reconstruire à partir de l'API (perdrait le regroupement/les formulaires
// soigneusement conçus des 141 outils déjà présents), on COMPLÈTE : tout outil renvoyé par
// GET /api/tools/list absent d'ici est ajouté automatiquement dans une catégorie
// "Autres outils" à part, avec un formulaire généré depuis son schéma JSON (moins soigné
// que les formulaires à la main, mais au moins DÉCOUVRABLE et utilisable).
function schemaToParams(schema) {
  const props = schema?.properties || {};
  const required = new Set(schema?.required || []);
  return Object.entries(props).map(([name, def]) => {
    let type = 'text';
    if (def.type === 'boolean') type = 'checkbox';
    else if (def.type === 'integer' || def.type === 'number') type = 'number';
    else if (def.type === 'array') type = def.items?.type === 'string' ? 'tags' : 'jsonarray';
    const label = name.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
    const param = { name, label, type, required: required.has(name), placeholder: def.description || '' };
    if (Array.isArray(def.enum)) {
      param.type = 'select';
      param.options = def.enum.map(v => ({ value: v, label: String(v) }));
    }
    return param;
  });
}
function prettifyToolId(id) {
  return id.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
}

// ── v2.158 — auto-catégorisation par préfixe (au lieu d'un vrac "Autres outils") ──
// La v2.157 comblait l'écart avec le backend mais entassait les 186 outils manquants dans
// UNE catégorie non triée. Ici, chaque outil manquant est rangé dans la catégorie EXISTANTE
// la plus pertinente par préfixe (ssh_* → SSH, net_* → Réseau...) — mêmes tools[] que les
// outils curés, juste ajoutés à la fin. Repli sur 'utilitaires' (déjà pensée pour ça :
// calculatrice, QR, hash...) pour tout préfixe ambigu ou non reconnu. Deux familles
// backend entières n'avaient encore AUCUNE catégorie ici : facturation (billing_*/client_*,
// 27 outils — /devis existe côté produit mais n'a jamais été relié à /outils) et fiches de
// révision (quiz_*, nouveauté de cette session) — elles reçoivent chacune une petite
// catégorie dédiée plutôt que d'être noyées dans 'utilitaires'.
const PREFIX_CATEGORY_MAP = [
  ['ssh_', 'ssh'], ['net_', 'reseau'], ['ip_', 'reseau'],
  ['winget_', 'pc'], ['win_', 'pc'], ['os_', 'pc'], ['system_', 'pc'], ['cmd_', 'pc'], ['pc_', 'pc'],
  ['tweak_', 'utilitaires'], ['registry_', 'utilitaires'], ['catharsis_', 'utilitaires'],
  ['email_', 'email'],
  ['calendar_', 'calendar'], ['event_', 'calendar'],
  ['google_', 'cloud'], ['onedrive_', 'cloud'],
  ['memory_', 'memoire'],
  ['pdf_', 'documents'], ['docx', 'documents'], ['pptx', 'documents'], ['xlsx', 'documents'],
  ['csv_', 'documents'], ['document_', 'documents'],
  ['image_', 'infographie'], ['images_', 'infographie'], ['gif_', 'infographie'],
  ['video_', 'voix'], ['audio_', 'voix'], ['voice_', 'voix'],
  ['web_', 'web'], ['webapp_', 'web'],
  ['file_', 'fichiers'], ['zip_', 'archives'],
  ['billing_', 'facturation'], ['client_', 'facturation'],
  ['quiz_', 'quiz'],
  ['task_', 'taches'], ['note_', 'taches'], ['long_', 'taches'],
  ['itsm_', 'utilitaires'], ['it_', 'utilitaires'], ['ops_', 'utilitaires'], ['ai_', 'utilitaires'],
  ['code_', 'utilitaires'], ['skill_', 'utilitaires'], ['telegram_', 'utilitaires'],
];
function pickCategoryId(id) {
  for (const [prefix, catId] of PREFIX_CATEGORY_MAP) {
    if (id.startsWith(prefix)) return catId;
  }
  return 'utilitaires';
}
const PREFIX_ICON_MAP = [
  ['ssh_', '🔐'], ['net_', '🌐'], ['win_', '🖥️'], ['winget_', '📦'], ['pc_', '🖥️'],
  ['email_', '📧'], ['calendar_', '📅'], ['event_', '📅'], ['memory_', '🧠'],
  ['pdf_', '📄'], ['docx', '📝'], ['pptx', '📊'], ['xlsx', '📈'],
  ['image_', '🖼️'], ['video_', '🎬'], ['audio_', '🎙️'], ['voice_', '🎙️'],
  ['web_', '🌐'], ['webapp_', '🌐'], ['file_', '📁'],
  ['billing_', '💰'], ['client_', '💰'], ['quiz_', '🎓'], ['task_', '✅'], ['note_', '📝'],
];
function pickAutoIcon(id) {
  for (const [prefix, icon] of PREFIX_ICON_MAP) {
    if (id.startsWith(prefix)) return icon;
  }
  return '🧩';
}
// Point d'extension pour curer à la main un outil auto-généré, sans dupliquer toute son
// entrée (contrairement au catalogue statique) — vide au départ, la "curation" devient
// l'exception plutôt que la règle par défaut pour tout nouvel outil futur.
const TOOL_OVERRIDES = {};
function applyOverride(autoTool) {
  const ov = TOOL_OVERRIDES[autoTool.id];
  return ov ? { ...autoTool, ...ov } : autoTool;
}
// Catégories synthétiques pour les préfixes sans catégorie existante (facturation, quiz) —
// créées seulement si au moins un outil y atterrit réellement (voir buildDynamicCatalog).
const SYNTHETIC_CATEGORIES = {
  facturation: { id: 'facturation', label: 'Facturation', icon: '💰', color: '#22c55e',
                 description: 'Devis, factures, clients (voir aussi la page Devis & Factu).' },
  quiz:        { id: 'quiz', label: 'Fiches de révision', icon: '🎓', color: '#eab308',
                 description: 'Génération et révision de fiches Q/R avec répétition espacée.' },
};

// ── Regroupement des 17 catégories en 4 familles ──────────────────────────────
// 17 onglets à plat débordait déjà la barre horizontale (illisible). Un niveau
// intermédiaire (même logique que les sections de la sidebar) : on choisit une
// famille, puis la catégorie précise à l'intérieur.
const GROUPS = [
  { id: 'contenu',      label: 'Contenu & Documents', icon: '📄', categories: ['infographie', 'documents', 'ocr', 'voix'] },
  { id: 'systeme',      label: 'Système & Réseau',     icon: '🖥️', categories: ['pc', 'fichiers', 'reseau', 'ssh', 'archives', 'utilitaires'] },
  { id: 'organisation', label: 'Organisation',         icon: '🗂️', categories: ['calendar', 'taches', 'cloud', 'email', 'memoire'] },
  { id: 'web',          label: 'Web & Données',        icon: '🌐', categories: ['web', 'donnees'] },
];
function groupOf(categoryId) {
  return GROUPS.find(g => g.categories.includes(categoryId))?.id || GROUPS[0].id;
}

// ══════════════════════════════════════════════════════════════════════════════
// Composant outil individuel
// ══════════════════════════════════════════════════════════════════════════════

function buildArgs(tool, values) {
  const args = {};
  (tool.params || []).forEach(p => {
    const v = values[p.name];
    if (p.type === 'tags' || p.type === 'numbers') {
      const arr = String(v).split(',').map(s => s.trim()).filter(Boolean);
      args[p.name] = p.type === 'numbers' ? arr.map(Number) : arr;
    } else if (p.type === 'jsonarray') {
      try { args[p.name] = JSON.parse(v || '[]'); } catch { args[p.name] = []; }
    } else if (p.type === 'checkbox') {
      args[p.name] = !!v;
    } else if (p.type === 'number') {
      args[p.name] = v !== '' ? Number(v) : undefined;
    } else if (v !== '' && v !== undefined) {
      args[p.name] = v;
    }
  });
  return args;
}

function ToolCard({ tool, categoryColor }) {
  const [expanded, setExpanded] = useState(false);
  const initValues = () => {
    const init = {};
    (tool.params || []).forEach(p => {
      init[p.name] = p.defaultValue ?? (p.type === 'checkbox' ? false : '');
    });
    return init;
  };
  const [values, setValues] = useState(initValues);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  // Templates
  const [templates, setTemplates] = useState([]);
  const [savingTpl, setSavingTpl] = useState(false);
  const [tplName, setTplName] = useState('');
  const [showTplSave, setShowTplSave] = useState(false);

  // Charger les templates de cet outil
  useEffect(() => {
    if (!expanded) return;
    fetch(`${BACKEND_URL}/api/templates?tool_name=${encodeURIComponent(tool.id)}`)
      .then(r => r.json())
      .then(setTemplates)
      .catch(() => {});
  }, [expanded, tool.id]);

  const handleChange = useCallback((name, val) => {
    setValues(prev => ({ ...prev, [name]: val }));
  }, []);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setResult(null);
    setError(null);
    const args = buildArgs(tool, values);
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName: tool.id, args }),
      });
      const data = await res.json();
      if (data.result?.error) setError(data.result.error);
      else setResult(data.result);
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }, [tool, values]);

  const handleSaveTemplate = useCallback(async () => {
    if (!tplName.trim()) return;
    setSavingTpl(true);
    try {
      const args = buildArgs(tool, values);
      await fetch(`${BACKEND_URL}/api/templates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: tplName.trim(), tool_name: tool.id, args, category: tool.id }),
      });
      const updated = await fetch(`${BACKEND_URL}/api/templates?tool_name=${encodeURIComponent(tool.id)}`).then(r => r.json());
      setTemplates(updated);
      setTplName('');
      setShowTplSave(false);
    } catch {}
    setSavingTpl(false);
  }, [tool, values, tplName]);

  const handleLoadTemplate = useCallback((tpl) => {
    const merged = initValues();
    if (tpl.args) Object.assign(merged, tpl.args);
    setValues(merged);
  }, []);

  const handleDeleteTemplate = useCallback(async (tplId, e) => {
    e.stopPropagation();
    await fetch(`${BACKEND_URL}/api/templates/${tplId}`, { method: 'DELETE' });
    setTemplates(prev => prev.filter(t => t.id !== tplId));
  }, []);

  const hasRequired = (tool.params || []).filter(p => p.required).every(p => {
    const v = values[p.name];
    return v !== '' && v !== undefined && v !== null;
  });

  return (
    <div style={{
      background: 'var(--bg-glass)',
      border: `1px solid ${expanded ? categoryColor + '40' : 'rgba(255,255,255,0.06)'}`,
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
      transition: 'border-color 0.2s, box-shadow 0.2s',
      boxShadow: expanded ? `0 0 24px ${categoryColor}18` : 'none',
    }}>
      {/* ── En-tête ── */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
          padding: '16px 18px', cursor: 'pointer', gap: '12px',
          background: expanded ? `${categoryColor}08` : 'transparent',
          transition: 'background 0.2s',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', flex: 1 }}>
          <span style={{
            fontSize: '1.4rem', lineHeight: 1, marginTop: '1px',
            filter: expanded ? 'none' : 'grayscale(0.3)',
          }}>
            {tool.icon}
          </span>
          <div style={{ flex: 1 }}>
            <div style={{
              fontWeight: 600, fontSize: 'var(--font-sm)',
              color: expanded ? categoryColor : 'var(--text-primary)',
              transition: 'color 0.2s',
            }}>
              {tool.name}
            </div>
            <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', marginTop: '3px', lineHeight: 1.45 }}>
              {tool.description}
            </div>
            {tool.requiresAuth && (
              <span style={{
                display: 'inline-block', marginTop: '6px',
                fontSize: '10px', padding: '2px 8px',
                borderRadius: '10px', fontWeight: 600,
                background: 'rgba(239,68,68,0.12)', color: '#f87171',
                border: '1px solid rgba(239,68,68,0.2)',
              }}>
                🔐 Connexion {tool.requiresAuth === 'google' ? 'Google' : 'Microsoft'} requise
              </span>
            )}
          </div>
        </div>
        <span style={{
          fontSize: '12px', color: 'var(--text-muted)', flexShrink: 0, marginTop: '3px',
          transform: expanded ? 'rotate(180deg)' : 'none',
          transition: 'transform 0.2s',
        }}>▼</span>
      </div>

      {/* ── Formulaire (expandable) ── */}
      {expanded && tool.custom === 'fileManager' && (
        <div style={{ padding: '0 12px 14px', borderTop: `1px solid ${categoryColor}20` }}>
          <FileManager accentColor={categoryColor} />
        </div>
      )}
      {expanded && tool.custom !== 'fileManager' && (
        <div style={{ padding: '0 18px 18px', borderTop: `1px solid ${categoryColor}20` }}>
          {/* Tips */}
          {tool.tips?.length > 0 && (
            <div style={{
              margin: '14px 0 12px',
              padding: '10px 14px',
              background: `${categoryColor}0d`,
              borderRadius: 'var(--radius-md)',
              borderLeft: `3px solid ${categoryColor}`,
            }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: categoryColor, marginBottom: '5px', letterSpacing: '0.06em' }}>
                💡 CONSEILS
              </div>
              {tool.tips.map((tip, i) => (
                <div key={i} style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  • {tip}
                </div>
              ))}
            </div>
          )}

          {/* Paramètres */}
          {(tool.params || []).length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: tool.tips?.length ? 0 : '14px' }}>
              {tool.params.map(param => (
                <ParamInput
                  key={param.name}
                  param={param}
                  value={values[param.name]}
                  onChange={val => handleChange(param.name, val)}
                  accentColor={categoryColor}
                />
              ))}
            </div>
          )}

          {/* Templates chargement */}
          {templates.length > 0 && (
            <div style={{ marginTop: '14px', display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>📂 TEMPLATES :</span>
              {templates.map(tpl => (
                <div key={tpl.id} style={{
                  display: 'inline-flex', alignItems: 'center', gap: '4px',
                  padding: '3px 10px 3px 8px',
                  background: `${categoryColor}15`, border: `1px solid ${categoryColor}30`,
                  borderRadius: '20px', cursor: 'pointer', fontSize: '11px', color: categoryColor,
                }}
                  onClick={() => handleLoadTemplate(tpl)}
                  title={`Charger "${tpl.name}"`}
                >
                  <span>{tpl.name}</span>
                  <span
                    onClick={e => handleDeleteTemplate(tpl.id, e)}
                    style={{ opacity: 0.5, fontSize: '10px', marginLeft: '2px' }}
                    title="Supprimer"
                  >✕</span>
                </div>
              ))}
            </div>
          )}

          {/* Bouton Exécuter + Sauvegarder template */}
          <div style={{ marginTop: '16px', display: 'flex', gap: '8px' }}>
            <button
              onClick={handleRun}
              disabled={running || !hasRequired}
              style={{
                flex: 1, padding: '10px',
                background: (running || !hasRequired) ? 'rgba(255,255,255,0.04)' : `linear-gradient(135deg, ${categoryColor}cc, ${categoryColor}88)`,
                color: (running || !hasRequired) ? 'var(--text-muted)' : 'white',
                border: `1px solid ${(running || !hasRequired) ? 'var(--border)' : categoryColor + '60'}`,
                borderRadius: 'var(--radius-md)',
                cursor: (running || !hasRequired) ? 'not-allowed' : 'pointer',
                fontWeight: 700, fontSize: 'var(--font-sm)',
                letterSpacing: '0.04em',
                transition: 'all 0.2s',
              }}
            >
              {running ? '⏳ En cours…' : `▶ Exécuter`}
            </button>
            {(tool.params || []).length > 0 && (
              <button
                onClick={() => setShowTplSave(s => !s)}
                title="Sauvegarder cette configuration comme template"
                style={{
                  padding: '10px 14px',
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)',
                  cursor: 'pointer', fontSize: '14px', color: 'var(--text-muted)',
                  transition: 'all 0.2s',
                }}
              >
                💾
              </button>
            )}
          </div>

          {/* Formulaire sauvegarde template */}
          {showTplSave && (
            <div style={{
              marginTop: '10px', display: 'flex', gap: '8px',
              padding: '10px 12px',
              background: 'rgba(255,255,255,0.03)',
              border: `1px solid ${categoryColor}30`,
              borderRadius: 'var(--radius-md)',
            }}>
              <input
                value={tplName}
                onChange={e => setTplName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSaveTemplate()}
                placeholder="Nom du template…"
                style={{
                  flex: 1, padding: '6px 10px', fontSize: '12px',
                  background: 'var(--bg-primary)', border: '1px solid var(--border)',
                  borderRadius: '6px', color: 'var(--text-primary)', outline: 'none',
                }}
              />
              <button
                onClick={handleSaveTemplate}
                disabled={!tplName.trim() || savingTpl}
                style={{
                  padding: '6px 14px', fontSize: '12px', fontWeight: 600,
                  background: tplName.trim() ? categoryColor : 'rgba(255,255,255,0.04)',
                  color: tplName.trim() ? 'white' : 'var(--text-muted)',
                  border: 'none', borderRadius: '6px', cursor: tplName.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                {savingTpl ? '…' : 'Sauver'}
              </button>
            </div>
          )}

          {/* Résultat */}
          {(result || error) && (
            <ResultPanel result={result} error={error} accentColor={categoryColor} />
          )}
        </div>
      )}
    </div>
  );
}

// ── Champ de paramètre générique ──────────────────────────────────────────────

// Appelle un outil backend (pour les actions sur fichiers)
async function callBackendTool(toolName, args) {
  try {
    const res = await fetch(`${BACKEND_URL}/api/tools`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ toolName, args }),
    });
    return (await res.json()).result || {};
  } catch (e) { return { error: String(e) }; }
}

function FileAction({ icon, title, onClick }) {
  return (
    <button onClick={onClick} title={title}
      style={{ padding: '2px 6px', borderRadius: 4, border: '1px solid rgba(255,255,255,0.1)',
        background: 'rgba(255,255,255,0.05)', cursor: 'pointer', fontSize: 11, lineHeight: 1 }}
      onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.12)'}
      onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}>
      {icon}
    </button>
  );
}

// ── Explorateur de fichiers Windows (sélecteur) ───────────────────────────────
const FILE_ICONS = {
  pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', csv: '📊', ppt: '📙', pptx: '📙',
  png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', svg: '🖼️', bmp: '🖼️',
  mp4: '🎬', mov: '🎬', avi: '🎬', mkv: '🎬', webm: '🎬', mp3: '🎵', wav: '🎵', flac: '🎵',
  zip: '🗜️', rar: '🗜️', '7z': '🗜️', txt: '📃', md: '📃', json: '🔣', xml: '🔣',
  exe: '⚙️', msi: '⚙️', bat: '⚙️', ps1: '⚙️', py: '🐍', js: '📜', html: '🌐', css: '🎨',
};
const fileIcon = (e) => e.is_dir ? '📁' : (FILE_ICONS[e.ext] || '📄');

function FilePicker({ open, mode = 'any', onSelect, onClose }) {
  const [cwd, setCwd] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('');

  const load = useCallback(async (path) => {
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName: 'pc_browse', args: { path: path || '' } }),
      });
      const d = (await res.json()).result || {};
      if (d.error && !d.entries) { setData({ ...d, entries: [] }); }
      else { setData(d); setCwd(d.path || path || ''); }
    } catch (e) { setData({ error: String(e), entries: [], roots: [] }); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (open) { setFilter(''); load(''); } }, [open, load]);
  if (!open) return null;

  const entries = (data?.entries || []).filter(e =>
    !filter || e.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 2000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 'min(820px,95vw)', height: 'min(620px,90vh)', background: 'var(--bg-secondary)',
        border: '1px solid var(--border)', borderRadius: 12, display: 'flex', flexDirection: 'column',
        overflow: 'hidden', boxShadow: '0 12px 40px rgba(0,0,0,0.5)',
      }}>
        {/* Barre du haut : remonter + chemin + recherche */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
          <button onClick={() => load(data?.parent || '')} disabled={!data?.parent}
            title="Dossier parent" style={pkBtn(!data?.parent)}>⬆️</button>
          <button onClick={() => load('')} title="Accueil" style={pkBtn(false)}>🏠</button>
          <div style={{ flex: 1, fontFamily: 'monospace', fontSize: 12, color: 'var(--text-secondary)',
            background: 'var(--bg-primary)', padding: '6px 10px', borderRadius: 6, overflow: 'hidden',
            whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{cwd || '…'}</div>
          <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="🔍 filtrer"
            style={{ width: 130, padding: '6px 10px', background: 'var(--bg-primary)', border: '1px solid var(--border)',
              borderRadius: 6, color: 'var(--text-primary)', fontSize: 12, outline: 'none' }} />
          <button onClick={onClose} style={pkBtn(false)}>✕</button>
        </div>

        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          {/* Accès rapides */}
          <div style={{ width: 165, borderRight: '1px solid var(--border)', overflowY: 'auto', padding: 8, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 700, padding: '4px 6px', letterSpacing: '0.05em' }}>ACCÈS RAPIDE</div>
            {(data?.roots || []).map(r => (
              <div key={r.path} onClick={() => load(r.path)} style={{
                display: 'flex', gap: 7, alignItems: 'center', padding: '6px 8px', borderRadius: 6,
                cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)',
              }} onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'}
                 onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <span>{r.icon}</span><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}</span>
              </div>
            ))}
          </div>

          {/* Liste des éléments */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {loading ? <div style={{ padding: 24 }}><LoadingRow /></div>
              : data?.error ? <div style={{ padding: 24, color: '#f87171', fontSize: 13 }}>⚠️ {data.error}</div>
              : entries.length === 0 ? <div style={{ padding: 24, color: 'var(--text-muted)', fontSize: 13 }}>Dossier vide</div>
              : entries.map(e => (
                <div key={e.path}
                  onClick={() => e.is_dir ? load(e.path) : onSelect(e.path)}
                  onDoubleClick={() => onSelect(e.path)}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 14px', cursor: 'pointer',
                    borderBottom: '1px solid var(--border)', fontSize: 13 }}
                  onMouseEnter={ev => ev.currentTarget.style.background = 'var(--bg-glass)'}
                  onMouseLeave={ev => ev.currentTarget.style.background = 'transparent'}>
                  <span style={{ fontSize: 16 }}>{fileIcon(e)}</span>
                  <span style={{ flex: 1, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.name}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{e.size_human}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', width: 105, textAlign: 'right' }}>{e.modified}</span>
                  {e.is_dir && <span style={{ color: 'var(--text-muted)' }}>›</span>}
                </div>
              ))}
          </div>
        </div>

        {/* Pied : sélectionner le dossier courant / annuler */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderTop: '1px solid var(--border)' }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {data?.folders ?? 0} dossiers · {data?.files ?? 0} fichiers — clic sur un dossier pour entrer, sur un fichier pour le choisir
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            {mode !== 'file' && (
              <button onClick={() => onSelect(cwd)} style={{ ...pkBtn(false), padding: '7px 14px', fontWeight: 600 }}>
                📁 Choisir ce dossier
              </button>
            )}
            <button onClick={onClose} style={{ ...pkBtn(false), padding: '7px 14px' }}>Annuler</button>
          </div>
        </div>
      </div>
    </div>
  );
}
const pkBtn = (disabled) => ({
  padding: '6px 10px', background: 'var(--bg-glass)', border: '1px solid var(--border)',
  borderRadius: 6, color: 'var(--text-secondary)', cursor: disabled ? 'not-allowed' : 'pointer',
  fontSize: 13, opacity: disabled ? 0.4 : 1,
});

// ── Gestionnaire de fichiers complet (naviguer + agir) ─────────────────────────
function FileManager({ accentColor }) {
  const [cwd, setCwd] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('');
  const [clip, setClip] = useState(null);   // { path, op:'move'|'copy', name }
  const { toast } = useToast();

  const flash = (m) => {
    const t = (m || '').trim();
    const isErr = t.startsWith('⚠️') || t.startsWith('❌') || /erreur/i.test(t);
    toast[isErr ? 'error' : 'success'](t.replace(/^(⚠️|❌)\s*/, ''));
  };
  const load = useCallback(async (path) => {
    setLoading(true);
    try {
      const d = await callBackendTool('pc_browse', { path: path || '' });
      if (d.entries) { setData(d); setCwd(d.path || path || ''); }
      else flash(d.error || 'Erreur');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(''); }, [load]);

  const act = async (name, args, okMsg) => {
    const r = await callBackendTool(name, args);
    if (r.error) flash('⚠️ ' + r.error);
    else { flash(okMsg || r.message || 'OK'); load(cwd); }
    return r;
  };
  const doRename = async (e) => {
    const nn = prompt('Nouveau nom :', e.name); if (!nn || nn === e.name) return;
    act('file_rename', { source: e.path, new_name: nn }, `Renommé en ${nn}`);
  };
  const doDelete = async (e) => {
    if (!confirm(`Supprimer « ${e.name} » ?\n${e.path}`)) return;
    act('file_delete', { path: e.path, confirmed: true }, 'Supprimé');
  };
  const doInfo = async (e) => {
    const r = await callBackendTool('file_info', { path: e.path });
    if (r.error) return flash(r.error);
    alert(`${e.name}\n\nChemin : ${e.path}\nTaille : ${r.size_human || r.size || '—'}\nModifié : ${r.modified || '—'}\nType : ${r.type || (e.is_dir ? 'dossier' : 'fichier')}`);
  };
  const paste = async () => {
    if (!clip) return;
    const dest = (cwd.replace(/[\\/]$/, '')) + '\\' + clip.name;
    await act(clip.op === 'move' ? 'file_move' : 'file_copy', { source: clip.path, destination: dest },
      clip.op === 'move' ? 'Déplacé' : 'Copié');
    setClip(null);
  };
  const newFolder = async () => {
    const n = prompt('Nom du nouveau dossier :'); if (!n) return;
    act('file_create_folder', { path: (cwd.replace(/[\\/]$/, '')) + '\\' + n }, `Dossier « ${n} » créé`);
  };

  const entries = (data?.entries || []).filter(e => !filter || e.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div style={{ marginTop: 12 }}>
      {/* Barre d'outils */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <button onClick={() => load(data?.parent || '')} disabled={!data?.parent} style={pkBtn(!data?.parent)} title="Parent">⬆️</button>
        <button onClick={() => load('')} style={pkBtn(false)} title="Accueil">🏠</button>
        <button onClick={() => load(cwd)} style={pkBtn(false)} title="Actualiser">🔄</button>
        <button onClick={newFolder} style={pkBtn(false)} title="Nouveau dossier">📁➕</button>
        {clip && <button onClick={paste} style={{ ...pkBtn(false), color: accentColor, fontWeight: 600 }}>📋 Coller ({clip.op === 'move' ? 'déplacer' : 'copier'}) « {clip.name} »</button>}
        <div style={{ flex: 1, fontFamily: 'monospace', fontSize: 11, color: 'var(--text-muted)', background: 'var(--bg-primary)', padding: '5px 8px', borderRadius: 5, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{cwd || '…'}</div>
        <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="🔍 filtrer" style={{ width: 110, padding: '5px 8px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text-primary)', fontSize: 12, outline: 'none' }} />
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        {/* Accès rapides */}
        <div style={{ width: 150, flexShrink: 0 }}>
          {(data?.roots || []).map(r => (
            <div key={r.path} onClick={() => load(r.path)} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '6px 8px', borderRadius: 5, cursor: 'pointer', fontSize: 12, color: 'var(--text-secondary)' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-glass)'} onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span>{r.icon}</span><span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}</span>
            </div>
          ))}
        </div>

        {/* Liste */}
        <div style={{ flex: 1, maxHeight: 420, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8 }}>
          {loading ? <div style={{ padding: 20 }}><LoadingRow /></div>
            : entries.length === 0 ? <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: 13 }}>Dossier vide</div>
            : entries.map(e => (
              <div key={e.path} className="fm-row" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderBottom: '1px solid var(--border)', fontSize: 13 }}
                onDoubleClick={() => e.is_dir ? load(e.path) : callBackendTool('pc_open_file', { path: e.path })}>
                <span style={{ fontSize: 15, cursor: 'pointer' }} onClick={() => e.is_dir && load(e.path)}>{fileIcon(e)}</span>
                <span style={{ flex: 1, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: e.is_dir ? 'pointer' : 'default' }}
                  onClick={() => e.is_dir && load(e.path)} title={e.path}>{e.name}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap', width: 70, textAlign: 'right' }}>{e.size_human}</span>
                <span style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
                  {!e.is_dir && <FileAction icon="📂" title="Ouvrir" onClick={() => callBackendTool('pc_open_file', { path: e.path })} />}
                  <FileAction icon="🔎" title="Révéler" onClick={() => callBackendTool('pc_reveal', { path: e.path })} />
                  <FileAction icon="✏️" title="Renommer" onClick={() => doRename(e)} />
                  <FileAction icon="✂️" title="Couper" onClick={() => { setClip({ path: e.path, op: 'move', name: e.name }); flash('Coupé — naviguez puis Coller'); }} />
                  <FileAction icon="📑" title="Copier" onClick={() => { setClip({ path: e.path, op: 'copy', name: e.name }); flash('Copié — naviguez puis Coller'); }} />
                  <FileAction icon="ℹ️" title="Propriétés" onClick={() => doInfo(e)} />
                  <FileAction icon="🗑️" title="Supprimer" onClick={() => doDelete(e)} />
                </span>
              </div>
            ))}
        </div>
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6 }}>
        {data?.folders ?? 0} dossiers · {data?.files ?? 0} fichiers · double-clic pour ouvrir/entrer
      </div>
    </div>
  );
}

function ParamInput({ param, value, onChange, accentColor }) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const inputStyle = {
    width: '100%', padding: '8px 12px',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    color: 'var(--text-primary)',
    fontSize: 'var(--font-sm)',
    outline: 'none',
    boxSizing: 'border-box',
    transition: 'border-color 0.2s',
  };

  return (
    <div>
      <label style={{
        display: 'flex', gap: '5px', alignItems: 'center',
        fontSize: 'var(--font-xs)', fontWeight: 600,
        color: 'var(--text-secondary)', marginBottom: '5px',
      }}>
        {param.label}
        {param.required && <span style={{ color: accentColor, fontSize: '11px' }}>*</span>}
      </label>

      {param.type === 'select' && (
        <select value={value} onChange={e => onChange(e.target.value)} style={{ ...inputStyle, cursor: 'pointer' }}>
          {!param.required && <option value="">— Optionnel —</option>}
          {param.options.map(o =>
            typeof o === 'string'
              ? <option key={o} value={o}>{o}</option>
              : <option key={o.value} value={o.value}>{o.label}</option>
          )}
        </select>
      )}

      {param.type === 'textarea' && (
        <textarea
          value={value} onChange={e => onChange(e.target.value)}
          placeholder={param.placeholder}
          rows={4}
          style={{ ...inputStyle, resize: 'vertical', fontFamily: 'monospace', lineHeight: 1.5 }}
        />
      )}

      {param.type === 'checkbox' && (
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', marginTop: '2px' }}>
          <input
            type="checkbox"
            checked={!!value}
            onChange={e => onChange(e.target.checked)}
            style={{ width: '16px', height: '16px', accentColor: accentColor }}
          />
          <span style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)' }}>
            {value ? 'Activé' : 'Désactivé'}
          </span>
        </label>
      )}

      {param.type === 'path' && (
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            type="text" value={value} onChange={e => onChange(e.target.value)}
            placeholder={param.placeholder || 'Cliquez sur Parcourir…'}
            style={{ ...inputStyle, flex: 1 }}
            onFocus={e => e.target.style.borderColor = accentColor}
            onBlur={e => e.target.style.borderColor = 'var(--border)'}
          />
          <button type="button" onClick={() => setPickerOpen(true)}
            title="Parcourir l'arborescence Windows"
            style={{ padding: '8px 12px', background: `${accentColor}1a`, border: `1px solid ${accentColor}40`,
              borderRadius: 'var(--radius-sm)', color: accentColor, cursor: 'pointer', fontSize: 13,
              whiteSpace: 'nowrap', fontWeight: 600 }}>
            📂 Parcourir
          </button>
          <FilePicker open={pickerOpen}
            onSelect={(p) => { onChange(p); setPickerOpen(false); }}
            onClose={() => setPickerOpen(false)} />
        </div>
      )}

      {['text', 'url', 'tags', 'numbers', 'jsonarray', 'number', 'date'].includes(param.type) && (
        <input
          type={param.type === 'date' ? 'date' : param.type === 'number' ? 'number' : 'text'}
          value={value}
          onChange={e => onChange(param.type === 'number' ? Number(e.target.value) : e.target.value)}
          placeholder={param.placeholder}
          min={param.min}
          max={param.max}
          style={inputStyle}
          onFocus={e => e.target.style.borderColor = accentColor}
          onBlur={e => e.target.style.borderColor = 'var(--border)'}
        />
      )}

      {(param.type === 'tags' || param.type === 'numbers') && (
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '3px' }}>
          Séparez les valeurs par des virgules
        </div>
      )}
    </div>
  );
}

// ── Affichage des résultats ───────────────────────────────────────────────────

function ResultPanel({ result, error, accentColor }) {
  const [collapsed, setCollapsed] = useState(false);
  const [showJson, setShowJson] = useState(false);

  if (error) return (
    <div style={{
      marginTop: '12px', padding: '12px 14px',
      background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
      borderRadius: 'var(--radius-md)', color: '#f87171', fontSize: 'var(--font-xs)',
    }}>
      ⚠️ {error}
    </div>
  );

  if (!result) return null;

  // Image (screenshot, infographie)
  const img = result.image || result.path?.match(/\.(png|jpg|jpeg|gif|webp)$/i)?.[0];
  const isImage = result.image?.startsWith('data:image') || false;

  // Fichiers listés
  const fileList = result.entries || result.files || result.results || result.items;
  const isFileList = Array.isArray(fileList);

  // Résultats web
  const webResults = result.results && Array.isArray(result.results) && result.results[0]?.url;

  return (
    <div style={{ marginTop: '12px' }}>
      {/* Header résultat */}
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px',
          background: `${accentColor}10`, borderRadius: collapsed ? 'var(--radius-md)' : 'var(--radius-md) var(--radius-md) 0 0',
          border: `1px solid ${accentColor}25`,
        }}
      >
        <span
          onClick={() => setCollapsed(c => !c)}
          style={{ fontSize: 'var(--font-xs)', fontWeight: 700, color: accentColor, cursor: 'pointer', flex: 1 }}
        >
          ✅ Résultat {collapsed ? '▼' : '▲'}
        </span>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            onClick={() => setShowJson(j => !j)}
            title={showJson ? 'Affichage lisible' : 'Voir le JSON brut'}
            style={{
              padding: '2px 8px', borderRadius: '4px',
              border: `1px solid ${showJson ? accentColor + '66' : 'rgba(255,255,255,0.1)'}`,
              background: showJson ? `${accentColor}22` : 'rgba(255,255,255,0.05)',
              color: showJson ? accentColor : 'var(--text-muted)', fontSize: '10px', cursor: 'pointer',
            }}
          >
            {showJson ? '✨ Lisible' : '{ } JSON'}
          </button>
          <button
            onClick={() => {
              const text = typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result);
              navigator.clipboard.writeText(text).catch(() => {});
            }}
            title="Copier en JSON"
            style={{
              padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
              background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
              fontSize: '10px', cursor: 'pointer',
            }}
          >
            📋 Copier
          </button>
          {result?.text && (
            <button
              onClick={() => navigator.clipboard.writeText(result.text).catch(() => {})}
              title="Copier le texte"
              style={{
                padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
                fontSize: '10px', cursor: 'pointer',
              }}
            >
              📝 Texte
            </button>
          )}
          {result?.path && (
            <button
              onClick={() => navigator.clipboard.writeText(result.path).catch(() => {})}
              title="Copier le chemin"
              style={{
                padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(255,255,255,0.1)',
                background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
                fontSize: '10px', cursor: 'pointer',
              }}
            >
              📂 Chemin
            </button>
          )}
        </div>
      </div>

      {!collapsed && showJson && (
        <pre style={{
          margin: 0, padding: '12px 14px', background: 'var(--bg-primary)',
          borderRadius: '0 0 var(--radius-md) var(--radius-md)',
          border: `1px solid ${accentColor}20`, borderTop: 'none',
          maxHeight: '420px', overflowY: 'auto', fontSize: '11px',
          color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result)}
        </pre>
      )}

      {!collapsed && !showJson && (
        <div style={{
          padding: '12px 14px',
          background: 'var(--bg-primary)',
          borderRadius: '0 0 var(--radius-md) var(--radius-md)',
          border: `1px solid ${accentColor}20`,
          borderTop: 'none',
          maxHeight: '380px', overflowY: 'auto',
        }}>
          {/* Succès simple */}
          {result.success && result.message && (
            <div style={{ color: '#4ade80', fontSize: 'var(--font-xs)', marginBottom: isFileList || isImage ? '10px' : 0 }}>
              ✓ {result.message}
              {result.path && !isImage && (
                <div style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: '10px', marginTop: '4px' }}>
                  📍 {result.path}
                </div>
              )}
            </div>
          )}

          {/* Image inline */}
          {isImage && (
            <img src={result.image} alt="Résultat"
              style={{ maxWidth: '100%', borderRadius: '6px', marginTop: '8px', cursor: 'pointer' }}
              onClick={() => window.open(result.image, '_blank')}
            />
          )}

          {/* Résultats de recherche web */}
          {webResults && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {result.results.map((r, i) => (
                <div key={i} style={{
                  padding: '8px 10px', borderRadius: '6px',
                  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
                }}>
                  <a href={r.url} target="_blank" rel="noopener noreferrer"
                    style={{ color: accentColor, fontWeight: 600, fontSize: 'var(--font-xs)', textDecoration: 'none' }}>
                    {r.title || r.url}
                  </a>
                  <div style={{ color: 'var(--text-muted)', fontSize: '10px', marginTop: '2px', fontFamily: 'monospace' }}>{r.url}</div>
                  {r.snippet && <div style={{ color: 'var(--text-secondary)', fontSize: '11px', marginTop: '4px', lineHeight: 1.4 }}>{r.snippet}</div>}
                </div>
              ))}
            </div>
          )}

          {/* Liste de fichiers */}
          {isFileList && !webResults && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {fileList.slice(0, 40).map((f, i) => {
                const fpath = (typeof f === 'object') ? (f.path || f.full_path || f.filepath || f.location) : null;
                return (
                  <div key={i} className="file-row" style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    gap: 8, padding: '5px 8px', borderRadius: '4px',
                    background: 'rgba(255,255,255,0.02)', fontSize: '11px',
                  }}>
                    <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}
                      title={fpath || ''}>
                      {f.is_dir ? '📁 ' : '📄 '}{f.name || (typeof f === 'string' ? f : fpath) || '—'}
                    </span>
                    {f.size_human && <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{f.size_human}</span>}
                    {fpath && (
                      <span style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                        <FileAction icon="📂" title="Ouvrir" onClick={() => callBackendTool('pc_open_file', { path: fpath })} />
                        <FileAction icon="🔎" title="Révéler dans l'Explorateur" onClick={() => callBackendTool('pc_reveal', { path: fpath })} />
                        <FileAction icon="📋" title="Copier le chemin" onClick={() => navigator.clipboard.writeText(fpath).catch(() => {})} />
                      </span>
                    )}
                  </div>
                );
              })}
              {fileList.length > 40 && (
                <div style={{ color: 'var(--text-muted)', fontSize: '10px', textAlign: 'center', marginTop: '4px' }}>
                  +{fileList.length - 40} éléments supplémentaires
                </div>
              )}
            </div>
          )}

          {/* Texte brut (read, system_info, etc.) */}
          {result.content && (
            <pre style={{
              fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.5,
              whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
            }}>
              {String(result.content).slice(0, 3000)}
              {String(result.content).length > 3000 && '\n…(tronqué)'}
            </pre>
          )}

          {/* OCR — texte extrait */}
          {result.text && !result.content && (
            <div>
              {result.model && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '8px', fontFamily: 'monospace' }}>
                  Modèle : {result.model} — {result.char_count} caractères extraits
                </div>
              )}
              <pre style={{
                fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6,
                whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
                padding: '10px', background: 'rgba(255,255,255,0.03)',
                borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)',
              }}>
                {result.text}
              </pre>
            </div>
          )}

          {/* Réseau — output texte (ping, traceroute) */}
          {result.output && (
            <div>
              {result.summary && (
                <div style={{ marginBottom: '8px', padding: '6px 10px', background: `${accentColor}12`, borderRadius: '6px',
                  fontSize: '12px', color: accentColor, fontFamily: 'monospace' }}>
                  ⚡ {result.summary.trim()}
                </div>
              )}
              <pre style={{
                fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.5,
                whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
                maxHeight: '260px', overflowY: 'auto',
              }}>
                {result.output}
              </pre>
            </div>
          )}

          {/* Réseau — ports ouverts */}
          {result.open_ports !== undefined && (
            <div>
              <div style={{ fontSize: '12px', color: accentColor, marginBottom: '8px', fontFamily: 'monospace' }}>
                {result.summary}
              </div>
              {result.open_ports.length > 0 ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {result.open_ports.map(p => (
                    <span key={p} style={{
                      padding: '3px 10px', borderRadius: '12px', fontSize: '12px',
                      background: '#22c55e22', border: '1px solid #22c55e44', color: '#4ade80',
                      fontFamily: 'monospace',
                    }}>
                      :{p}
                    </span>
                  ))}
                </div>
              ) : (
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Aucun port ouvert trouvé.</div>
              )}
            </div>
          )}

          {/* Réseau — appareils ARP */}
          {result.devices !== undefined && Array.isArray(result.devices) && (
            <div>
              <div style={{ fontSize: '12px', color: accentColor, marginBottom: '10px', fontFamily: 'monospace' }}>
                {result.count} appareil{result.count > 1 ? 's' : ''} détecté{result.count > 1 ? 's' : ''}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {result.devices.map((d, i) => (
                  <div key={i} style={{
                    display: 'grid', gridTemplateColumns: '140px 160px 1fr',
                    gap: '8px', padding: '5px 8px', borderRadius: '5px',
                    background: 'rgba(255,255,255,0.02)', fontSize: '11px', fontFamily: 'monospace',
                  }}>
                    <span style={{ color: accentColor }}>{d.ip}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{d.mac}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>{d.type}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Réseau — DNS */}
          {result.addresses && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>ADRESSES IP</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {result.addresses.map((a, i) => (
                    <span key={i} style={{
                      padding: '3px 10px', borderRadius: '12px',
                      background: `${accentColor}15`, border: `1px solid ${accentColor}30`,
                      color: accentColor, fontFamily: 'monospace', fontSize: '12px',
                    }}>{a}</span>
                  ))}
                </div>
              </div>
              {result.hostname && (
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                  ↩ {result.hostname}
                </div>
              )}
              {result.nslookup && (
                <pre style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'pre-wrap', margin: 0, maxHeight: '160px', overflowY: 'auto' }}>
                  {result.nslookup}
                </pre>
              )}
            </div>
          )}

          {/* Réseau — WHOIS */}
          {result.whois && (
            <pre style={{
              fontSize: '10px', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap',
              fontFamily: 'monospace', margin: 0, maxHeight: '260px', overflowY: 'auto',
              lineHeight: 1.5,
            }}>
              {result.whois}
            </pre>
          )}

          {/* Couleur (color_tool) */}
          {result.hex && result.rgb && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                <div style={{
                  width: '60px', height: '60px', borderRadius: '10px',
                  background: result.hex, border: '2px solid rgba(255,255,255,0.1)',
                  flexShrink: 0,
                }} />
                <div style={{ flex: 1 }}>
                  {[
                    ['HEX', result.hex],
                    ['RGB', result.rgb_str],
                    ['HSL', result.hsl_str],
                    ['Luminance', result.luminance],
                    ['Clarté', result.brightness],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', gap: '8px', fontSize: '12px', marginBottom: '2px' }}>
                      <span style={{ color: 'var(--text-muted)', minWidth: '80px' }}>{k}</span>
                      <code style={{ color: accentColor }}>{v}</code>
                    </div>
                  ))}
                </div>
                {result.complementary && (
                  <div style={{ textAlign: 'center' }}>
                    <div style={{
                      width: '40px', height: '40px', borderRadius: '8px',
                      background: result.complementary, border: '2px solid rgba(255,255,255,0.1)',
                    }} />
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '4px' }}>Comp.</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* IP Info */}
          {result.country && result.city && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
              {[
                ['IP', result.ip], ['Pays', `${result.country_code} ${result.country}`],
                ['Ville', result.city], ['Région', result.region],
                ['Fuseau', result.timezone], ['ISP', result.isp],
                ['ASN', result.asn], ['Lat/Lon', `${result.latitude}, ${result.longitude}`],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '11px' }}>{v}</span>
                </div>
              ))}
            </div>
          )}

          {/* Hash */}
          {result.hash && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{result.algorithm} ({result.source})</div>
              <code style={{
                wordBreak: 'break-all', padding: '8px 10px', background: 'rgba(255,255,255,0.04)',
                borderRadius: '6px', fontSize: '12px', color: accentColor, fontFamily: 'monospace',
                border: '1px solid rgba(255,255,255,0.06)',
              }}>
                {result.hash}
              </code>
            </div>
          )}

          {/* URL Analyze */}
          {result.status && result.url && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{
                  padding: '2px 10px', borderRadius: '12px', fontWeight: 700,
                  background: result.status < 400 ? '#22c55e22' : '#ef444422',
                  color: result.status < 400 ? '#4ade80' : '#f87171',
                  border: `1px solid ${result.status < 400 ? '#22c55e44' : '#ef444444'}`,
                }}>
                  HTTP {result.status}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>{result.response_time_ms}ms</span>
                {result.server && <span style={{ color: 'var(--text-muted)' }}>🖥️ {result.server}</span>}
              </div>
              {result.title && <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{result.title}</div>}
              {result.description && <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>{result.description}</div>}
              <a href={result.url} target="_blank" rel="noopener noreferrer" style={{ color: accentColor, fontSize: '11px', wordBreak: 'break-all' }}>{result.url}</a>
            </div>
          )}

          {/* PDF Info */}
          {result.pages !== undefined && result.file && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12px' }}>
              {[
                ['Fichier', result.file?.split('\\').pop()],
                ['Pages', result.pages],
                ['Taille', `${result.size_kb} Ko`],
                ['Chiffré', result.encrypted ? 'Oui' : 'Non'],
                ['Titre', result.title],
                ['Auteur', result.author],
                ['Créateur', result.creator],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '11px', wordBreak: 'break-all' }}>{v}</span>
                </div>
              ))}
            </div>
          )}

          {/* XLSX / CSV data table */}
          {result.headers && result.data && Array.isArray(result.data) && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
                <thead>
                  <tr>
                    {result.headers.map(h => (
                      <th key={h} style={{
                        padding: '5px 8px', textAlign: 'left', borderBottom: `1px solid ${accentColor}30`,
                        color: accentColor, fontWeight: 700, whiteSpace: 'nowrap',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.data.slice(0, 20).map((row, i) => (
                    <tr key={i} style={{ background: i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent' }}>
                      {result.headers.map(h => (
                        <td key={h} style={{
                          padding: '4px 8px', color: 'var(--text-secondary)',
                          borderBottom: '1px solid rgba(255,255,255,0.04)',
                          maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {row[h] ?? ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.data.length > 20 && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '6px' }}>
                  +{result.data.length - 20} lignes supplémentaires
                </div>
              )}
            </div>
          )}

          {/* QR Code image */}
          {result.output && result.size_px && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-start' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                💾 Sauvegardé : <code style={{ color: accentColor }}>{result.output?.split('\\').pop()}</code>
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                {result.size_px?.[0]}×{result.size_px?.[1]} px · {result.size_kb} Ko
              </div>
            </div>
          )}

          {/* Base64 result */}
          {result.action === 'encode' && result.result && !result.hex && (
            <code style={{
              wordBreak: 'break-all', padding: '8px 10px', background: 'rgba(255,255,255,0.04)',
              borderRadius: '6px', fontSize: '12px', color: accentColor, fontFamily: 'monospace',
              border: '1px solid rgba(255,255,255,0.06)', display: 'block',
            }}>
              {result.result}
            </code>
          )}

          {/* Translation result */}
          {result.translated && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '11px' }}>
                {result.source_lang?.toUpperCase()} → {result.target_lang?.toUpperCase()}
              </div>
              <div style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                {result.translated}
              </div>
            </div>
          )}

          {/* Password result */}
          {result.password && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <code style={{
                padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: '8px',
                fontSize: '16px', color: accentColor, fontFamily: 'monospace', letterSpacing: '0.05em',
                border: `1px solid ${accentColor}30`,
              }}>
                {result.password}
              </code>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Entropie : {result.entropy_bits} bits · Force : {result.strength}
              </div>
            </div>
          )}

          {/* Code Python result */}
          {result.stdout !== undefined && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {result.stdout && result.stdout !== '(aucune sortie)' && (
                <div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>STDOUT</div>
                  <pre style={{
                    padding: '8px 12px', background: '#0d1117', borderRadius: '6px',
                    fontSize: '12px', color: '#c9d1d9', fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap', margin: 0, maxHeight: '200px', overflowY: 'auto',
                    border: '1px solid rgba(228, 228, 231,0.08)',
                  }}>
                    {result.stdout}
                  </pre>
                </div>
              )}
              {result.stderr && (
                <div>
                  <div style={{ fontSize: '10px', color: '#f87171', marginBottom: '4px' }}>STDERR</div>
                  <pre style={{ padding: '8px 12px', background: '#1a0808', borderRadius: '6px', fontSize: '11px', color: '#f87171', fontFamily: 'monospace', whiteSpace: 'pre-wrap', margin: 0 }}>
                    {result.stderr}
                  </pre>
                </div>
              )}
              {result.result !== null && result.result !== undefined && (
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '12px' }}>
                  <span style={{ color: 'var(--text-muted)' }}>result =</span>
                  <code style={{ color: accentColor, fontFamily: 'monospace' }}>{String(result.result)}</code>
                </div>
              )}
              {result.vars && Object.keys(result.vars).length > 0 && (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  Variables: {Object.entries(result.vars).map(([k,v]) => `${k}=${v}`).join(', ')}
                </div>
              )}
            </div>
          )}

          {/* JSON brut fallback — pour tout le reste */}
          {!result.content && !result.text && !result.output && result.open_ports === undefined
           && !result.devices && !result.addresses && !result.whois
           && !result.hex && !result.country && !result.hash && !result.status
           && !result.pages && !result.headers && !result.translated && !result.password
           && result.stdout === undefined
           && !(result.success && result.message) && !isFileList && !webResults && !isImage && (
            <PrettyResult result={result} />
          )}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Page principale
// ══════════════════════════════════════════════════════════════════════════════

function OutilsPageInner() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState('infographie');
  const [activeGroup, setActiveGroup] = useState(() => groupOf('infographie'));
  const [search, setSearch] = useState(() => searchParams.get('q') || '');

  // v2.157/v2.158 — complète le catalogue statique avec les outils backend absents d'ici,
  // auto-catégorisés par préfixe (voir pickCategoryId/pickAutoIcon ci-dessus) plutôt que
  // dans un vrac unique. Best-effort : si l'appel échoue, le catalogue statique reste
  // utilisable tel quel, rien ne casse.
  const [extraTools, setExtraTools] = useState([]);
  useEffect(() => {
    const curatedIds = new Set(CATEGORIES.flatMap(c => c.tools.map(t => t.id)));
    fetch(`${BACKEND_URL}/api/tools/list`)
      .then(r => r.json())
      .then(d => {
        const extra = (d.tools || [])
          .map(t => t.function)
          .filter(f => f && f.name && !curatedIds.has(f.name))
          .map(f => applyOverride({
            id: f.name, icon: pickAutoIcon(f.name), name: prettifyToolId(f.name),
            description: f.description || '', params: schemaToParams(f.parameters),
            _categoryId: pickCategoryId(f.name),
          }));
        setExtraTools(extra);
      })
      .catch(() => {});
  }, []);

  // Regroupe les outils manquants par catégorie cible, puis fusionne CHAQUE catégorie
  // statique concernée (copie, tools[] curatés d'abord + auto ajoutés ensuite — le tableau
  // CATEGORIES original n'est jamais muté). Les catégories synthétiques (facturation, quiz)
  // ne sont créées que si au moins un outil y atterrit réellement.
  const categories = useMemo(() => {
    if (!extraTools.length) return CATEGORIES;
    const byCategory = new Map();
    for (const t of extraTools) {
      const { _categoryId, ...tool } = t;
      if (!byCategory.has(_categoryId)) byCategory.set(_categoryId, []);
      byCategory.get(_categoryId).push(tool);
    }
    const merged = CATEGORIES.map(cat => {
      const extras = byCategory.get(cat.id);
      return extras ? { ...cat, tools: [...cat.tools, ...extras] } : cat;
    });
    const staticIds = new Set(CATEGORIES.map(c => c.id));
    for (const [catId, tools] of byCategory) {
      if (!staticIds.has(catId) && SYNTHETIC_CATEGORIES[catId]) {
        merged.push({ ...SYNTHETIC_CATEGORIES[catId], tools });
      }
    }
    return merged;
  }, [extraTools]);

  const groups = useMemo(() => {
    if (!extraTools.length) return GROUPS;
    const presentIds = new Set(categories.map(c => c.id));
    return GROUPS.map(g => {
      const toAdd = Object.keys(SYNTHETIC_CATEGORIES).filter(id => presentIds.has(id) && !g.categories.includes(id));
      // Les deux catégories synthétiques actuelles (facturation, quiz) sont de l'organisation.
      return g.id === 'organisation' && toAdd.length ? { ...g, categories: [...g.categories, ...toAdd] } : g;
    });
  }, [extraTools, categories]);

  const activeCategory = categories.find(c => c.id === activeTab) || categories[0];
  const totalTools = categories.reduce((acc, c) => acc + c.tools.length, 0);
  const groupCategories = categories.filter(c => groups.find(g => g.id === activeGroup)?.categories.includes(c.id));

  const selectGroup = (groupId) => {
    setActiveGroup(groupId);
    const first = groups.find(g => g.id === groupId)?.categories[0];
    if (first) setActiveTab(first);
  };

  // Search: filter across all categories
  const searchLower = search.trim().toLowerCase();
  const searchResults = searchLower
    ? categories.flatMap(cat =>
        cat.tools
          .filter(t =>
            t.name.toLowerCase().includes(searchLower) ||
            t.description?.toLowerCase().includes(searchLower) ||
            t.id.toLowerCase().includes(searchLower)
          )
          .map(t => ({ ...t, _category: cat }))
      )
    : null;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ─── En-tête ─────────────────────────────────────────────────────── */}
      <div className="page-header" style={{ borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              🔧 Boîte à outils
            </h1>
            <p style={{ fontSize: 'var(--font-xs)', color: 'var(--text-muted)', margin: '4px 0 0', letterSpacing: '0.03em' }}>
              {totalTools} outils disponibles — exécutables directement ou via Marvin
            </p>
          </div>
          {/* Search bar */}
          <div style={{ position: 'relative', flexShrink: 0 }}>
            <span style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: '14px', pointerEvents: 'none' }}>🔍</span>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={`Rechercher parmi ${totalTools} outils…`}
              style={{
                padding: '8px 12px 8px 32px',
                background: 'var(--bg-glass)',
                border: search ? '1px solid var(--accent)' : '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                fontSize: 'var(--font-sm)',
                width: '280px',
                outline: 'none',
              }}
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '14px', lineHeight: 1 }}
              >✕</button>
            )}
          </div>
        </div>
      </div>

      {/* ─── Familles (niveau 1, hidden during search) ─────────────────────── */}
      <div style={{
        display: searchResults !== null ? 'none' : 'flex',
        gap: '6px', padding: '12px 24px 0', flexShrink: 0,
      }}>
        {groups.map(g => {
          const isActive = g.id === activeGroup;
          const count = g.categories.reduce((acc, cid) => acc + (categories.find(c => c.id === cid)?.tools.length || 0), 0);
          return (
            <button
              key={g.id}
              onClick={() => selectGroup(g.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: '7px',
                padding: '7px 14px', border: `1px solid ${isActive ? 'var(--accent-primary)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-full)', cursor: 'pointer',
                background: isActive ? 'rgba(79, 140, 255,0.12)' : 'transparent',
                color: isActive ? 'var(--accent-primary)' : 'var(--text-secondary)',
                fontWeight: isActive ? 700 : 500, fontSize: 'var(--font-xs)',
                transition: 'all 0.15s',
              }}
            >
              <span>{g.icon}</span>
              <span>{g.label}</span>
              <span style={{ fontSize: '10px', opacity: 0.6 }}>{count}</span>
            </button>
          );
        })}
      </div>

      {/* ─── Catégories du groupe actif (niveau 2, hidden during search) ───── */}
      <div style={{
        display: searchResults !== null ? 'none' : 'flex',
        gap: '4px', padding: '10px 24px 0',
        overflowX: 'auto', flexShrink: 0,
        borderBottom: '1px solid var(--border)',
        scrollbarWidth: 'none',
      }}>
        {groupCategories.map(cat => {
          const isActive = cat.id === activeTab;
          return (
            <button
              key={cat.id}
              onClick={() => setActiveTab(cat.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '8px 16px', border: 'none', borderRadius: 'var(--radius-md) var(--radius-md) 0 0',
                cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
                background: isActive ? 'var(--bg-glass)' : 'transparent',
                color: isActive ? cat.color : 'var(--text-muted)',
                borderBottom: isActive ? `2px solid ${cat.color}` : '2px solid transparent',
                fontWeight: isActive ? 700 : 400,
                fontSize: 'var(--font-xs)',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.color = 'var(--text-secondary)'; }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.color = 'var(--text-muted)'; }}
            >
              <span>{cat.icon}</span>
              <span>{cat.label}</span>
              <span style={{
                fontSize: '10px', padding: '1px 6px', borderRadius: '10px',
                background: isActive ? `${cat.color}20` : 'rgba(255,255,255,0.05)',
                color: isActive ? cat.color : 'var(--text-muted)',
              }}>
                {cat.tools.length}
              </span>
            </button>
          );
        })}
      </div>

      {/* ─── Contenu ─────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px 32px' }}>

        {/* ── Search results ───────────────────────────────────────────── */}
        {searchResults !== null ? (
          <>
            <div style={{
              display: 'flex', alignItems: 'center', gap: '10px',
              padding: '10px 14px', marginBottom: '16px',
              background: 'rgba(79, 140, 255,0.06)',
              border: '1px solid rgba(79, 140, 255,0.2)',
              borderRadius: 'var(--radius-md)',
              fontSize: 'var(--font-xs)', color: '#4f8cff',
            }}>
              🔍 <strong>{searchResults.length}</strong> outil{searchResults.length !== 1 ? 's' : ''} correspondant{searchResults.length !== 1 ? 's' : ''} à «&nbsp;{search}&nbsp;»
            </div>
            {searchResults.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
                Aucun outil ne correspond à cette recherche.
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '14px' }}>
                {searchResults.map(tool => (
                  <ToolCard key={tool.id} tool={tool} categoryColor={tool._category.color} />
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            {/* ── Category header ───────────────────────────────────────── */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '14px',
              padding: '14px 18px', marginBottom: '20px',
              background: `${activeCategory.color}0a`,
              borderRadius: 'var(--radius-lg)',
              border: `1px solid ${activeCategory.color}22`,
            }}>
              <span style={{ fontSize: '2rem' }}>{activeCategory.icon}</span>
              <div>
                <div style={{ fontWeight: 700, fontSize: 'var(--font-sm)', color: activeCategory.color }}>
                  {activeCategory.label}
                </div>
                <div style={{ fontSize: 'var(--font-xs)', color: 'var(--text-secondary)', marginTop: '2px' }}>
                  {activeCategory.description}
                </div>
              </div>
              <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, color: activeCategory.color }}>
                  {activeCategory.tools.length}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>outil{activeCategory.tools.length > 1 ? 's' : ''}</div>
              </div>
            </div>

            {/* ── Tools grid ────────────────────────────────────────────── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '14px' }}>
              {activeCategory.tools.map(tool => (
                <ToolCard key={tool.id} tool={tool} categoryColor={activeCategory.color} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function OutilsPage() {
  return (
    <Suspense fallback={null}>
      <OutilsPageInner />
    </Suspense>
  );
}
