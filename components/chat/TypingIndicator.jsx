'use client';

import { useEffect, useMemo, useState } from 'react';
import Image from 'next/image';
import styles from './TypingIndicator.module.css';


const TOOL_LABELS = {
  web_search: 'Recherche Web',
  web_research: 'Recherche Web documentée',
  web_deep_research: 'Recherche Web approfondie',
  ai_research_swarm: 'Équipe de recherche',
  ai_model_council: 'Conseil de modèles',
  ai_cortex_search: 'Analyse Cortex',
  ai_code_forge: 'Code Forge',
  ai_test_forge: 'Validation du code',
  code_workspace_start: 'Mission de développement',
  code_workspace_control: 'Mission de développement',
};

const STAGE_LABELS = {
  planning: 'Préparation du plan',
  searching: 'Recherche en cours',
  reading: 'Lecture des sources',
  checking: 'Vérification',
  synthesizing: 'Synthèse',
  testing: 'Tests',
  repairing: 'Correction',
  waiting: 'Toujours actif',
};

function formatElapsed(seconds) {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${String(seconds % 60).padStart(2, '0')} s`;
}

function metricLabel(key) {
  return String(key || '').replaceAll('_', ' ');
}

export default function TypingIndicator({
  status = 'submitted',
  toolName = null,
  progress = null,
  progressEvents = [],
  startedAt = null,
  onStop = null,
}) {
  const [clock, setClock] = useState({ now: 0, mountedAt: 0 });
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const mountedAt = Date.now();
    setClock({ now: mountedAt, mountedAt });
    const interval = setInterval(
      () => setClock(value => ({ ...value, now: Date.now() })),
      500,
    );
    return () => clearInterval(interval);
  }, []);

  const { now, mountedAt } = clock;
  const elapsed = Math.max(
    0,
    Math.floor((now - (Number(startedAt) || mountedAt)) / 1000),
  );
  const latestAt = Number(progress?.receivedAt || startedAt || mountedAt);
  const silentSeconds = Math.max(0, Math.floor((now - latestAt) / 1000));
  const hasMeasuredProgress = Number(progress?.total) > 0;
  const percent = hasMeasuredProgress
    ? Math.min(100, Math.round((Number(progress.current || 0) / Number(progress.total)) * 100))
    : null;

  const title = toolName
    ? TOOL_LABELS[toolName] || String(toolName).replaceAll('_', ' ')
    : status === 'streaming'
      ? 'Rédaction de la réponse'
      : 'Analyse de la demande';
  const activity = progress?.label
    || STAGE_LABELS[progress?.stage]
    || (status === 'streaming' ? 'Marvin rédige' : 'Marvin réfléchit');
  const metrics = useMemo(
    () => Object.entries(progress?.metrics || {}).slice(0, 4),
    [progress?.metrics],
  );
  const visibleEvents = (progressEvents || []).slice(-8);

  return (
    <section className={styles.beacon} aria-live="polite" aria-label="Activité de Marvin">
      <div className={styles.summary}>
        <div className={styles.avatar} aria-hidden="true">
          <Image src="/marvin-logo.svg" alt="" width={34} height={34} priority />
        </div>
        <div className={styles.main}>
          <div className={styles.titleRow}>
            <strong>{title}</strong>
            <span className={styles.live}><i /> En cours</span>
            <time>{formatElapsed(elapsed)}</time>
          </div>
          <div className={styles.activity}>
            <span>{activity}</span>
            {progress?.detail && <span className={styles.detail}>· {progress.detail}</span>}
          </div>
          {hasMeasuredProgress && (
            <div
              className={styles.progressTrack}
              role="progressbar"
              aria-valuemin="0"
              aria-valuemax={progress.total}
              aria-valuenow={progress.current}
              aria-label={activity}
            >
              <div className={styles.progressFill} style={{ width: `${percent}%` }} />
            </div>
          )}
          <div className={styles.facts}>
            {hasMeasuredProgress && (
              <span>{progress.current}/{progress.total}</span>
            )}
            {metrics.map(([key, value]) => (
              <span key={key}>{value} {metricLabel(key)}</span>
            ))}
            {silentSeconds >= 20 && (
              <span className={styles.waiting}>
                Aucun nouvel événement depuis {silentSeconds} s · processus toujours surveillé
              </span>
            )}
          </div>
        </div>
        <div className={styles.actions}>
          {visibleEvents.length > 0 && (
            <button type="button" onClick={() => setExpanded(value => !value)}>
              {expanded ? 'Masquer' : 'Activité'}
            </button>
          )}
          {onStop && (
            <button type="button" className={styles.stop} onClick={onStop}>
              Arrêter
            </button>
          )}
        </div>
      </div>
      {expanded && visibleEvents.length > 0 && (
        <ol className={styles.timeline}>
          {visibleEvents.map((event, index) => (
            <li key={`${event.receivedAt || index}-${index}`}>
              <i aria-hidden="true" />
              <div>
                <strong>{event.label || STAGE_LABELS[event.stage] || 'Étape en cours'}</strong>
                {event.detail && <span>{event.detail}</span>}
              </div>
              {event.total > 0 && <small>{event.current}/{event.total}</small>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
