'use client';

import { useState } from 'react';

/**
 * Rendu PROPRE et présentable d'un résultat d'outil (au lieu du JSON brut).
 * Gère objets imbriqués, listes, et formate les valeurs courantes. Réutilisable
 * dans le chat (MessageBubble::ToolCallInline, fallback générique) ET la page Outils.
 */

const KEY_LABELS = {
  message: 'Message', path: 'Chemin', file: 'Fichier', files: 'Fichiers', name: 'Nom',
  size_kb: 'Taille', size: 'Taille', size_mb: 'Taille', count: 'Nombre', pages: 'Pages',
  total_pages: 'Pages totales', pages_read: 'Pages lues', chars: 'Caractères',
  formatted: 'Date / heure', local: 'Heure locale', utc: 'UTC', timezone: 'Fuseau horaire',
  weekday: 'Jour', city: 'Ville', country: 'Pays', region: 'Région', title: 'Titre',
  status: 'Statut', url: 'URL', link: 'Lien', results: 'Résultats', events: 'Événements',
  tasks: 'Tâches', notes: 'Notes', hash: 'Empreinte', algorithm: 'Algorithme',
  extension: 'Extension', modified: 'Modifié le', created_at: 'Créé le', start: 'Début',
  end: 'Fin', start_at: 'Début', end_at: 'Fin', location: 'Lieu', description: 'Description',
  username: "Nom d'utilisateur", home: 'Dossier personnel', desktop: 'Bureau',
  documents: 'Documents', downloads: 'Téléchargements', pictures: 'Images', music: 'Musique',
  videos: 'Vidéos', drive: 'Lecteur', paths: 'Chemins', summary: 'Résumé', answer: 'Réponse',
  sources: 'Sources', temperature: 'Température', humidity: 'Humidité', wind: 'Vent',
  snippet: 'Extrait', text: 'Texte', content: 'Contenu', email: 'Email', from: 'De',
  subject: 'Objet', date: 'Date', priority: 'Priorité', due_date: 'Échéance', tags: 'Étiquettes',
  desktop_contents: 'Contenu du bureau', cpu_percent: 'Processeur', ram_used_gb: 'RAM utilisée',
  ram_total_gb: 'RAM totale', ram_percent: 'RAM', disk_free_gb: 'Disque libre', disk_total_gb: 'Disque total',
  disk_percent: 'Disque', uptime: 'Allumé depuis', model: 'Modèle', version: 'Version', os: 'Système',
  hostname: 'Nom du PC', cpu: 'Processeur', ram: 'Mémoire', gpu: 'Carte graphique', vram_gb: 'VRAM',
  account: 'Compte', folder: 'Dossier', score: 'Score', total: 'Total', errors: 'Erreurs',
  // Devis / factures (billing_*)
  total_ht: 'Total HT', total_ttc: 'Total TTC', tva_rate: 'Taux TVA', tva_amount: 'TVA',
  amount_paid: 'Montant payé', total_unpaid_ttc: 'Impayé', unit_price: 'Prix unitaire',
  client_name: 'Client', client_type: 'Type de client', contact_name: 'Contact',
  contact_email: 'Email contact', contact_phone: 'Téléphone', siret: 'SIRET',
  previous_provider: 'Ancien prestataire', previous_amount: 'Ancien montant',
  payment_method: 'Moyen de paiement', paid_date: 'Payé le', is_overdue: 'Retard',
  overdue_count: 'Factures en retard', items: 'Lignes', qty: 'Quantité', label: 'Intitulé',
  // Diagnostics Windows (win_*)
  DisplayName: 'Nom affiché', StartType: 'Démarrage', Status: 'Statut', TaskName: 'Tâche',
  TaskPath: 'Chemin', State: 'État', InterfaceDescription: 'Interface', LinkSpeed: 'Débit',
  Manufacturer: 'Fabricant', Model: 'Modèle', SerialNumber: 'N° de série',
};

// Clés purement techniques → masquées par défaut (toujours visibles via « détails »)
const HIDDEN = new Set(['success', 'requiresConfirmation', 'needsClarification', 'pending',
  'ok', 'method', 'scope', 'hint', 'unix', 'colorId', 'target', 'elapsed_ms', 'id', 'doc_id',
  'external_id', 'reminded', 'all_day', 'toolCallId']);

// Champs monétaires → formatés en euros plutôt qu'en nombre brut.
const CURRENCY_KEYS = new Set(['total_ht', 'total_ttc', 'unit_price', 'amount_paid',
  'previous_amount', 'tva_amount', 'total_unpaid_ttc', 'price', 'montant', 'subtotal']);

// Statuts connus (devis/factures/services Windows) → puce colorée au lieu de texte brut.
const STATUS_COLORS = {
  paid: '#34d399', payée: '#34d399', running: '#34d399', accepted: '#34d399', acceptée: '#34d399',
  sent: '#60a5fa', envoyée: '#60a5fa', ready: '#60a5fa',
  partial: '#eab308', partielle: '#eab308', pending: '#eab308',
  overdue: '#f87171', 'en retard': '#f87171', stopped: '#f87171', cancelled: '#f87171',
  refusée: '#f87171', disabled: '#9ca3af', draft: '#9ca3af', brouillon: '#9ca3af',
};

function humanize(k) {
  return KEY_LABELS[k] || k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

function fmtCurrency(v) {
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (typeof n !== 'number' || isNaN(n)) return String(v);
  return n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
}

function isDateStr(s) {
  return typeof s === 'string' && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s);
}
function fmtDate(s) {
  try {
    let iso = s.replace(' ', 'T');
    // La quasi-totalité des dates renvoyées par les outils viennent du backend Python
    // (SQLite `datetime('now')`, UTC naïf, sans fuseau) — sans indication explicite de
    // fuseau, le navigateur les interprète comme une heure LOCALE, décalant l'affichage
    // de l'écart UTC de l'utilisateur. On force UTC avec 'Z', SAUF si la chaîne porte déjà
    // un fuseau explicite (Z ou +HH:MM/-HH:MM, ex. dates d'emails/calendrier déjà correctes).
    if (!/[Zz]$/.test(iso) && !/[+-]\d{2}:?\d{2}$/.test(iso)) iso += 'Z';
    const d = new Date(iso);
    if (isNaN(d)) return s;
    return d.toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
  } catch { return s; }
}
function looksLikePath(s) {
  return typeof s === 'string' && /[\\/].+[\\/]|^[A-Za-z]:\\/.test(s);
}

const C = {
  row: { display: 'flex', gap: 10, padding: '3px 0', alignItems: 'baseline', flexWrap: 'wrap' },
  key: { fontSize: 12, color: 'var(--text-muted)', minWidth: 110, flexShrink: 0 },
  val: { fontSize: 13, color: 'var(--text-primary)', wordBreak: 'break-word', flex: 1, minWidth: 0 },
  mono: { fontFamily: 'monospace', fontSize: 12 },
  sub: { borderLeft: '2px solid var(--border)', paddingLeft: 12, marginTop: 2 },
  chip: { display: 'inline-block', padding: '1px 8px', borderRadius: 12, background: 'rgba(255,255,255,0.06)', fontSize: 12, margin: '2px 4px 2px 0' },
};

function Value({ v, k, depth }) {
  if (v === null || v === undefined || v === '') return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  if (k === 'is_overdue' && v === true) {
    return <span style={{ color: '#f87171', fontWeight: 600 }}>⚠️ En retard</span>;
  }
  if (typeof v === 'boolean') return <span style={{ color: v ? '#34d399' : '#f87171' }}>{v ? '✓ oui' : '✗ non'}</span>;
  if (typeof v === 'number') {
    if (CURRENCY_KEYS.has(k)) return <span>{fmtCurrency(v)}</span>;
    if (/_kb$/.test(k || '')) return <span>{v < 1024 ? `${Math.round(v)} Ko` : `${(v / 1024).toFixed(1)} Mo`}</span>;
    if (k === 'tva_rate') return <span>{v}%</span>;
    return <span>{v.toLocaleString('fr-FR')}</span>;
  }
  if (typeof v === 'string') {
    if ((k === 'status' || k === 'Status' || k === 'State') && STATUS_COLORS[v.toLowerCase()]) {
      const color = STATUS_COLORS[v.toLowerCase()];
      return <span style={{ ...C.chip, background: `${color}22`, color, fontWeight: 600 }}>{v}</span>;
    }
    if (CURRENCY_KEYS.has(k)) return <span>{fmtCurrency(v)}</span>;
    if (isDateStr(v)) return <span>{fmtDate(v)}</span>;
    const long = v.length > 600;
    const txt = long ? v.slice(0, 600) + '…' : v;
    return <span style={looksLikePath(v) ? C.mono : { whiteSpace: 'pre-wrap' }}>{txt}</span>;
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return <span style={{ color: 'var(--text-muted)' }}>aucun</span>;
    // tableau de primitives → chips ; tableau d'objets → sous-cartes
    if (v.every((x) => typeof x !== 'object' || x === null)) {
      return <span>{v.slice(0, 40).map((x, i) => <span key={i} style={C.chip}>{String(x)}</span>)}{v.length > 40 && <span style={{ color: 'var(--text-muted)' }}>+{v.length - 40}</span>}</span>;
    }
    return (
      <div style={{ width: '100%' }}>
        {v.slice(0, 25).map((item, i) => (
          <div key={i} style={{ ...C.sub, marginBottom: 6 }}><ObjectRows obj={item} depth={depth + 1} /></div>
        ))}
        {v.length > 25 && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>+{v.length - 25} de plus…</div>}
      </div>
    );
  }
  if (typeof v === 'object') {
    return <div style={C.sub}><ObjectRows obj={v} depth={depth + 1} /></div>;
  }
  return <span>{String(v)}</span>;
}

function ObjectRows({ obj, depth = 0 }) {
  if (obj === null || typeof obj !== 'object') return <Value v={obj} depth={depth} />;
  const entries = Object.entries(obj).filter(([k, val]) => !HIDDEN.has(k) && val !== null && val !== '');
  if (!entries.length) return null;
  // message en premier, mis en valeur
  entries.sort((a, b) => (a[0] === 'message' ? -1 : b[0] === 'message' ? 1 : 0));
  return (
    <div>
      {entries.map(([k, val]) => {
        if (k === 'message' && depth === 0) {
          return <div key={k} style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>{String(val)}</div>;
        }
        return (
          <div key={k} style={C.row}>
            <span style={C.key}>{humanize(k)}</span>
            <span style={C.val}><Value v={val} k={k} depth={depth} /></span>
          </div>
        );
      })}
    </div>
  );
}

export default function PrettyResult({ result }) {
  const [raw, setRaw] = useState(false);
  if (result === null || result === undefined) return null;
  if (typeof result === 'string') {
    return <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', color: 'var(--text-primary)' }}>{result}</div>;
  }
  const data = (result.result && typeof result.result === 'object') ? result.result : result;
  const err = data.error || result.error;
  return (
    <div>
      {err
        ? <div style={{ fontSize: 13, color: '#f87171' }}>❌ {String(err)}</div>
        : <ObjectRows obj={data} />}
      <button onClick={() => setRaw(!raw)}
        style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0, textDecoration: 'underline' }}>
        {raw ? '✨ Affichage lisible' : '{ } Voir en JSON'}
      </button>
      {raw && (
        <pre style={{ marginTop: 6, fontSize: 11, background: 'rgba(0,0,0,0.3)', padding: 10, borderRadius: 8, overflowX: 'auto', color: 'var(--text-secondary)' }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}
