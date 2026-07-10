'use client';
import { useState, useEffect, useCallback } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';

const BACKEND = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));

// Outils disponibles pour le planificateur (les plus utiles)
const SCHEDULABLE_TOOLS = [
  // Système & PC
  { id: 'pc_system_info',    label: '💻 Infos système',        args: [] },
  { id: 'pc_process_list',   label: '⚙️ Processus actifs',     args: [] },
  { id: 'pc_screenshot',     label: '📸 Capture d\'écran',     args: [{ name: 'output_path', label: 'Dossier', placeholder: 'Bureau (défaut)' }] },
  { id: 'pc_run_command',    label: '🖥️ Commande shell',        args: [{ name: 'command', label: 'Commande', placeholder: 'ipconfig' }, { name: 'confirmed', label: 'Confirmé', type: 'hidden', default: 'true' }] },
  { id: 'pc_run_powershell', label: '⚡ Script PowerShell',     args: [{ name: 'script', label: 'Script', placeholder: 'Get-Date' }, { name: 'confirmed', label: 'Confirmé', type: 'hidden', default: 'true' }] },
  // Réseau
  { id: 'net_ping',          label: '📡 Ping',                 args: [{ name: 'host', label: 'Hôte', placeholder: '8.8.8.8' }, { name: 'count', label: 'Paquets', type: 'number', default: '2' }] },
  { id: 'net_scan_local',    label: '🏠 Scan réseau local',    args: [] },
  { id: 'net_port_scan',     label: '🔭 Scan de ports',        args: [{ name: 'host', label: 'Hôte', placeholder: '192.168.1.1' }, { name: 'ports', label: 'Ports', placeholder: '80,443,22,3389' }] },
  { id: 'net_dns_lookup',    label: '🌐 DNS Lookup',           args: [{ name: 'host', label: 'Hôte', placeholder: 'example.com' }] },
  // Web & contenu
  { id: 'web_search',        label: '🔍 Recherche web',        args: [{ name: 'query', label: 'Requête', placeholder: 'actualités tech' }] },
  { id: 'web_browse',        label: '🌐 Lire une URL',         args: [{ name: 'url', label: 'URL', placeholder: 'https://example.com' }] },
  // Fichiers & données
  { id: 'file_list',         label: '📁 Lister un dossier',    args: [{ name: 'path', label: 'Dossier', placeholder: 'C:\\Users\\Chawb\\Desktop' }] },
  { id: 'file_read',         label: '📄 Lire un fichier',      args: [{ name: 'path', label: 'Chemin', placeholder: '' }] },
  { id: 'csv_analyze',       label: '📊 Analyser un CSV',      args: [{ name: 'path', label: 'Chemin CSV', placeholder: '' }, { name: 'action', label: 'Action', placeholder: 'summary' }] },
  // Notes, tâches & mémoire
  { id: 'task_list',         label: '✅ Lister les tâches',    args: [] },
  { id: 'memory_list',       label: '🧠 Mémoires',             args: [] },
  { id: 'note_list',         label: '📝 Lister les notes',     args: [] },
  // Calendrier
  { id: 'calendar_list',     label: '📅 Calendrier',           args: [{ name: 'days', label: 'Jours', type: 'number', default: '7' }] },
  // Météo
  { id: 'weather',           label: '🌤️ Météo',               args: [{ name: 'city', label: 'Ville', placeholder: 'Paris' }] },
  // Nouveaux outils Section 16
  { id: 'url_analyze',       label: '🔗 Analyser une URL',     args: [{ name: 'url', label: 'URL', placeholder: 'https://example.com' }] },
  { id: 'ip_info',           label: '🌍 Infos IP',             args: [{ name: 'ip', label: 'Adresse IP', placeholder: '8.8.8.8' }] },
  { id: 'zip_list',          label: '🗜️ Lister un ZIP',        args: [{ name: 'path', label: 'Chemin ZIP', placeholder: 'C:\\...\\archive.zip' }] },
];

const SCHEDULES = [
  { value: 'every 1 minutes',  label: '⚡ Chaque minute' },
  { value: 'every 5 minutes',  label: '🕐 Toutes les 5 min' },
  { value: 'every 15 minutes', label: '🕒 Toutes les 15 min' },
  { value: 'every 30 minutes', label: '🕕 Toutes les 30 min' },
  { value: 'every hour',       label: '🕐 Chaque heure' },
  { value: 'every 6 hours',    label: '🕕 Toutes les 6h' },
  { value: 'every day',        label: '📅 Chaque jour' },
  { value: 'daily at 08:00',   label: '🌅 Chaque jour à 8h' },
  { value: 'daily at 12:00',   label: '☀️ Chaque jour à 12h' },
  { value: 'daily at 18:00',   label: '🌆 Chaque jour à 18h' },
  { value: 'weekdays at 09:00',label: '💼 Jours ouvrés à 9h' },
  { value: 'weekdays at 18:00',label: '💼 Jours ouvrés à 18h' },
  { value: 'weekends at 10:00',label: '🏖️ Week-ends à 10h' },
  { value: 'every lundi at 09:00', label: '📆 Chaque lundi à 9h' },
  { value: 'every vendredi at 17:00', label: '📆 Chaque vendredi à 17h' },
  { value: 'monthly on day 1 at 09:00', label: '🗓️ Le 1er du mois à 9h' },
  { value: '__custom__',       label: '⚙️ Personnalisé (cron / texte)' },
];

function StatusDot({ enabled, lastResult }) {
  const hasError = lastResult && (() => { try { return JSON.parse(lastResult)?.error; } catch { return false; } })();
  const color = !enabled ? '#6b7280' : hasError ? '#ef4444' : '#22c55e';
  const shadow = !enabled ? 'none' : hasError ? '0 0 6px #ef444488' : '0 0 6px #22c55e88';
  return (
    <span style={{
      display: 'inline-block', width: '9px', height: '9px',
      borderRadius: '50%', background: color, boxShadow: shadow, flexShrink: 0,
    }} />
  );
}

function JobRow({ job, onToggle, onDelete, onRunNow }) {
  const [expanded, setExpanded] = useState(false);
  let lastResultParsed = null;
  try { lastResultParsed = job.last_result ? JSON.parse(job.last_result) : null; } catch {}

  const toolDef = SCHEDULABLE_TOOLS.find(t => t.id === job.tool_name);
  const schedLabel = SCHEDULES.find(s => s.value === job.schedule)?.label || job.schedule;

  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: `1px solid ${job.enabled ? 'rgba(79, 140, 255,0.2)' : 'rgba(255,255,255,0.06)'}`,
      borderRadius: '12px',
      overflow: 'hidden',
      transition: 'border-color 0.2s',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '14px 18px' }}>
        <StatusDot enabled={job.enabled} lastResult={job.last_result} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-primary)' }}>
              {job.name}
            </span>
            <span style={{
              fontSize: '10px', padding: '2px 8px', borderRadius: '10px',
              background: 'rgba(79, 140, 255,0.12)', color: '#4f8cff', fontFamily: 'monospace',
            }}>
              {toolDef?.label || job.tool_name}
            </span>
            <span style={{
              fontSize: '10px', padding: '2px 8px', borderRadius: '10px',
              background: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)',
            }}>
              {schedLabel}
            </span>
          </div>
          <div style={{ display: 'flex', gap: '16px', marginTop: '4px', flexWrap: 'wrap' }}>
            {job.last_run && (
              <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                Dernier : {new Date(job.last_run + 'Z').toLocaleString('fr-FR')}
              </span>
            )}
            {job.next_run && job.enabled && (
              <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                Prochain : {new Date(job.next_run + 'Z').toLocaleString('fr-FR')}
              </span>
            )}
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
              ×{job.run_count || 0} exécutions
            </span>
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
          <button
            onClick={() => onRunNow(job)}
            title="Exécuter maintenant"
            style={btnStyle('#4f8cff')}
          >▶</button>
          <button
            onClick={() => onToggle(job)}
            title={job.enabled ? 'Désactiver' : 'Activer'}
            style={btnStyle(job.enabled ? '#22c55e' : '#6b7280')}
          >
            {job.enabled ? '⏸' : '▶'}
          </button>
          <button
            onClick={() => setExpanded(e => !e)}
            title="Détails"
            style={btnStyle('#3b82f6')}
          >
            {expanded ? '▲' : '▼'}
          </button>
          <button
            onClick={() => onDelete(job.id)}
            title="Supprimer"
            style={btnStyle('#ef4444')}
          >✕</button>
        </div>
      </div>

      {/* Détails expandables */}
      {expanded && (
        <div style={{
          padding: '12px 18px 16px',
          borderTop: '1px solid rgba(255,255,255,0.06)',
          background: 'rgba(0,0,0,0.15)',
        }}>
          {job.args && Object.keys(job.args).length > 0 && (
            <div style={{ marginBottom: '10px' }}>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px', letterSpacing: '0.05em' }}>PARAMÈTRES</div>
              <pre style={{ fontSize: '11px', color: 'var(--text-secondary)', fontFamily: 'monospace', margin: 0 }}>
                {JSON.stringify(job.args, null, 2)}
              </pre>
            </div>
          )}
          {lastResultParsed && (
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px', letterSpacing: '0.05em' }}>DERNIER RÉSULTAT</div>
              {lastResultParsed.error ? (
                <div style={{ color: '#f87171', fontSize: '11px' }}>⚠️ {lastResultParsed.error}</div>
              ) : (
                <pre style={{ fontSize: '11px', color: '#4ade80', fontFamily: 'monospace', margin: 0, maxHeight: '120px', overflowY: 'auto' }}>
                  {JSON.stringify(lastResultParsed, null, 2).slice(0, 600)}
                </pre>
              )}
            </div>
          )}
          {!job.last_run && <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Pas encore exécuté.</div>}
        </div>
      )}
    </div>
  );
}

function btnStyle(color) {
  return {
    width: '30px', height: '30px',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: `${color}15`, border: `1px solid ${color}40`,
    borderRadius: '8px', cursor: 'pointer', fontSize: '12px', color: color,
    transition: 'all 0.15s',
  };
}

// ── Formulaire création ─────────────────────────────────────────────────────
function CreateJobForm({ onCreated }) {
  const [name, setName] = useState('');
  const [toolId, setToolId] = useState(SCHEDULABLE_TOOLS[0].id);
  const [schedule, setSchedule] = useState(SCHEDULES[2].value);
  const [customSched, setCustomSched] = useState('');
  const [preview, setPreview] = useState(null);
  const [argValues, setArgValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const toolDef = SCHEDULABLE_TOOLS.find(t => t.id === toolId) || SCHEDULABLE_TOOLS[0];
  const effectiveSched = schedule === '__custom__' ? customSched : schedule;

  // Aperçu des prochaines exécutions (live)
  useEffect(() => {
    if (!effectiveSched?.trim()) { setPreview(null); return; }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${BACKEND}/api/cron/preview`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ schedule: effectiveSched }),
        });
        setPreview((await r.json()).next_runs || null);
      } catch { setPreview(null); }
    }, 350);
    return () => clearTimeout(t);
  }, [effectiveSched]);

  const handleCreate = async () => {
    if (!name.trim()) { setError('Donnez un nom au job.'); return; }
    setSaving(true);
    setError('');
    // Construire les args
    const args = {};
    toolDef.args.forEach(a => {
      const v = argValues[a.name] ?? a.default ?? '';
      if (v !== '') args[a.name] = a.type === 'number' ? Number(v) : v;
    });
    try {
      const res = await fetch(`${BACKEND}/api/cron`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), tool_name: toolId, args, schedule: effectiveSched }),
      });
      if (!res.ok) throw new Error(await res.text());
      const job = await res.json();
      onCreated(job);
      setName('');
      setArgValues({});
    } catch (e) {
      setError(e.message);
    }
    setSaving(false);
  };

  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      border: '1px solid rgba(79, 140, 255,0.25)',
      borderRadius: '14px',
      padding: '20px 24px',
    }}>
      <div style={{ fontWeight: 700, fontSize: '0.95rem', marginBottom: '18px', color: '#4f8cff' }}>
        ➕ Nouveau job planifié
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
        {/* Nom */}
        <div>
          <label style={labelStyle}>Nom du job *</label>
          <input
            value={name} onChange={e => setName(e.target.value)}
            placeholder="Ex: Ping quotidien Google"
            style={inputStyle}
          />
        </div>

        {/* Planning */}
        <div>
          <label style={labelStyle}>Planification</label>
          <select value={schedule} onChange={e => setSchedule(e.target.value)} style={inputStyle}>
            {SCHEDULES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          {schedule === '__custom__' && (
            <input value={customSched} onChange={e => setCustomSched(e.target.value)}
              placeholder="ex: 0 9 * * 1-5  ·  daily at 14:30  ·  every 2 hours  ·  weekdays at 8h"
              style={{ ...inputStyle, marginTop: 8, fontFamily: 'monospace' }} />
          )}
          {preview && preview.length > 0 && (
            <div style={{ marginTop: 8, padding: '8px 10px', background: 'rgba(79, 140, 255,0.07)',
              border: '1px solid rgba(79, 140, 255,0.2)', borderRadius: 6, fontSize: 11, color: 'var(--text-secondary)' }}>
              <span style={{ color: '#4f8cff', fontWeight: 700 }}>🕐 Prochaines exécutions :</span>{' '}
              {preview.slice(0, 4).join('  ·  ')}
            </div>
          )}
        </div>

        {/* Outil */}
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={labelStyle}>Outil à exécuter</label>
          <select
            value={toolId}
            onChange={e => { setToolId(e.target.value); setArgValues({}); }}
            style={inputStyle}
          >
            {SCHEDULABLE_TOOLS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </div>

        {/* Args dynamiques */}
        {toolDef.args.map(arg => (
          <div key={arg.name}>
            <label style={labelStyle}>{arg.label}</label>
            <input
              type={arg.type === 'number' ? 'number' : 'text'}
              value={argValues[arg.name] ?? arg.default ?? ''}
              onChange={e => setArgValues(prev => ({ ...prev, [arg.name]: e.target.value }))}
              placeholder={arg.placeholder || ''}
              style={inputStyle}
            />
          </div>
        ))}
      </div>

      {error && (
        <div style={{ marginTop: '12px', color: '#f87171', fontSize: '12px' }}>⚠️ {error}</div>
      )}

      <button
        onClick={handleCreate}
        disabled={saving || !name.trim()}
        style={{
          marginTop: '16px',
          padding: '10px 24px',
          background: name.trim() ? 'linear-gradient(135deg, #4f8cffcc, #4f8cff88)' : 'rgba(255,255,255,0.04)',
          color: name.trim() ? 'white' : 'var(--text-muted)',
          border: 'none', borderRadius: '10px',
          cursor: name.trim() ? 'pointer' : 'not-allowed',
          fontWeight: 700, fontSize: '0.875rem',
        }}
      >
        {saving ? '⏳ Création…' : '✓ Créer le job'}
      </button>
    </div>
  );
}

const labelStyle = {
  display: 'block', fontSize: '11px', fontWeight: 600,
  color: 'var(--text-muted)', marginBottom: '5px', letterSpacing: '0.04em',
};
const inputStyle = {
  width: '100%', padding: '8px 12px',
  background: 'var(--bg-primary)', border: '1px solid var(--border)',
  borderRadius: '8px', color: 'var(--text-primary)',
  fontSize: '0.875rem', outline: 'none', boxSizing: 'border-box',
};

// ══════════════════════════════════════════════════════════════════════════════
// Page principale
// ══════════════════════════════════════════════════════════════════════════════
export default function CronPage() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [runningId, setRunningId] = useState(null);
  const { toast: realToast } = useToast();
  const showToast = (msg, color = '#22c55e') => {
    (color === '#ef4444' ? realToast.error : realToast.success)(msg);
  };

  const fetchJobs = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND}/api/cron`);
      setJobs(await r.json());
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchJobs();
    const iv = setInterval(fetchJobs, 15000); // rafraîchit toutes les 15s
    return () => clearInterval(iv);
  }, [fetchJobs]);

  const handleToggle = async (job) => {
    await fetch(`${BACKEND}/api/cron/${job.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !job.enabled }),
    });
    showToast(job.enabled ? '⏸ Job suspendu' : '▶ Job activé');
    fetchJobs();
  };

  const handleDelete = async (id) => {
    if (!confirm('Supprimer ce job planifié ?')) return;
    await fetch(`${BACKEND}/api/cron/${id}`, { method: 'DELETE' });
    setJobs(prev => prev.filter(j => j.id !== id));
    showToast('🗑️ Job supprimé', '#ef4444');
  };

  const handleRunNow = async (job) => {
    setRunningId(job.id);
    try {
      const res = await fetch(`${BACKEND}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName: job.tool_name, args: job.args || {} }),
      });
      const data = await res.json();
      if (data.result?.error) {
        showToast(`⚠️ ${data.result.error}`, '#ef4444');
      } else {
        showToast('✅ Exécution terminée');
      }
      fetchJobs();
    } catch (e) {
      showToast(`❌ ${e.message}`, '#ef4444');
    }
    setRunningId(null);
  };

  const handleCreated = (job) => {
    setJobs(prev => [...prev, job]);
    showToast('✅ Job planifié créé !');
  };

  const active = jobs.filter(j => j.enabled);
  const inactive = jobs.filter(j => !j.enabled);

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-primary)', color: 'var(--text-primary)', padding: '28px 32px', maxWidth: '900px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '28px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 700 }}>⏰ Planificateur</h1>
          <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
            {jobs.length} job{jobs.length !== 1 ? 's' : ''} — {active.length} actif{active.length !== 1 ? 's' : ''}
          </p>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
          {[
            { label: 'Actifs', value: active.length, color: '#22c55e' },
            { label: 'Inactifs', value: inactive.length, color: '#6b7280' },
          ].map(s => (
            <div key={s.label} style={{
              padding: '6px 14px', borderRadius: '8px',
              background: `${s.color}12`, border: `1px solid ${s.color}30`,
              textAlign: 'center',
            }}>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Formulaire création */}
      <CreateJobForm onCreated={handleCreated} />

      {/* Liste des jobs */}
      <div style={{ marginTop: '28px' }}>
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}><LoadingRow /></div>
        ) : jobs.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: '40px',
            color: 'var(--text-muted)', fontSize: '0.9rem',
            border: '1px dashed rgba(255,255,255,0.1)', borderRadius: '14px',
          }}>
            Aucun job planifié. Créez-en un ci-dessus !
          </div>
        ) : (
          <>
            {active.length > 0 && (
              <div style={{ marginBottom: '20px' }}>
                <div style={{ fontSize: '11px', color: '#22c55e', fontWeight: 700, letterSpacing: '0.08em', marginBottom: '10px' }}>
                  ● ACTIFS ({active.length})
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {active.map(job => (
                    <JobRow
                      key={job.id} job={job}
                      onToggle={handleToggle} onDelete={handleDelete}
                      onRunNow={job => { handleRunNow(job); }}
                    />
                  ))}
                </div>
              </div>
            )}
            {inactive.length > 0 && (
              <div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.08em', marginBottom: '10px' }}>
                  ○ INACTIFS ({inactive.length})
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {inactive.map(job => (
                    <JobRow
                      key={job.id} job={job}
                      onToggle={handleToggle} onDelete={handleDelete}
                      onRunNow={handleRunNow}
                    />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <style>{`
        @keyframes slideIn {
          from { transform: translateY(10px); opacity: 0; }
          to   { transform: translateY(0);    opacity: 1; }
        }
        select option { background: #1a1a1a; }
      `}</style>
    </div>
  );
}
