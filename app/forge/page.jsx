'use client';

import { useCallback, useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/backend';

function percent(value) {
  return value == null ? 'N/D' : `${Math.round(value * 100)} %`;
}

function Metric({ label, value, color = '#60a5fa' }) {
  return (
    <div style={{ padding: 14, border: '1px solid var(--border)', borderRadius: 12, background: 'rgba(255,255,255,.025)' }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em' }}>{label}</div>
      <div style={{ color, fontSize: 24, fontWeight: 750, marginTop: 5 }}>{value}</div>
    </div>
  );
}

function parseSources(value) {
  return String(value || '').split(/\r?\n/).map((line, index) => {
    const match = line.trim().match(/^\[([A-Za-z0-9_-]+)\]\s+(\S+)(?:\s+\|\s+([^|]+))?(?:\s+\|\s+(.+))?$/);
    if (!match) return null;
    return {
      citation: match[1],
      url: match[2],
      title: match[3]?.trim() || `Source ${index + 1}`,
      excerpt: match[4]?.trim() || '',
    };
  }).filter(Boolean);
}

const DEFAULT_DUEL_SCORES = {
  A: { correctness: 3, completeness: 3, evidence: 3, usefulness: 3 },
  B: { correctness: 3, completeness: 3, evidence: 3, usefulness: 3 },
};

export default function ForgePage() {
  const [summary, setSummary] = useState(null);
  const [scenarios, setScenarios] = useState([]);
  const [arena, setArena] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [submission, setSubmission] = useState({ scenario_id: '', system: 'Marvin', answer: '', sources: '', duration_ms: '' });
  const [submitting, setSubmitting] = useState(false);
  const [match, setMatch] = useState(null);
  const [duelScores, setDuelScores] = useState(DEFAULT_DUEL_SCORES);
  const [duelBusy, setDuelBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [summaryResponse, scenariosResponse, arenaResponse, evidenceResponse] = await Promise.all([
        fetch(`${BACKEND_URL}/api/forge/summary`),
        fetch(`${BACKEND_URL}/api/forge/scenarios`),
        fetch(`${BACKEND_URL}/api/forge/arena/leaderboard`),
        fetch(`${BACKEND_URL}/api/knowledge/evidence-summary`),
      ]);
      if (!summaryResponse.ok || !scenariosResponse.ok || !arenaResponse.ok || !evidenceResponse.ok) throw new Error('API Forge indisponible');
      setSummary(await summaryResponse.json());
      const scenarioRows = (await scenariosResponse.json()).scenarios || [];
      setScenarios(scenarioRows);
      setArena(await arenaResponse.json());
      setEvidence(await evidenceResponse.json());
      setSubmission(current => ({ ...current, scenario_id: current.scenario_id || scenarioRows[0]?.id || '' }));
    } catch (err) {
      setError(err.message || 'Erreur Forge');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  const metrics = Object.fromEntries((summary?.by_scenario || []).map(item => [item.id, item]));

  async function submitArena(event) {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    setNotice('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/forge/arena/submissions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: submission.scenario_id,
          system: submission.system.trim(),
          answer: submission.answer.trim(),
          sources: parseSources(submission.sources),
          duration_ms: submission.duration_ms ? Number(submission.duration_ms) : null,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Soumission refusée');
      setNotice(`Soumission enregistrée : score ${Math.round(data.submission.quality_score * 100)} %, dette ${Math.round(data.submission.epistemic_debt.score * 100)} %.`);
      setSubmission(current => ({ ...current, answer: '', sources: '', duration_ms: '' }));
      await load();
    } catch (err) {
      setError(err.message || 'Erreur Frontier Arena');
    } finally {
      setSubmitting(false);
    }
  }

  async function createDuel() {
    setDuelBusy(true);
    setError('');
    setNotice('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/forge/arena/matches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: submission.scenario_id }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Aucun duel disponible');
      setMatch(data.match);
      setDuelScores(DEFAULT_DUEL_SCORES);
    } catch (err) {
      setError(err.message || 'Erreur duel Arena');
    } finally {
      setDuelBusy(false);
    }
  }

  function setDuelScore(slot, dimension, value) {
    setDuelScores(current => ({
      ...current,
      [slot]: { ...current[slot], [dimension]: Number(value) },
    }));
  }

  async function voteDuel(winner) {
    if (!match) return;
    setDuelBusy(true);
    setError('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/forge/arena/matches/${match.id}/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ winner, scores: duelScores }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Vote refusé');
      setMatch(data.match);
      setNotice('Duel enregistré. Les identités sont maintenant révélées.');
      await load();
    } catch (err) {
      setError(err.message || 'Erreur de vote');
    } finally {
      setDuelBusy(false);
    }
  }

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '28px 32px', color: 'var(--text-primary)' }}>
      <div style={{ maxWidth: 1080, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: '1.7rem', color: '#60a5fa' }}>Marvin Forge</h1>
            <p style={{ margin: '7px 0 20px', color: 'var(--text-muted)', fontSize: 13, maxWidth: 720 }}>
              Evaluation déterministe des traces agentiques. Les résultats sont calculés sur les événements, les outils et l’état de terminaison, sans juge LLM.
            </p>
          </div>
          <button type="button" onClick={load} disabled={loading}
            style={{ padding: '8px 13px', borderRadius: 9, border: '1px solid var(--border)', background: 'var(--bg-glass)', color: 'var(--text-secondary)', cursor: 'pointer' }}>
            {loading ? 'Chargement' : 'Actualiser'}
          </button>
        </div>

        {error && <div style={{ color: '#f87171', marginBottom: 16 }}>{error}</div>}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(155px,1fr))', gap: 10, marginBottom: 20 }}>
          <Metric label="Scénarios" value={summary?.scenarios ?? 0} />
          <Metric label="Scénarios actifs" value={summary?.enabled_scenarios ?? 0} color="#2dd4bf" />
          <Metric label="Exécutions" value={summary?.runs ?? 0} color="#c084fc" />
          <Metric label="Réussite globale" value={percent(summary?.success_rate)} color="#34d399" />
          <Metric label="Couverture preuves" value={percent(evidence?.claim_coverage)} color="#fbbf24" />
          <Metric label="Dette épistémique" value={percent(evidence?.average_epistemic_debt)} color="#fb7185" />
        </div>

        <div style={{ border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', background: 'rgba(255,255,255,.02)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px,2fr) 85px repeat(4,80px)', gap: 8, padding: '10px 14px', color: 'var(--text-muted)', fontSize: 11, borderBottom: '1px solid var(--border)' }}>
            <span>Scénario</span><span>Runs</span><span>Pass 1</span><span>Pass 3</span><span>Pass 5</span><span>Pass@3</span>
          </div>
          {scenarios.map(item => {
            const metric = metrics[item.id] || {};
            return (
              <div key={item.id} style={{ display: 'grid', gridTemplateColumns: 'minmax(220px,2fr) 85px repeat(4,80px)', gap: 8, padding: '13px 14px', alignItems: 'center', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                <div>
                  <div style={{ fontWeight: 700 }}>{item.name}</div>
                  <div style={{ color: 'var(--text-muted)', marginTop: 3 }}>{item.id} · {item.category} · {item.enabled ? 'actif' : 'inactif'}</div>
                </div>
                <span>{metric.runs || 0}</span>
                <span>{metric.pass_1 == null ? 'N/D' : metric.pass_1 ? 'OK' : 'Echec'}</span>
                <span>{metric.pass_3 == null ? 'N/D' : metric.pass_3 ? 'OK' : 'Echec'}</span>
                <span>{metric.pass_5 == null ? 'N/D' : metric.pass_5 ? 'OK' : 'Echec'}</span>
                <span>{metric.pass_at_3 == null ? 'N/D' : metric.pass_at_3 ? 'OK' : 'Echec'}</span>
              </div>
            );
          })}
          {!scenarios.length && !loading && <div style={{ padding: 18, color: 'var(--text-muted)' }}>Aucun scénario Forge.</div>}
        </div>

        <div style={{ marginTop: 20, display: 'grid', gridTemplateColumns: 'minmax(0,1.2fr) minmax(300px,.8fr)', gap: 16, alignItems: 'start' }}>
          <section style={{ border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden', background: 'rgba(255,255,255,.02)' }}>
            <div style={{ padding: '13px 15px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontWeight: 750 }}>Frontier Arena</div>
              <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 4 }}>
                Comparaison neutre de Marvin et de réponses importées sur le même corpus Forge.
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(130px,1.4fr) repeat(4,minmax(70px,1fr))', gap: 8, padding: '9px 13px', color: 'var(--text-muted)', fontSize: 10, borderBottom: '1px solid var(--border)' }}>
              <span>Système</span><span>Réussite</span><span>Qualité</span><span>Preuves</span><span>Dette</span>
            </div>
            {(arena?.systems || []).map((item, index) => (
              <div key={item.system} style={{ display: 'grid', gridTemplateColumns: 'minmax(130px,1.4fr) repeat(4,minmax(70px,1fr))', gap: 8, padding: '11px 13px', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                <span style={{ fontWeight: 700 }}>{index + 1}. {item.system}<small style={{ display: 'block', color: 'var(--text-muted)', fontWeight: 400 }}>{item.submissions} essai(s){item.blind_matches ? ` · ${item.blind_matches} duel(s), ${percent(item.blind_win_rate)} gagnés` : ''}</small></span>
                <span>{percent(item.success_rate)}</span>
                <span>{percent(item.quality_score)}</span>
                <span>{percent(item.evidence_score)}</span>
                <span style={{ color: item.epistemic_debt > .55 ? '#fb7185' : '#fbbf24' }}>{percent(item.epistemic_debt)}</span>
              </div>
            ))}
            {!arena?.systems?.length && <div style={{ padding: 16, color: 'var(--text-muted)', fontSize: 12 }}>Aucune comparaison importée.</div>}
          </section>

          <form onSubmit={submitArena} style={{ border: '1px solid var(--border)', borderRadius: 14, padding: 15, background: 'rgba(255,255,255,.02)' }}>
            <div style={{ fontWeight: 750, marginBottom: 11 }}>Importer un résultat</div>
            <label style={{ display: 'block', color: 'var(--text-muted)', fontSize: 11, marginBottom: 5 }}>Scénario commun</label>
            <select value={submission.scenario_id} onChange={event => setSubmission({ ...submission, scenario_id: event.target.value })}
              style={{ width: '100%', padding: 9, borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', marginBottom: 10 }}>
              {scenarios.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}
            </select>
            <label style={{ display: 'block', color: 'var(--text-muted)', fontSize: 11, marginBottom: 5 }}>Système évalué</label>
            <input required value={submission.system} onChange={event => setSubmission({ ...submission, system: event.target.value })}
              style={{ width: '100%', padding: 9, boxSizing: 'border-box', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', marginBottom: 10 }} />
            <label style={{ display: 'block', color: 'var(--text-muted)', fontSize: 11, marginBottom: 5 }}>Réponse complète</label>
            <textarea required rows={6} value={submission.answer} onChange={event => setSubmission({ ...submission, answer: event.target.value })}
              style={{ width: '100%', padding: 9, boxSizing: 'border-box', resize: 'vertical', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', marginBottom: 10 }} />
            <label style={{ display: 'block', color: 'var(--text-muted)', fontSize: 11, marginBottom: 5 }}>Sources, une par ligne</label>
            <textarea rows={3} value={submission.sources} onChange={event => setSubmission({ ...submission, sources: event.target.value })}
              placeholder="[doc-1] https://example.org/document | Titre | Extrait justificatif"
              style={{ width: '100%', padding: 9, boxSizing: 'border-box', resize: 'vertical', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', marginBottom: 10 }} />
            <input type="number" min="0" value={submission.duration_ms} onChange={event => setSubmission({ ...submission, duration_ms: event.target.value })}
              placeholder="Durée en millisecondes"
              style={{ width: '100%', padding: 9, boxSizing: 'border-box', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)', marginBottom: 10 }} />
            <button disabled={submitting || !submission.scenario_id} type="submit"
              style={{ width: '100%', padding: 10, border: 0, borderRadius: 9, background: '#2563eb', color: 'white', fontWeight: 750, cursor: 'pointer' }}>
              {submitting ? 'Évaluation' : 'Évaluer et classer'}
            </button>
            {notice && <div style={{ color: '#34d399', fontSize: 11, marginTop: 9 }}>{notice}</div>}
          </form>
        </div>

        <section style={{ marginTop: 18, border: '1px solid var(--border)', borderRadius: 14, padding: 15, background: 'rgba(192,132,252,.045)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontWeight: 750 }}>Duel en aveugle</div>
              <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 4 }}>
                Les noms, scores automatiques, coûts et durées restent masqués jusqu’au vote.
              </div>
            </div>
            <button type="button" onClick={createDuel} disabled={duelBusy || !submission.scenario_id}
              style={{ padding: '9px 13px', borderRadius: 9, border: '1px solid #7c3aed', background: '#6d28d9', color: 'white', fontWeight: 700, cursor: 'pointer' }}>
              {duelBusy ? 'Traitement' : 'Créer un duel'}
            </button>
          </div>
          {arena?.blind && (
            <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 8 }}>
              {arena.blind.matches} duel(s) · {arena.blind.votes} vote(s) · {arena.blind.pending} en attente
            </div>
          )}
          {match && (
            <>
              <div style={{ marginTop: 13, padding: 11, borderRadius: 9, background: 'rgba(255,255,255,.03)', fontSize: 12 }}>
                <strong>{match.scenario_name}</strong>
                <div style={{ color: 'var(--text-muted)', marginTop: 5 }}>{match.prompt}</div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 12, marginTop: 12 }}>
                {['A', 'B'].map(slot => {
                  const candidate = match.candidates?.[slot];
                  if (!candidate) return null;
                  return (
                    <article key={slot} style={{ border: '1px solid var(--border)', borderRadius: 12, padding: 13, minWidth: 0 }}>
                      <div style={{ fontWeight: 800, color: slot === 'A' ? '#60a5fa' : '#c084fc' }}>
                        Réponse {slot}{candidate.system ? ` — ${candidate.system}` : ''}
                      </div>
                      <div style={{ whiteSpace: 'pre-wrap', fontSize: 12, lineHeight: 1.55, maxHeight: 320, overflowY: 'auto', marginTop: 9 }}>{candidate.answer}</div>
                      {(candidate.sources || []).length > 0 && (
                        <details style={{ marginTop: 9, fontSize: 11 }}>
                          <summary>Sources ({candidate.sources.length})</summary>
                          {candidate.sources.map((source, index) => (
                            <div key={`${slot}-${index}`} style={{ marginTop: 5, overflowWrap: 'anywhere' }}>
                              [{source.citation || index + 1}] {source.title || source.url}
                            </div>
                          ))}
                        </details>
                      )}
                      {!match.voted && (
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 70px', gap: 7, alignItems: 'center', marginTop: 12 }}>
                          {[
                            ['correctness', 'Exactitude'],
                            ['completeness', 'Complétude'],
                            ['evidence', 'Preuves'],
                            ['usefulness', 'Utilité'],
                          ].map(([dimension, label]) => (
                            <div key={dimension} style={{ display: 'contents' }}>
                              <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</label>
                              <select value={duelScores[slot][dimension]} onChange={event => setDuelScore(slot, dimension, event.target.value)}
                                style={{ padding: 6, borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}>
                                {[1, 2, 3, 4, 5].map(value => <option value={value} key={value}>{value}/5</option>)}
                              </select>
                            </div>
                          ))}
                        </div>
                      )}
                      {match.voted && (
                        <div style={{ marginTop: 10, color: 'var(--text-muted)', fontSize: 11 }}>
                          Qualité automatique {percent(candidate.quality_score)} · citations {percent(candidate.evidence_score)} · dette {percent(candidate.epistemic_debt?.score)}
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
              {!match.voted && (
                <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap', marginTop: 12 }}>
                  <button type="button" disabled={duelBusy} onClick={() => voteDuel('A')} style={{ padding: '9px 14px', borderRadius: 8, border: 0, background: '#2563eb', color: 'white' }}>A gagne</button>
                  <button type="button" disabled={duelBusy} onClick={() => voteDuel('TIE')} style={{ padding: '9px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-glass)', color: 'var(--text-primary)' }}>Égalité</button>
                  <button type="button" disabled={duelBusy} onClick={() => voteDuel('B')} style={{ padding: '9px 14px', borderRadius: 8, border: 0, background: '#7c3aed', color: 'white' }}>B gagne</button>
                </div>
              )}
              {match.voted && <div style={{ textAlign: 'center', marginTop: 12, color: '#34d399', fontSize: 12 }}>Vote : {match.vote?.winner === 'TIE' ? 'égalité' : `réponse ${match.vote?.winner}`}</div>}
            </>
          )}
        </section>

        <div style={{ marginTop: 18, padding: 14, borderRadius: 12, border: '1px solid var(--border)', background: 'rgba(96,165,250,.06)' }}>
          <div style={{ fontWeight: 700, marginBottom: 7 }}>Exécution contrôlée</div>
          <code style={{ color: '#93c5fd', fontSize: 12 }}>backend\.venv\Scripts\python.exe scripts\run_forge.py --all-enabled --repeat 3</code>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 7 }}>
            Les scénarios Council et recherche restent inactifs par défaut pour éviter les coûts et effets de bord involontaires.
          </div>
        </div>
      </div>
    </div>
  );
}
