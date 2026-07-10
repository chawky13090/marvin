'use client';

import styles from './StatusBadge.module.css';

const STATUS_CONFIG = {
  connected: {
    dotClass: 'dotConnected',
    labelClass: 'labelConnected',
    defaultLabel: 'Connecté',
  },
  disconnected: {
    dotClass: 'dotDisconnected',
    labelClass: 'labelDisconnected',
    defaultLabel: 'Déconnecté',
  },
  pending: {
    dotClass: 'dotPending',
    labelClass: 'labelPending',
    defaultLabel: 'En attente',
  },
};

export default function StatusBadge({ status = 'disconnected', label }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.disconnected;
  const displayLabel = label || config.defaultLabel;

  return (
    <span className={styles.wrapper}>
      <span className={`${styles.dot} ${styles[config.dotClass]}`} />
      <span className={`${styles.label} ${styles[config.labelClass]}`}>
        {displayLabel}
      </span>
    </span>
  );
}
