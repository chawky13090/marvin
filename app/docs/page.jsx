'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

// ── Styles partagés ──────────────────────────────────────────────────────────
const card = {
  background: 'var(--bg-glass)',
  border: '1px solid var(--border)',
  borderRadius: '12px',
  padding: '16px 20px',
};
const input = {
  width: '100%', padding: '8px 12px',
  background: 'var(--bg-primary)', border: '1px solid var(--border)',
  borderRadius: '6px', color: 'var(--text-primary)', fontSize: '13px',
  outline: 'none', boxSizing: 'border-box',
};
const btn = (variant = 'default') => ({
  padding: '8px 14px', borderRadius: '6px', border: 'none',
  cursor: 'pointer', fontSize: '13px', fontWeight: 600,
  background: variant === 'primary' ? 'linear-gradient(135deg,#4f8cff,#38bdf8)'
            : variant === 'danger'  ? 'rgba(239,68,68,0.15)'
            : variant === 'success' ? 'rgba(34,197,94,0.15)'
            : 'rgba(255,255,255,0.05)',
  color: variant === 'primary' ? '#111'
       : variant === 'danger'  ? '#f87171'
       : variant === 'success' ? '#4ade80'
       : 'var(--text-primary)',
  border: variant === 'danger' ? '1px solid rgba(239,68,68,0.3)'
        : variant === 'success' ? '1px solid rgba(34,197,94,0.3)'
        : '1px solid transparent',
});

const INTERVENTION_TYPES = [
  { value: 'incident',    label: '🚨 Incident',     color: '#ef4444' },
  { value: 'request',     label: '📨 Demande',      color: '#3b82f6' },
  { value: 'change',      label: '🔄 Changement',   color: '#a855f7' },
  { value: 'problem',     label: '🔍 Problème',     color: '#f97316' },
  { value: 'deployment',  label: '🚀 Déploiement',  color: '#22c55e' },
  { value: 'maintenance', label: '🛠️ Maintenance',  color: '#f59e0b' },
  { value: 'audit',       label: '📋 Audit',        color: '#06b6d4' },
  { value: 'other',       label: '📌 Autre',        color: '#888' },
];

const STATUSES = [
  { value: 'open',         label: 'Ouverte',     color: '#3b82f6' },
  { value: 'in_progress',  label: 'En cours',    color: '#f59e0b' },
  { value: 'resolved',     label: 'Résolue',     color: '#22c55e' },
  { value: 'closed',       label: 'Clôturée',    color: '#888' },
  { value: 'cancelled',    label: 'Annulée',     color: '#ef4444' },
];

const PRIORITIES = [
  { value: 'low',      label: '🟢 Basse',    color: '#22c55e' },
  { value: 'medium',   label: '🟡 Moyenne',  color: '#f59e0b' },
  { value: 'high',     label: '🟠 Élevée',   color: '#f97316' },
  { value: 'critical', label: '🔴 Critique', color: '#ef4444' },
];

const DOC_TYPES = [
  { value: 'report',         label: '📄 Rapport d\'intervention',  icon: '📄', tool: 'doc_generate_report' },
  { value: 'procedure',      label: '📘 Procédure technique',      icon: '📘', tool: 'doc_generate_procedure' },
  { value: 'client_sheet',   label: '🏷️ Fiche client',             icon: '🏷️', tool: 'doc_generate_client_sheet' },
  { value: 'recovery_plan',  label: '🛡️ Plan de reprise (PRA)',    icon: '🛡️', tool: 'doc_generate_recovery_plan' },
  { value: 'maintenance',    label: '🔧 Procédure maintenance',    icon: '🔧', tool: 'doc_generate_maintenance' },
  { value: 'runbook',        label: '🚨 Runbook urgence',          icon: '🚨', tool: 'doc_generate_runbook' },
  { value: 'schema',         label: '🗺️ Schéma logique',           icon: '🗺️', tool: 'doc_generate_schema' },
  { value: 'postmortem',     label: '📋 Post-mortem (RCA)',        icon: '📋', tool: 'doc_generate_postmortem' },
  { value: 'change',         label: '🔄 Demande de changement',    icon: '🔄', tool: 'doc_generate_change' },
  { value: 'onboarding',     label: '👤 Arrivée / Départ IT',      icon: '👤', tool: 'doc_generate_onboarding' },
];

// ── API helpers ──────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(`${BACKEND}${path}`, opts);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})).then(d => d.detail || '');
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}
async function tool(name, args) {
  const res = await fetch(`${BACKEND}/api/tools`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toolName: name, args }),
  });
  const data = await res.json();
  return data.result || {};
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function DocsPage() {
  const [view, setView] = useState('dashboard');  // dashboard | intervention | new_intervention | generate | knowledge
  const [interventions, setInterventions] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [clients, setClients] = useState([]);
  const [assets, setAssets] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const { toast: realToast } = useToast();
  const showToast = (msg, type = 'info') => {
    (realToast[type] || realToast.info)(msg);
  };

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [iv, dc, cl, as] = await Promise.all([
        api('/api/docs/interventions'),
        api('/api/docs/documents'),
        api('/api/billing/clients').catch(() => ({ clients: [] })),
        api('/api/docs/assets'),
      ]);
      setInterventions(iv.interventions || []);
      setDocuments(dc.documents || []);
      setClients(cl.clients || []);
      setAssets(as.assets || []);
    } catch (e) {
      showToast('Erreur chargement : ' + e.message, 'error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: 'var(--bg-primary)' }}>
      {/* Sidebar */}
      <div style={{
        width: '290px', flexShrink: 0,
        borderRight: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        overflowY: 'auto',
        padding: '16px 12px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '18px', padding: '0 6px' }}>
          <span style={{ fontSize: '22px' }}>📚</span>
          <div>
            <div style={{ fontWeight: 800, color: 'var(--text-primary)', fontSize: '14px' }}>Doc Tech</div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>AGENT IA</div>
          </div>
        </div>

        <button onClick={() => { setSelected(null); setView('new_intervention'); }}
          style={{ ...btn('primary'), width: '100%', marginBottom: '6px' }}>
          ➕ Nouvelle intervention
        </button>
        <button onClick={() => setView('knowledge')} style={{ ...btn(), width: '100%', marginBottom: '6px' }}>
          🔍 Knowledge base
        </button>
        <button onClick={() => setView('dashboard')} style={{ ...btn(), width: '100%', marginBottom: '14px' }}>
          📊 Tableau de bord
        </button>

        <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.08em', padding: '0 6px', marginBottom: '6px' }}>
          INTERVENTIONS RÉCENTES ({interventions.length})
        </div>
        {interventions.slice(0, 25).map(i => {
          const tp = INTERVENTION_TYPES.find(t => t.value === i.intervention_type);
          const st = STATUSES.find(s => s.value === i.status);
          return (
            <div key={i.id}
              onClick={() => { setSelected(i); setView('intervention'); }}
              style={{
                padding: '8px 10px', marginBottom: '4px',
                borderRadius: '6px', cursor: 'pointer',
                background: selected?.id === i.id ? 'rgba(79, 140, 255,0.12)' : 'transparent',
                border: '1px solid ' + (selected?.id === i.id ? 'rgba(79, 140, 255,0.3)' : 'transparent'),
              }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-primary)' }}>{i.number}</span>
                <span style={{
                  fontSize: '9px', padding: '1px 5px', borderRadius: '8px',
                  background: (st?.color || '#888') + '22', color: st?.color || '#888',
                }}>{st?.label}</span>
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-primary)', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {tp?.label.split(' ')[0]} {i.title}
              </div>
            </div>
          );
        })}
      </div>

      {/* Main */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px 32px', position: 'relative' }}>
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '60px' }}><LoadingRow /></div>
        ) : view === 'dashboard' ? (
          <DashboardView interventions={interventions} documents={documents} clients={clients}
            assets={assets} setView={setView} setSelected={setSelected} showToast={showToast} />
        ) : view === 'new_intervention' ? (
          <NewInterventionView clients={clients} reload={reload} showToast={showToast}
            setView={setView} setSelected={setSelected} />
        ) : view === 'intervention' && selected ? (
          <InterventionView intervention={selected} clients={clients} documents={documents}
            reload={reload} showToast={showToast} setView={setView} setSelected={setSelected} />
        ) : view === 'knowledge' ? (
          <KnowledgeView showToast={showToast} setView={setView} setSelected={setSelected} />
        ) : (
          <DashboardView interventions={interventions} documents={documents} clients={clients}
            assets={assets} setView={setView} setSelected={setSelected} showToast={showToast} />
        )}
      </div>
    </div>
  );
}

// ── Dashboard ────────────────────────────────────────────────────────────────
function DashboardView({ interventions, documents, clients, assets, setView }) {
  const stats = useMemo(() => ({
    open: interventions.filter(i => i.status === 'open').length,
    in_progress: interventions.filter(i => i.status === 'in_progress').length,
    resolved_this_week: interventions.filter(i => {
      if (i.status !== 'resolved' && i.status !== 'closed') return false;
      // Timestamp SQLite UTC naïf (sans 'Z') — +'Z' évite un décalage de l'écart UTC local.
      const d = new Date((i.created_at || '').replace(' ', 'T') + 'Z');
      const week = new Date(); week.setDate(week.getDate() - 7);
      return d >= week;
    }).length,
    critical: interventions.filter(i => i.priority === 'critical' && i.status !== 'closed').length,
  }), [interventions]);

  return (
    <div>
      <h1 style={{ fontSize: '1.6rem', fontWeight: 800, marginBottom: '6px' }}>📚 Agent IA Documentation Technique</h1>
      <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginBottom: '24px' }}>
        Transforme vos interventions en documentation professionnelle (rapport, procédure, fiche client, PRA, runbook…).
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px', marginBottom: '24px' }}>
        <StatCard icon="🚨" label="À traiter" value={stats.open} color="#3b82f6" />
        <StatCard icon="⏳" label="En cours" value={stats.in_progress} color="#f59e0b" />
        <StatCard icon="🔴" label="Critiques" value={stats.critical} color="#ef4444" />
        <StatCard icon="✅" label="Résolues 7j" value={stats.resolved_this_week} color="#22c55e" />
        <StatCard icon="📄" label="Documents" value={documents.length} color="#4f8cff" />
        <StatCard icon="💻" label="Assets" value={assets.length} color="#a855f7" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
        <div style={card}>
          <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '14px' }}>🎯 Actions rapides</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <QuickAction icon="➕" title="Nouvelle intervention" desc="Documenter une intervention terrain"
              onClick={() => setView('new_intervention')} />
            <QuickAction icon="🔍" title="Knowledge base" desc="Chercher dans les interventions passées"
              onClick={() => setView('knowledge')} />
          </div>
        </div>
        <div style={card}>
          <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '14px' }}>📊 Types de documents générables</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {DOC_TYPES.map(d => (
              <span key={d.value} style={{
                fontSize: '11px', padding: '4px 10px', borderRadius: '12px',
                background: 'rgba(79, 140, 255,0.1)', color: '#4f8cff',
                border: '1px solid rgba(79, 140, 255,0.25)',
              }}>{d.icon} {d.label.replace(d.icon + ' ', '')}</span>
            ))}
          </div>
        </div>
      </div>

      <div style={{ ...card, marginTop: '16px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '12px' }}>📋 Dernières interventions</h3>
        {interventions.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '13px', padding: '12px' }}>
            Aucune intervention enregistrée. Cliquez sur "Nouvelle intervention" pour commencer.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {interventions.slice(0, 10).map(i => {
              const tp = INTERVENTION_TYPES.find(t => t.value === i.intervention_type);
              const st = STATUSES.find(s => s.value === i.status);
              const pr = PRIORITIES.find(p => p.value === i.priority);
              return (
                <div key={i.id} style={{
                  display: 'grid', gridTemplateColumns: '90px 1fr 100px 80px 80px',
                  gap: '10px', alignItems: 'center', padding: '8px 12px',
                  background: 'rgba(255,255,255,0.02)', borderRadius: '6px',
                  fontSize: '12px', border: '1px solid var(--border)',
                }}>
                  <span style={{ fontFamily: 'monospace', color: 'var(--text-secondary)' }}>{i.number}</span>
                  <span style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.title}</span>
                  <span style={{ color: tp?.color, fontSize: '11px' }}>{tp?.label}</span>
                  <span style={{ color: pr?.color, fontSize: '11px' }}>{pr?.label}</span>
                  <span style={{ padding: '2px 8px', borderRadius: '10px',
                      background: st?.color + '22', color: st?.color, fontSize: '10px', textAlign: 'center' }}>
                    {st?.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ icon, label, value, color }) {
  return (
    <div style={card}>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{icon} {label}</div>
      <div style={{ fontSize: '1.7rem', fontWeight: 800, color: color || 'var(--text-primary)', marginTop: '4px' }}>{value}</div>
    </div>
  );
}

function QuickAction({ icon, title, desc, onClick }) {
  return (
    <button onClick={onClick} style={{
      padding: '12px 14px', background: 'rgba(255,255,255,0.02)',
      border: '1px solid var(--border)', borderRadius: '8px',
      textAlign: 'left', cursor: 'pointer', transition: 'all 0.15s',
      color: 'var(--text-primary)', display: 'flex', gap: '10px', alignItems: 'center',
    }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = '#4f8cff'; e.currentTarget.style.background = 'rgba(79, 140, 255,0.06)'; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}>
      <span style={{ fontSize: '22px' }}>{icon}</span>
      <div>
        <div style={{ fontWeight: 700, fontSize: '13px' }}>{title}</div>
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{desc}</div>
      </div>
    </button>
  );
}

// ── New intervention (with AI analysis) ──────────────────────────────────────
function NewInterventionView({ clients, reload, showToast, setView, setSelected }) {
  const [form, setForm] = useState({
    title: '', intervention_type: 'incident', priority: 'medium', status: 'open',
    client_id: '', technician: '', raw_notes: '', commands_executed: '',
    ticket_refs: '', client_emails: '', network_config: '',
    summary: '', resolution: '', recommendations: '',
    duration_minutes: '',
  });
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [creating, setCreating] = useState(false);

  const update = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const analyze = async () => {
    if (!form.raw_notes && !form.commands_executed) {
      showToast('Saisissez des notes ou commandes à analyser', 'error');
      return;
    }
    setAnalyzing(true);
    setAnalysis(null);
    try {
      const combined = [form.raw_notes, form.commands_executed, form.network_config].filter(Boolean).join('\n\n');
      const r = await tool('doc_analyze_input', { raw_text: combined });
      if (r.error) { showToast(r.error, 'error'); return; }
      setAnalysis(r);
      // Auto-fill form from analysis
      setForm(f => ({
        ...f,
        intervention_type: r.main_type || f.intervention_type,
        priority: r.suggested_priority || f.priority,
        commands_executed: f.commands_executed || (r.extracted_commands || []).join('\n'),
      }));
      showToast(`Analyse OK : ${r.command_count} commandes, ${r.itil_categories.length} catégories ITIL`, 'success');
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
    finally { setAnalyzing(false); }
  };

  const create = async () => {
    if (!form.title.trim()) { showToast('Titre requis', 'error'); return; }
    setCreating(true);
    try {
      const body = {
        ...form,
        tags: analysis?.suggested_tags || [],
        rgpd_relevant: analysis?.rgpd_relevant || false,
        itil_category: analysis?.itil_categories?.[0] || '',
        duration_minutes: parseInt(form.duration_minutes) || null,
      };
      const interv = await api('/api/docs/interventions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      showToast(`Intervention ${interv.number} créée`, 'success');
      setSelected(interv); setView('intervention'); reload();
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
    finally { setCreating(false); }
  };

  return (
    <div>
      <h2 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '20px' }}>➕ Nouvelle intervention</h2>

      <div style={{ ...card, marginBottom: '16px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '12px', marginBottom: '12px' }}>
          <Field label="Titre" required>
            <input value={form.title} onChange={e => update('title', e.target.value)} style={input}
              placeholder="ex: Panne serveur AD - dimanche 14h" />
          </Field>
          <Field label="Type">
            <select value={form.intervention_type} onChange={e => update('intervention_type', e.target.value)} style={input}>
              {INTERVENTION_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="Priorité">
            <select value={form.priority} onChange={e => update('priority', e.target.value)} style={input}>
              {PRIORITIES.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '12px' }}>
          <Field label="Client">
            <select value={form.client_id} onChange={e => update('client_id', e.target.value)} style={input}>
              <option value="">— Aucun —</option>
              {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Technicien">
            <input value={form.technician} onChange={e => update('technician', e.target.value)} style={input} placeholder="Votre nom" />
          </Field>
          <Field label="Durée (min)">
            <input type="number" value={form.duration_minutes} onChange={e => update('duration_minutes', e.target.value)} style={input} placeholder="60" />
          </Field>
        </div>
      </div>

      <div style={{ ...card, marginBottom: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700 }}>📝 Entrées (matières premières)</h3>
          <button onClick={analyze} disabled={analyzing} style={{ ...btn('primary'), opacity: analyzing ? 0.5 : 1 }}>
            {analyzing ? '⏳ Analyse...' : '🤖 Analyser avec l\'IA'}
          </button>
        </div>
        <Field label="📝 Notes brutes de l'intervention">
          <textarea value={form.raw_notes} onChange={e => update('raw_notes', e.target.value)}
            style={{ ...input, minHeight: '100px', resize: 'vertical', fontFamily: 'inherit' }}
            placeholder="Décrivez ce que vous avez fait, ce que vous avez vu, les symptômes..." />
        </Field>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '12px' }}>
          <Field label="⚡ Commandes exécutées">
            <textarea value={form.commands_executed} onChange={e => update('commands_executed', e.target.value)}
              style={{ ...input, minHeight: '80px', fontFamily: 'monospace', fontSize: '11px' }}
              placeholder="ipconfig /all&#10;Get-Service AD*&#10;..." />
          </Field>
          <Field label="🌐 Configuration réseau">
            <textarea value={form.network_config} onChange={e => update('network_config', e.target.value)}
              style={{ ...input, minHeight: '80px', fontFamily: 'monospace', fontSize: '11px' }}
              placeholder="LAN: 192.168.1.0/24&#10;Firewall: pfSense&#10;..." />
          </Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '12px' }}>
          <Field label="🎫 Références tickets">
            <input value={form.ticket_refs} onChange={e => update('ticket_refs', e.target.value)} style={input}
              placeholder="GLPI #1234, ITSM-456" />
          </Field>
          <Field label="📧 Email(s) client (références)">
            <input value={form.client_emails} onChange={e => update('client_emails', e.target.value)} style={input}
              placeholder="contact@..., extraits emails..." />
          </Field>
        </div>
      </div>

      {analysis && (
        <div style={{ ...card, marginBottom: '16px', background: 'rgba(34,197,94,0.05)', border: '1px solid rgba(34,197,94,0.2)' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700, color: '#4ade80', marginBottom: '10px' }}>🤖 Analyse IA</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', fontSize: '12px' }}>
            <KV k="Type détecté" v={analysis.main_type} />
            <KV k="Priorité suggérée" v={analysis.suggested_priority} />
            <KV k="Commandes extraites" v={analysis.command_count} />
            <KV k="IPs trouvées" v={analysis.ip_addresses?.length || 0} />
            <KV k="MACs trouvées" v={analysis.mac_addresses?.length || 0} />
            <KV k="Chemins fichiers" v={analysis.file_paths?.length || 0} />
            <KV k="ITIL" v={analysis.itil_categories?.join(', ') || '—'} />
            <KV k="RGPD pertinent" v={analysis.rgpd_relevant ? '⚠️ Oui' : 'Non'} />
          </div>
          {analysis.suggested_tags?.length > 0 && (
            <div style={{ marginTop: '10px', display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
              {analysis.suggested_tags.map(t => (
                <span key={t} style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '10px',
                    background: 'rgba(34,197,94,0.15)', color: '#4ade80' }}>{t}</span>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ ...card, marginBottom: '16px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '12px' }}>✅ Synthèse & résolution</h3>
        <Field label="Synthèse (1-2 lignes)">
          <input value={form.summary} onChange={e => update('summary', e.target.value)} style={input}
            placeholder="ex: Redémarrage service AD pour résoudre la panne d'authentification" />
        </Field>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '10px' }}>
          <Field label="Résolution / actions effectuées">
            <textarea value={form.resolution} onChange={e => update('resolution', e.target.value)} style={{ ...input, minHeight: '70px' }} />
          </Field>
          <Field label="Recommandations">
            <textarea value={form.recommendations} onChange={e => update('recommendations', e.target.value)} style={{ ...input, minHeight: '70px' }} />
          </Field>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '10px' }}>
        <button onClick={create} disabled={creating} style={{ ...btn('primary'), opacity: creating ? 0.5 : 1 }}>
          {creating ? '⏳ Création...' : '💾 Créer l\'intervention'}
        </button>
        <button onClick={() => setView('dashboard')} style={btn()}>Annuler</button>
      </div>
    </div>
  );
}

function Field({ label, required, children }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '5px', fontWeight: 600 }}>
        {label} {required && <span style={{ color: '#ef4444' }}>*</span>}
      </label>
      {children}
    </div>
  );
}

function KV({ k, v }) {
  return (
    <div>
      <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{k}</div>
      <div style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: 600 }}>{v}</div>
    </div>
  );
}

// ── Intervention view + document generation ──────────────────────────────────
function InterventionView({ intervention, clients, documents, reload, showToast, setView }) {
  const [iv, setIv] = useState(intervention);
  const [genFormat, setGenFormat] = useState('pdf');
  const [generating, setGenerating] = useState(null);
  const [interventionDocs, setInterventionDocs] = useState([]);

  useEffect(() => { setIv(intervention); }, [intervention]);

  useEffect(() => {
    api(`/api/docs/documents?intervention_id=${intervention.id}`)
      .then(d => setInterventionDocs(d.documents || []))
      .catch(() => {});
  }, [intervention.id, documents]);

  const update = (k, v) => setIv(prev => ({ ...prev, [k]: v }));

  const save = async () => {
    try {
      const updated = await api(`/api/docs/interventions/${iv.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(iv),
      });
      setIv(updated);
      showToast('Intervention enregistrée', 'success');
      reload();
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
  };

  const generate = async (docType) => {
    setGenerating(docType.value);
    try {
      const args = { intervention_id: iv.id, format: genFormat };
      if (docType.value === 'client_sheet' || docType.value === 'recovery_plan' || docType.value === 'maintenance') {
        args.client_id = iv.client_id;
        if (!iv.client_id) { showToast('Client requis pour ' + docType.label, 'error'); setGenerating(null); return; }
      }
      if (docType.value === 'schema') {
        args.network_config = iv.network_config || iv.raw_notes;
        args.title = `Schéma — ${iv.title}`;
      }
      const r = await tool(docType.tool, args);
      if (r.error) { showToast(r.error, 'error'); return; }
      showToast(`${docType.label} généré : ${r.path?.split('\\').pop()}`, 'success');
      reload();
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
    finally { setGenerating(null); }
  };

  const remove = async () => {
    if (!confirm(`Supprimer l'intervention ${iv.number} et ses documents ?`)) return;
    try {
      await api(`/api/docs/interventions/${iv.id}`, { method: 'DELETE' });
      showToast('Supprimée', 'success'); setView('dashboard'); reload();
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
  };

  const client = clients.find(c => c.id === iv.client_id);
  const tp = INTERVENTION_TYPES.find(t => t.value === iv.intervention_type);
  const st = STATUSES.find(s => s.value === iv.status);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
        <h2 style={{ fontSize: '1.3rem', fontWeight: 800 }}>
          {tp?.label.split(' ')[0]} {iv.number} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>· {iv.title}</span>
        </h2>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={save} style={btn('primary')}>💾 Enregistrer</button>
          <button onClick={remove} style={btn('danger')}>🗑️</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: '16px', marginBottom: '16px' }}>
        <div style={card}>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '10px', marginBottom: '12px' }}>
            <Field label="Titre"><input value={iv.title} onChange={e => update('title', e.target.value)} style={input} /></Field>
            <Field label="Statut">
              <select value={iv.status} onChange={e => update('status', e.target.value)} style={input}>
                {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </Field>
            <Field label="Priorité">
              <select value={iv.priority} onChange={e => update('priority', e.target.value)} style={input}>
                {PRIORITIES.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </Field>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '12px' }}>
            <Field label="Notes brutes">
              <textarea value={iv.raw_notes || ''} onChange={e => update('raw_notes', e.target.value)}
                style={{ ...input, minHeight: '90px', fontSize: '12px' }} />
            </Field>
            <Field label="Commandes exécutées">
              <textarea value={iv.commands_executed || ''} onChange={e => update('commands_executed', e.target.value)}
                style={{ ...input, minHeight: '90px', fontFamily: 'monospace', fontSize: '11px' }} />
            </Field>
          </div>
          <Field label="Synthèse">
            <input value={iv.summary || ''} onChange={e => update('summary', e.target.value)} style={input} />
          </Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '10px' }}>
            <Field label="Résolution"><textarea value={iv.resolution || ''} onChange={e => update('resolution', e.target.value)} style={{ ...input, minHeight: '60px' }} /></Field>
            <Field label="Recommandations"><textarea value={iv.recommendations || ''} onChange={e => update('recommendations', e.target.value)} style={{ ...input, minHeight: '60px' }} /></Field>
          </div>
        </div>

        <div style={card}>
          <h3 style={{ fontSize: '13px', fontWeight: 700, marginBottom: '10px' }}>ℹ️ Métadonnées</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
            <KV k="Type" v={tp?.label || '—'} />
            <KV k="Statut" v={<span style={{ padding: '2px 8px', borderRadius: '10px', background: st?.color+'22', color: st?.color }}>{st?.label}</span>} />
            <KV k="Client" v={client?.name || '—'} />
            <KV k="Technicien" v={iv.technician || '—'} />
            <KV k="Durée" v={iv.duration_minutes ? `${iv.duration_minutes} min` : '—'} />
            <KV k="ITIL" v={iv.itil_category || '—'} />
            <KV k="RGPD" v={iv.rgpd_relevant ? '⚠️ Pertinent' : 'Non'} />
            {iv.tags?.length > 0 && (
              <div>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>TAGS</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '3px' }}>
                  {iv.tags.map(t => (
                    <span key={t} style={{ fontSize: '10px', padding: '1px 7px', borderRadius: '8px',
                        background: 'rgba(79, 140, 255,0.15)', color: '#4f8cff' }}>{t}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700 }}>📄 Générer une documentation</h3>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Format :</span>
            {['pdf', 'docx', 'md'].map(f => (
              <button key={f} onClick={() => setGenFormat(f)} style={{
                ...btn(genFormat === f ? 'success' : 'default'),
                padding: '4px 12px', fontSize: '11px', textTransform: 'uppercase',
              }}>{f}</button>
            ))}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '10px' }}>
          {DOC_TYPES.map(d => (
            <button key={d.value} onClick={() => generate(d)} disabled={generating === d.value}
              style={{
                padding: '12px', background: 'rgba(255,255,255,0.02)',
                border: '1px solid var(--border)', borderRadius: '8px',
                textAlign: 'left', cursor: 'pointer', transition: 'all 0.15s',
                color: 'var(--text-primary)', opacity: generating === d.value ? 0.5 : 1,
                display: 'flex', flexDirection: 'column', gap: '4px',
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = '#4f8cff'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; }}>
              <div style={{ fontSize: '20px' }}>{d.icon}</div>
              <div style={{ fontWeight: 700, fontSize: '12px' }}>{d.label.replace(d.icon + ' ', '')}</div>
              {generating === d.value && (
                <div style={{ fontSize: '10px', color: '#4f8cff' }}>⏳ Génération...</div>
              )}
            </button>
          ))}
        </div>
      </div>

      {interventionDocs.length > 0 && (
        <div style={{ ...card, marginTop: '16px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '12px' }}>📚 Documents générés ({interventionDocs.length})</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {interventionDocs.map(d => (
              <div key={d.id} style={{
                padding: '8px 12px', background: 'rgba(255,255,255,0.02)',
                borderRadius: '6px', border: '1px solid var(--border)',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px',
              }}>
                <span>
                  {DOC_TYPES.find(t => t.value === d.doc_type)?.icon || '📄'} <strong>{d.title}</strong>
                  <span style={{ color: 'var(--text-muted)', marginLeft: '8px' }}>· {d.format.toUpperCase()} · {(d.size_bytes/1024).toFixed(1)} Ko</span>
                </span>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                  {d.file_path?.split('\\').pop()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── v2.30 Operations Safety panels ── */}
      <OperationsSafetyPanel intervention={iv} client={client} showToast={showToast} />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// v2.30 — Operations Safety : panneaux frontend
// ══════════════════════════════════════════════════════════════════════════════

const RISK_COLORS = {
  safe: '#22c55e', medium: '#f59e0b', high: '#f97316', critical: '#ef4444', blocked: '#dc2626',
};
const RISK_LABELS = {
  safe: '🟢 Sûr', medium: '🟡 Modéré', high: '🟠 Élevé', critical: '🔴 Critique', blocked: '🚫 Bloqué',
};
const CHECK_STATUS_COLORS = {
  ok: '#22c55e', warning: '#f59e0b', failed: '#ef4444', skipped: '#888',
};

function OperationsSafetyPanel({ intervention, client, showToast }) {
  const [cmdAnalysis, setCmdAnalysis] = useState(null);
  const [analyzingCmd, setAnalyzingCmd] = useState(false);
  const [checks, setChecks] = useState([]);
  const [health, setHealth] = useState(null);
  const [computingHealth, setComputingHealth] = useState(false);
  const [busy, setBusy] = useState(null);

  const loadChecks = useCallback(async () => {
    try {
      const r = await api(`/api/ops/checks?intervention_id=${intervention.id}`);
      const detailed = await Promise.all((r.checks || []).map(c => api(`/api/ops/checks/${c.id}`)));
      setChecks(detailed);
    } catch { /* ignore */ }
  }, [intervention.id]);

  const loadHealth = useCallback(async () => {
    if (!client?.id) return;
    try {
      const r = await api(`/api/client-health/${client.id}`);
      setHealth(r.score);
    } catch { /* ignore */ }
  }, [client?.id]);

  useEffect(() => { loadChecks(); loadHealth(); }, [loadChecks, loadHealth]);

  // ── Command Safety ──
  const analyzeCommands = async () => {
    setAnalyzingCmd(true);
    try {
      const text = [intervention.raw_notes, intervention.commands_executed, intervention.network_config]
        .filter(Boolean).join('\n');
      const ext = await tool('cmd_extract_from_text', { text });
      if (!ext.commands || ext.commands.length === 0) {
        showToast('Aucune commande détectée dans les notes', 'info');
        setCmdAnalysis({ analyses: [], highest_risk: 'safe', verdict: 'Aucune commande' });
        return;
      }
      const r = await tool('cmd_analyze_risk', { commands: ext.commands, intervention_id: intervention.id });
      setCmdAnalysis(r);
    } catch (e) { showToast('Erreur : ' + e.message, 'error'); }
    finally { setAnalyzingCmd(false); }
  };

  const requireApproval = async (cmd) => {
    const r = await tool('cmd_require_approval', { command: cmd, intervention_id: intervention.id });
    if (r.error) showToast(r.error, 'error');
    else showToast('Demande d\'approbation créée — commande NON exécutée', 'success');
  };

  // ── Pre/Post-Check ──
  const createCheck = async (checkType) => {
    setBusy(checkType);
    try {
      const r = await tool('ops_precheck_create', { intervention_id: intervention.id, check_type: checkType });
      if (r.error) { showToast(r.error, 'error'); return; }
      showToast(`${checkType === 'precheck' ? 'Pré-check' : 'Post-check'} créé`, 'success');
      loadChecks();
    } finally { setBusy(null); }
  };

  const setItemResult = async (checkId, itemId, status) => {
    await tool(checks.find(c => c.id === checkId)?.check_type === 'postcheck' ? 'ops_postcheck_run' : 'ops_precheck_run',
      { check_id: checkId, results: [{ item_id: itemId, status }] });
    loadChecks();
  };

  const addEvidence = async (checkId) => {
    const content = prompt('Contenu de la preuve (texte, commande, chemin, log) :');
    if (!content) return;
    const r = await tool('ops_evidence_add', {
      evidence_type: 'text', content, check_id: checkId, intervention_id: intervention.id });
    if (r.error) showToast(r.error, 'error');
    else { showToast('Preuve ajoutée', 'success'); loadChecks(); }
  };

  const genValidationReport = async () => {
    setBusy('report');
    try {
      const r = await tool('ops_validation_report_generate', { intervention_id: intervention.id, format: 'pdf' });
      if (r.error) showToast(r.error, 'error');
      else showToast('Rapport de validation : ' + r.path?.split('\\').pop(), 'success');
    } finally { setBusy(null); }
  };

  // ── Client Health ──
  const computeHealth = async () => {
    if (!client?.id) { showToast('Aucun client lié', 'error'); return; }
    setComputingHealth(true);
    try {
      const r = await tool('client_health_compute', { client_id: client.id });
      if (r.error) { showToast(r.error, 'error'); return; }
      showToast(`Score santé : ${r.scores.global}/100 (${r.risk_level})`, 'success');
      loadHealth();
    } finally { setComputingHealth(false); }
  };

  return (
    <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* ── COMMAND SAFETY ── */}
      <div style={{ ...card, borderLeft: '3px solid #ef4444' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700 }}>🛡️ Command Safety — Analyse de risque</h3>
          <button onClick={analyzeCommands} disabled={analyzingCmd} style={{ ...btn('primary'), opacity: analyzingCmd ? 0.5 : 1 }}>
            {analyzingCmd ? '⏳ Analyse...' : '🔍 Analyser les commandes'}
          </button>
        </div>
        {!cmdAnalysis ? (
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Analyse les commandes des notes/commandes de l'intervention pour détecter les opérations dangereuses.
          </div>
        ) : cmdAnalysis.analyses?.length === 0 ? (
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Aucune commande détectée.</div>
        ) : (
          <>
            <div style={{ marginBottom: '10px', padding: '8px 12px', borderRadius: '6px',
              background: RISK_COLORS[cmdAnalysis.highest_risk] + '18',
              border: `1px solid ${RISK_COLORS[cmdAnalysis.highest_risk]}40`,
              color: RISK_COLORS[cmdAnalysis.highest_risk], fontWeight: 700, fontSize: '13px' }}>
              {cmdAnalysis.verdict}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {cmdAnalysis.analyses.map((a, i) => (
                <div key={i} style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.02)',
                  borderRadius: '6px', border: `1px solid ${RISK_COLORS[a.risk_level]}30` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <code style={{ fontSize: '12px', color: 'var(--text-primary)' }}>{a.command}</code>
                    <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
                      background: RISK_COLORS[a.risk_level] + '22', color: RISK_COLORS[a.risk_level], fontWeight: 700 }}>
                      {RISK_LABELS[a.risk_level]} · {a.platform}
                    </span>
                  </div>
                  {a.risk_level !== 'safe' && (
                    <div style={{ marginTop: '4px', fontSize: '11px', color: 'var(--text-secondary)' }}>
                      ⚠️ {a.risk_explanation}
                      {a.safer_alternative && (
                        <div style={{ marginTop: '3px', color: '#4ade80' }}>✅ {a.safer_alternative}</div>
                      )}
                    </div>
                  )}
                  {(a.risk_level === 'critical' || a.risk_level === 'blocked') && (
                    <button onClick={() => requireApproval(a.command)} style={{ ...btn('danger'), marginTop: '6px', padding: '3px 10px', fontSize: '11px' }}>
                      🔒 Demander une approbation
                    </button>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* ── PRE/POST CHECK ── */}
      <div style={{ ...card, borderLeft: '3px solid #4f8cff' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700 }}>✅ Pre-Check / Post-Check</h3>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            <button onClick={() => createCheck('precheck')} disabled={busy} style={btn()}>➕ Créer Pre-Check</button>
            <button onClick={() => createCheck('postcheck')} disabled={busy} style={btn()}>🚀 Lancer Post-Check</button>
            <button onClick={genValidationReport} disabled={busy || checks.length === 0} style={btn('primary')}>📄 Rapport de validation</button>
          </div>
        </div>
        {checks.length === 0 ? (
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Aucune checklist. Créez un pre-check (avant) ou post-check (après) pour valider l'intervention.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {checks.map(c => (
              <div key={c.id} style={{ padding: '10px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 700 }}>
                    {c.check_type === 'precheck' ? '🔍' : '✅'} {c.title}
                  </span>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{c.summary}</span>
                    <button onClick={() => addEvidence(c.id)} style={{ ...btn(), padding: '2px 8px', fontSize: '11px' }}>📎 Preuve</button>
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                  {c.items.map(it => {
                    const res = it.result;
                    return (
                      <div key={it.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', padding: '4px 0' }}>
                        <span style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '8px',
                          background: it.severity === 'critical' ? '#ef444422' : it.severity === 'warning' ? '#f59e0b22' : '#88888822',
                          color: it.severity === 'critical' ? '#f87171' : it.severity === 'warning' ? '#f59e0b' : '#aaa' }}>
                          {it.severity}
                        </span>
                        <span style={{ flex: 1, color: 'var(--text-primary)' }}>{it.label}</span>
                        <div style={{ display: 'flex', gap: '3px' }}>
                          {['ok','warning','failed','skipped'].map(st => (
                            <button key={st} onClick={() => setItemResult(c.id, it.id, st)}
                              title={st}
                              style={{
                                width: '24px', height: '20px', padding: 0, borderRadius: '4px', cursor: 'pointer',
                                border: '1px solid ' + ((res?.status === st) ? CHECK_STATUS_COLORS[st] : 'var(--border)'),
                                background: (res?.status === st) ? CHECK_STATUS_COLORS[st] + '33' : 'transparent',
                                fontSize: '11px',
                              }}>
                              {st === 'ok' ? '✓' : st === 'warning' ? '!' : st === 'failed' ? '✗' : '–'}
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
                {c.evidence?.length > 0 && (
                  <div style={{ marginTop: '6px', fontSize: '10px', color: 'var(--text-muted)' }}>
                    📎 {c.evidence.length} preuve(s)
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── CLIENT HEALTH SCORE ── */}
      {client?.id && (
        <div style={{ ...card, borderLeft: '3px solid #a855f7' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ fontSize: '14px', fontWeight: 700 }}>💜 Client Health Score — {client.name}</h3>
            <button onClick={computeHealth} disabled={computingHealth} style={{ ...btn('primary'), opacity: computingHealth ? 0.5 : 1 }}>
              {computingHealth ? '⏳ Calcul...' : '🔄 Calculer le score'}
            </button>
          </div>
          {!health ? (
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Aucun score calculé. Cliquez "Calculer le score" pour évaluer la santé opérationnelle du client.
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: '20px', marginBottom: '14px' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '2.5rem', fontWeight: 800,
                    color: health.global_score >= 80 ? '#22c55e' : health.global_score >= 60 ? '#f59e0b' : health.global_score >= 40 ? '#f97316' : '#ef4444' }}>
                    {health.global_score}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>/ 100</div>
                  <span style={{ fontSize: '11px', padding: '2px 10px', borderRadius: '10px', marginTop: '4px', display: 'inline-block',
                    background: { low:'#22c55e22', medium:'#f59e0b22', high:'#f9731622', critical:'#ef444422' }[health.risk_level],
                    color: { low:'#22c55e', medium:'#f59e0b', high:'#f97316', critical:'#ef4444' }[health.risk_level] }}>
                    {health.risk_level}
                  </span>
                </div>
                <div style={{ flex: 1, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: '8px' }}>
                  {[['🔐 Sécurité','security_score'],['💾 Backup/PRA','backup_score'],['📄 Doc','documentation_score'],['🖥️ Infra','infrastructure_score'],['🚨 Incidents','incident_score']].map(([lbl, key]) => (
                    <div key={key}>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{lbl}</div>
                      <div style={{ height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', marginTop: '3px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${health[key]}%`,
                          background: health[key] >= 70 ? '#22c55e' : health[key] >= 40 ? '#f59e0b' : '#ef4444' }} />
                      </div>
                      <div style={{ fontSize: '11px', fontWeight: 700, marginTop: '2px' }}>{health[key]}</div>
                    </div>
                  ))}
                </div>
              </div>
              {health.recommendations?.length > 0 && (
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 700, marginBottom: '6px' }}>🎯 Recommandations</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {health.recommendations.slice(0, 8).map((r, i) => {
                      const pc = { critical:'#ef4444', high:'#f97316', medium:'#f59e0b', low:'#22c55e' }[r.priority] || '#888';
                      return (
                        <div key={i} style={{ fontSize: '11px', padding: '6px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: '5px', borderLeft: `2px solid ${pc}` }}>
                          <strong style={{ color: pc }}>{r.priority?.toUpperCase()}</strong> — {r.title}
                          {r.description && <div style={{ color: 'var(--text-secondary)', marginTop: '2px' }}>{r.description}</div>}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Knowledge base search ────────────────────────────────────────────────────
function KnowledgeView({ showToast, setView, setSelected }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  const search = async () => {
    if (!q.trim()) return;
    setSearching(true);
    try {
      const r = await tool('doc_knowledge_search', { query: q });
      if (r.error) { showToast(r.error, 'error'); return; }
      setResults(r.results || []);
    } finally { setSearching(false); }
  };

  return (
    <div>
      <h2 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '20px' }}>🔍 Knowledge Base</h2>
      <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '20px' }}>
        Recherchez dans vos interventions passées pour résoudre rapidement des incidents similaires.
      </p>

      <div style={{ ...card, marginBottom: '16px' }}>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && search()}
            placeholder="ex: 'sauvegarde échec', 'wifi lent', 'mot de passe expiré'..." style={{ ...input, flex: 1 }} />
          <button onClick={search} disabled={searching || !q.trim()} style={btn('primary')}>
            {searching ? '⏳' : '🔍 Chercher'}
          </button>
        </div>
      </div>

      {results.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '10px' }}>{results.length} résultat(s)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {results.map(r => (
              <div key={r.id} onClick={() => {
                  api(`/api/docs/interventions/${r.id}`).then(iv => { setSelected(iv); setView('intervention'); });
                }}
                style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.02)',
                  borderRadius: '6px', border: '1px solid var(--border)', cursor: 'pointer' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <span style={{ fontWeight: 700, fontSize: '13px' }}>{r.number} — {r.title}</span>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{r.created_at?.slice(0, 10)} · score {r.score}</span>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{r.snippet}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {results.length === 0 && q && !searching && (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontSize: '13px' }}>
          Aucun résultat. La knowledge base se remplit au fur et à mesure des interventions documentées.
        </div>
      )}
    </div>
  );
}
