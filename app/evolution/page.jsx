'use client';
import { useCallback, useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/backend';

export default function EvolutionPage() {
  const [data, setData] = useState({ experiments: [], allowed_targets: {} });
  const [form, setForm] = useState({ name: '', target: 'research_swarm_concurrency', candidate_value: 4, hypothesis: '' });
  const [selected, setSelected] = useState(null);
  const [baseline, setBaseline] = useState('[{"success":true,"duration_ms":1000},{"success":true,"duration_ms":1100},{"success":false,"duration_ms":1200}]');
  const [candidate, setCandidate] = useState('[{"success":true,"duration_ms":900},{"success":true,"duration_ms":950},{"success":true,"duration_ms":1000}]');
  const [error, setError] = useState('');
  const load = useCallback(() => fetch(`${BACKEND_URL}/api/evolution/experiments`).then(r => r.json()).then(setData).catch(e => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  const create = async () => {
    setError('');
    const r = await fetch(`${BACKEND_URL}/api/evolution`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
    const d = await r.json(); if (!r.ok) setError(d.detail || 'Erreur'); else { setForm({ ...form, name: '', hypothesis: '' }); load(); }
  };
  const call = async (path, payload) => {
    setError('');
    try {
      const r = await fetch(`${BACKEND_URL}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setSelected(d.experiment || selected);
      await load();
    } catch (err) { setError(err.message || 'Action Evolution Lab impossible'); }
  };
  const evaluate = () => {
    try {
      call(`/api/evolution/${selected.id}/evaluate`, { baseline_trials: JSON.parse(baseline), candidate_trials: JSON.parse(candidate) });
    } catch { setError('Les essais doivent être des tableaux JSON valides.'); }
  };
  return <div style={{ height: '100%', overflowY: 'auto', padding: 28, color: 'var(--text-primary)' }}><div style={{ maxWidth: 1050, margin: 'auto' }}>
    <h1 style={{ color: '#c084fc' }}>Evolution Lab</h1>
    <p style={{ color: 'var(--text-muted)' }}>Les candidats ne sont promus qu’après trois essais baseline, trois essais candidate, amélioration mesurée, zéro échec critique et confirmation humaine.</p>
    {error && <div style={{ color: '#f87171' }}>{error}</div>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(210px,1fr))', gap: 8, padding: 14, border: '1px solid var(--border)', borderRadius: 12 }}>
      <input placeholder="Nom de l'expérience" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
      <select value={form.target} onChange={e => setForm({ ...form, target: e.target.value })}>{Object.keys(data.allowed_targets || {}).map(k => <option key={k}>{k}</option>)}</select>
      <input type="number" value={form.candidate_value} onChange={e => setForm({ ...form, candidate_value: Number(e.target.value) })} />
      <input placeholder="Hypothèse mesurable" value={form.hypothesis} onChange={e => setForm({ ...form, hypothesis: e.target.value })} />
      <button onClick={create} disabled={!form.name.trim()}>Créer le candidat</button>
    </div>
    <div style={{ display: 'grid', gap: 10, marginTop: 16 }}>{data.experiments.map(x => <div key={x.id} onClick={() => setSelected(x)} style={{ padding: 14, border: `1px solid ${selected?.id === x.id ? '#c084fc' : 'var(--border)'}`, borderRadius: 12, cursor: 'pointer' }}>
      <b>{x.name}</b> <span style={{ color: '#c084fc' }}>{x.status}</span>
      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 5 }}>{x.target}: {String(x.baseline_value)} → {String(x.candidate_value)}</div>
      <div style={{ fontSize: 12, marginTop: 5 }}>{x.hypothesis}</div>
      {x.evaluation && <div style={{ marginTop: 7, color: x.evaluation.promotable ? '#34d399' : '#fbbf24' }}>Promotion: {x.evaluation.promotable ? 'autorisable' : 'refusée'}</div>}
    </div>)}</div>
    {selected && <div style={{ marginTop: 18, padding: 15, border: '1px solid rgba(192,132,252,.4)', borderRadius: 12 }}>
      <h3 style={{ marginTop: 0 }}>Évaluer {selected.name}</h3>
      <p style={{ color: 'var(--text-muted)', fontSize: 12 }}>Chaque tableau doit contenir au moins trois essais avec success, duration_ms et éventuellement critical_failure.</p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <label style={{ fontSize: 12 }}>Baseline<textarea value={baseline} onChange={e => setBaseline(e.target.value)} style={{ width: '100%', minHeight: 120, display: 'block', marginTop: 5 }} /></label>
        <label style={{ fontSize: 12 }}>Candidate<textarea value={candidate} onChange={e => setCandidate(e.target.value)} style={{ width: '100%', minHeight: 120, display: 'block', marginTop: 5 }} /></label>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <button onClick={evaluate}>Calculer l'évaluation</button>
        <button disabled={!selected.evaluation?.promotable || selected.status === 'promoted'} onClick={() => call(`/api/evolution/${selected.id}/promote`, { confirmed: true })}>Promouvoir</button>
        <button disabled={selected.status !== 'promoted'} onClick={() => call(`/api/evolution/${selected.id}/rollback`, { confirmed: true })}>Rollback</button>
      </div>
      {selected.evaluation && <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{JSON.stringify(selected.evaluation, null, 2)}</pre>}
    </div>}
  </div></div>;
}
