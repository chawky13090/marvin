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
  const [swarmIntegrity, setSwarmIntegrity] = useState(null);
  const [fleetBusy, setFleetBusy] = useState(false);
  const [modelToPull, setModelToPull] = useState('');
  const [researchConfig, setResearchConfig] = useState({
    depth: 'deep',
    freshness: '',
    sourcePolicy: 'primary_first',
  });
  const [steeringQuery, setSteeringQuery] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const [response, fleetResponse, swarmResponse] = await Promise.all([
        fetch(`${BACKEND_URL}/api/model-market/catalog?need=${encodeURIComponent(need)}`),
        fetch(`${BACKEND_URL}/api/model-market/fleet`),
        fetch(`${BACKEND_URL}/api/model-market/swarm/runs?limit=1`),
      ]);
      if (!response.ok) throw new Error(`Model Market HTTP ${response.status}`);
      setCatalog(await response.json());
      if (fleetResponse.ok) setFleet(await fleetResponse.json());
      if (swarmResponse.ok) {
        setSwarmIntegrity((await swarmResponse.json()).evidence_integrity || null);
      }
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
        body: JSON.stringify({
          question: question.trim(),
          agent_count: 5,
          sources_per_agent: researchConfig.depth === 'exhaustive' ? 8 : 5,
          max_duration_seconds: researchConfig.depth === 'exhaustive' ? 1800 : 900,
          engine_version: 'v3',
          depth: researchConfig.depth,
          freshness: researchConfig.freshness || null,
          source_policy: researchConfig.sourcePolicy,
        }),
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

  const downloadReport = (format) => {
    if (!result) return;
    const sources = (result.sources || [])
      .map((source, index) => `[${source.id || index + 1}] ${source.title || source.url}\n${source.url}`)
      .join('\n\n');
    const content = format === 'json'
      ? JSON.stringify(result, null, 2)
      : `# Rapport de recherche\n\n${result.answer || ''}\n\n## Sources\n\n${sources}\n`;
    const blob = new Blob([content], {
      type: format === 'json' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8',
    });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `marvin-research-${result.id || 'report'}.${format === 'json' ? 'json' : 'md'}`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const steerResearch = async () => {
    if (!job?.id || !steeringQuery.trim()) return;
    try {
      const response = await fetch(`${BACKEND_URL}/api/model-market/swarm/jobs/${job.id}/steer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: steeringQuery.trim() }),
      });
      if (!response.ok) throw new Error(`Réorientation HTTP ${response.status}`);
      setSteeringQuery('');
    } catch (err) {
      setError(err.message || 'Réorientation impossible');
    }
  };

  const downloadGeneratedReport = async (format) => {
    if (!result?.id) return;
    try {
      const response = await fetch(
        `${BACKEND_URL}/api/model-market/swarm/runs/${encodeURIComponent(result.id)}/export?format=${format}`,
      );
      if (!response.ok) throw new Error(`Export ${format.toUpperCase()} HTTP ${response.status}`);
      const blob = await response.blob();
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `marvin-research-${result.id}.${format}`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (err) {
      setError(err.message || 'Export impossible');
    }
  };

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '28px 32px', color: 'var(--text-primary)' }}>
      <div style={{ maxWidth: 1180, margin: '0 auto' }}>
        <h1 style={{ margin: 0, color: '#2dd4bf', fontSize: '1.7rem' }}>Model Market et Recherche approfondie</h1>
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
              {catalog?.evidence_integrity && <div style={{ color: catalog.evidence_integrity.valid ? catalog.evidence_integrity.legacy_records ? '#fbbf24' : '#34d399' : '#fb7185', fontSize: 10, marginTop: 5 }}>
                {catalog.evidence_integrity.valid
                  ? catalog.evidence_integrity.legacy_records
                    ? `Télémétrie cohérente · ${catalog.evidence_integrity.legacy_records} observation(s) historique(s) non signée(s)`
                    : `Télémétrie vérifiable · ${catalog.evidence_integrity.signed_records} observation(s) chaînée(s)`
                  : 'Télémétrie compromise · scores appris ignorés, priorités officielles actives'}
              </div>}
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
          <div style={{ fontWeight: 750 }}>Research Engine v3</div>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, margin: '5px 0 11px' }}>
            Marvin planifie, explore via SearXNG, comble les angles morts puis audite les citations avec cinq rôles Cloud spécialisés.
          </div>
          {swarmIntegrity && <div style={{ color: swarmIntegrity.valid ? swarmIntegrity.legacy_records ? '#fbbf24' : '#34d399' : '#fb7185', fontSize: 10, marginBottom: 9 }}>
            {swarmIntegrity.valid
              ? swarmIntegrity.legacy_records
                ? `Runs cohérents · ${swarmIntegrity.legacy_records} recherche(s) historique(s) non signée(s)`
                : `Preuves Swarm vérifiables · ${swarmIntegrity.signed_records} run(s) chaîné(s)`
              : 'Intégrité des runs compromise · tout nouveau résultat sera signalé non persisté'}
          </div>}
          <textarea value={question} onChange={event => setQuestion(event.target.value)}
            placeholder="Question de recherche complexe et non sensible"
            style={{ width: '100%', minHeight: 90, resize: 'vertical', boxSizing: 'border-box', borderRadius: 10, padding: 11, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 8, marginTop: 9 }}>
            <label style={{ display: 'grid', gap: 5, fontSize: 11, color: 'var(--text-muted)' }}>
              Profondeur
              <select value={researchConfig.depth} onChange={event => setResearchConfig(current => ({ ...current, depth: event.target.value }))}
                style={{ padding: '8px 10px', borderRadius: 9, background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
                <option value="quick">Rapide</option>
                <option value="deep">Approfondie</option>
                <option value="exhaustive">Exhaustive</option>
              </select>
            </label>
            <label style={{ display: 'grid', gap: 5, fontSize: 11, color: 'var(--text-muted)' }}>
              Sources
              <select value={researchConfig.sourcePolicy} onChange={event => setResearchConfig(current => ({ ...current, sourcePolicy: event.target.value }))}
                style={{ padding: '8px 10px', borderRadius: 9, background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
                <option value="balanced">Équilibrées</option>
                <option value="primary_first">Primaires d’abord</option>
                <option value="academic">Académiques</option>
                <option value="official_only">Officielles uniquement</option>
              </select>
            </label>
            <label style={{ display: 'grid', gap: 5, fontSize: 11, color: 'var(--text-muted)' }}>
              Fraîcheur
              <select value={researchConfig.freshness} onChange={event => setResearchConfig(current => ({ ...current, freshness: event.target.value }))}
                style={{ padding: '8px 10px', borderRadius: 9, background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>
                <option value="">Sans filtre</option>
                <option value="day">24 heures</option>
                <option value="week">7 jours</option>
                <option value="month">30 jours</option>
                <option value="year">12 mois</option>
              </select>
            </label>
          </div>
          <button type="button" onClick={runSwarm} disabled={running || !question.trim()}
            style={{ marginTop: 9, padding: '9px 14px', borderRadius: 9, border: '1px solid rgba(45,212,191,.45)', background: 'rgba(45,212,191,.14)', color: '#5eead4', cursor: 'pointer', fontWeight: 700 }}>
            {running ? 'Recherche en cours…' : 'Lancer la recherche'}
          </button>
          {job && running && <div style={{ marginTop: 10, padding: 11, border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text-muted)', fontSize: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span>{job.progress?.message || job.progress?.stage || job.status}</span>
              <span>{job.progress?.completed || 0}/{job.progress?.total || job.agent_count}</span>
            </div>
            <div style={{ height: 4, borderRadius: 4, background: 'rgba(255,255,255,.08)', marginTop: 8, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, ((job.progress?.completed || 0) / Math.max(1, job.progress?.total || 1)) * 100)}%`, height: '100%', background: '#2dd4bf', transition: 'width .25s ease' }} />
            </div>
            {job.progress?.metrics && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8, fontSize: 10 }}>
              <span>{job.progress.metrics.queries || 0} requêtes</span>
              <span>{job.progress.metrics.unique_sources || 0} sources uniques</span>
              <span>{job.progress.metrics.unique_domains || 0} domaines</span>
              {job.progress.metrics.axis_coverage != null && <span>{Math.round(job.progress.metrics.axis_coverage * 100)} % de couverture</span>}
            </div>}
            <div style={{ display: 'flex', gap: 6, marginTop: 9 }}>
              <input value={steeringQuery} onChange={event => setSteeringQuery(event.target.value)}
                placeholder="Ajouter un angle ou un domaine à examiner"
                style={{ flex: 1, minWidth: 0, padding: '6px 8px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }} />
              <button type="button" onClick={steerResearch} disabled={!steeringQuery.trim()}
                style={{ padding: '6px 9px', borderRadius: 7, border: '1px solid var(--border)' }}>Orienter</button>
            </div>
            <button onClick={() => fetch(`${BACKEND_URL}/api/model-market/swarm/jobs/${job.id}`, { method: 'DELETE' })}
              style={{ marginTop: 9, padding: '5px 9px', borderRadius: 7, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)' }}>Annuler</button>
          </div>}
        </section>

        {result && (
          <section style={{ marginTop: 18, border: '1px solid var(--border)', borderRadius: 14, padding: 16, background: 'rgba(255,255,255,.02)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
              <div style={{ fontWeight: 750 }}>Rapport final</div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button type="button" onClick={() => downloadReport('md')}>Markdown</button>
                <button type="button" onClick={() => downloadGeneratedReport('docx')}>Word</button>
                <button type="button" onClick={() => downloadGeneratedReport('pdf')}>PDF</button>
                <button type="button" onClick={() => downloadReport('json')}>Données et preuves</button>
              </div>
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 12 }}>
              {result.engine_version === 'v3' ? 'Moteur adaptatif v3' : 'Moteur historique v2'} · {result.queries?.length || result.cells?.length || 0} requêtes/analyses · {result.sources?.length || 0} sources · {(result.models_consulted || []).length} modèles
            </div>
            {result.forge && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 8, marginBottom: 12 }}>
              <div style={{ padding: 9, borderRadius: 9, background: 'rgba(255,255,255,.03)' }}>Citations valides<br /><strong>{Math.round(result.forge.citation_validity * 100)} %</strong></div>
              <div style={{ padding: 9, borderRadius: 9, background: 'rgba(255,255,255,.03)' }}>Faits cités<br /><strong>{Math.round(result.forge.factual_citation_coverage * 100)} %</strong></div>
              <div style={{ padding: 9, borderRadius: 9, background: 'rgba(255,255,255,.03)' }}>Domaines<br /><strong>{result.source_coverage?.unique_domains || 0}</strong></div>
              <div style={{ padding: 9, borderRadius: 9, background: 'rgba(255,255,255,.03)', color: result.forge.gate_passed ? '#34d399' : '#fbbf24' }}>Contrôle qualité<br /><strong>{result.forge.gate_passed ? 'Validé' : 'À vérifier'}</strong></div>
            </div>}
            <div style={{ color: result.evidence_persisted === true ? '#34d399' : result.evidence_persisted === false ? '#fb7185' : '#fbbf24', fontSize: 11, marginBottom: 12 }}>
              {result.evidence_persisted === true
                ? `Preuve persistée · séquence ${result.sequence || 'N/D'} · ${result.record_hash?.slice(0, 14) || 'empreinte indisponible'}`
                : result.evidence_persisted === false
                  ? `Rapport livré mais preuve non persistée · ${result.evidence_error || 'erreur inconnue'}`
                  : 'Rapport historique · aucun reçu de preuve disponible'}
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
