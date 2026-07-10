'use client';

import { useEffect, useCallback } from 'react';
import styles from './ConfirmDialog.module.css';

export default function ConfirmDialog({
  isOpen,
  onConfirm,
  onCancel,
  icon = '⚠️',
  title = 'Confirmer l\'action',
  message = 'Êtes-vous sûr de vouloir continuer ?',
  confirmLabel = 'Confirmer',
  cancelLabel = 'Annuler',
  variant = 'primary', // 'primary' | 'danger'
}) {
  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Escape') {
        onCancel();
      }
    },
    [onCancel]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  return (
    <div className={styles.overlay} onClick={onCancel}>
      <div className={styles.dialog} onClick={(e) => e.stopPropagation()}>
        <span className={styles.icon}>{icon}</span>
        <h3 className={styles.title}>{title}</h3>
        <p className={styles.message}>{message}</p>
        <div className={styles.actions}>
          <button
            className={`btn btn-secondary ${styles.btnCancel}`}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            className={`btn ${variant === 'danger' ? 'btn-danger' : 'btn-primary'} ${styles.btnConfirm}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
