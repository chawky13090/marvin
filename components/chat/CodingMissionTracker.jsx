'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

const EVENT_LABELS = {
  'mission.run.started': 'Nouvelle tentative démarrée',
  'code.forge.started': 'Analyse du correctif',
  'repair.started': 'Correction ciblée en cours',
  'repair.scheduled': 'Nouvelle correction planifiée',
  'validation.failed': 'Validation refusée',
  'mission.blocked': 'Mission bloquée',
  'delivery.pack.created': 'Dossier de livraison créé',
  'delivery.accepted': 'Livrable accepté',
  checkpoint: 'Étape enregistrée',
  created: 'Mission créée',
};

const STAGE_LABELS = {
  planning: 'Préparation', architecture: 'Architecture', implementation: 'Implémentation',
  review: 'Revue experte', test_forge: 'Tests dans l’environnement isolé',
  repair: 'Correction après test', apply_worktree: 'Application dans le workspace',
  windows_native_vm: 'Validation Windows native', acceptance: 'Contrôle final',
  retry_wait: 'Reprise automatique planifiée', completed: 'Livraison terminée',
  code_forge: 'Analyse Code Forge',
};

const STATUS_LABELS = {
  completed: 'Réussie', running: 'En cours', queued: 'Reprise automatique',
  interrupted: 'Reprise automatique', paused: 'En pause', blocked: 'Bloquée',
  failed: 'Échec', cancelled: 'Annulée',
};

function initialMissionId(result) {
  return result?.project?.id || result?.mission_id || result?.job?.mission_id || '';
}

function eventDetail(event) {
  const payload = event?.payload || {};
  if (event.type === 'mission.run.started' && payload.attempt) return `tentative ${payload.attempt}`;
  if (event.type === 'checkpoint') {
    const phase = payload.phase || payload.state?.stage;
    const state = payload.state || {};
    const label = phase ? (STAGE_LABELS[phase] || String(phase).replaceAll('_', ' ')) : '';
    if (phase === 'implementing' && state.file_count) return `${label} · ${state.file_count} fichier(s) conservé(s)`;
    if (phase === 'reviewing' && Number.isFinite(state.issue_count)) return `${label} · ${state.issue_count} problème(s) détecté(s)`;
    if (phase === 'testing') {
      const failedSteps = Array.isArray(state.failed_steps) ? state.failed_steps : [];
      return failedSteps.length ? `${label} · à corriger : ${failedSteps.join(', ')}` : `${label} · validations réussies`;
    }
    if (phase === 'failed') return `${label} · score ${state.score ?? 'inconnu'}/10, ${state.critical ?? 0} critique(s), ${state.high ?? 0} élevé(s)`;
    if (phase === 'paused' && state.retry_in_seconds) return `${label} · reprise dans ${state.retry_in_seconds} s`;
    if (phase === 'accepted') return `${label} · preuves et livrable enregistrés`;
    return label;
  }
  const repair = payload.repair_context || {};
  const diagnostic = repair.step_diagnostics?.[0];
  if (diagnostic?.stderr) return String(diagnostic.stderr).split('\n').filter(Boolean).slice(-1)[0].slice(0, 260);
  if (repair.failed_steps?.length) return `contrôle à corriger : ${repair.failed_steps.join(', ')}`;
  if (payload.error) return String(payload.error).slice(0, 260);
  if (payload.retry_in_seconds) return `reprise dans ${payload.retry_in_seconds} s`;
  return '';
}

function eventTime(value) {
  const date = new Date(value || '');
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

function recentEvents(items) {
  return [...(Array.isArray(items) ? items : [])]
    .sort((left, right) => new Date(left?.at || 0).getTime() - new Date(right?.at || 0).getTime())
    .slice(-12);
}

export default function CodingMissionTracker({ result }) {
  const missionId = useMemo(() => initialMissionId(result), [result]);
  const initialJob = result?.auto_job || result?.job || {};
  const [events, setEvents] = useState(() => recentEvents(result?.events));
  const [job, setJob] = useState(initialJob);
  const [status, setStatus] = useState(initialJob.status || result?.status || result?.project?.status || 'running');
  const [connected, setConnected] = useState(false);

  const refresh = useCallback(async () => {
    if (!missionId) return;
    try {
      const response = await fetch(`/api/coding/projects/${missionId}`, { cache: 'no-store' });
      if (!response.ok) return;
      const body = await response.json();
      const nextJob = body?.auto_job || {};
      setJob(nextJob);
      setStatus(nextJob.status || body?.project?.status || 'running');
      if (Array.isArray(body?.events)) setEvents(recentEvents(body.events));
    } catch {
      // Le flux SSE ou le prochain rafraîchissement reprendra le suivi.
    }
  }, [missionId]);

  useEffect(() => {
    if (!missionId) return undefined;
    refresh();
    const timer = window.setInterval(refresh, 3000);
    let cursor = 0;
    const source = new EventSource(`/api/coding/projects/${missionId}/events/stream?after=${cursor}`);
    source.addEventListener('open', () => setConnected(true));
    source.addEventListener('mission', event => {
      const item = JSON.parse(event.data);
      cursor = Number(item.cursor || cursor);
      setEvents(current => [...current.filter(row => row.cursor !== item.cursor), item].slice(-12));
      refresh();
    });
    source.addEventListener('terminal', event => {
      const body = JSON.parse(event.data);
      setStatus(body.status || 'completed');
      setConnected(false);
      refresh();
      source.close();
    });
    source.onerror = () => setConnected(false);
    return () => {
      window.clearInterval(timer);
      source.close();
    };
  }, [missionId, refresh]);

  if (!missionId) return null;
  const progress = job?.progress || result?.progress || {};
  const percent = Math.max(0, Math.min(100, Number(progress.percent || (status === 'completed' ? 100 : 0))));
  const stage = STAGE_LABELS[progress.stage] || String(progress.stage || 'Préparation').replaceAll('_', ' ');
  const failed = ['blocked', 'failed', 'cancelled'].includes(status);
  const complete = status === 'completed';
  const color = complete ? '#34d399' : failed ? '#fb7185' : '#60a5fa';

  return (
    <section aria-label="Avancement de la Coding Mission" style={{ display: 'grid', gap: 12, padding: 14, border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg-tertiary)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontWeight: 750, color: 'var(--text-primary)' }}>Avancement du travail</div>
          <div style={{ marginTop: 3, color: 'var(--text-secondary)', fontSize: 12 }}>{stage}{job?.attempts ? ` · tentative ${job.attempts}` : ''}</div>
        </div>
        <div style={{ color, fontWeight: 750, fontSize: 12, textAlign: 'right' }}>{STATUS_LABELS[status] || status}{connected && !complete ? ' · direct' : ''}</div>
      </div>
      <div>
        <div style={{ height: 7, overflow: 'hidden', borderRadius: 99, background: 'var(--bg-secondary)' }}>
          <div style={{ width: `${percent}%`, height: '100%', background: color, transition: 'width 300ms ease' }} />
        </div>
        <div style={{ marginTop: 5, display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)', fontSize: 11 }}>
          <span>{percent} %</span><span>{complete ? 'Livrable validé' : 'Le travail continue automatiquement'}</span>
        </div>
      </div>
      {events.length > 0 && (
        <div style={{ display: 'grid', gap: 7 }}>
          {events.slice(-6).reverse().map((item, index) => {
            const detail = eventDetail(item);
            const isError = ['validation.failed', 'mission.blocked'].includes(item.type);
            return (
              <div key={`${item.cursor || item.at}-${index}`} style={{ display: 'grid', gridTemplateColumns: '42px 1fr', gap: 8, fontSize: 11, lineHeight: 1.4 }}>
                <span style={{ color: 'var(--text-muted)' }}>{eventTime(item.at)}</span>
                <span style={{ color: isError ? '#fb7185' : 'var(--text-secondary)' }}>
                  <b style={{ color: isError ? '#fb7185' : 'var(--text-primary)' }}>{EVENT_LABELS[item.type] || item.type}</b>{detail ? ` — ${detail}` : ''}
                </span>
              </div>
            );
          })}
        </div>
      )}
      <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>Tu peux changer de page : l’état et les preuves sont conservés et réapparaîtront ici.</div>
      <button type="button" onClick={() => { window.location.href = `/code?mission=${missionId}`; }} style={{ justifySelf: 'start', border: '1px solid var(--border)', borderRadius: 7, padding: '6px 9px', background: 'var(--bg-secondary)', color: 'var(--text-primary)', cursor: 'pointer' }}>
        Voir les détails dans Code Workspace
      </button>
    </section>
  );
}
