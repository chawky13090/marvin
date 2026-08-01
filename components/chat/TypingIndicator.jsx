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
  density = 'wide',
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

  const isThinking = robotMode === 'thinking' || robotMode === 'waiting';
  const robotSrc = isThinking ? '/assets/marvin-thinking.png' : '/assets/marvin-activity-robot.png';

  return (
    <div
      className={`${styles.activityDock} ${compact ? styles.standalone : ''} ${styles[`density_${density}`]} ${styles[`robot_${robotMode}`]}`}
      aria-label="Activité de Marvin"
      data-layout={compact ? 'standalone' : 'composer'}
      data-robot-state={robotMode}
    >
      <span className={styles.liveStatus} role="status" aria-live="polite">
        {title}. {compactLabel}.
      </span>
      <button
        type="button"
        className={styles.activitySummary}
        onClick={() => hasDetails && setExpanded(value => !value)}
        aria-expanded={hasDetails ? expanded : undefined}
        title={hasDetails ? "Afficher l'activité détaillée" : title}
      >
        <span className={styles.activityText}>
          <strong>{title}</strong>
          <span>{compactLabel}</span>
        </span>
        <time>{formatElapsed(elapsed)}</time>
        <span className={styles.progressTrack} aria-hidden="true">
          <span className={hasMeasuredProgress ? styles.progressValue : styles.progressIndeterminate} style={ringStyle} />
        </span>
      </button>

      <button
        type="button"
        className={styles.robotButton}
        onClick={onStop}
        disabled={!onStop}
        aria-label="Arrêter la tâche de Marvin"
        title="Arrêter la tâche de Marvin"
      >
        <span className={styles.robotAura} aria-hidden="true" />
        <Image className={styles.robot} src={robotSrc} width={82} height={82} alt="" priority />
        <span className={styles.robotScanner} aria-hidden="true" />
        <span className={styles.stopOverlay} aria-hidden="true">Arrêter</span>
      </button>

      {expanded && hasDetails && (
        <section className={styles.details} aria-label="Détails de l'activité">
          <div className={styles.detailsHeader}>
            <strong>Activité de Marvin</strong>
            <button type="button" onClick={() => setExpanded(false)} aria-label="Fermer les détails">×</button>
          </div>
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
        </section>
      )}
    </div>
  );
}
