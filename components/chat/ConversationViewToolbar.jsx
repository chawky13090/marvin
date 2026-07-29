'use client';

import styles from './ConversationViewToolbar.module.css';

const MODES = [
  { id: 'reading', short: 'L', label: 'Lecture', description: 'Résultat prioritaire, détails repliés' },
  { id: 'technical', short: 'T', label: 'Technique', description: 'Activités et résultats développés' },
  { id: 'audit', short: 'A', label: 'Audit', description: 'Chronologie complète et exportable' },
];

export default function ConversationViewToolbar({
  mode,
  onModeChange,
  onExport,
  hasMessages,
  inHeader = false,
}) {
  return (
    <div
      className={`${styles.toolbar} ${inHeader ? styles.toolbarInHeader : ''}`}
      aria-label="Mode d'affichage de la conversation"
    >
      <div className={styles.modeGroup} role="tablist" aria-label="Niveau de détail">
        {MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={mode === item.id}
            className={`${styles.modeButton} ${mode === item.id ? styles.modeButtonActive : ''}`}
            onClick={() => onModeChange(item.id)}
            title={item.description}
          >
            <span className={styles.shortLabel} aria-hidden="true">{item.short}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      <span className={styles.description}>
        {MODES.find((item) => item.id === mode)?.description}
      </span>

      {mode === 'audit' && (
        <div className={styles.exportGroup}>
          <span className={styles.localOnly}>Export local · secrets masqués</span>
          <button type="button" disabled={!hasMessages} onClick={() => onExport('markdown')}>Markdown</button>
          <button type="button" disabled={!hasMessages} onClick={() => onExport('json')}>JSON</button>
        </div>
      )}
    </div>
  );
}
