'use client';

import { useState } from 'react';

export function CredentialGroup({
  groupKey, icon, title, group, credentials,
  credValues, setCredValues, credVisible, setCredVisible,
  credSaving, onSave, onDelete, oauthButton, note,
}) {
  const [expanded, setExpanded] = useState(true);
  const groupCreds = Object.entries(credentials).filter(([, meta]) => meta.group === groupKey);
  const isConnected = group?.connected;

  return (
    <div className="card" style={{
      border: `1px solid ${isConnected ? 'rgba(16,185,129,0.3)' : 'var(--border)'}`,
      borderLeft: `4px solid ${isConnected ? '#10b981' : 'rgba(79, 140, 255,0.4)'}`,
    }}>
      {/* Header */}
      <div
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', marginBottom: expanded ? '16px' : 0 }}
        onClick={() => setExpanded(e => !e)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '1.4rem' }}>{icon}</span>
          <div>
            <div style={{ fontWeight: 700, fontSize: 'var(--font-sm)', color: 'var(--text-primary)' }}>{title}</div>
            <div style={{ fontSize: '11px', color: isConnected ? '#10b981' : 'var(--text-muted)' }}>
              {isConnected ? '✅ Connecté' : `${group?.keys_set || 0} / ${group?.total_keys || 0} clés configurées`}
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{
            padding: '2px 10px', borderRadius: '12px', fontSize: '10px', fontWeight: 700,
            background: isConnected ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.04)',
            color: isConnected ? '#10b981' : 'var(--text-muted)',
            border: `1px solid ${isConnected ? 'rgba(16,185,129,0.4)' : 'var(--border)'}`,
          }}>
            {isConnected ? 'CONNECTÉ' : 'INACTIF'}
          </span>
          <span style={{ color: 'var(--text-muted)', fontSize: '1rem' }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {note && (
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', padding: '8px 12px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', marginBottom: '4px' }}>
              💡 {note}
            </div>
          )}

          {groupCreds.map(([name, meta]) => {
            const hasValue = meta.has_value;
            const isSecret = meta.secret;
            const isEditing = credValues[name] !== undefined;
            const saving = credSaving[name];
            const visible = credVisible[name];

            return (
              <div key={name} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {meta.label}
                  {hasValue && <span style={{ color: '#10b981', fontSize: '10px' }}>● Configuré</span>}
                </label>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <div style={{ flex: 1, position: 'relative' }}>
                    <input
                      className="input"
                      type={isSecret && !visible ? 'password' : 'text'}
                      value={isEditing ? credValues[name] : (hasValue && isSecret ? '' : (meta.value || ''))}
                      placeholder={hasValue ? (isSecret ? '••••••••••••••• (configuré)' : meta.value) : `Entrez ${meta.label}...`}
                      onChange={e => setCredValues(v => ({ ...v, [name]: e.target.value }))}
                      style={{ width: '100%', paddingRight: isSecret ? '40px' : '12px', fontSize: 'var(--font-xs)', fontFamily: isSecret && !visible ? 'monospace' : 'inherit' }}
                    />
                    {isSecret && (
                      <button
                        onClick={() => setCredVisible(v => ({ ...v, [name]: !v[name] }))}
                        style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: '14px', padding: '2px' }}
                      >
                        {visible ? '🙈' : '👁️'}
                      </button>
                    )}
                  </div>
                  {isEditing && (
                    <button
                      onClick={() => onSave(name)}
                      disabled={saving}
                      style={{
                        padding: '0 14px', background: 'var(--accent-gradient)', border: 'none',
                        borderRadius: 'var(--radius-md)', color: 'white', fontWeight: 700,
                        cursor: 'pointer', fontSize: '12px', whiteSpace: 'nowrap', opacity: saving ? 0.6 : 1,
                      }}
                    >
                      {saving ? '...' : '💾 Sauver'}
                    </button>
                  )}
                  {hasValue && !isEditing && (
                    <button
                      onClick={() => onDelete(name)}
                      style={{
                        padding: '0 12px', background: 'transparent',
                        border: '1px solid rgba(239,68,68,0.3)', borderRadius: 'var(--radius-md)',
                        color: 'rgba(239,68,68,0.7)', cursor: 'pointer', fontSize: '12px',
                      }}
                    >
                      🗑️
                    </button>
                  )}
                </div>
              </div>
            );
          })}

          {/* Bouton OAuth */}
          {oauthButton && (
            <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <button
                onClick={oauthButton.onClick}
                disabled={oauthButton.disabled}
                style={{
                  padding: '10px 20px',
                  background: oauthButton.disabled ? 'var(--bg-secondary)' : 'var(--accent-gradient)',
                  border: oauthButton.disabled ? '1px solid var(--border)' : 'none',
                  borderRadius: 'var(--radius-md)',
                  color: oauthButton.disabled ? 'var(--text-muted)' : 'white',
                  fontWeight: 700, cursor: oauthButton.disabled ? 'not-allowed' : 'pointer',
                  fontSize: 'var(--font-sm)', transition: 'all 0.2s',
                  boxShadow: oauthButton.disabled ? 'none' : 'var(--accent-glow)',
                }}
              >
                {oauthButton.label}
              </button>
              {oauthButton.hint && (
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>← {oauthButton.hint}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
