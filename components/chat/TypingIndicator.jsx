'use client';
import { useState, useEffect } from 'react';

/**
 * Adaptive typing indicator — shows different messages based on how long
 * the request is taking and what's happening.
 *
 * Optional prop `status` :
 *   - 'submitted' : request sent, waiting for model
 *   - 'streaming' : model is generating tokens
 *   - 'tool'      : a tool is being called
 */
export default function TypingIndicator({ status = 'submitted', toolName = null }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 500);
    return () => clearInterval(interval);
  }, []);

  // Adaptive message based on elapsed time + status
  let label = 'Marvin réfléchit';
  let hint = null;
  if (status === 'tool' && toolName) {
    label = `Marvin utilise ${toolName}`;
  } else if (status === 'streaming') {
    label = 'Marvin écrit';
  } else if (elapsed > 30) {
    label = 'Marvin charge un modèle…';
    hint = '~10-30s pour le 1er appel';
  } else if (elapsed > 10) {
    label = 'Marvin réfléchit profondément';
  }

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '8px 0',
      animation: 'fadeIn 0.3s ease',
    }}>
      <div style={{
        width: '32px', height: '32px', borderRadius: '50%',
        background: '#111',
        border: '1px solid rgba(79, 140, 255,0.25)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        overflow: 'hidden',
        boxShadow: '0 0 8px rgba(79, 140, 255,0.1)',
      }}>
        <img src="/marvin-logo.svg" alt="Marvin" style={{ width: '26px', height: '26px', objectFit: 'contain' }} />
      </div>
      <div style={{
        background: 'var(--bg-glass)',
        backdropFilter: 'blur(20px)',
        border: '1px solid var(--border)',
        borderRadius: '16px 16px 16px 4px',
        padding: '10px 18px',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: 'var(--font-sm)', color: 'var(--text-secondary)', marginRight: '8px' }}>
            {label}
          </span>
          {[0, 1, 2].map(i => (
            <span key={i} style={{
              width: '6px', height: '6px',
              borderRadius: '50%',
              background: 'var(--accent-primary)',
              animation: `typing-dot 1.4s ease-in-out ${i * 0.2}s infinite`,
              display: 'inline-block',
            }} />
          ))}
          {elapsed > 3 && (
            <span style={{
              marginLeft: '10px', fontSize: '11px', color: 'var(--text-muted)',
              fontFamily: 'monospace',
            }}>
              {elapsed}s
            </span>
          )}
        </div>
        {hint && (
          <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
            {hint}
          </span>
        )}
      </div>
    </div>
  );
}
