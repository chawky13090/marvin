'use client';
import { useState, useRef, useCallback, useEffect } from 'react';

import { BACKEND_URL } from '@/lib/backend';

// ── Outils disponibles ────────────────────────────────────────────────────────

const TOOL_OPTIONS = [
  // Réseau
  { name: 'net_ping',          label: '📶 Ping',              category: 'Réseau',    args: [{ key: 'host',    label: 'Hôte',       placeholder: 'google.com' }] },
  { name: 'net_port_scan',     label: '🔌 Scan de ports',     category: 'Réseau',    args: [{ key: 'host',    label: 'Hôte',       placeholder: '' }, { key: 'ports', label: 'Ports', placeholder: '80,443,22' }] },
  { name: 'net_dns_lookup',    label: '🌐 DNS Lookup',        category: 'Réseau',    args: [{ key: 'host', label: 'Hôte', placeholder: 'example.com' }] },
  { name: 'net_traceroute',    label: '🗺️ Traceroute',        category: 'Réseau',    args: [{ key: 'host',    label: 'Hôte',       placeholder: '' }] },
  { name: 'net_scan_local',    label: '🔍 Scan réseau local', category: 'Réseau',    args: [] },
  { name: 'net_whois',         label: '🔎 Whois',             category: 'Réseau',    args: [{ key: 'domain',  label: 'Domaine',    placeholder: '' }] },
  // Système
  { name: 'pc_system_info',    label: '💻 Infos système',     category: 'Système',   args: [] },
  { name: 'pc_process_list',   label: '⚙️ Processus',         category: 'Système',   args: [{ key: 'sort_by', label: 'Tri',        placeholder: 'memory' }] },
  { name: 'pc_run_command',    label: '🖥️ Commande shell',    category: 'Système',   args: [{ key: 'command', label: 'Commande',   placeholder: 'ipconfig' }, { key: 'confirmed', label: '(conf)', placeholder: 'true' }] },
  { name: 'pc_run_powershell', label: '⚡ PowerShell',         category: 'Système',   args: [{ key: 'script',  label: 'Script',     placeholder: 'Get-Date' }, { key: 'confirmed', label: '(conf)', placeholder: 'true' }] },
  { name: 'pc_screenshot',     label: '📷 Capture écran',     category: 'Système',   args: [] },
  { name: 'pc_window_list',    label: '🪟 Fenêtres ouvertes', category: 'Système',   args: [] },
  { name: 'pc_notify',         label: '🔔 Notification',      category: 'Système',   args: [{ key: 'title', label: 'Titre', placeholder: 'Marvin' }, { key: 'message', label: 'Message', placeholder: '' }] },
  // Fichiers
  { name: 'file_list',         label: '📁 Lister dossier',    category: 'Fichiers',  args: [{ key: 'path',    label: 'Chemin',     placeholder: '~' }] },
  { name: 'file_read',         label: '📄 Lire fichier',      category: 'Fichiers',  args: [{ key: 'path',    label: 'Chemin',     placeholder: '' }] },
  { name: 'file_write',        label: '✏️ Écrire fichier',    category: 'Fichiers',  args: [{ key: 'path',    label: 'Chemin',     placeholder: '' }, { key: 'content', label: 'Contenu', placeholder: '' }] },
  { name: 'csv_analyze',       label: '📊 Analyser CSV',      category: 'Fichiers',  args: [{ key: 'path',    label: 'Chemin CSV', placeholder: '' }] },
  // Web
  { name: 'web_search',        label: '🔍 Recherche web',     category: 'Web',       args: [{ key: 'query',   label: 'Requête',    placeholder: '' }] },
  { name: 'web_browse',        label: '🌐 Lire page web',     category: 'Web',       args: [{ key: 'url',     label: 'URL',        placeholder: 'https://example.com' }] },
  // Utilitaires
  { name: 'weather',           label: '🌤️ Météo',             category: 'Outils',    args: [{ key: 'city',    label: 'Ville',      placeholder: 'Paris' }] },
  { name: 'calculator',        label: '🧮 Calculateur',       category: 'Outils',    args: [{ key: 'expression', label: 'Expression', placeholder: '2+2' }] },
  { name: 'hash_compute',      label: '🔏 Hash',              category: 'Outils',    args: [{ key: 'text',    label: 'Texte',      placeholder: '' }] },
  { name: 'translate',         label: '🌍 Traduction',        category: 'Outils',    args: [{ key: 'text',    label: 'Texte',      placeholder: '' }, { key: 'target', label: 'Langue cible', placeholder: 'en' }] },
  { name: 'qr_generate',       label: '📱 QR Code',           category: 'Outils',    args: [{ key: 'data',    label: 'Contenu',    placeholder: 'https://...' }] },
  // Analyse & IA
  { name: 'ocr_extract',       label: '🔍 OCR image',         category: 'Analyse',   args: [{ key: 'image_path', label: 'Chemin image', placeholder: '' }] },
  { name: 'voice_transcribe',  label: '🎙️ Transcription',     category: 'Analyse',   args: [{ key: 'audio_path', label: 'Chemin audio', placeholder: '' }] },
  // Calendrier & tâches
  { name: 'calendar_list',     label: '📅 Calendrier',        category: 'Agenda',    args: [{ key: 'days',    label: 'Jours',      placeholder: '7' }] },
  { name: 'task_list',         label: '✅ Tâches',             category: 'Agenda',    args: [] },
  { name: 'memory_list',       label: '🧠 Mémoires',           category: 'Agenda',    args: [] },
  // Documents
  { name: 'pdf_read',          label: '📕 Lire PDF',          category: 'Docs',      args: [{ key: 'path',    label: 'Chemin',     placeholder: '' }] },
  { name: 'pdf_info',          label: '📕 Infos PDF',         category: 'Docs',      args: [{ key: 'path',    label: 'Chemin',     placeholder: '' }] },
  { name: 'xlsx_read',         label: '📗 Lire Excel',        category: 'Docs',      args: [{ key: 'path',    label: 'Chemin',     placeholder: '' }] },
  { name: 'url_analyze',       label: '🔗 Analyser URL',      category: 'Web',       args: [{ key: 'url',     label: 'URL',        placeholder: 'https://example.com' }] },
  { name: 'zip_list',          label: '🗜️ Lister ZIP',        category: 'Fichiers',  args: [{ key: 'path',    label: 'Chemin',     placeholder: '' }] },
  { name: 'color_tool',        label: '🎨 Couleur',           category: 'Outils',    args: [{ key: 'color',   label: 'Couleur',    placeholder: '#FF5733' }] },
  { name: 'ip_info',           label: '🌍 Infos IP',          category: 'Réseau',    args: [{ key: 'ip',      label: 'IP',         placeholder: '8.8.8.8' }] },
];

const TOOL_MAP = Object.fromEntries(TOOL_OPTIONS.map(t => [t.name, t]));

// ── Presets de scénarios ──────────────────────────────────────────────────────

const PRESETS = [
  {
    label: '🌐 Audit réseau multi-hôtes',
    tasks: [
      { tool_name: 'net_ping',       args: { host: 'google.com' },   label: 'Ping Google' },
      { tool_name: 'net_ping',       args: { host: '1.1.1.1' },      label: 'Ping Cloudflare' },
      { tool_name: 'net_ping',       args: { host: '8.8.8.8' },      label: 'Ping DNS Google' },
      { tool_name: 'net_dns_lookup', args: { host: 'google.com' }, label: 'DNS Google' },
      { tool_name: 'net_scan_local', args: {},                        label: 'Scan réseau local' },
    ],
  },
  {
    label: '💻 Diagnostic système complet',
    tasks: [
      { tool_name: 'pc_system_info',  args: {},                       label: 'Infos CPU/RAM' },
      { tool_name: 'pc_process_list', args: { sort_by: 'memory' },   label: 'Top processus RAM' },
      { tool_name: 'pc_window_list',  args: {},                       label: 'Fenêtres ouvertes' },
      { tool_name: 'net_ping',        args: { host: '8.8.8.8' },     label: 'Connectivité' },
    ],
  },
  {
    label: '🔍 Reconnaissance de domaine',
    tasks: [
      { tool_name: 'net_dns_lookup', args: { host: 'example.com' },                     label: 'DNS' },
      { tool_name: 'net_whois',      args: { host: 'example.com' },                     label: 'Whois' },
      { tool_name: 'net_ping',       args: { host: 'example.com' },                       label: 'Ping' },
      { tool_name: 'net_port_scan',  args: { host: 'example.com', ports: '80,443,21,22,25' }, label: 'Ports ouverts' },
    ],
  },
];

// ── Composants ────────────────────────────────────────────────────────────────

function TaskBuilder({ tasks, onTasksChange }) {
  function addTask() {
    const tool = TOOL_OPTIONS[0];
    const args = {};
    (tool.args || []).forEach(a => { args[a.key] = a.placeholder || ''; });
    onTasksChange([...tasks, { id: crypto.randomUUID(), tool_name: tool.name, args, label: '' }]);
  }

  function updateTask(idx, updates) {
    const next = tasks.map((t, i) => i === idx ? { ...t, ...updates } : t);
    onTasksChange(next);
  }

  function changeToolForTask(idx, toolName) {
    const tool = TOOL_MAP[toolName];
    const args = {};
    (tool?.args || []).forEach(a => { args[a.key] = a.placeholder || ''; });
    updateTask(idx, { tool_name: toolName, args });
  }

  function removeTask(idx) {
    onTasksChange(tasks.filter((_, i) => i !== idx));
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {tasks.map((task, idx) => {
        const toolDef = TOOL_MAP[task.tool_name];
        return (
          <div key={task.id} style={{
            background: 'var(--bg-glass)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)', padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: toolDef?.args?.length ? '10px' : 0 }}>
              <div style={{
                width: '22px', height: '22px', borderRadius: '50%', flexShrink: 0,
                background: 'var(--accent-gradient)', color: 'white',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '11px', fontWeight: 700,
              }}>{idx + 1}</div>

              <select
                value={task.tool_name}
                onChange={e => changeToolForTask(idx, e.target.value)}
                style={{
                  flex: 1, background: 'var(--bg-primary)', border: '1px solid var(--border)',
                  borderRadius: '6px', color: 'var(--text-primary)', padding: '5px 8px',
                  fontSize: 'var(--font-sm)',
                }}
              >
                {Object.entries(
                  TOOL_OPTIONS.reduce((acc, t) => { (acc[t.category] = acc[t.category] || []).push(t); return acc; }, {})
                ).map(([cat, tools]) => (
                  <optgroup key={cat} label={cat}>
                    {tools.map(t => <option key={t.name} value={t.name}>{t.label}</option>)}
                  </optgroup>
                ))}
              </select>

              <input
                value={task.label}
                onChange={e => updateTask(idx, { label: e.target.value })}
                placeholder="Nom de l'agent"
                style={{
                  width: '130px', background: 'var(--bg-primary)', border: '1px solid var(--border)',
                  borderRadius: '6px', color: 'var(--text-muted)', padding: '5px 8px',
                  fontSize: '12px',
                }}
              />

              <button
                onClick={() => removeTask(idx)}
                style={{ background: 'none', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '6px', cursor: 'pointer', color: '#ef4444', padding: '4px 8px', fontSize: '12px' }}
              >×</button>
            </div>

            {toolDef?.args?.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '6px' }}>
                {toolDef.args.map(argDef => (
                  <div key={argDef.key}>
                    <label style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block', marginBottom: '2px' }}>{argDef.label}</label>
                    <input
                      value={task.args?.[argDef.key] ?? ''}
                      onChange={e => updateTask(idx, { args: { ...task.args, [argDef.key]: e.target.value } })}
                      placeholder={argDef.placeholder || ''}
                      style={{
                        width: '100%', background: 'var(--bg-primary)', border: '1px solid var(--border)',
                        borderRadius: '4px', color: 'var(--text-primary)', padding: '4px 7px',
                        fontSize: '12px', boxSizing: 'border-box',
                      }}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      <button
        onClick={addTask}
        style={{
          padding: '10px', borderRadius: 'var(--radius-md)',
          border: '2px dashed rgba(79, 140, 255,0.3)', background: 'transparent',
          color: 'var(--accent-primary)', cursor: 'pointer',
          fontSize: 'var(--font-sm)', fontWeight: 600, transition: 'all 0.2s',
        }}
        onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(79, 140, 255,0.6)'; e.currentTarget.style.background = 'rgba(79, 140, 255,0.04)'; }}
        onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(79, 140, 255,0.3)'; e.currentTarget.style.background = 'transparent'; }}
      >
        + Ajouter un agent
      </button>
    </div>
  );
}

// ── Carte résultat d'un agent ─────────────────────────────────────────────────

function AgentResultCard({ task, result }) {
  const [expanded, setExpanded] = useState(false);
  const toolDef = TOOL_MAP[task.tool_name];
  const label = task.label || toolDef?.label || task.tool_name;

  const status = result
    ? (result.success ? 'success' : 'error')
    : 'running';

  const statusColor = { success: '#22c55e', error: '#ef4444', running: '#4f8cff' }[status];
  const statusBg    = { success: 'rgba(34,197,94,0.08)', error: 'rgba(239,68,68,0.08)', running: 'rgba(79, 140, 255,0.08)' }[status];
  const statusIcon  = { success: '✅', error: '❌', running: '⏳' }[status];

  // Extract a quick summary from common result shapes
  const getSummary = () => {
    if (!result?.result) return null;
    const r = result.result;
    if (r.error)   return <span style={{ color: '#ef4444' }}>{r.error}</span>;
    if (r.summary) return r.summary;
    if (r.reachable !== undefined) return r.reachable ? `✓ ${r.host} — ${r.min_ms ?? '?'}ms` : `✗ ${r.host} — injoignable`;
    if (r.addresses) return r.addresses.join(', ');
    if (r.cpu_percent !== undefined) return `CPU: ${r.cpu_percent}% | RAM: ${r.ram_percent}%`;
    if (r.total_gb !== undefined) return `${r.used_gb}/${r.total_gb} Go`;
    if (r.devices)  return `${r.devices.length} appareil(s)`;
    if (r.open_ports) return `Ports ouverts : ${r.open_ports.join(', ') || 'aucun'}`;
    if (r.text)    return r.text.slice(0, 80) + (r.text.length > 80 ? '…' : '');
    if (r.output)  return r.output.slice(0, 120) + (r.output.length > 120 ? '…' : '');
    return JSON.stringify(r).slice(0, 100);
  };

  return (
    <div style={{
      background: statusBg,
      border: `1px solid ${statusColor}30`,
      borderRadius: 'var(--radius-md)',
      overflow: 'hidden',
      transition: 'all 0.3s ease',
      animation: result ? 'slideUp 0.3s ease' : 'none',
    }}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 14px', cursor: result ? 'pointer' : 'default' }}
        onClick={() => result && setExpanded(!expanded)}
      >
        {/* Spinner ou icône */}
        {status === 'running' ? (
          <div style={{
            width: '20px', height: '20px', border: '2px solid rgba(79, 140, 255,0.3)',
            borderTop: '2px solid #4f8cff', borderRadius: '50%',
            animation: 'spin 1s linear infinite', flexShrink: 0,
          }} />
        ) : (
          <span style={{ fontSize: '18px', flexShrink: 0 }}>{statusIcon}</span>
        )}

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 'var(--font-sm)', color: 'var(--text-primary)' }}>{label}</div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            {toolDef?.label || task.tool_name}
            {result && <span style={{ marginLeft: '8px', color: statusColor }}>{result.duration_ms}ms</span>}
          </div>
        </div>

        {result && (
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textAlign: 'right' }}>
            {getSummary()}
          </div>
        )}

        {result && <span style={{ color: 'var(--text-muted)', fontSize: '10px', flexShrink: 0 }}>{expanded ? '▲' : '▼'}</span>}
      </div>

      {expanded && result?.result && (
        <div style={{ borderTop: `1px solid ${statusColor}20`, padding: '10px 14px' }}>
          <pre style={{
            margin: 0, fontSize: '11px', color: 'var(--text-secondary)',
            background: 'rgba(0,0,0,0.2)', borderRadius: '4px', padding: '8px 10px',
            overflow: 'auto', maxHeight: '200px', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          }}>
            {JSON.stringify(result.result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Statistiques de run ───────────────────────────────────────────────────────

function RunStats({ results, totalMs, running }) {
  if (!results.length && !running) return null;
  const done      = results.length;
  const succeeded = results.filter(r => r.success).length;
  const failed    = done - succeeded;
  const avgMs     = done > 0 ? Math.round(results.reduce((s, r) => s + r.duration_ms, 0) / done) : 0;

  return (
    <div style={{
      display: 'flex', gap: '16px', padding: '12px 16px',
      background: 'var(--bg-glass)', borderRadius: 'var(--radius-md)',
      border: '1px solid var(--border)', fontSize: 'var(--font-xs)', flexWrap: 'wrap',
    }}>
      <Stat label="Terminés" value={done} color="var(--text-primary)" />
      <Stat label="Succès"   value={succeeded} color="#22c55e" />
      {failed > 0 && <Stat label="Erreurs" value={failed} color="#ef4444" />}
      {done > 0 && <Stat label="Durée moy." value={`${avgMs}ms`} color="var(--text-muted)" />}
      {totalMs > 0 && <Stat label="Total" value={`${totalMs}ms`} color="var(--accent-primary)" />}
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
      <span style={{ fontWeight: 700, fontSize: '1rem', color }}>{value}</span>
      <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>{label}</span>
    </div>
  );
}

// ── Page principale ───────────────────────────────────────────────────────────

export default function AgentsPage() {
  const [tasks, setTasks] = useState([
    { id: crypto.randomUUID(), tool_name: 'net_ping',       args: { host: 'google.com' }, label: 'Ping Google' },
    { id: crypto.randomUUID(), tool_name: 'pc_system_info', args: {},                     label: 'Infos système' },
  ]);
  const [running, setRunning]   = useState(false);
  const [results, setResults]   = useState({}); // id → result object
  const [totalMs, setTotalMs]   = useState(0);
  const [history, setHistory]   = useState([]);  // [{label, results, totalMs, ts}]
  const [activeTab, setActiveTab] = useState('builder'); // 'builder' | 'history'
  const esRef = useRef(null);

  // Cleanup on unmount
  useEffect(() => () => esRef.current?.close(), []);

  function loadPreset(preset) {
    setTasks(preset.tasks.map(t => ({ ...t, id: crypto.randomUUID() })));
    setResults({});
    setTotalMs(0);
  }

  async function runAgents() {
    if (!tasks.length) return;
    setRunning(true);
    setResults({});
    setTotalMs(0);

    // Mark all tasks as "pending" (no result yet)
    const initial = {};
    tasks.forEach(t => { initial[t.id] = null; });
    setResults({ ...initial });

    // Close any existing SSE
    if (esRef.current) esRef.current.close();

    try {
      // Use fetch for POST + streaming
      const res = await fetch(`${BACKEND_URL}/api/agents/parallel/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tasks: tasks.map(t => ({ id: t.id, tool_name: t.tool_name, args: t.args || {}, label: t.label || '' })) }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.event === 'task_done') {
              setResults(prev => ({ ...prev, [data.id]: data }));
            } else if (data.event === 'all_done') {
              setTotalMs(data.total_ms);
              setRunning(false);
              // Save to history
              setHistory(prev => [{
                label: `Exécution du ${new Date().toLocaleTimeString('fr-FR')}`,
                tasks: [...tasks],
                total_ms: data.total_ms,
                ts: Date.now(),
              }, ...prev.slice(0, 9)]);
            }
          } catch { /* ignore parse errors */ }
        }
      }
    } catch (err) {
      console.error('Agent run error:', err);
      // Fall back to non-streaming
      try {
        const res = await fetch(`${BACKEND_URL}/api/agents/parallel`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tasks: tasks.map(t => ({ id: t.id, tool_name: t.tool_name, args: t.args || {}, label: t.label || '' })) }),
        });
        const data = await res.json();
        const newResults = {};
        (data.results || []).forEach(r => { newResults[r.id] = r; });
        setResults(newResults);
        setTotalMs(data.total_ms || 0);
        setHistory(prev => [{
          label: `Exécution du ${new Date().toLocaleTimeString('fr-FR')}`,
          tasks: [...tasks],
          total_ms: data.total_ms || 0,
          ts: Date.now(),
        }, ...prev.slice(0, 9)]);
      } catch (err2) {
        console.error('Fallback also failed:', err2);
      }
    } finally {
      setRunning(false);
    }
  }

  function stopAgents() {
    esRef.current?.close();
    setRunning(false);
  }

  const resultList = tasks.map(t => results[t.id] ? { task: t, result: results[t.id] } : { task: t, result: null });
  const hasAnyResult = Object.values(results).some(r => r !== null && r !== undefined);

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* ══ Panneau gauche : configuration ══ */}
      <div style={{
        width: '380px', flexShrink: 0,
        borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column',
        background: '#0d0d0d',
      }}>
        {/* Onglets */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
          {[['builder', '⚙️ Configuration'], ['history', '📜 Historique']].map(([tab, label]) => (
            <button key={tab} onClick={() => setActiveTab(tab)} style={{
              flex: 1, padding: '14px', background: 'none',
              border: 'none', cursor: 'pointer',
              borderBottom: activeTab === tab ? '2px solid var(--accent-primary)' : '2px solid transparent',
              color: activeTab === tab ? 'var(--accent-primary)' : 'var(--text-muted)',
              fontSize: 'var(--font-sm)', fontWeight: activeTab === tab ? 700 : 400,
              transition: 'all 0.2s',
            }}>{label}</button>
          ))}
        </div>

        {activeTab === 'builder' ? (
          <>
            {/* Presets */}
            <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>
                Scénarios prédéfinis
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                {PRESETS.map(p => (
                  <button key={p.label} onClick={() => loadPreset(p)} style={{
                    padding: '7px 10px', textAlign: 'left', background: 'rgba(255,255,255,0.03)',
                    border: '1px solid var(--border)', borderRadius: '6px',
                    color: 'var(--text-secondary)', cursor: 'pointer',
                    fontSize: '12px', transition: 'all 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'rgba(79, 140, 255,0.06)'; e.currentTarget.style.borderColor = 'rgba(79, 140, 255,0.2)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
                  >
                    {p.label} <span style={{ color: 'var(--text-muted)' }}>({p.tasks.length} agents)</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Builder */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
              <TaskBuilder tasks={tasks} onTasksChange={setTasks} />
            </div>

            {/* Bouton run */}
            <div style={{ padding: '14px', borderTop: '1px solid var(--border)' }}>
              {running ? (
                <button
                  onClick={stopAgents}
                  className="btn"
                  style={{
                    width: '100%', padding: '12px',
                    background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
                    color: '#ef4444', cursor: 'pointer', borderRadius: 'var(--radius-md)',
                    fontWeight: 700, fontSize: 'var(--font-sm)',
                  }}
                >
                  ⏹ Arrêter
                </button>
              ) : (
                <button
                  onClick={runAgents}
                  disabled={tasks.length === 0}
                  className="btn btn-primary"
                  style={{ width: '100%', padding: '12px', fontWeight: 700, fontSize: 'var(--font-sm)', opacity: tasks.length === 0 ? 0.5 : 1 }}
                >
                  ▶ Lancer {tasks.length} agent{tasks.length > 1 ? 's' : ''} en parallèle
                </button>
              )}
            </div>
          </>
        ) : (
          /* Historique */
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
            {history.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 16px', color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>
                <div style={{ fontSize: '2rem', marginBottom: '8px' }}>📜</div>
                Aucune exécution dans cet historique.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {history.map((h, i) => (
                  <div key={h.ts} style={{
                    padding: '10px 12px',
                    background: 'var(--bg-glass)', borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)', cursor: 'pointer',
                  }}
                  onClick={() => loadPreset({ tasks: h.tasks })}
                  >
                    <div style={{ fontWeight: 600, fontSize: 'var(--font-sm)', marginBottom: '4px' }}>{h.label}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', gap: '10px' }}>
                      <span>⚙️ {h.tasks.length} agents</span>
                      <span>⏱ {h.total_ms}ms</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ══ Panneau droit : résultats ══ */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Header */}
        <div className="page-header" style={{ borderBottom: '1px solid var(--border)' }}>
          <div>
            <h1 style={{ marginBottom: '2px' }}>🤖 Multi-Agents</h1>
            <p style={{ margin: 0, fontSize: 'var(--font-sm)', color: 'var(--text-muted)' }}>
              Exécution parallèle d'outils — résultats en temps réel
            </p>
          </div>
          {(hasAnyResult || running) && (
            <RunStats
              results={Object.values(results).filter(Boolean)}
              totalMs={totalMs}
              running={running}
            />
          )}
        </div>

        {/* Grille de résultats */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          {!hasAnyResult && !running ? (
            /* État initial */
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '16px', color: 'var(--text-muted)' }}>
              <div style={{ fontSize: '4rem' }}>🤖</div>
              <h2 style={{ margin: 0 }}>Agents prêts</h2>
              <p style={{ margin: 0, textAlign: 'center', maxWidth: '420px', fontSize: 'var(--font-sm)' }}>
                Configurez vos agents à gauche puis lancez-les en parallèle.
                Chaque agent exécute un outil indépendamment et les résultats arrivent au fur et à mesure.
              </p>
              <div style={{ display: 'flex', gap: '10px', marginTop: '8px' }}>
                {PRESETS.map(p => (
                  <button key={p.label} onClick={() => { loadPreset(p); }} className="btn btn-secondary" style={{ fontSize: 'var(--font-xs)' }}>
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {/* Barre de progression */}
              {running && (
                <div style={{ marginBottom: '4px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: 'var(--font-xs)', color: 'var(--text-muted)' }}>
                    <span>⏳ Agents en cours…</span>
                    <span>{Object.values(results).filter(Boolean).length} / {tasks.length}</span>
                  </div>
                  <div style={{ height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden' }}>
                    <div style={{
                      height: '100%', borderRadius: '2px',
                      background: 'var(--accent-gradient)',
                      width: `${(Object.values(results).filter(Boolean).length / tasks.length) * 100}%`,
                      transition: 'width 0.3s ease',
                    }} />
                  </div>
                </div>
              )}

              {/* Cartes agents */}
              {resultList.map(({ task, result }) => (
                <AgentResultCard key={task.id} task={task} result={result} />
              ))}
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
