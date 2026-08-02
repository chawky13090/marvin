export const ORGANIZATION_CATEGORIES = [
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
];
