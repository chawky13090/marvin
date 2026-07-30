'use client';

import { useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/backend';

const MODES = {
  normal: {
    label: 'Normal',
    description: 'Marvin demande votre accord pour les actions sensibles.',
    color: 'var(--text-secondary)',
  },
  auto: {
    label: 'Auto',
    description: 'Les actions locales réversibles sont autorisées pendant une heure.',
    color: '#60a5fa',
  },
  full: {
    label: 'Accès complet',
    description: 'Toutes les actions validées par le harness sont autorisées pendant une heure.',
    color: '#c084fc',
  },
};

export default function AutonomyControl({ disabled = false }) {
  const [grant, setGrant] = useState({ mode: 'normal', active: false });
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmFull, setConfirmFull] = useState(false);
  const [now, setNow] = useState(0);
  const mode = grant.active ? grant.mode : 'normal';
  const definition = MODES[mode] || MODES.normal;
  const referenceTime = now || Number(grant.created_at || 0) * 1000;
  const remainingMinutes = grant.active && grant.expires_at
    ? Math.max(0, Math.ceil((grant.expires_at * 1000 - referenceTime) / 60000))
    : 0;

  useEffect(() => {
    let cancelled = false;
    fetch(`${BACKEND_URL}/api/autonomy`)
      .then(response => response.json())
      .then(data => { if (!cancelled) setGrant(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!grant.active) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, [grant.active]);

  const selectMode = async (nextMode) => {
    if (nextMode === 'full' && !confirmFull) {
      setConfirmFull(true);
      setError('');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`${BACKEND_URL}/api/autonomy`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: nextMode, durationMinutes: 60 }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Mode indisponible.');
      setGrant(data);
      setOpen(false);
      setConfirmFull(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Mode indisponible.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ position: 'relative', flexShrink: 0 }}>
      <button
        type="button"
        className="autonomy-control-trigger"
        disabled={disabled || busy}
        onClick={() => {
          setOpen(value => !value);
          setConfirmFull(false);
          setError('');
        }}
        aria-expanded={open}
        title="Choisir le niveau d’autonomie de Marvin"
        style={{
          minHeight: 34,
          maxWidth: 132,
          padding: '5px 8px',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          borderRadius: 999,
          border: `1px solid ${mode === 'normal' ? 'var(--border)' : 'color-mix(in srgb, currentColor 42%, transparent)'}`,
          background: mode === 'normal' ? 'var(--bg-glass)' : 'rgba(79,140,255,.09)',
          color: definition.color,
          cursor: disabled || busy ? 'not-allowed' : 'pointer',
          fontSize: 11,
          fontWeight: 700,
        }}
      >
        <span aria-hidden>{mode === 'normal' ? '◉' : mode === 'auto' ? '▶' : '◆'}</span>
        <span className="autonomy-control-label">
          {mode === 'normal' ? 'Normal · confirme' : `${definition.label} · ${remainingMinutes} min`}
        </span>
        <span className="autonomy-control-chevron" aria-hidden>▼</span>
      </button>

      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 110 }} />
          <div
            className="autonomy-control-popover"
            role="dialog"
            aria-label="Niveau d’autonomie"
            style={{
              position: 'absolute',
              bottom: 'calc(100% + 8px)',
              left: 0,
              zIndex: 111,
              width: 320,
              padding: 10,
              borderRadius: 14,
              border: '1px solid var(--border)',
              background: 'var(--bg-secondary)',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            <div style={{ padding: '3px 5px 8px', fontWeight: 750 }}>Autonomie de Marvin</div>
            <div style={{ padding: '0 5px 8px', color: 'var(--text-muted)', fontSize: 10.5, lineHeight: 1.4 }}>
              Permissions accessibles : <strong style={{ color: 'var(--text-primary)' }}>{grant.permissionLabel || 'Standard'}</strong>.
              {' '}Les validations sont un réglage distinct.
            </div>
            <a
              href="/settings?tab=permissions"
              style={{ display: 'block', margin: '-3px 5px 7px', color: 'var(--accent)', fontSize: 10.5 }}
            >
              Modifier les permissions
            </a>
            {Object.entries(MODES).map(([key, item]) => (
              <button
                key={key}
                type="button"
                onClick={() => selectMode(key)}
                disabled={busy}
                aria-pressed={mode === key}
                style={{
                  width: '100%',
                  padding: '9px 10px',
                  display: 'block',
                  border: '1px solid transparent',
                  borderRadius: 9,
                  background: mode === key ? 'rgba(79,140,255,.11)' : 'transparent',
                  color: 'var(--text-primary)',
                  textAlign: 'left',
                  cursor: busy ? 'wait' : 'pointer',
                }}
              >
                <strong style={{ display: 'block', color: item.color }}>{item.label}</strong>
                <span style={{ display: 'block', marginTop: 3, color: 'var(--text-muted)', fontSize: 10.5, lineHeight: 1.35 }}>
                  {item.description}
                </span>
              </button>
            ))}
            {confirmFull && (
              <div
                role="alert"
                style={{
                  margin: '7px 4px',
                  padding: 9,
                  borderRadius: 9,
                  border: '1px solid rgba(192,132,252,.35)',
                  background: 'rgba(192,132,252,.08)',
                  color: 'var(--text-secondary)',
                  fontSize: 10.5,
                  lineHeight: 1.4,
                }}
              >
                Accès complet autorise pendant une heure toutes les actions admises par votre niveau de permission, y compris les effets irréversibles.
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => selectMode('full')}
                  style={{
                    width: '100%',
                    marginTop: 8,
                    padding: '7px 9px',
                    borderRadius: 8,
                    border: '1px solid rgba(192,132,252,.5)',
                    background: 'rgba(192,132,252,.15)',
                    color: '#d8b4fe',
                    fontWeight: 750,
                    cursor: busy ? 'wait' : 'pointer',
                  }}
                >
                  Activer l’accès complet pendant 1 h
                </button>
              </div>
            )}
            {error && (
              <div role="alert" style={{ margin: '7px 5px 2px', color: 'var(--danger)', fontSize: 10.5 }}>
                {error}
              </div>
            )}
            <div style={{ margin: '7px 5px 2px', color: 'var(--warning)', fontSize: 10.5, lineHeight: 1.4 }}>
              Auto et Accès complet expirent automatiquement. Validation, preuves, idempotence et journalisation restent actives.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
