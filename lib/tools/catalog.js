import { CONTENT_CATEGORIES } from './catalog/content.js';
import { ORGANIZATION_CATEGORIES } from './catalog/organization.js';
import { SYSTEM_CATEGORIES } from './catalog/system.js';
import { WEB_CATEGORIES } from './catalog/web.js';

const CATEGORY_ORDER = [
  'infographie', 'documents', 'fichiers', 'web', 'pc', 'calendar', 'cloud', 'taches',
  'memoire', 'reseau', 'ocr', 'email', 'ssh', 'archives', 'voix', 'utilitaires', 'donnees',
];
const CATEGORIES = [
  ...CONTENT_CATEGORIES,
  ...SYSTEM_CATEGORIES,
  ...ORGANIZATION_CATEGORIES,
  ...WEB_CATEGORIES,
].sort((left, right) => CATEGORY_ORDER.indexOf(left.id) - CATEGORY_ORDER.indexOf(right.id));

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

export {
  CATEGORIES,
  GROUPS,
  SYNTHETIC_CATEGORIES,
  applyOverride,
  groupOf,
  pickAutoIcon,
  pickCategoryId,
  prettifyToolId,
  schemaToParams,
};
