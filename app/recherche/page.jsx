'use client';

import { useState, useRef } from 'react';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

// Métadonnées d'affichage par source
const SOURCES = {
  documents:     { icon: '📄', label: 'Documents indexés', color: '#a78bfa' },
  files_name:    { icon: '🗂️', label: 'Fichiers (nom)', color: '#60a5fa' },
  files_content: { icon: '🔎', label: 'Fichiers (contenu)', color: '#60a5fa' },
  notes:         { icon: '📝', label: 'Notes', color: '#fbbf24' },
  tasks:         { icon: '✅', label: 'Tâches', color: '#34d399' },
  events:        { icon: '📅', label: 'Agenda', color: '#f472b6' },
  memory:        { icon: '🧠', label: 'Mémoire', color: '#22d3ee' },
  emails:        { icon: '📧', label: 'Emails', color: '#fb923c' },
  web:           { icon: '🌐', label: 'Web', color: '#4ade80' },
};
const DEFAULT_SCOPE = ['documents', 'files_name', 'files_content', 'notes', 'tasks', 'events', 'memory'];
const ORDER = ['documents', 'files_content', 'files_name', 'notes', 'tasks', 'events', 'memory', 'emails', 'web'];

export default function RecherchePage() {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);
  const [withEmails, setWithEmails] = useState(false);
  const [withWeb, setWithWeb] = useState(false);
  const inputRef = useRef(null);

  async function openPath(path) {
    try { await fetch(`${BACKEND}/api/tools`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ toolName: 'pc_open_file', args: { path } }) }); } catch {}
  }

  async function search(e) {
    e?.preventDefault();
    if (!q.trim()) return;
    setBusy(true); setData(null);
    const scope = [...DEFAULT_SCOPE, ...(withEmails ? ['emails'] : []), ...(withWeb ? ['web'] : [])];
    try {
      const r = await fetch(`${BACKEND}/api/search/unified?query=${encodeURIComponent(q.trim())}&scope=${scope.join(',')}&limit=6`).then(r => r.json());
      setData(r.error ? { error: r.error } : r);
    } catch { setData({ error: 'Backend injoignable' }); }
    setBusy(false);
  }

  const inp = { padding: '12px 14px', borderRadius: 12, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 15 };

  function renderItem(src, it, i) {
    const c = SOURCES[src].color;
    if (src === 'documents')
      return <div key={i}><div style={{ fontSize: 13, fontWeight: 600 }}>📄 {it.name} <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>({it.score})</span></div>{it.snippet && <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontStyle: 'italic' }}>« …{it.snippet}… »</div>}</div>;
    if (src === 'files_name' || src === 'files_content')
      return <div key={i}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{it.is_dir ? '📁' : '📄'} {it.name}</span>
          <span style={{ flex: 1 }} />
          <button onClick={() => openPath(it.path)} style={{ fontSize: 11, padding: '3px 9px', borderRadius: 7, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}>📂 Ouvrir</button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', wordBreak: 'break-all' }}>{it.path}</div>
        {it.snippet && <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontStyle: 'italic', marginTop: 2 }}>« …{it.snippet}… »</div>}
      </div>;
    if (src === 'notes')
      return <div key={i}><div style={{ fontSize: 13, fontWeight: 600 }}>📝 {it.title || '(sans titre)'}</div>{it.snippet && <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{it.snippet}</div>}</div>;
    if (src === 'tasks')
      return <div key={i} style={{ fontSize: 13 }}>✅ {it.title} <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>· {it.status}{it.due_date ? ` · échéance ${it.due_date}` : ''}</span></div>;
    if (src === 'events')
      return <div key={i} style={{ fontSize: 13 }}>📅 {it.title} <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>· {it.start_at}{it.source && it.source !== 'local' ? ` · ${it.source}` : ''}</span></div>;
    if (src === 'memory')
      return <div key={i} style={{ fontSize: 13, color: 'var(--text-secondary)' }}>🧠 <span style={{ fontSize: 10, color: c, textTransform: 'uppercase' }}>{it.type}</span> {it.text}</div>;
    if (src === 'emails')
      return <div key={i} style={{ fontSize: 13 }}>📧 {it.subject || '(sans objet)'} <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>· {it.from}{it.date ? ` · ${it.date}` : ''}</span></div>;
    if (src === 'web')
      return <div key={i}><a href={it.url} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontWeight: 600, color: c, textDecoration: 'none' }}>🌐 {it.title}</a>{it.snippet && <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{it.snippet}</div>}</div>;
    return null;
  }

  const results = data?.results || {};
  const activeSources = ORDER.filter(s => (results[s] || []).length > 0);

  return (
    <div style={{ height: '100vh', overflowY: 'auto', background: 'var(--bg-primary)', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 880, margin: '0 auto' }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#22d3ee' }}>🔍 Recherche unifiée</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 18 }}>
          Une seule recherche, partout à la fois : tes documents, tout le PC (nom + contenu), notes, tâches, agenda et mémoire. 100 % local.
        </div>

        <form onSubmit={search} style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} autoFocus placeholder="Cherche un nom, un sujet, un client… (ex : « KOIOS », « facture », « garantie »)"
            style={{ ...inp, flex: 1 }} />
          <button type="submit" disabled={busy || !q.trim()}
            style={{ padding: '12px 26px', borderRadius: 12, border: 'none', background: '#22d3ee', color: '#0a0a0a', fontWeight: 800, cursor: busy ? 'wait' : 'pointer', fontSize: 15 }}>
            {busy ? '⏳' : 'Chercher'}
          </button>
        </form>
        <div style={{ display: 'flex', gap: 18, marginBottom: 22, fontSize: 12, color: 'var(--text-secondary)' }}>
          <span style={{ color: 'var(--text-muted)' }}>Ajouter :</span>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input type="checkbox" checked={withEmails} onChange={e => setWithEmails(e.target.checked)} /> 📧 Emails
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input type="checkbox" checked={withWeb} onChange={e => setWithWeb(e.target.checked)} /> 🌐 Web
          </label>
        </div>

        {data?.error && <div style={{ fontSize: 14, color: '#f87171' }}>⚠️ {data.error}</div>}

        {data && !data.error && (
          <>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 14 }}>
              <strong style={{ color: 'var(--text-primary)' }}>{data.total}</strong> résultat(s) dans {activeSources.length} source(s).
            </div>
            {data.total === 0 && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Rien trouvé. Essaie un autre terme, ou ajoute les emails / le web.</div>}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {activeSources.map(src => (
                <div key={src} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: 14, padding: '14px 16px' }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: SOURCES[src].color, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
                    {SOURCES[src].icon} {SOURCES[src].label}
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>{results[src].length}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                    {results[src].map((it, i) => renderItem(src, it, i))}
                  </div>
                </div>
              ))}
            </div>
            {data.errors && Object.keys(data.errors).length > 0 && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 14 }}>
                Sources indisponibles : {Object.entries(data.errors).map(([s, e]) => `${SOURCES[s]?.label || s}`).join(', ')}
              </div>
            )}
          </>
        )}

        {!data && !busy && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'center', padding: 30 }}>
            Tape un terme ci-dessus : Marvin interroge toutes tes sources en même temps.
          </div>
        )}
      </div>
    </div>
  );
}
