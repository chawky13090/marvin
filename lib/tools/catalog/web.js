export const WEB_CATEGORIES = [
  {
    id: 'web', label: 'Web', icon: '🌐', color: '#06b6d4',
    description: 'Recherchez sur Internet et lisez des pages web.',
    tools: [
      {
        id: 'web_search', icon: '🔍', name: 'Recherche web',
        description: 'Effectue une recherche via SearXNG et retourne titres, URLs et extraits.',
        tips: ['Utilise exclusivement SearXNG', 'Retourne jusqu\'à 20 résultats', 'Aucun fallback direct vers un moteur tiers'],
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
