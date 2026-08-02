'use client';

import { useEffect, useRef, useState } from 'react';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

export const card = {
  background: '#111',
  border: '1px solid rgba(228, 228, 231,0.08)',
  borderRadius: '12px',
  padding: '20px',
};

export const btn = (active, color = '#4f8cff') => ({
  padding: '9px 20px',
  borderRadius: '8px',
  border: `1px solid ${active ? color : 'rgba(228, 228, 231,0.15)'}`,
  background: active ? `${color}18` : 'transparent',
  color: active ? color : 'var(--text-secondary)',
  fontSize: '13px',
  fontWeight: active ? 600 : 400,
  cursor: 'pointer',
  transition: 'all 0.18s ease',
  whiteSpace: 'nowrap',
});

export const primaryBtn = (disabled) => ({
  padding: '10px 24px',
  borderRadius: '8px',
  border: 'none',
  background: disabled ? '#333' : 'linear-gradient(135deg,#4f8cff,#38bdf8)',
  color: disabled ? '#666' : '#111',
  fontSize: '14px',
  fontWeight: 700,
  cursor: disabled ? 'not-allowed' : 'pointer',
  transition: 'all 0.18s ease',
});

export const label = {
  display: 'block',
  fontSize: '12px',
  color: 'var(--text-muted)',
  marginBottom: '6px',
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
};

export const input = {
  width: '100%',
  background: '#0d0d0d',
  border: '1px solid rgba(228, 228, 231,0.12)',
  borderRadius: '8px',
  padding: '10px 12px',
  color: 'var(--text-primary)',
  fontSize: '14px',
  outline: 'none',
  boxSizing: 'border-box',
};

export const select = {
  ...input,
  cursor: 'pointer',
};

// Formate une durée en secondes → "45s" / "2 min 10 s"
export function fmtDuration(sec) {
  if (sec == null || sec < 0) return '—';
  sec = Math.round(sec);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m} min ${s}s` : `${m} min`;
}

// ── Image drop zone ───────────────────────────────────────────────────────────

export function DropZone({ files, onFiles, multiple = false, label: lbl = 'Glisser une image ici ou cliquer' }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef();

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
    if (dropped.length) onFiles(multiple ? dropped : [dropped[0]]);
  };

  const handleInput = (e) => {
    const selected = Array.from(e.target.files).filter(f => f.type.startsWith('image/'));
    if (selected.length) onFiles(multiple ? selected : [selected[0]]);
  };

  const previews = files.map(f => URL.createObjectURL(f));

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      style={{
        border: `2px dashed ${dragging ? '#4f8cff' : 'rgba(228, 228, 231,0.18)'}`,
        borderRadius: '10px',
        padding: files.length ? '12px' : '32px',
        textAlign: 'center',
        cursor: 'pointer',
        background: dragging ? 'rgba(79, 140, 255,0.05)' : '#0d0d0d',
        transition: 'all 0.18s ease',
        minHeight: '80px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '10px',
      }}
    >
      <input ref={inputRef} type="file" accept="image/*" multiple={multiple} onChange={handleInput} style={{ display: 'none' }} />
      {files.length === 0 ? (
        <>
          <span style={{ fontSize: '2rem' }}>🖼️</span>
          <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>{lbl}</span>
        </>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'center' }}>
          {previews.map((src, i) => (
            <img
              key={i}
              src={src}
              alt=""
              style={{ width: '80px', height: '80px', objectFit: 'cover', borderRadius: '6px', border: '1px solid rgba(228, 228, 231,0.15)' }}
            />
          ))}
          <div style={{
            width: '80px', height: '80px', display: 'flex', alignItems: 'center', justifyContent: 'center',
            borderRadius: '6px', border: '1px dashed rgba(228, 228, 231,0.18)', fontSize: '11px', color: 'var(--text-muted)',
          }}>
            + Ajouter
          </div>
        </div>
      )}
    </div>
  );
}

// ── SSE Generation progress ───────────────────────────────────────────────────

export function GenerationProgress({ predictionId, onDone, onCancel }) {
  const [status, setStatus] = useState('starting');
  const [logs, setLogs] = useState('');
  const [outputUrl, setOutputUrl] = useState(null);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(0);
  const abortRef = useRef(null);

  useEffect(() => {
    if (!predictionId) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    (async () => {
      try {
        const res = await fetch(`${BACKEND}/api/video/status/${predictionId}`, { signal: ctrl.signal });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data:')) continue;
            try {
              const d = JSON.parse(line.slice(5).trim());
              setStatus(d.status);
              if (d.logs) setLogs(d.logs);
              if (d.error) setError(d.error);
              if (d.output_url) {
                setOutputUrl(d.output_url);
                setProgress(100);
              }
              // Rough progress estimate
              if (d.status === 'processing') setProgress(p => Math.min(p + 8, 90));
              if (d.status === 'starting')   setProgress(5);
              if (d.status === 'succeeded' || d.status === 'failed') {
                setProgress(100);
                onDone?.(d);
              }
            } catch { /* skip */ }
          }
        }
      } catch (e) {
        if (e.name !== 'AbortError') setError(String(e));
      }
    })();

    return () => ctrl.abort();
  }, [predictionId]);

  const cancelGen = async () => {
    abortRef.current?.abort();
    try { await fetch(`${BACKEND}/api/video/cancel/${predictionId}`, { method: 'POST' }); } catch { }
    onCancel?.();
  };

  const statusColor = {
    starting: '#888',
    processing: '#4f8cff',
    succeeded: '#22c55e',
    failed: '#ef4444',
    canceled: '#888',
  }[status] || '#888';

  return (
    <div style={{ ...card, marginTop: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{
            width: '10px', height: '10px', borderRadius: '50%',
            background: statusColor,
            boxShadow: status === 'processing' ? `0 0 8px ${statusColor}` : 'none',
            display: 'inline-block',
            animation: status === 'processing' ? 'pulse 1.5s infinite' : 'none',
          }} />
          <span style={{ fontSize: '13px', color: statusColor, fontWeight: 600 }}>
            {{ starting: 'Démarrage…', processing: 'Génération en cours…', succeeded: 'Terminé !', failed: 'Échec', canceled: 'Annulé' }[status] || status}
          </span>
        </div>
        {(status === 'starting' || status === 'processing') && (
          <button onClick={cancelGen} style={{ ...btn(false, '#ef4444'), padding: '5px 12px', fontSize: '12px' }}>
            Annuler
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div style={{ background: '#1a1a1a', borderRadius: '4px', height: '4px', marginBottom: '12px' }}>
        <div style={{
          height: '4px', borderRadius: '4px',
          background: status === 'succeeded' ? '#22c55e' : status === 'failed' ? '#ef4444' : 'linear-gradient(90deg,#4f8cff,#38bdf8)',
          width: `${progress}%`,
          transition: 'width 0.4s ease',
        }} />
      </div>

      {error && (
        <div style={{ background: '#1a0808', border: '1px solid #ef444440', borderRadius: '6px', padding: '10px', fontSize: '12px', color: '#ef4444', marginBottom: '12px' }}>
          ⚠️ {error}
        </div>
      )}

      {logs && (
        <pre style={{ background: '#0d0d0d', borderRadius: '6px', padding: '10px', fontSize: '11px', color: '#888', maxHeight: '120px', overflow: 'auto', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {logs}
        </pre>
      )}

      {outputUrl && status === 'succeeded' && (
        <VideoResult url={outputUrl} predictionId={predictionId} onSaved={() => {}} />
      )}
    </div>
  );
}

// ── Video result display ──────────────────────────────────────────────────────

export function VideoResult({ url, localUrl, predictionId }) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(!!localUrl);
  const [savedFilename, setSavedFilename] = useState(null);
  const displayUrl = localUrl || url;
  const isGif = displayUrl?.endsWith('.gif') || displayUrl?.includes('image/gif');

  const saveLocally = async () => {
    if (saving || saved) return;
    setSaving(true);
    try {
      const res = await fetch(`${BACKEND}/api/video/download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (data.success) {
        setSaved(true);
        setSavedFilename(data.filename);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginTop: '14px' }}>
      <div style={{ fontSize: '12px', color: '#22c55e', marginBottom: '10px', fontWeight: 600 }}>
        ✅ Vidéo générée
      </div>
      <div style={{ background: '#0d0d0d', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(228, 228, 231,0.1)' }}>
        {isGif ? (
          <img src={displayUrl} alt="Vidéo générée" style={{ width: '100%', maxHeight: '400px', objectFit: 'contain', display: 'block' }} />
        ) : (
          <video
            src={displayUrl}
            controls
            autoPlay
            loop
            style={{ width: '100%', maxHeight: '400px', display: 'block', background: '#000' }}
          />
        )}
      </div>
      <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
        <a
          href={displayUrl}
          target="_blank"
          rel="noreferrer"
          style={{ ...btn(false), textDecoration: 'none', fontSize: '12px' }}
        >
          🔗 Ouvrir original
        </a>
        {url && !localUrl && (
          <button
            onClick={saveLocally}
            disabled={saving || saved}
            style={{ ...btn(saved, '#22c55e'), fontSize: '12px' }}
          >
            {saving ? '⏳ Sauvegarde…' : saved ? `✅ Sauvegardé${savedFilename ? ` — ${savedFilename}` : ''}` : '💾 Sauvegarder localement'}
          </button>
        )}
        {localUrl && (
          <a
            href={localUrl}
            download
            style={{ ...btn(false), textDecoration: 'none', fontSize: '12px' }}
          >
            ⬇️ Télécharger
          </a>
        )}
      </div>
    </div>
  );
}

// ── Tab: Text to Video ────────────────────────────────────────────────────────
