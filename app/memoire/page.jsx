'use client';

import { useState, useEffect, useCallback } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

export default function MemoirePage() {
  const [data, setData] = useState({ counts: { facts: 0, qa: 0 }, facts: [], qa: [] });
  const [newFact, setNewFact] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { const r = await fetch(`${BACKEND}/api/learning`).then(r => r.json()); setData(r); } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  async function del(kind, id) {
    try { await fetch(`${BACKEND}/api/learning/${kind}/${id}`, { method: 'DELETE' }); load(); } catch {}
  }
  async function addFact(e) {
    e.preventDefault();
    if (!newFact.trim()) return;
    try { await fetch(`${BACKEND}/api/learning/fact`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: newFact.trim() }) }); setNewFact(''); load(); } catch {}
  }

  return (
    <div style={{ height: '100vh', overflowY: 'auto', background: 'var(--bg-primary)', color: 'var(--text-primary)', padding: '28px 32px' }}>
      <div style={{ maxWidth: 820, margin: '0 auto' }}>
        <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#c084fc' }}>🧠 Mémoire de Marvin</h1>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 18 }}>
          Ce que Marvin a appris de vos échanges (faits durables + réponses réutiles). Il s'en sert pour mieux te répondre. 100 % local. Tu peux corriger ou supprimer.
        </div>

        {/* Apprendre un fait manuellement */}
        <form onSubmit={addFact} style={{ display: 'flex', gap: 8, marginBottom: 22 }}>
          <input value={newFact} onChange={e => setNewFact(e.target.value)} placeholder="Apprends quelque chose à Marvin (ex : « Mon comptable s'appelle Paul »)"
            style={{ flex: 1, padding: '11px 14px', borderRadius: 12, border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-primary)', fontSize: 14 }} />
          <button type="submit" disabled={!newFact.trim()} style={{ padding: '11px 20px', borderRadius: 12, border: 'none', background: 'var(--accent-gradient, #c084fc)', color: '#1a1a1a', fontWeight: 800, cursor: 'pointer', fontSize: 14 }}>＋ Apprendre</button>
        </form>

        {/* Faits */}
        <div style={{ marginBottom: 26 }}>
          <h3 style={{ fontSize: '1rem', marginBottom: 10 }}>📌 Ce qu'il sait sur toi <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({data.counts?.facts || 0})</span></h3>
          {loading ? <LoadingRow />
            : data.facts.length === 0 ? <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Rien encore. Marvin apprendra au fil de vos conversations.</div>
            : data.facts.map(f => (
              <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', marginBottom: 6, background: 'rgba(192,132,252,0.06)', border: '1px solid rgba(192,132,252,0.2)', borderRadius: 10 }}>
                <span style={{ flex: 1, fontSize: 14 }}>{f.text}</span>
                <button onClick={() => del('facts', f.id)} title="Oublier" style={{ background: 'transparent', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 14 }}>🗑️</button>
              </div>
            ))}
        </div>

        {/* Q/R réutilisables */}
        <div>
          <h3 style={{ fontSize: '1rem', marginBottom: 10 }}>💡 Réponses apprises <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({data.counts?.qa || 0})</span></h3>
          {(!loading && data.qa.length === 0) && <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Aucune réponse réutilisable mémorisée pour l'instant.</div>}
          {data.qa.map(item => (
            <div key={item.id} style={{ padding: '12px 14px', marginBottom: 8, background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#c084fc' }}>Q : {item.q}</span>
                <button onClick={() => del('qa', item.id)} title="Oublier" style={{ background: 'transparent', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: 13, flexShrink: 0 }}>🗑️</button>
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap' }}>{item.a}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
