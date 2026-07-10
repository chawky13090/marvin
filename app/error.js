'use client';

import { useEffect } from 'react';

// Garde-fou global : capture toute erreur runtime d'une page (ex. réponse API vide
// -> "Unexpected end of JSON input") et affiche un écran de récupération propre
// au lieu d'une page blanche.
export default function Error({ error, reset }) {
  useEffect(() => {
    console.error('[Marvin] Erreur capturée :', error);
  }, [error]);

  const msg = String(error?.message || error || 'Erreur inconnue');
  const isJson = /JSON|Unexpected end of JSON input/i.test(msg);

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg-primary, #0d0d0d)', color: 'var(--text-primary, #eee)', padding: '24px',
    }}>
      <div style={{
        maxWidth: '520px', width: '100%', padding: '28px 30px', textAlign: 'center',
        background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '16px',
      }}>
        <div style={{ fontSize: '2.4rem', marginBottom: '10px' }}>⚠️</div>
        <h2 style={{ margin: '0 0 8px', fontSize: '1.15rem', color: '#f87171' }}>Une erreur est survenue</h2>
        <p style={{ margin: '0 0 14px', fontSize: '13px', color: 'var(--text-muted, #999)', lineHeight: 1.6 }}>
          {isJson
            ? "Un service a renvoyé une réponse vide. C'est souvent que le backend n'est pas lancé, ou que ses fichiers ne sont pas à jour."
            : "Marvin a rencontré un problème inattendu."}
        </p>

        <pre style={{
          textAlign: 'left', fontSize: '11px', color: '#fca5a5', background: 'rgba(239,68,68,0.07)',
          border: '1px solid rgba(239,68,68,0.2)', borderRadius: '8px', padding: '10px 12px',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '120px', overflow: 'auto', margin: '0 0 16px',
        }}>{msg}</pre>

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'center', flexWrap: 'wrap' }}>
          <button onClick={() => reset()}
            style={{ padding: '9px 18px', borderRadius: '9px', border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '13px',
              background: 'linear-gradient(135deg,#4f8cffcc,#4f8cff88)', color: 'white' }}>
            🔄 Réessayer
          </button>
          <button onClick={() => window.location.reload()}
            style={{ padding: '9px 18px', borderRadius: '9px', cursor: 'pointer', fontWeight: 600, fontSize: '13px',
              background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border, #333)', color: 'var(--text-primary, #eee)' }}>
            Recharger la page
          </button>
        </div>

        <div style={{ marginTop: '16px', fontSize: '11px', color: 'var(--text-muted, #888)', lineHeight: 1.6 }}>
          Si ça persiste : vérifie que le <strong>backend</strong> tourne (<code>http://localhost:8005/api/health</code>)
          et que tes fichiers frontend/backend sont <strong>de la même version</strong>.
        </div>
      </div>
    </div>
  );
}
