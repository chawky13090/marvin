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
  compact = false,
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

  const hasDetails = visibleEvents.length > 0
    || metrics.length > 0
    || Boolean(progress?.detail);

  const compactLabel = hasMeasuredProgress
    ? `${activity} · ${progress.current}/${progress.total}`
    : silentSeconds >= 20
      ? `${activity} · ${silentSeconds}s sans nouvel évènement`
      : activity;

  const ringStyle = hasMeasuredProgress
    ? { '--ring-percent': `${percent}%` }
    : undefined;

  const robotMode = progress?.stage === 'searching' ? 'searching'
    : progress?.stage === 'reading' ? 'reading'
      : progress?.stage === 'checking' || progress?.stage === 'testing' ? 'checking'
        : progress?.stage === 'repairing' ? 'repairing'
          : progress?.stage === 'waiting' ? 'waiting'
            : status === 'streaming' ? 'writing'
              : 'thinking';

  return (
    <div
      className={`${styles.beacon} ${compact ? styles.compact : ''} ${styles[`robot_${robotMode}`]}`}
      aria-live="polite"
      aria-label="Activité de Marvin"
      data-layout={compact ? 'compact' : 'lateral'}
    >
      <div className={styles.robotPanel} aria-hidden="true">
        <span className={styles.robotAura} />
        <Image className={styles.robot} src="/assets/marvin-activity-robot.png" width={150} height={150} alt="" priority />
        <span className={styles.robotScanner} />
        <span className={styles.robotCaption}>Marvin travaille</span>
      </div>

      <section className={styles.infoPanel}>
        <div className={styles.infoTopline}>
          <div className={styles.activityBody}>
            <div className={styles.activityHeader}>
              <strong>{title}</strong>
              <time>{formatElapsed(elapsed)}</time>
            </div>
            <div className={styles.label}>{compactLabel}</div>
          </div>
          <div className={styles.actions}>
            {hasDetails && (
              <button type="button" className={styles.more} onClick={() => setExpanded(value => !value)} aria-label={expanded ? 'Masquer les détails' : "Voir l'activité détaillée"}>
                {expanded ? '▲' : '⋯'}
              </button>
            )}
            {onStop && <button type="button" className={styles.stop} onClick={onStop} aria-label="Arrêter">✕</button>}
          </div>
        </div>
        <div className={styles.progressTrack} aria-hidden="true">
          <span className={hasMeasuredProgress ? styles.progressValue : styles.progressIndeterminate} style={ringStyle} />
        </div>

        {expanded && hasDetails && (
          <div className={styles.details}>
          {progress?.detail && <div className={styles.detail}>{progress.detail}</div>}
          {metrics.length > 0 && (
            <div className={styles.facts}>
              {metrics.map(([key, value]) => (
                <span key={key}>{value} {metricLabel(key)}</span>
              ))}
            </div>
          )}
          {visibleEvents.length > 0 && (
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
          </div>
        )}
      </section>
    </div>
  );
}
