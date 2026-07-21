'use client';
import { useCallback, useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/backend';

export default function MissionsPage() {
  const [missions, setMissions] = useState([]);
  const [selected, setSelected] = useState(null);
  const [checkpoint, setCheckpoint] = useState('');
  const load = useCallback(async () => {
    const d = await fetch(`${BACKEND_URL}/api/missions`).then(r => r.json());
    setMissions(d.missions || []);
  }, []);
  useEffect(() => { load(); const timer = setInterval(load, 5000); return () => clearInterval(timer); }, [load]);
  const loadDetail = useCallback(async (missionId) => {
    const detail = await fetch(`${BACKEND_URL}/api/missions/${missionId}`).then(r => r.json());
    setSelected(detail);
  }, []);
  useEffect(() => {
    const missionId = selected?.mission?.id;
    if (!missionId) return undefined;
    const timer = setInterval(() => loadDetail(missionId), 3000);
    return () => clearInterval(timer);
  }, [selected?.mission?.id, loadDetail]);
  const action = async (path, method = 'POST', body) => {
    const response = await fetch(`${BACKEND_URL}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    if (!response.ok) return;
    await load();
    if (selected?.mission?.id) await loadDetail(selected.mission.id);
  };
  return <div style={{ height: '100%', display: 'grid', gridTemplateColumns: '330px 1fr', color: 'var(--text-primary)' }}>
    <aside style={{ overflowY: 'auto', borderRight: '1px solid var(--border)', padding: 16 }}><h2>Mission Canvas</h2>{missions.map(m => <button key={m.id} onClick={() => loadDetail(m.id)}
      style={{ width: '100%', textAlign: 'left', padding: 11, marginBottom: 7, borderRadius: 9, border: '1px solid var(--border)', background: 'var(--bg-glass)', color: 'var(--text-primary)' }}>
      <b>{m.goal}</b><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{m.status} · {m.steps?.length || 0} étapes</div>
    </button>)}</aside>
    <main style={{ overflowY: 'auto', padding: 24 }}>{!selected ? <div style={{ color: 'var(--text-muted)' }}>Sélectionne une mission.</div> : <>
      <h1>{selected.mission.goal}</h1><div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
        <button onClick={() => window.confirm('Mettre cette mission en pause ?') && action(`/api/missions/${selected.mission.id}/pause`, 'POST', { reason: 'Pause depuis Mission Canvas' })}>Pause</button>
        <button onClick={() => action(`/api/missions/${selected.mission.id}/resume`)}>Reprendre</button>
      </div>
      <div style={{ display: 'flex', gap: 7, marginBottom: 18 }}>
        <input value={checkpoint} onChange={e => setCheckpoint(e.target.value)} placeholder="Nom du checkpoint" />
        <button disabled={!checkpoint.trim()} onClick={async () => { await action(`/api/missions/${selected.mission.id}/checkpoints`, 'POST', { label: checkpoint.trim(), state: { source: 'mission_canvas' } }); setCheckpoint(''); }}>Créer un checkpoint</button>
      </div>
      <div style={{ display: 'grid', gap: 10 }}>{selected.mission.steps.map(step => <div key={step.index} style={{ padding: 13, borderRadius: 11, border: '1px solid var(--border)', background: step.status === 'done' ? 'rgba(52,211,153,.08)' : 'var(--bg-glass)' }}>
        <b>{step.index}. {step.title}</b><span style={{ marginLeft: 10, color: 'var(--text-muted)' }}>{step.status}</span>
        {step.status !== 'done' && <button onClick={() => window.confirm(`Relancer uniquement l'étape ${step.index} ?`) && action(`/api/missions/${selected.mission.id}/steps/${step.index}/retry`)} style={{ float: 'right' }}>Retry</button>}
      </div>)}</div>
      <h3 style={{ marginTop: 22 }}>Chronologie</h3>{selected.events.slice(0, 30).map(e => <div key={e.id} style={{ fontSize: 12, padding: '6px 0', borderBottom: '1px solid var(--border)' }}>{e.at} · {e.type}</div>)}
    </>}</main>
  </div>;
}
