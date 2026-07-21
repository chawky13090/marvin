'use client';

import { useCallback, useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/backend';

const NEEDS = [
  'general', 'reasoning', 'agentic', 'code', 'code_architecture',
  'code_implementation', 'code_review', 'vision', 'research',
  'verification', 'synthesis', 'productivity', 'multilingual',
];

function Score({ value }) {
  const color = value >= 70 ? '#34d399' : value >= 50 ? '#fbbf24' : '#f87171';
  return <span style={{ color, fontWeight: 800 }}>{Math.round(value)}</span>;
}

export default function ModelMarketPage() {
  const [need, setNeed] = useState('research');
  const [catalog, setCatalog] = useState(null);
  const [question, setQuestion] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const [fleet, setFleet] = useState(null);
  const [fleetBusy, setFleetBusy] = useState(false);
  const [modelToPull, setModelToPull] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/model-market/catalog?need=${encodeURIComponent(need)}`);
      if (!response.ok) throw new Error(`Model Market HTTP ${response.status}`);
      setCatalog(await response.json());
      const fleetResponse = await fetch(`${BACKEND_URL}/api/model-market/fleet`);
      if (fleetResponse.ok) setFleet(await fleetResponse.json());
    } catch (err) {
      setError(err.message || 'Model Market indisponible');
    }
  }, [need]);

  useEffect(() => { load(); }, [load]);

  const syncFleet = async () => {
    setFleetBusy(true);
    setError('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/model-market/fleet/sync`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      await load();
    } catch (err) {
      setError(err.message || 'Synchronisation Ollama Cloud impossible');
    } finally {
      setFleetBusy(false);
    }
  };

  const pullModel = async () => {
    if (!modelToPull.trim()) return;
    setFleetBusy(true);
    setError('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/model-market/fleet/pull`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelToPull.trim() }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
      }
      setModelToPull('');
      await load();
    } catch (err) {
      setError(err.message || 'Téléchargement du modèle impossible');
    } finally {
      setFleetBusy(false);
    }
  };

  const runSwarm = async () => {
    if (!question.trim()) return;
    setRunning(true);
    setResult(null);
    setError('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/model-market/swarm/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim(), agent_count: 5, sources_per_agent: 3 }),
      });
      const data = await response.json();
      if (!response.ok || !data.job) throw new Error(data.detail || `HTTP ${response.status}`);
      setJob(data.job);
      const id = data.job.id;
      const stream = await fetch(`${BACKEND_URL}/api/model-market/swarm/jobs/${id}/stream`);
      if (!stream.ok || !stream.body) throw new Error('Flux Research Swarm indisponible');
      const reader = stream.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let completedResult = null;
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() || '';
        for (const frame of frames) {
          const line = frame.split('\n').find(value => value.startsWith('data: '));
          if (!line) continue;
          const current = JSON.parse(line.slice(6));
          setJob(current);
          if (current.status === 'completed') completedResult = current.result;
          if (['failed', 'cancelled', 'interrupted'].includes(current.status)) {
            throw new Error(current.error || current.status);
          }
        }
      }
      if (!completedResult) throw new Error('Research Swarm terminé sans résultat');
      setResult(completedResult);
      await load();
    } catch (err) {
      setError(err.message || 'Research Swarm a échoué');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '28px 32px', color: 'var(--text-primary)' }}>
      <div style={{ maxWidth: 1180, margin: '0 auto' }}>
        <h1 style={{ margin: 0, color: '#2dd4bf', fontSize: '1.7rem' }}>Model Market et Research Swarm</h1>
        <p style={{ color: 'var(--text-muted)', maxWidth: 820, fontSize: 13 }}>
          Classement fondé sur les modèles réellement installés et leurs appels réels. Aucune sonde cloud payante n’est déclenchée pour produire les scores.
        </p>

        {error && <div style={{ color: '#f87171', margin: '14px 0' }}>{error}</div>}

        <section style={{ border: '1px solid rgba(96,165,250,.35)', borderRadius: 14, padding: 16, background: 'rgba(59,130,246,.05)', marginTop: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontWeight: 750 }}>Parc Ollama Cloud</div>
              <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 3 }}>
                {fleet?.installed_count ?? 0} modèles accessibles · {(fleet?.missing_recommended || []).length} recommandé(s) manquant(s)
              </div>
            </div>
            <button type="button" onClick={syncFleet} disabled={fleetBusy}
              style={{ padding: '8px 12px', borderRadius: 9, border: '1px solid rgba(96,165,250,.45)', background: 'rgba(59,130,246,.12)', color: '#93c5fd', fontWeight: 700 }}>
              {fleetBusy ? 'Synchronisation…' : 'Synchroniser les meilleurs modèles'}
            </button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(245px,1fr))', gap: 8, marginTop: 12 }}>
            {(fleet?.recommended || []).map(item => (
              <div key={item.model} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 10 }}>
                <div style={{ fontWeight: 700, fontSize: 12, wordBreak: 'break-word' }}>{item.model}</div>
                <div style={{ color: item.installed ? '#34d399' : '#fbbf24', fontSize: 10, marginTop: 4 }}>
                  {item.installed ? 'Accessible' : 'À télécharger'}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: 10, marginTop: 5 }}>{item.reason}</div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            <input value={modelToPull} onChange={event => setModelToPull(event.target.value)}
              placeholder="autre-modele:cloud"
              style={{ flex: 1, minWidth: 230, padding: '8px 10px', borderRadius: 9, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }} />
            <button type="button" onClick={pullModel} disabled={fleetBusy || !modelToPull.trim()}
              style={{ padding: '8px 12px', borderRadius: 9, border: '1px solid var(--border)', background: 'rgba(255,255,255,.04)', color: 'var(--text-primary)', fontWeight: 700 }}>
              Ajouter un modèle Cloud
            </button>
          </div>
        </section>

        <section style={{ border: '1px solid var(--border)', borderRadius: 14, padding: 16, background: 'rgba(255,255,255,.02)', marginTop: 18 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontWeight: 750 }}>Marché des modèles</div>
              <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 3 }}>
                {catalog?.installed_count ?? 0} modèles cloud · {catalog?.observation_count ?? 0} observations · {catalog?.need_label || need}
              </div>
            </div>
            <select value={need} onChange={event => setNeed(event.target.value)}
              style={{ padding: '8px 10px', borderRadius: 9, background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
              {NEEDS.map(item => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(245px,1fr))', gap: 10, marginTop: 14 }}>
            {(catalog?.models || []).map((model, index) => (
              <div key={model.model} style={{ border: '1px solid var(--border)', borderRadius: 11, padding: 12, background: index === 0 ? 'rgba(45,212,191,.07)' : 'rgba(255,255,255,.02)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ fontWeight: 700, wordBreak: 'break-word' }}>{index + 1}. {model.model}</div>
                  <Score value={model.score} />
                </div>
                <div style={{ color: '#93c5fd', fontSize: 11, marginTop: 5 }}>{model.family}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 7 }}>
                  {model.observations.calls} appel(s) · {model.observations.success_rate == null ? 'non mesuré' : `${Math.round(model.observations.success_rate * 100)} % succès`}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: 10, marginTop: 7 }}>{model.reasons.join(' · ')}</div>
              </div>
            ))}
          </div>
        </section>

        <section style={{ border: '1px solid rgba(20,184,166,.35)', borderRadius: 14, padding: 16, background: 'rgba(20,184,166,.05)', marginTop: 18 }}>
          <div style={{ fontWeight: 750 }}>Research Swarm</div>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, margin: '5px 0 11px' }}>
            Cinq familles cloud distinctes recherchent en parallèle : sources primaires, état de l’art, contradiction, exécution et vérification.
          </div>
          <textarea value={question} onChange={event => setQuestion(event.target.value)}
            placeholder="Question de recherche complexe et non sensible"
            style={{ width: '100%', minHeight: 90, resize: 'vertical', boxSizing: 'border-box', borderRadius: 10, padding: 11, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }} />
          <button type="button" onClick={runSwarm} disabled={running || !question.trim()}
            style={{ marginTop: 9, padding: '9px 14px', borderRadius: 9, border: '1px solid rgba(45,212,191,.45)', background: 'rgba(45,212,191,.14)', color: '#5eead4', cursor: 'pointer', fontWeight: 700 }}>
            {running ? 'Essaim en cours…' : 'Lancer Research Swarm'}
          </button>
          {job && running && <div style={{ marginTop: 8, color: 'var(--text-muted)', fontSize: 12 }}>
            {job.progress?.stage || job.status} · {job.progress?.completed || 0}/{job.progress?.total || job.agent_count}
            <button onClick={() => fetch(`${BACKEND_URL}/api/model-market/swarm/jobs/${job.id}`, { method: 'DELETE' })} style={{ marginLeft: 10 }}>Annuler</button>
          </div>}
        </section>

        {result && (
          <section style={{ marginTop: 18, border: '1px solid var(--border)', borderRadius: 14, padding: 16, background: 'rgba(255,255,255,.02)' }}>
            <div style={{ fontWeight: 750, marginBottom: 8 }}>Rapport final</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 12 }}>
              {result.cells?.length || 0} cellules · {result.sources?.length || 0} sources · {(result.models_consulted || []).length} modèles
            </div>
            <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit', lineHeight: 1.55, fontSize: 13 }}>{result.answer}</pre>
            <div style={{ marginTop: 14, display: 'grid', gap: 6 }}>
              {(result.sources || []).map((source, index) => (
                <a key={source.url} href={source.url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', fontSize: 12 }}>
                  [{source.citations?.join(', ') || source.citation || index + 1}] {source.title || source.url}
                </a>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
