'use client';
import { useState, useEffect, useCallback } from 'react';

const BACKEND_URL = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));

// ── Liste des outils disponibles pour les steps ──────────────────────────────

const TOOL_OPTIONS = [
  // Réseau
  { name: 'net_ping',          label: '📶 Ping',              args: [{ key: 'host',    label: 'Hôte',     default: 'google.com' }] },
  { name: 'net_port_scan',     label: '🔌 Scan de ports',     args: [{ key: 'host',    label: 'Hôte',     default: '' }, { key: 'ports', label: 'Ports (ex: 80,443)', default: '80,443' }] },
  { name: 'net_dns_lookup',    label: '🌐 DNS Lookup',        args: [{ key: 'host', label: 'Hôte', default: '' }] },
  { name: 'net_traceroute',    label: '🗺️ Traceroute',        args: [{ key: 'host',    label: 'Hôte',     default: '' }] },
  { name: 'net_scan_local',    label: '🔍 Scan réseau local', args: [] },
  { name: 'net_whois',         label: '🔎 Whois',             args: [{ key: 'host', label: 'Hôte', default: '' }] },
  // Système
  { name: 'pc_system_info',    label: '💻 Infos système',     args: [] },
  { name: 'pc_process_list',   label: '⚙️ Processus',         args: [{ key: 'sort_by', label: 'Tri',      default: 'memory' }] },
  { name: 'pc_run_command',    label: '🖥️ Commande shell',    args: [{ key: 'command', label: 'Commande', default: '' }, { key: 'confirmed', label: '(confirmé)', default: 'true' }] },
  { name: 'pc_run_powershell', label: '⚡ PowerShell',         args: [{ key: 'script',  label: 'Script',   default: '' }, { key: 'confirmed', label: '(confirmé)', default: 'true' }] },
  { name: 'pc_screenshot',     label: '📷 Capture écran',     args: [] },
  { name: 'pc_window_list',    label: '🪟 Fenêtres ouvertes', args: [] },
  { name: 'pc_notify',         label: '🔔 Notification',      args: [{ key: 'title', label: 'Titre', default: 'Marvin' }, { key: 'message', label: 'Message', default: '' }] },
  // Fichiers & données
  { name: 'file_list',         label: '📁 Lister dossier',    args: [{ key: 'path',    label: 'Chemin',   default: '~' }] },
  { name: 'file_read',         label: '📄 Lire fichier',      args: [{ key: 'path',    label: 'Chemin',   default: '' }] },
  { name: 'file_write',        label: '✏️ Écrire fichier',    args: [{ key: 'path',    label: 'Chemin',   default: '' }, { key: 'content', label: 'Contenu', default: '' }] },
  { name: 'csv_analyze',       label: '📊 Analyser CSV',      args: [{ key: 'path',    label: 'Chemin',   default: '' }, { key: 'action',  label: 'Action',  default: 'summary' }] },
  // Web & recherche
  { name: 'web_search',        label: '🔍 Recherche web',     args: [{ key: 'query',   label: 'Requête',  default: '' }] },
  { name: 'web_browse',        label: '🌐 Lire page web',     args: [{ key: 'url',     label: 'URL',      default: '' }] },
  // Utilitaires
  { name: 'weather',           label: '🌤️ Météo',             args: [{ key: 'city',    label: 'Ville',    default: 'Paris' }] },
  { name: 'calculator',        label: '🧮 Calculateur',       args: [{ key: 'expression', label: 'Expression', default: '' }] },
  { name: 'hash_compute',      label: '🔏 Hash SHA256',       args: [{ key: 'text',    label: 'Texte',    default: '' }, { key: 'algorithm', label: 'Algorithme', default: 'sha256' }] },
  // OCR & IA
  { name: 'ocr_extract',       label: '🔍 OCR image',         args: [{ key: 'image_path', label: 'Chemin image', default: '' }] },
  // Calendrier
  { name: 'calendar_list',     label: '📅 Calendrier',        args: [{ key: 'days',    label: 'Jours',    default: '7' }] },
  // Notes & mémoire
  { name: 'memory_save',       label: '🧠 Mémoriser',         args: [{ key: 'content', label: 'Contenu',  default: '' }] },
  { name: 'note_create',       label: '📝 Créer note',        args: [{ key: 'title',   label: 'Titre',    default: '' }, { key: 'content', label: 'Contenu', default: '' }] },
  // Section 16
  { name: 'pdf_read',          label: '📕 Lire un PDF',       args: [{ key: 'path',    label: 'Chemin',   default: '' }, { key: 'pages', label: 'Pages (ex: 1-3)', default: '' }] },
  { name: 'pdf_info',          label: '📕 Infos PDF',         args: [{ key: 'path',    label: 'Chemin',   default: '' }] },
  { name: 'xlsx_read',         label: '📗 Lire Excel',        args: [{ key: 'path',    label: 'Chemin',   default: '' }, { key: 'action', label: 'Action', default: 'read' }] },
  { name: 'url_analyze',       label: '🔗 Analyser URL',      args: [{ key: 'url',     label: 'URL',      default: '' }] },
  { name: 'zip_list',          label: '🗜️ Lister ZIP',        args: [{ key: 'path',    label: 'Chemin',   default: '' }] },
  { name: 'color_tool',        label: '🎨 Couleur',           args: [{ key: 'color',   label: 'Couleur',  default: '' }] },
  { name: 'ip_info',           label: '🌍 Infos IP',          args: [{ key: 'ip',      label: 'Adresse IP', default: '' }] },
  // Section 17
  { name: 'sqlite_tables',     label: '🗃️ Tables SQLite',     args: [{ key: 'db_path', label: 'Chemin DB', default: '' }] },
  { name: 'sqlite_query',      label: '🗃️ Requête SQLite',    args: [{ key: 'db_path', label: 'Chemin DB', default: '' }, { key: 'query', label: 'SQL', default: 'SELECT * FROM sqlite_master' }] },
  { name: 'git_info',          label: '🌿 Infos Git',         args: [{ key: 'path',    label: 'Dossier',   default: '' }, { key: 'action', label: 'Action', default: 'status' }] },
];

const TOOL_MAP = Object.fromEntries(TOOL_OPTIONS.map(t => [t.name, t]));

// ── Composants helper ─────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const cfg = {
    success: { bg: 'rgba(34,197,94,0.15)', color: '#22c55e', label: '✅ Succès' },
    failed:  { bg: 'rgba(239,68,68,0.15)', color: '#ef4444', label: '❌ Échoué' },
    running: { bg: 'rgba(79, 140, 255,0.15)', color: '#4f8cff', label: '⏳ En cours' },
  }[status] || { bg: 'rgba(100,116,139,0.15)', color: '#64748b', label: status || '—' };
  return (
    <span style={{ background: cfg.bg, color: cfg.color, padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: 600 }}>
      {cfg.label}
    </span>
  );
}

// ── Step editor card ──────────────────────────────────────────────────────────

function StepCard({ step, index, total, onChange, onDelete, onMoveUp, onMoveDown }) {
  const toolDef = TOOL_MAP[step.tool_name] || null;

  return (
    <div style={{
      background: step.enabled ? 'var(--bg-glass)' : 'rgba(255,255,255,0.02)',
      border: `1px solid ${step.enabled ? 'rgba(79, 140, 255,0.15)' : 'var(--border)'}`,
      borderRadius: 'var(--radius-md)',
      padding: '14px 16px',
      opacity: step.enabled ? 1 : 0.5,
      transition: 'all 0.2s',
    }}>
      {/* En-tête step */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: toolDef && toolDef.args.length > 0 ? '12px' : 0 }}>
        {/* Numéro */}
        <div style={{
          width: '26px', height: '26px', borderRadius: '50%', flexShrink: 0,
          background: 'var(--accent-gradient)', color: 'white',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '12px', fontWeight: 700,
        }}>
          {index + 1}
        </div>

        {/* Sélecteur outil */}
        <select
          value={step.tool_name}
          onChange={e => {
            const tool = TOOL_MAP[e.target.value];
            const defaultArgs = {};
            (tool?.args || []).forEach(a => { defaultArgs[a.key] = a.default; });
            onChange({ ...step, tool_name: e.target.value, args: defaultArgs });
          }}
          style={{
            flex: 1, background: 'var(--bg-primary)', border: '1px solid var(--border)',
            borderRadius: '6px', color: 'var(--text-primary)', padding: '6px 10px',
            fontSize: 'var(--font-sm)',
          }}
        >
          <option value="">— Choisir un outil —</option>
          {TOOL_OPTIONS.map(t => (
            <option key={t.name} value={t.name}>{t.label}</option>
          ))}
        </select>

        {/* Label personnalisé */}
        <input
          value={step.label || ''}
          onChange={e => onChange({ ...step, label: e.target.value })}
          placeholder="Étiquette (optionnel)"
          style={{
            width: '160px', background: 'var(--bg-primary)', border: '1px solid var(--border)',
            borderRadius: '6px', color: 'var(--text-muted)', padding: '6px 8px',
            fontSize: '12px',
          }}
        />

        {/* Actions */}
        <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
          <button onClick={() => onChange({ ...step, enabled: !step.enabled })}
            title={step.enabled ? 'Désactiver' : 'Activer'}
            style={{ background: 'none', border: '1px solid var(--border)', borderRadius: '6px', cursor: 'pointer', padding: '4px 8px', color: 'var(--text-muted)', fontSize: '12px' }}>
            {step.enabled ? '⏸' : '▶'}
          </button>
          <button onClick={onMoveUp} disabled={index === 0}
            style={{ background: 'none', border: '1px solid var(--border)', borderRadius: '6px', cursor: index === 0 ? 'not-allowed' : 'pointer', padding: '4px 8px', color: 'var(--text-muted)', opacity: index === 0 ? 0.3 : 1 }}>
            ↑
          </button>
          <button onClick={onMoveDown} disabled={index === total - 1}
            style={{ background: 'none', border: '1px solid var(--border)', borderRadius: '6px', cursor: index === total - 1 ? 'not-allowed' : 'pointer', padding: '4px 8px', color: 'var(--text-muted)', opacity: index === total - 1 ? 0.3 : 1 }}>
            ↓
          </button>
          <button onClick={onDelete}
            style={{ background: 'none', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '6px', cursor: 'pointer', padding: '4px 8px', color: '#ef4444', fontSize: '12px' }}>
            ×
          </button>
        </div>
      </div>

      {/* Arguments */}
      {toolDef && toolDef.args.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '8px', marginTop: '4px' }}>
          {toolDef.args.map(argDef => (
            <div key={argDef.key}>
              <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '3px' }}>
                {argDef.label}
              </label>
              <input
                value={step.args?.[argDef.key] ?? argDef.default}
                onChange={e => onChange({ ...step, args: { ...step.args, [argDef.key]: e.target.value } })}
                placeholder={argDef.default || `{{prev.${argDef.key}}}`}
                style={{
                  width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)',
                  borderRadius: '6px', color: 'var(--text-primary)', padding: '5px 8px',
                  fontSize: '12px', boxSizing: 'border-box',
                }}
              />
            </div>
          ))}
        </div>
      )}

      {/* Indication variable injection */}
      {index > 0 && (
        <div style={{ marginTop: '8px', fontSize: '10px', color: 'var(--text-muted)' }}>
          💡 Utilisez <code style={{ color: 'var(--accent-secondary)' }}>{'{{prev.KEY}}'}</code> pour injecter une valeur de l'étape précédente
        </div>
      )}
    </div>
  );
}

// ── Résultat d'exécution ──────────────────────────────────────────────────────

function RunResult({ run }) {
  const [open, setOpen] = useState(true);
  if (!run) return null;

  return (
    <div style={{
      background: run.status === 'success' ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)',
      border: `1px solid ${run.status === 'success' ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)'}`,
      borderRadius: 'var(--radius-md)',
      overflow: 'hidden',
    }}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 16px', cursor: 'pointer' }}
        onClick={() => setOpen(!open)}
      >
        <StatusBadge status={run.status} />
        <span style={{ fontSize: 'var(--font-sm)', fontWeight: 600, flex: 1 }}>
          Exécution — {run.duration_ms}ms
        </span>
        <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div style={{ padding: '0 16px 14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {(run.steps_results || []).map((sr, i) => (
            <div key={i} style={{
              background: 'var(--bg-primary)',
              borderRadius: '6px',
              padding: '10px 12px',
              border: `1px solid ${sr.skipped ? 'var(--border)' : sr.success ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)'}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: sr.skipped ? 0 : '6px' }}>
                <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)' }}>#{i + 1}</span>
                <span style={{ fontSize: 'var(--font-xs)', fontWeight: 600 }}>{sr.tool_name || '—'}</span>
                {sr.skipped ? (
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)', marginLeft: 'auto' }}>⏭ Ignoré</span>
                ) : (
                  <>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)', marginLeft: 'auto' }}>{sr.duration_ms}ms</span>
                    <StatusBadge status={sr.success ? 'success' : 'failed'} />
                  </>
                )}
              </div>
              {!sr.skipped && sr.result && (
                <pre style={{
                  margin: 0, fontSize: '11px', color: 'var(--text-secondary)',
                  background: 'rgba(0,0,0,0.2)', borderRadius: '4px', padding: '6px 8px',
                  overflow: 'auto', maxHeight: '140px', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                }}>
                  {JSON.stringify(sr.result, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Page principale ───────────────────────────────────────────────────────────

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState([]);
  const [selected, setSelected] = useState(null); // workflow courant
  const [editing, setEditing] = useState(false);  // mode éditeur
  const [editSteps, setEditSteps] = useState([]);
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchWorkflows = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/workflows`);
      if (res.ok) setWorkflows(await res.json());
    } catch { }
    setLoading(false);
  }, []);

  useEffect(() => { fetchWorkflows(); }, [fetchWorkflows]);

  const fetchHistory = useCallback(async (wid) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/workflows/${wid}/runs?limit=10`);
      if (res.ok) setHistory(await res.json());
    } catch { }
  }, []);

  useEffect(() => {
    if (selected) fetchHistory(selected.id);
  }, [selected, fetchHistory]);

  // ── CRUD ──────────────────────────────────────────────────────────────────────

  function startCreate() {
    setSelected(null);
    setEditName('Nouveau workflow');
    setEditDesc('');
    setEditSteps([]);
    setEditing(true);
    setLastRun(null);
  }

  function startEdit(wf) {
    setSelected(wf);
    setEditName(wf.name);
    setEditDesc(wf.description || '');
    setEditSteps(JSON.parse(JSON.stringify(wf.steps || [])));
    setEditing(true);
    setLastRun(null);
  }

  async function saveWorkflow() {
    const payload = { name: editName, description: editDesc, steps: editSteps };
    let res;
    if (selected?.id) {
      res = await fetch(`${BACKEND_URL}/api/workflows/${selected.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
    } else {
      res = await fetch(`${BACKEND_URL}/api/workflows`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
    }
    if (res.ok) {
      const saved = await res.json();
      setSelected(saved);
      setEditing(false);
      fetchWorkflows();
    }
  }

  async function deleteWorkflow(wf) {
    if (!confirm(`Supprimer le workflow "${wf.name}" ?`)) return;
    await fetch(`${BACKEND_URL}/api/workflows/${wf.id}`, { method: 'DELETE' });
    if (selected?.id === wf.id) { setSelected(null); setEditing(false); }
    fetchWorkflows();
  }

  // ── Exécution ─────────────────────────────────────────────────────────────────

  async function runWorkflow(wid) {
    setRunning(true);
    setLastRun(null);
    try {
      const res = await fetch(`${BACKEND_URL}/api/workflows/${wid}/run`, { method: 'POST' });
      const data = await res.json();
      setLastRun(data);
      fetchHistory(wid);
      fetchWorkflows();
    } catch (e) {
      setLastRun({ status: 'failed', steps_results: [{ tool_name: 'Erreur', result: { error: String(e) }, success: false, duration_ms: 0 }], duration_ms: 0 });
    } finally {
      setRunning(false);
    }
  }

  // ── Steps editor helpers ──────────────────────────────────────────────────────

  function addStep() {
    const tool = TOOL_OPTIONS[0];
    const defaultArgs = {};
    (tool.args || []).forEach(a => { defaultArgs[a.key] = a.default; });
    setEditSteps(prev => [...prev, {
      id: crypto.randomUUID(),
      tool_name: tool.name,
      args: defaultArgs,
      label: '',
      enabled: true,
    }]);
  }

  function updateStep(idx, newStep) {
    setEditSteps(prev => prev.map((s, i) => i === idx ? newStep : s));
  }

  function deleteStep(idx) {
    setEditSteps(prev => prev.filter((_, i) => i !== idx));
  }

  function moveStep(idx, dir) {
    setEditSteps(prev => {
      const arr = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= arr.length) return arr;
      [arr[idx], arr[target]] = [arr[target], arr[idx]];
      return arr;
    });
  }

  // ── Rendu ─────────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* ══ Panneau gauche : liste workflows ══ */}
      <div style={{
        width: '300px', flexShrink: 0,
        borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column',
        background: '#0d0d0d',
      }}>
        <div style={{ padding: '16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0, fontSize: 'var(--font-base)', fontWeight: 700 }}>⚡ Workflows</h2>
          <button className="btn btn-primary" onClick={startCreate} style={{ padding: '6px 12px', fontSize: 'var(--font-xs)' }}>+ Nouveau</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
          {loading ? (
            [1,2,3].map(i => <div key={i} className="skeleton" style={{ height: '68px', marginBottom: '6px' }} />)
          ) : workflows.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 16px', color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
              <div style={{ fontSize: '2rem', marginBottom: '8px' }}>⚡</div>
              Aucun workflow.
              <br />Créez-en un pour enchaîner des outils.
            </div>
          ) : (
            workflows.map(wf => (
              <div
                key={wf.id}
                onClick={() => { setSelected(wf); setEditing(false); setLastRun(null); fetchHistory(wf.id); }}
                style={{
                  padding: '12px', borderRadius: 'var(--radius-md)', marginBottom: '4px',
                  cursor: 'pointer',
                  background: selected?.id === wf.id ? 'rgba(79, 140, 255,0.08)' : 'transparent',
                  border: `1px solid ${selected?.id === wf.id ? 'rgba(79, 140, 255,0.25)' : 'transparent'}`,
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => { if (selected?.id !== wf.id) e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; }}
                onMouseLeave={e => { if (selected?.id !== wf.id) e.currentTarget.style.background = 'transparent'; }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
                  <span style={{ fontWeight: 600, fontSize: 'var(--font-sm)', color: selected?.id === wf.id ? 'var(--accent-primary)' : 'var(--text-primary)' }}>
                    {wf.name}
                  </span>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button
                      onClick={e => { e.stopPropagation(); startEdit(wf); }}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: '12px', padding: '2px 4px' }}
                      title="Modifier"
                    >✏️</button>
                    <button
                      onClick={e => { e.stopPropagation(); deleteWorkflow(wf); }}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)', fontSize: '12px', padding: '2px 4px' }}
                      title="Supprimer"
                    >🗑️</button>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: 'var(--text-muted)' }}>
                  <span>⚙️ {wf.steps?.length || 0} étape{wf.steps?.length > 1 ? 's' : ''}</span>
                  {wf.run_count > 0 && <span>▶ {wf.run_count}×</span>}
                  {wf.last_status && <StatusBadge status={wf.last_status} />}
                </div>
                {wf.description && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{wf.description}</div>}
              </div>
            ))
          )}
        </div>
      </div>

      {/* ══ Panneau droit : éditeur / détail ══ */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* ── Éditeur ── */}
        {editing ? (
          <>
            <div className="page-header" style={{ borderBottom: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
                <input
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  style={{
                    background: 'transparent', border: 'none', outline: 'none',
                    color: 'var(--text-primary)', fontSize: '1.2rem', fontWeight: 700,
                    flex: 1,
                  }}
                  placeholder="Nom du workflow"
                />
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-secondary" onClick={() => setEditing(false)}>Annuler</button>
                <button className="btn btn-primary" onClick={saveWorkflow} disabled={!editName.trim() || editSteps.length === 0}>
                  💾 Sauvegarder
                </button>
              </div>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <input
                value={editDesc}
                onChange={e => setEditDesc(e.target.value)}
                placeholder="Description (optionnel)"
                style={{
                  background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)', padding: '10px 14px',
                  color: 'var(--text-muted)', fontSize: 'var(--font-sm)',
                }}
              />

              {/* Étapes */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {editSteps.map((step, idx) => (
                  <StepCard
                    key={step.id}
                    step={step}
                    index={idx}
                    total={editSteps.length}
                    onChange={ns => updateStep(idx, ns)}
                    onDelete={() => deleteStep(idx)}
                    onMoveUp={() => moveStep(idx, -1)}
                    onMoveDown={() => moveStep(idx, 1)}
                  />
                ))}
              </div>

              <button
                onClick={addStep}
                style={{
                  padding: '12px', borderRadius: 'var(--radius-md)',
                  border: '2px dashed rgba(79, 140, 255,0.3)',
                  background: 'transparent', color: 'var(--accent-primary)',
                  cursor: 'pointer', fontSize: 'var(--font-sm)', fontWeight: 600,
                  transition: 'all 0.2s',
                }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(79, 140, 255,0.6)'; e.currentTarget.style.background = 'rgba(79, 140, 255,0.04)'; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(79, 140, 255,0.3)'; e.currentTarget.style.background = 'transparent'; }}
              >
                + Ajouter une étape
              </button>

              {editSteps.length === 0 && (
                <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
                  <div style={{ fontSize: '2.5rem', marginBottom: '10px' }}>🔗</div>
                  Ajoutez des étapes pour construire votre workflow.
                  <br />Chaque étape exécute un outil. Utilisez <code style={{ color: 'var(--accent-secondary)' }}>{'{{prev.KEY}}'}</code> pour chaîner les sorties.
                </div>
              )}
            </div>
          </>
        ) : selected ? (
          /* ── Détail workflow ── */
          <>
            <div className="page-header" style={{ borderBottom: '1px solid var(--border)' }}>
              <div>
                <h1 style={{ marginBottom: '2px' }}>{selected.name}</h1>
                {selected.description && <p style={{ margin: 0, fontSize: 'var(--font-sm)', color: 'var(--text-muted)' }}>{selected.description}</p>}
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-secondary" onClick={() => startEdit(selected)} style={{ fontSize: 'var(--font-xs)' }}>✏️ Modifier</button>
                <button
                  className="btn btn-primary"
                  onClick={() => runWorkflow(selected.id)}
                  disabled={running || !selected.steps?.length}
                  style={{ fontSize: 'var(--font-xs)', minWidth: '100px' }}
                >
                  {running ? '⏳ En cours…' : '▶ Exécuter'}
                </button>
              </div>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Steps en lecture seule */}
              <div>
                <h3 style={{ fontSize: 'var(--font-sm)', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '10px' }}>
                  Étapes — {selected.steps?.length || 0}
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {(selected.steps || []).map((step, idx) => {
                    const toolDef = TOOL_MAP[step.tool_name];
                    return (
                      <div key={step.id} style={{
                        display: 'flex', alignItems: 'flex-start', gap: '12px',
                        padding: '12px 14px',
                        background: step.enabled ? 'var(--bg-glass)' : 'rgba(255,255,255,0.02)',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
                        opacity: step.enabled ? 1 : 0.45,
                      }}>
                        <div style={{
                          width: '24px', height: '24px', borderRadius: '50%', flexShrink: 0,
                          background: 'var(--accent-gradient)', color: 'white',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: '11px', fontWeight: 700, marginTop: '1px',
                        }}>
                          {idx + 1}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 600, fontSize: 'var(--font-sm)', marginBottom: '2px' }}>
                            {step.label || toolDef?.label || step.tool_name}
                            {!step.enabled && <span style={{ marginLeft: '8px', fontSize: '10px', color: 'var(--text-muted)' }}>(désactivé)</span>}
                          </div>
                          {Object.keys(step.args || {}).length > 0 && (
                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '4px' }}>
                              {Object.entries(step.args).map(([k, v]) => v ? (
                                <span key={k} style={{
                                  fontSize: '10px', padding: '2px 7px',
                                  background: 'rgba(79, 140, 255,0.1)', borderRadius: '10px',
                                  color: 'var(--accent-primary)',
                                }}>
                                  {k}: {String(v).length > 30 ? String(v).slice(0, 30) + '…' : v}
                                </span>
                              ) : null)}
                            </div>
                          )}
                        </div>
                        {idx < (selected.steps?.length - 1) && (
                          <div style={{ alignSelf: 'flex-end', color: 'var(--text-muted)', fontSize: '12px', paddingBottom: '0px' }}>→</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Résultat de la dernière exécution */}
              {lastRun && (
                <div>
                  <h3 style={{ fontSize: 'var(--font-sm)', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '10px' }}>
                    Résultat
                  </h3>
                  <RunResult run={lastRun} />
                </div>
              )}

              {/* Historique des runs */}
              {history.length > 0 && (
                <div>
                  <h3 style={{ fontSize: 'var(--font-sm)', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '10px' }}>
                    Historique récent
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {history.slice(0, 8).map(run => (
                      <div key={run.id} style={{
                        display: 'flex', alignItems: 'center', gap: '10px',
                        padding: '8px 12px', background: 'var(--bg-glass)',
                        borderRadius: 'var(--radius-md)', border: '1px solid var(--border)',
                        fontSize: 'var(--font-xs)',
                      }}>
                        <StatusBadge status={run.status} />
                        <span style={{ color: 'var(--text-muted)', flex: 1 }}>
                          {new Date((run.started_at || '').replace(' ', 'T') + 'Z').toLocaleString('fr-FR')}
                        </span>
                        <span style={{ color: 'var(--text-muted)' }}>{run.duration_ms}ms</span>
                        <span style={{ color: 'var(--text-muted)' }}>{run.steps_results?.length || 0} étapes</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          /* ── État vide ── */
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '16px', color: 'var(--text-muted)' }}>
            <div style={{ fontSize: '4rem' }}>⚡</div>
            <h2 style={{ margin: 0 }}>Workflows</h2>
            <p style={{ margin: 0, textAlign: 'center', maxWidth: '380px', fontSize: 'var(--font-sm)' }}>
              Enchaînez des outils pour automatiser vos tâches. Chaque étape peut passer ses résultats à la suivante.
            </p>
            <button className="btn btn-primary" onClick={startCreate}>+ Créer un workflow</button>
          </div>
        )}
      </div>
    </div>
  );
}
