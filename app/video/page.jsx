'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';

const BACKEND = (typeof window!=='undefined'&&window.location?window.location.protocol+'//'+window.location.hostname+':8005':(process.env.NEXT_PUBLIC_BACKEND_URL||'http://127.0.0.1:8005'));

// ── Shared styles ─────────────────────────────────────────────────────────────

const card = {
  background: '#111',
  border: '1px solid rgba(228, 228, 231,0.08)',
  borderRadius: '12px',
  padding: '20px',
};

const btn = (active, color = '#4f8cff') => ({
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

const primaryBtn = (disabled) => ({
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

const label = {
  display: 'block',
  fontSize: '12px',
  color: 'var(--text-muted)',
  marginBottom: '6px',
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
};

const input = {
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

const select = {
  ...input,
  cursor: 'pointer',
};

// Formate une durée en secondes → "45s" / "2 min 10 s"
function fmtDuration(sec) {
  if (sec == null || sec < 0) return '—';
  sec = Math.round(sec);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m} min ${s}s` : `${m} min`;
}

// ── Image drop zone ───────────────────────────────────────────────────────────

function DropZone({ files, onFiles, multiple = false, label: lbl = 'Glisser une image ici ou cliquer' }) {
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

function GenerationProgress({ predictionId, onDone, onCancel }) {
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

function VideoResult({ url, localUrl, predictionId }) {
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

function TextToVideoTab({ models }) {
  const [modelKey, setModelKey] = useState(Object.keys(models)[0] || '');
  const [prompt, setPrompt] = useState('');
  const [generating, setGenerating] = useState(false);
  const [predictionId, setPredictionId] = useState(null);
  const [doneData, setDoneData] = useState(null);
  const [err, setErr] = useState('');

  const selectedModel = models[modelKey];

  const generate = async () => {
    if (!prompt.trim() || generating) return;
    setGenerating(true);
    setErr('');
    setPredictionId(null);
    setDoneData(null);
    try {
      const res = await fetch(`${BACKEND}/api/video/generate/text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_key: modelKey, prompt: prompt.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Erreur');
      setPredictionId(data.prediction_id);
    } catch (e) {
      setErr(e.message);
      setGenerating(false);
    }
  };

  const handleDone = (d) => {
    setDoneData(d);
    setGenerating(false);
  };

  const handleCancel = () => {
    setGenerating(false);
    setPredictionId(null);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={card}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
          <div>
            <span style={label}>Modèle</span>
            <select value={modelKey} onChange={e => setModelKey(e.target.value)} style={select}>
              {Object.entries(models).map(([k, m]) => (
                <option key={k} value={k}>{m.name}</option>
              ))}
            </select>
            {selectedModel && (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '5px' }}>
                {selectedModel.description}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
            <button
              onClick={generate}
              disabled={!prompt.trim() || generating}
              style={primaryBtn(!prompt.trim() || generating)}
            >
              {generating ? '⏳ Génération…' : '🎬 Générer'}
            </button>
          </div>
        </div>

        <div>
          <span style={label}>Prompt</span>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) generate(); }}
            placeholder="Décrivez la vidéo à générer… (Ctrl+Entrée pour lancer)"
            rows={4}
            style={{ ...input, resize: 'vertical', lineHeight: '1.5' }}
          />
        </div>

        {err && (
          <div style={{ marginTop: '10px', padding: '10px', background: '#1a0808', border: '1px solid #ef444440', borderRadius: '6px', fontSize: '13px', color: '#ef4444' }}>
            ⚠️ {err}
          </div>
        )}
      </div>

      {predictionId && (
        <GenerationProgress
          predictionId={predictionId}
          onDone={handleDone}
          onCancel={handleCancel}
        />
      )}

      {!predictionId && doneData?.output_url && (
        <div style={card}>
          <VideoResult url={doneData.output_url} />
        </div>
      )}
    </div>
  );
}

// ── Tab: Image to Video ───────────────────────────────────────────────────────

function ImageToVideoTab({ models }) {
  const [modelKey, setModelKey] = useState(Object.keys(models)[0] || '');
  const [prompt, setPrompt] = useState('');
  const [imageFiles, setImageFiles] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [predictionId, setPredictionId] = useState(null);
  const [doneData, setDoneData] = useState(null);
  const [err, setErr] = useState('');

  const selectedModel = models[modelKey];

  const generate = async () => {
    if (!imageFiles.length || generating) return;
    setGenerating(true);
    setErr('');
    setPredictionId(null);
    setDoneData(null);

    const fd = new FormData();
    fd.append('model_key', modelKey);
    fd.append('prompt', prompt.trim());
    fd.append('image', imageFiles[0]);

    try {
      const res = await fetch(`${BACKEND}/api/video/generate/image`, { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Erreur');
      setPredictionId(data.prediction_id);
    } catch (e) {
      setErr(e.message);
      setGenerating(false);
    }
  };

  const handleDone = (d) => { setDoneData(d); setGenerating(false); };
  const handleCancel = () => { setGenerating(false); setPredictionId(null); };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={card}>
        <div style={{ marginBottom: '16px' }}>
          <span style={label}>Image de départ</span>
          <DropZone
            files={imageFiles}
            onFiles={setImageFiles}
            multiple={false}
            label="Glisser une image ici ou cliquer pour choisir"
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
          <div>
            <span style={label}>Modèle</span>
            <select value={modelKey} onChange={e => setModelKey(e.target.value)} style={select}>
              {Object.entries(models).map(([k, m]) => (
                <option key={k} value={k}>{m.name}</option>
              ))}
            </select>
            {selectedModel && (
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '5px' }}>
                {selectedModel.description}
              </div>
            )}
          </div>
          <div>
            <span style={label}>Prompt (optionnel)</span>
            <input
              type="text"
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="Décrire le mouvement souhaité…"
              style={input}
            />
          </div>
        </div>

        <button
          onClick={generate}
          disabled={!imageFiles.length || generating}
          style={primaryBtn(!imageFiles.length || generating)}
        >
          {generating ? '⏳ Génération…' : '🎬 Animer l\'image'}
        </button>

        {err && (
          <div style={{ marginTop: '10px', padding: '10px', background: '#1a0808', border: '1px solid #ef444440', borderRadius: '6px', fontSize: '13px', color: '#ef4444' }}>
            ⚠️ {err}
          </div>
        )}
      </div>

      {predictionId && (
        <GenerationProgress
          predictionId={predictionId}
          onDone={handleDone}
          onCancel={handleCancel}
        />
      )}
    </div>
  );
}

// ── Tab: Slideshow ────────────────────────────────────────────────────────────

function SlideshowTab() {
  const [images, setImages] = useState([]);
  const [format, setFormat] = useState('gif');
  const [duration, setDuration] = useState(2.0);
  const [transitionFrames, setTransitionFrames] = useState(8);
  const [fps, setFps] = useState(24);
  const [fadeDuration, setFadeDuration] = useState(0.5);
  const [width, setWidth] = useState(640);
  const [height, setHeight] = useState(480);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState('');

  const addImages = (newFiles) => {
    setImages(prev => [...prev, ...newFiles]);
  };

  const removeImage = (idx) => {
    setImages(prev => prev.filter((_, i) => i !== idx));
  };

  const moveImage = (from, to) => {
    setImages(prev => {
      const arr = [...prev];
      const [item] = arr.splice(from, 1);
      arr.splice(to, 0, item);
      return arr;
    });
  };

  const generate = async () => {
    if (images.length < 2 || generating) return;
    setGenerating(true);
    setErr('');
    setResult(null);

    const fd = new FormData();
    fd.append('format', format);
    fd.append('duration', String(duration));
    fd.append('transition_frames', String(transitionFrames));
    fd.append('fps', String(fps));
    fd.append('fade_duration', String(fadeDuration));
    fd.append('width', String(width));
    fd.append('height', String(height));
    images.forEach(f => fd.append('images', f));

    try {
      const res = await fetch(`${BACKEND}/api/video/slideshow`, { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Erreur');
      setResult(data);
    } catch (e) {
      setErr(e.message);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={card}>
        <div style={{ marginBottom: '16px' }}>
          <span style={label}>Images ({images.length} sélectionnée{images.length !== 1 ? 's' : ''})</span>
          <DropZone
            files={[]}
            onFiles={addImages}
            multiple={true}
            label="Glisser plusieurs images ou cliquer pour sélectionner"
          />
        </div>

        {images.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
            {images.map((f, i) => (
              <div key={i} style={{ position: 'relative', borderRadius: '6px', overflow: 'hidden' }}>
                <img
                  src={URL.createObjectURL(f)}
                  alt=""
                  style={{ width: '72px', height: '72px', objectFit: 'cover', display: 'block' }}
                />
                <div style={{
                  position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  gap: '4px', opacity: 0, transition: 'opacity 0.15s',
                }}
                  onMouseEnter={e => e.currentTarget.style.opacity = 1}
                  onMouseLeave={e => e.currentTarget.style.opacity = 0}
                >
                  {i > 0 && <button onClick={() => moveImage(i, i-1)} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: '14px' }}>◀</button>}
                  <button onClick={() => removeImage(i)} style={{ background: '#ef444480', border: 'none', color: '#fff', cursor: 'pointer', borderRadius: '4px', padding: '2px 5px', fontSize: '11px' }}>✕</button>
                  {i < images.length - 1 && <button onClick={() => moveImage(i, i+1)} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: '14px' }}>▶</button>}
                </div>
                <div style={{ position: 'absolute', top: '2px', left: '4px', fontSize: '10px', fontWeight: 700, color: '#fff', textShadow: '0 1px 3px #000' }}>
                  {i + 1}
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '14px', marginBottom: '16px' }}>
          <div>
            <span style={label}>Format</span>
            <div style={{ display: 'flex', gap: '6px' }}>
              {['gif', 'mp4'].map(f => (
                <button key={f} onClick={() => setFormat(f)} style={{ ...btn(format === f), flex: 1, padding: '8px 0' }}>
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div>
            <span style={label}>Durée / image — {duration}s</span>
            <input type="range" min="0.5" max="10" step="0.5" value={duration}
              onChange={e => setDuration(Number(e.target.value))}
              style={{ width: '100%', accentColor: '#4f8cff' }}
            />
          </div>
          {format === 'gif' ? (
            <div>
              <span style={label}>Frames transition — {transitionFrames}</span>
              <input type="range" min="0" max="20" step="2" value={transitionFrames}
                onChange={e => setTransitionFrames(Number(e.target.value))}
                style={{ width: '100%', accentColor: '#4f8cff' }}
              />
            </div>
          ) : (
            <>
              <div>
                <span style={label}>FPS — {fps}</span>
                <input type="range" min="12" max="60" step="6" value={fps}
                  onChange={e => setFps(Number(e.target.value))}
                  style={{ width: '100%', accentColor: '#4f8cff' }}
                />
              </div>
              <div>
                <span style={label}>Fondu — {fadeDuration}s</span>
                <input type="range" min="0" max="2" step="0.1" value={fadeDuration}
                  onChange={e => setFadeDuration(Number(e.target.value))}
                  style={{ width: '100%', accentColor: '#4f8cff' }}
                />
              </div>
            </>
          )}
          <div>
            <span style={label}>Résolution</span>
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
              <input type="number" value={width} onChange={e => setWidth(Number(e.target.value))} min="160" max="1920" step="80"
                style={{ ...input, width: '70px' }} />
              <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>×</span>
              <input type="number" value={height} onChange={e => setHeight(Number(e.target.value))} min="120" max="1080" step="80"
                style={{ ...input, width: '70px' }} />
            </div>
          </div>
        </div>

        <button
          onClick={generate}
          disabled={images.length < 2 || generating}
          style={primaryBtn(images.length < 2 || generating)}
        >
          {generating ? '⏳ Création en cours…' : `🎞️ Créer le diaporama ${format.toUpperCase()}`}
        </button>
        {images.length > 0 && images.length < 2 && (
          <div style={{ fontSize: '12px', color: '#4f8cff', marginTop: '6px' }}>
            ℹ️ Ajoutez au moins 2 images
          </div>
        )}

        {err && (
          <div style={{ marginTop: '10px', padding: '10px', background: '#1a0808', border: '1px solid #ef444440', borderRadius: '6px', fontSize: '13px', color: '#ef4444' }}>
            ⚠️ {err}
          </div>
        )}
      </div>

      {result && (
        <div style={card}>
          <div style={{ fontSize: '12px', color: '#22c55e', marginBottom: '10px', fontWeight: 600 }}>
            ✅ Diaporama créé — {result.size_human} — {result.format}
          </div>
          <VideoResult
            localUrl={`${BACKEND}${result.url}`}
          />
        </div>
      )}
    </div>
  );
}

// ── Video gallery ─────────────────────────────────────────────────────────────

// ── Tab: Édition / Conversion vidéo & GIF (ffmpeg local) ────────────────────────

const EDIT_OPS = [
  { id: 'to_gif',         icon: '🎞️', label: 'Vidéo → GIF',      needsFile: true,  accept: 'video/*' },
  { id: 'gif_to_video',   icon: '📹', label: 'GIF → MP4',         needsFile: true,  accept: 'image/gif' },
  { id: 'compress',       icon: '🗜️', label: 'Compresser',        needsFile: true,  accept: 'video/*' },
  { id: 'trim',           icon: '✂️', label: 'Découper',          needsFile: true,  accept: 'video/*' },
  { id: 'resize',         icon: '📐', label: 'Redimensionner',    needsFile: true,  accept: 'video/*' },
  { id: 'speed',          icon: '⏩', label: 'Vitesse',           needsFile: true,  accept: 'video/*' },
  { id: 'watermark',      icon: '🏷️', label: 'Filigrane',         needsFile: true,  accept: 'video/*' },
  { id: 'optimize_gif',   icon: '✨', label: 'Optimiser GIF',     needsFile: true,  accept: 'image/gif' },
  { id: 'extract_frames', icon: '🖼️', label: 'Extraire images',   needsFile: true,  accept: 'video/*' },
  { id: 'info',           icon: 'ℹ️', label: 'Infos média',       needsFile: true,  accept: 'video/*,image/gif' },
  { id: 'screen_record',  icon: '🔴', label: 'Capturer écran',    needsFile: false, accept: '' },
];

function EditTab({ onDone }) {
  const [op, setOp] = useState('to_gif');
  const [file, setFile] = useState(null);
  const [params, setParams] = useState({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef();

  const current = EDIT_OPS.find(o => o.id === op);
  const setP = (k, v) => setParams(p => ({ ...p, [k]: v }));

  const run = async () => {
    setError(null); setResult(null);
    if (current.needsFile && !file) { setError('Sélectionnez un fichier.'); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('operation', op);
      if (file) fd.append('file', file);
      Object.entries(params).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) fd.append(k, v);
      });
      const res = await fetch(`${BACKEND}/api/video/edit`, { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Échec du traitement');
      setResult(data);
      onDone?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const numField = (key, lbl, ph) => (
    <div style={{ flex: 1, minWidth: 120 }}>
      <label style={label}>{lbl}</label>
      <input type="number" style={input} placeholder={ph}
        value={params[key] ?? ''} onChange={e => setP(key, e.target.value)} />
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 12 }}>
          🛠️ Opération
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {EDIT_OPS.map(o => (
            <button key={o.id} onClick={() => { setOp(o.id); setResult(null); setError(null); }}
              style={btn(op === o.id)}>
              {o.icon} {o.label}
            </button>
          ))}
        </div>
      </div>

      <div style={card}>
        {current.needsFile && (
          <div style={{ marginBottom: 16 }}>
            <label style={label}>Fichier source</label>
            <input ref={inputRef} type="file" accept={current.accept}
              onChange={e => { setFile(e.target.files[0] || null); setResult(null); }}
              style={{ display: 'none' }} />
            <div onClick={() => inputRef.current?.click()}
              style={{
                ...input, cursor: 'pointer', display: 'flex', alignItems: 'center',
                justifyContent: 'space-between', color: file ? 'var(--text-primary)' : 'var(--text-muted)',
              }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {file ? `📎 ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} Mo)` : 'Cliquer pour choisir un fichier…'}
              </span>
              <span style={{ color: '#4f8cff', fontSize: 12 }}>Parcourir</span>
            </div>
          </div>
        )}

        {/* Operation-specific params */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          {op === 'to_gif' && <>
            {numField('fps', 'FPS', '12')}
            {numField('width', 'Largeur (px)', '480')}
            {numField('start', 'Début (s)', 'optionnel')}
            {numField('duration', 'Durée (s)', 'optionnel')}
          </>}
          {op === 'gif_to_video' && <>{numField('fps', 'FPS', 'auto')}</>}
          {op === 'compress' && <>
            {numField('crf', 'Qualité CRF (18-35)', '28')}
            {numField('scale_width', 'Réduire largeur (px)', 'optionnel')}
          </>}
          {op === 'trim' && <>
            {numField('start', 'Début (s)', '0')}
            {numField('end', 'Fin (s)', 'optionnel')}
            {numField('duration', 'Durée (s)', 'optionnel')}
          </>}
          {op === 'resize' && <>
            {numField('width', 'Largeur (px)', 'optionnel')}
            {numField('height', 'Hauteur (px)', 'optionnel')}
          </>}
          {op === 'speed' && <>{numField('factor', 'Facteur (2=2x, 0.5=ralenti)', '2.0')}</>}
          {op === 'watermark' && <>
            <div style={{ flex: 2, minWidth: 180 }}>
              <label style={label}>Texte</label>
              <input style={input} placeholder="© Ma société 2026"
                value={params.text ?? ''} onChange={e => setP('text', e.target.value)} />
            </div>
            <div style={{ flex: 1, minWidth: 140 }}>
              <label style={label}>Position</label>
              <select style={select} value={params.position ?? 'bottom-right'}
                onChange={e => setP('position', e.target.value)}>
                <option value="bottom-right">Bas droite</option>
                <option value="bottom-left">Bas gauche</option>
                <option value="top-right">Haut droite</option>
                <option value="top-left">Haut gauche</option>
                <option value="center">Centre</option>
              </select>
            </div>
            {numField('font_size', 'Taille police', '24')}
          </>}
          {op === 'optimize_gif' && <>
            {numField('fps', 'FPS', '10')}
            {numField('width', 'Largeur (px)', 'optionnel')}
            {numField('colors', 'Couleurs (2-256)', '128')}
          </>}
          {op === 'extract_frames' && <>
            {numField('fps', 'Images/sec', '1')}
            {numField('max_frames', 'Max images', '30')}
          </>}
          {op === 'screen_record' && <>
            {numField('duration', 'Durée (s, max 20)', '5')}
            {numField('fps', 'FPS', '10')}
            <div style={{ flex: 2, minWidth: 180 }}>
              <label style={label}>Zone (x,y,larg,haut) — vide = plein écran</label>
              <input style={input} placeholder="ex: 0,0,800,600"
                value={params.region ?? ''} onChange={e => setP('region', e.target.value)} />
            </div>
          </>}
          {op === 'info' && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '4px 0' }}>
              Affiche durée, résolution, FPS, codec et taille du fichier.
            </div>
          )}
        </div>

        <div style={{ marginTop: 18 }}>
          <button onClick={run} disabled={busy} style={primaryBtn(busy)}>
            {busy ? '⏳ Traitement…' : `${current.icon} Lancer`}
          </button>
        </div>

        {error && (
          <div style={{ marginTop: 14, padding: '10px 14px', background: '#1a0808',
            border: '1px solid #ef444440', borderRadius: 8, color: '#ef4444', fontSize: 13 }}>
            ⚠️ {error}
          </div>
        )}

        {result && (
          <div style={{ marginTop: 14, padding: '12px 16px', background: 'rgba(34,197,94,0.06)',
            border: '1px solid rgba(34,197,94,0.2)', borderRadius: 8, fontSize: 13, color: '#22c55e' }}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>✅ Terminé</div>
            {op === 'info' && (
              <div style={{ color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.7 }}>
                {result.resolution && <div>Résolution : {result.resolution}</div>}
                {result.duration_sec != null && <div>Durée : {result.duration_sec}s</div>}
                {result.fps != null && <div>FPS : {result.fps}</div>}
                {result.codec && <div>Codec : {result.codec}</div>}
                {result.bitrate_kbps != null && <div>Bitrate : {result.bitrate_kbps} kbps</div>}
                {result.frames != null && <div>Images : {result.frames}</div>}
                {result.size_human && <div>Taille : {result.size_human}</div>}
              </div>
            )}
            {op === 'extract_frames' && (
              <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                {result.frame_count ?? result.frames?.length ?? 0} image(s) extraite(s)
                {result.output_dir && <> → <code>{result.output_dir}</code></>}
              </div>
            )}
            {result.url && op !== 'info' && op !== 'extract_frames' && (
              <div>
                {result.size_human && <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 8 }}>
                  Taille : {result.size_human}
                  {result.reduction_pct != null && <> · Réduction : {result.reduction_pct}%</>}
                </div>}
                <div style={{ borderRadius: 8, overflow: 'hidden', maxWidth: 360, marginBottom: 8 }}>
                  {result.filename?.toLowerCase().endsWith('.gif')
                    ? <img src={`${BACKEND}${result.url}`} alt="" style={{ width: '100%', display: 'block' }} />
                    : <video src={`${BACKEND}${result.url}`} controls style={{ width: '100%', display: 'block' }} />}
                </div>
                <a href={`${BACKEND}${result.url}`} download style={{ color: '#4f8cff', fontWeight: 600, textDecoration: 'none' }}>
                  ⬇️ Télécharger {result.filename}
                </a>
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{
        padding: '12px 16px', background: 'rgba(96,165,250,0.06)',
        border: '1px solid rgba(96,165,250,0.15)', borderRadius: 8,
        fontSize: 12, color: '#60a5fa',
      }}>
        🛠️ Édition <strong>100% locale via ffmpeg</strong> — aucune clé API, aucun GPU requis.
        Conversion, compression, découpe, filigrane, capture d'écran GIF… Le résultat apparaît dans la galerie ci-dessous.
      </div>
    </div>
  );
}

function VideoGallery({ refresh }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND}/api/video/files`);
      const data = await res.json();
      setFiles(data.files || []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load, refresh]);

  const deleteFile = async (filename) => {
    if (!confirm(`Supprimer ${filename} ?`)) return;
    setDeleting(filename);
    try {
      await fetch(`${BACKEND}/api/video/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
      setFiles(prev => prev.filter(f => f.filename !== filename));
    } finally {
      setDeleting(null);
    }
  };

  if (loading) return null;
  if (!files.length) return (
    <div style={{ ...card, textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px', padding: '32px' }}>
      📂 Aucune vidéo générée pour l'instant
    </div>
  );

  return (
    <div style={card}>
      <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '14px' }}>
        📂 Vidéos générées ({files.length})
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
        {files.map(f => {
          const url = `${BACKEND}/api/video/files/${encodeURIComponent(f.filename)}`;
          const isGif = f.type === 'GIF';
          return (
            <div key={f.filename} style={{
              background: '#0d0d0d', borderRadius: '8px', border: '1px solid rgba(228, 228, 231,0.1)',
              overflow: 'hidden',
            }}>
              {isGif ? (
                <img src={url} alt="" style={{ width: '100%', height: '130px', objectFit: 'cover', display: 'block' }} />
              ) : (
                <video src={url} style={{ width: '100%', height: '130px', objectFit: 'cover', display: 'block' }} muted loop
                  onMouseEnter={e => e.target.play()} onMouseLeave={e => e.target.pause()} />
              )}
              <div style={{ padding: '8px 10px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {f.filename}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '6px' }}>
                  <span style={{ fontSize: '10px', color: '#666' }}>{f.size_human} · {f.type}</span>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <a href={url} download style={{ fontSize: '13px', cursor: 'pointer', textDecoration: 'none' }}>⬇️</a>
                    <button
                      onClick={() => deleteFile(f.filename)}
                      disabled={deleting === f.filename}
                      style={{ background: 'none', border: 'none', fontSize: '13px', cursor: 'pointer', color: 'inherit' }}
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Tab: Local AI video ───────────────────────────────────────────────────────

function LocalStatusBadge({ status }) {
  const map = {
    starting:    { color: '#4f8cff', label: 'Démarrage…'      },
    downloading: { color: '#f59e0b', label: 'Téléchargement…' },
    loading:     { color: '#4f8cff', label: 'Chargement…'     },
    processing:  { color: '#3b82f6', label: 'Génération…'     },
    succeeded:   { color: '#22c55e', label: 'Terminé'         },
    error:       { color: '#ef4444', label: 'Erreur'          },
    cancelled:   { color: '#f59e0b', label: 'Annulé'          },
    idle:        { color: '#555',    label: 'Prêt'            },
  };
  const s = map[status] || map.idle;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '5px',
      fontSize: '11px', fontWeight: 600, color: s.color,
    }}>
      <span style={{
        width: '7px', height: '7px', borderRadius: '50%', background: s.color,
        animation: ['starting','downloading','loading','processing'].includes(status) ? 'pulse 1.4s infinite' : 'none',
        display: 'inline-block',
      }} />
      {s.label}
    </span>
  );
}

function LocalModelCard({ modelKey, spec, isSelected, onSelect }) {
  return (
    <div
      onClick={() => onSelect(modelKey)}
      style={{
        padding: '12px 14px',
        borderRadius: '8px',
        border: `1px solid ${isSelected ? 'rgba(79, 140, 255,0.5)' : 'rgba(228, 228, 231,0.1)'}`,
        background: isSelected ? 'rgba(79, 140, 255,0.06)' : '#0d0d0d',
        cursor: 'pointer',
        transition: 'all 0.18s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '4px' }}>
        <span style={{ fontSize: '13px', fontWeight: 600, color: isSelected ? '#4f8cff' : 'var(--text-primary)' }}>
          {spec.name}
        </span>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {spec.recommended && (
            <span style={{ fontSize: '10px', background: '#22c55e20', color: '#22c55e', padding: '2px 7px', borderRadius: '10px', border: '1px solid #22c55e30' }}>
              ⭐ Recommandé
            </span>
          )}
          {spec.cached && (
            <span style={{ fontSize: '10px', background: '#3b82f620', color: '#60a5fa', padding: '2px 7px', borderRadius: '10px', border: '1px solid #3b82f630' }}>
              ✅ En cache
            </span>
          )}
          <span style={{ fontSize: '10px', color: '#888' }}>{spec.size_gb} Go</span>
        </div>
      </div>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{spec.description}</div>
      {spec.vram_hint && (
        <div style={{ fontSize: '10px', color: spec.vram_ok === false ? '#ef4444' : '#f59e0b', marginTop: '4px' }}>{spec.vram_hint}</div>
      )}
    </div>
  );
}

function LocalVideoTab() {
  const [localModels, setLocalModels] = useState({});
  const [device, setDevice]           = useState(null);
  const [loading, setLoading]         = useState(true);
  const [modelKey, setModelKey]       = useState('animatelcm');
  const [prompt, setPrompt]           = useState('');
  const [numSteps, setNumSteps]       = useState(6);
  const [numFrames, setNumFrames]     = useState(null);  // null = auto based on VRAM
  const [duration, setDuration]       = useState(4);     // durée cible (s) — AnimateLCM
  const [resolution, setResolution]   = useState(null);  // null=auto · 256/384/512
  const [guidance, setGuidance]       = useState(2.5);   // adhérence au prompt
  const [seed, setSeed]               = useState('');    // '' = aléatoire
  const [negPrompt, setNegPrompt]     = useState('');    // éléments à éviter
  const [enhancing, setEnhancing]     = useState(false); // ✨ amélioration prompt en cours
  const [imageFiles, setImageFiles]   = useState([]);

  // SSE state
  const [genStatus, setGenStatus]     = useState('idle');
  const [genStep, setGenStep]         = useState(0);
  const [genTotalSteps, setGenTotalSteps] = useState(6);
  const [genProgress, setGenProgress] = useState(0);
  const [genMessage, setGenMessage]   = useState('');
  const [genError, setGenError]       = useState('');
  const [genResult, setGenResult]     = useState(null);
  const [genEta, setGenEta]           = useState(null);
  const [genElapsed, setGenElapsed]   = useState(0);
  const abortRef = useRef(null);

  const selectedSpec = localModels[modelKey];
  const isI2V = selectedSpec?.mode === 'i2v';
  const isLCM = selectedSpec?.pipeline_class === 'AnimateDiffPipeline';

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${BACKEND}/api/video/local/models`);
        const data = await res.json();
        setLocalModels(data.models || {});
        setDevice(data.device || null);
        // Auto-sélection : le modèle recommandé et utilisable en priorité
        const entries = Object.entries(data.models || {});
        const reco = entries.find(([, s]) => s.recommended && s.vram_ok !== false);
        const usable = entries.find(([, s]) => s.vram_ok !== false);
        const chosen = (reco || usable || entries[0])?.[0];
        if (chosen) setModelKey(chosen);
      } catch { /* backend offline */ }
      finally { setLoading(false); }
    })();
  }, []);

  // Quand le modèle change → applique ses paramètres par défaut
  useEffect(() => {
    if (selectedSpec) {
      setNumSteps(selectedSpec.steps || 6);
      setNumFrames(null);  // auto
      setGuidance(selectedSpec.guidance ?? 2.5);
      setResolution(null); // auto selon VRAM
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelKey, loading]);

  // ✨ Améliore le prompt via le LLM local (traduit en anglais + enrichit)
  const enhancePrompt = async () => {
    if (!prompt.trim() || enhancing) return;
    setEnhancing(true);
    try {
      const res = await fetch(`${BACKEND}/api/video/enhance-prompt`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt.trim() }),
      });
      const data = await res.json();
      if (res.ok && data.enhanced) setPrompt(data.enhanced);
      else alert(data.detail || "Amélioration indisponible (Ollama lancé ?)");
    } catch (e) {
      alert("Erreur amélioration : " + e);
    } finally {
      setEnhancing(false);
    }
  };

  const generate = async () => {
    if (!prompt.trim() && !isI2V) return;
    if (isI2V && !imageFiles.length) return;

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setGenStatus('starting');
    setGenStep(0);
    setGenProgress(0);
    setGenError('');
    setGenResult(null);
    setGenEta(null);
    setGenElapsed(0);
    setGenMessage('Démarrage…');

    try {
      let res;
      if (isI2V) {
        const fd = new FormData();
        fd.append('model_key', modelKey);
        fd.append('prompt', prompt.trim());
        fd.append('num_steps', String(numSteps));
        fd.append('image', imageFiles[0]);
        res = await fetch(`${BACKEND}/api/video/local/generate/image`, { method: 'POST', body: fd, signal: ctrl.signal });
      } else {
        res = await fetch(`${BACKEND}/api/video/local/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model_key: modelKey,
            prompt: prompt.trim(),
            num_steps: numSteps,
            guidance: guidance,
            ...(seed !== '' && !isNaN(Number(seed)) ? { seed: Number(seed) } : {}),
            ...(negPrompt.trim() ? { negative_prompt: negPrompt.trim() } : {}),
            ...(isLCM ? { duration } : {}),
            ...(isLCM && resolution ? { resolution } : {}),
            ...(!isLCM && numFrames !== null ? { num_frames: numFrames } : {}),
          }),
          signal: ctrl.signal,
        });
      }

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          try {
            const d = JSON.parse(line.slice(5).trim());
            setGenStatus(d.status);
            if (d.message) setGenMessage(d.message);
            if (d.progress !== undefined) setGenProgress(d.progress);
            if (d.step !== undefined) setGenStep(d.step);
            if (d.total_steps !== undefined) setGenTotalSteps(d.total_steps);
            if (d.eta_seconds !== undefined && d.eta_seconds !== null) setGenEta(d.eta_seconds);
            if (d.elapsed_seconds !== undefined) setGenElapsed(d.elapsed_seconds);
            if (d.error) setGenError(d.error);
            if (d.status === 'cancelled') {
              setGenMessage(d.message || 'Génération annulée.');
            }
            if (d.status === 'succeeded') {
              setGenResult(d);
              setGenProgress(100);
            }
          } catch { /* skip */ }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') { setGenStatus('error'); setGenError(String(e)); }
    }
  };

  // Annulation coopérative : prévient le backend (arrêt propre entre 2 étapes)
  // PUIS coupe le flux HTTP. Ainsi le thread de génération s'arrête vraiment.
  const cancel = async () => {
    setGenMessage('Annulation en cours…');
    try { await fetch(`${BACKEND}/api/video/local/cancel`, { method: 'POST' }); } catch { /* ignore */ }
    // Laisse le backend émettre l'événement 'cancelled' ; on coupe le flux après un court délai.
    setTimeout(() => {
      abortRef.current?.abort();
      setGenStatus('idle'); setGenProgress(0); setGenMessage(''); setGenEta(null);
    }, 1500);
  };

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', padding: '48px' }}><LoadingRow /></div>;

  const isRunning = ['starting','downloading','loading','processing'].includes(genStatus);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

      {/* Device info */}
      {device && (
        <div style={{
          display: 'flex', gap: '16px', padding: '10px 14px',
          background: device.cuda ? 'rgba(59,130,246,0.07)' : 'rgba(245,158,11,0.07)',
          border: `1px solid ${device.cuda ? 'rgba(59,130,246,0.2)' : 'rgba(245,158,11,0.2)'}`,
          borderRadius: '8px', fontSize: '12px', alignItems: 'center',
        }}>
          <span style={{ fontSize: '1.2rem' }}>{device.cuda ? '⚡' : '🐌'}</span>
          <div>
            <span style={{ fontWeight: 600, color: device.cuda ? '#60a5fa' : '#f59e0b' }}>
              {device.device_name}
            </span>
            {device.cuda && <span style={{ color: '#666', marginLeft: '8px' }}>{device.vram_gb} Go VRAM</span>}
            {device.cuda && device.precision && (
              <span style={{ color: '#22c55e', marginLeft: '8px', fontSize: '11px' }}>
                · précision {device.precision}
                {device.precision === 'bf16' && ' (anti-écran-noir GTX 16xx)'}
              </span>
            )}
            {!device.cuda && (
              <span style={{ color: '#888', marginLeft: '8px' }}>
                Sans GPU : préférez AnimateLCM (plus rapide) ou les onglets Texte Animé / Diaporama (instantanés).
              </span>
            )}
            {device.cuda && device.vram_gb <= 4 && (
              <div style={{ color: '#888', marginTop: '4px', fontSize: '11px' }}>
                💡 GPU 4 Go : <strong>AnimateLCM ⚡</strong> est auto-optimisé (256px, bf16, attention découpée) →
                vidéo en ~2–4 min. CogVideoX est déconseillé (très lent sur cette carte).
              </div>
            )}
          </div>
        </div>
      )}

      <div style={card}>
        {/* Model grid */}
        <div style={{ marginBottom: '16px' }}>
          <span style={label}>Modèle (téléchargement automatique au premier lancement)</span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '8px' }}>
            {Object.entries(localModels).map(([k, spec]) => (
              <LocalModelCard key={k} modelKey={k} spec={spec} isSelected={modelKey === k} onSelect={setModelKey} />
            ))}
          </div>
        </div>

        {/* Image upload for I2V */}
        {isI2V && (
          <div style={{ marginBottom: '16px' }}>
            <span style={label}>Image de départ</span>
            <DropZone files={imageFiles} onFiles={setImageFiles} multiple={false}
              label="Glisser une image ici pour l'animer" />
          </div>
        )}

        {/* Prompt + bouton améliorer (LLM) */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ ...label, marginBottom: 0 }}>Prompt{isI2V ? ' (optionnel — décrit le mouvement)' : ' (écrivez en français, l\'IA traduit/enrichit)'}</span>
            {!isI2V && (
              <button onClick={enhancePrompt} disabled={enhancing || !prompt.trim()}
                title="Traduit en anglais et enrichit le prompt via le LLM local pour mieux respecter votre idée"
                style={{ ...btn(false, '#a855f7'), fontSize: '11px', padding: '4px 10px',
                         opacity: (enhancing || !prompt.trim()) ? 0.5 : 1 }}>
                {enhancing ? '✨ Amélioration…' : '✨ Améliorer le prompt'}
              </button>
            )}
          </div>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) generate(); }}
            placeholder={isI2V
              ? "Ex: La caméra tourne lentement autour du sujet…"
              : "Ex: un chat roux qui dort sur un canapé, lumière douce…"}
            rows={3}
            style={{ ...input, resize: 'vertical' }}
          />
        </div>

        {/* ── Contrôles AnimateLCM : durée + qualité + guidance ─────────────── */}
        {isLCM && (
          <>
            {/* Durée cible — VOUS décidez la longueur */}
            <div style={{ marginBottom: '16px' }}>
              <span style={label}>⏱️ Durée de la vidéo — {duration}s</span>
              <input type="range" min={1} max={8} step={1}
                value={duration}
                onChange={e => setDuration(Number(e.target.value))}
                style={{ width: '100%', accentColor: '#22c55e' }} />
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                Le mouvement natif fait ~2–4 s ; au-delà, le mouvement est ralenti et lissé (interpolation).
              </div>
            </div>

            {/* Qualité (résolution) — compromis netteté ↔ vitesse */}
            <div style={{ marginBottom: '16px' }}>
              <span style={label}>🎯 Qualité (respect du texte ↔ vitesse)</span>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {[
                  { v: 256, t: 'Rapide',    s: '256px · ~1-2 min' },
                  { v: 384, t: 'Équilibré', s: '384px · ~3-5 min' },
                  { v: 512, t: 'Qualité',   s: '512px · ~6-9 min' },
                ].map(o => {
                  const active = (resolution ?? (device?.vram_gb <= 4 ? 384 : 512)) === o.v;
                  return (
                    <button key={o.v} onClick={() => setResolution(o.v)}
                      style={{ ...btn(active), flex: 1, minWidth: 110, textAlign: 'center', padding: '8px 10px' }}>
                      <div style={{ fontWeight: 600 }}>{o.t}</div>
                      <div style={{ fontSize: '9px', opacity: 0.7 }}>{o.s}</div>
                    </button>
                  );
                })}
              </div>
              <div style={{ fontSize: '10px', color: '#f59e0b', marginTop: '4px' }}>
                💡 Plus la résolution est élevée, mieux le sujet de votre texte est rendu (256px peut l'omettre).
              </div>
            </div>

            {/* Guidance — force d'adhérence au prompt */}
            <div style={{ marginBottom: '16px' }}>
              <span style={label}>🧲 Fidélité au prompt (guidance) — {guidance}</span>
              <input type="range" min={1} max={5} step={0.5}
                value={guidance}
                onChange={e => setGuidance(Number(e.target.value))}
                style={{ width: '100%', accentColor: '#a855f7' }} />
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                Plus haut = colle plus au texte (2–3 recommandé). Trop haut peut saturer l'image.
              </div>
            </div>

            {/* Steps — qualité de débruitage */}
            <div style={{ marginBottom: '16px' }}>
              <span style={label}>Étapes de débruitage — {numSteps} (LCM : 4–8 ; +d'étapes = +net)</span>
              <input type="range" min={2} max={12} step={1}
                value={numSteps}
                onChange={e => setNumSteps(Number(e.target.value))}
                style={{ width: '100%', accentColor: '#4f8cff' }} />
            </div>
          </>
        )}

        {/* ── Contrôles CogVideoX (steps + frames) ───────────────────────────── */}
        {!isLCM && (
          <>
            <div style={{ marginBottom: '16px' }}>
              <span style={label}>Étapes de débruitage — {numSteps} (plus = meilleure qualité, plus lent)</span>
              <input type="range" min={10} max={100} step={5} value={numSteps}
                onChange={e => setNumSteps(Number(e.target.value))}
                style={{ width: '100%', accentColor: '#4f8cff' }} />
            </div>
            <div style={{ marginBottom: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={label}>Frames — {numFrames === null ? `Auto (${selectedSpec?.frames || 16})` : `${numFrames} frames (${(numFrames/(selectedSpec?.fps||8)).toFixed(1)}s)`}</span>
                {numFrames !== null && (
                  <button onClick={() => setNumFrames(null)}
                    style={{ fontSize: '10px', color: '#888', background: 'none', border: 'none', cursor: 'pointer' }}>
                    Reset (Auto)
                  </button>
                )}
              </div>
              <input type="range" min={9} max={49} step={4}
                value={numFrames ?? (selectedSpec?.frames || (device?.vram_gb <= 4 ? 9 : 16))}
                onChange={e => setNumFrames(Number(e.target.value))}
                style={{ width: '100%', accentColor: '#3b82f6' }} />
              {device?.vram_gb <= 4 && (
                <div style={{ fontSize: '10px', color: '#f59e0b', marginTop: '4px' }}>
                  ⚠️ GPU 4 Go — CogVideoX limite à 9 frames et reste TRÈS lent.
                  <strong> AnimateLCM ⚡ est bien plus rapide et fiable.</strong>
                </div>
              )}
            </div>
          </>
        )}

        {/* Négatif + graine (s'appliquent aux deux modèles) */}
        <div style={{ display: 'flex', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
          <div style={{ flex: 2, minWidth: 200 }}>
            <span style={label}>🚫 À éviter (negative prompt, optionnel)</span>
            <input value={negPrompt} onChange={e => setNegPrompt(e.target.value)}
              placeholder="ex: flou, déformé, texte, watermark…"
              style={input} />
          </div>
          <div style={{ flex: 1, minWidth: 140 }}>
            <span style={label}>🎲 Graine (seed)</span>
            <div style={{ display: 'flex', gap: '4px' }}>
              <input value={seed} onChange={e => setSeed(e.target.value.replace(/[^0-9]/g, ''))}
                placeholder="aléatoire" style={{ ...input, flex: 1 }} />
              <button onClick={() => setSeed('')} title="Aléatoire"
                style={{ ...btn(false), padding: '0 10px' }}>🎲</button>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button
            onClick={generate}
            disabled={isRunning || (!prompt.trim() && !isI2V) || (isI2V && !imageFiles.length)}
            style={primaryBtn(isRunning || (!prompt.trim() && !isI2V) || (isI2V && !imageFiles.length))}
          >
            {isRunning ? '⏳ En cours…' : '🎬 Générer localement'}
          </button>
          {isRunning && (
            <button onClick={cancel} style={{ ...btn(false, '#ef4444'), fontSize: '12px' }}>
              Annuler
            </button>
          )}
        </div>
      </div>

      {/* Progress panel */}
      {genStatus !== 'idle' && (
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <LocalStatusBadge status={genStatus} />
            {genStatus === 'processing' && genStep > 0 && (
              <span style={{ fontSize: '11px', color: '#888' }}>
                Étape {genStep} / {genTotalSteps}
                {genEta !== null && <span style={{ color: '#60a5fa', marginLeft: '8px' }}>· ⏱ ~{fmtDuration(genEta)} restant</span>}
                {genElapsed > 0 && <span style={{ color: '#666', marginLeft: '8px' }}>· {fmtDuration(genElapsed)} écoulé</span>}
              </span>
            )}
          </div>

          {/* Progress bar */}
          <div style={{ background: '#1a1a1a', borderRadius: '4px', height: '5px', marginBottom: '10px' }}>
            <div style={{
              height: '5px', borderRadius: '4px',
              background: genStatus === 'succeeded' ? '#22c55e'
                        : genStatus === 'error'     ? '#ef4444'
                        : genStatus === 'cancelled' ? '#f59e0b'
                        : 'linear-gradient(90deg,#4f8cff,#3b82f6)',
              width: `${genProgress}%`,
              transition: 'width 0.3s ease',
            }} />
          </div>

          {genMessage && (
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
              {genMessage}
            </div>
          )}

          {genError && (
            <div style={{ padding: '10px', background: '#1a0808', borderRadius: '6px', fontSize: '12px', color: '#ef4444' }}>
              ⚠️ {genError}
              {genError.toLowerCase().includes('out of memory') || genError.toLowerCase().includes('cuda') ? (
                <div style={{ marginTop: '8px', padding: '8px 10px', background: '#1a1000', border: '1px solid #f59e0b44', borderRadius: '6px', color: '#f59e0b', fontSize: '11px' }}>
                  <strong>💡 Erreur VRAM (GPU)</strong> — Votre GPU n&apos;a pas assez de mémoire. Solutions :
                  <ul style={{ margin: '6px 0 0 0', paddingLeft: '16px', lineHeight: 1.7 }}>
                    <li>Réduisez le nombre de frames (ex: 17 frames = 2s) — modifiez les paramètres avancés</li>
                    <li>Le modèle ajuste automatiquement les frames selon votre VRAM (4 Go → 17 frames)</li>
                    <li>Relancez — la mémoire GPU est parfois libérée entre les tentatives</li>
                    <li>Utilisez l&apos;onglet <strong>Texte Animé</strong> pour une génération sans GPU</li>
                  </ul>
                </div>
              ) : null}
            </div>
          )}

          {genStatus === 'downloading' && (
            <div style={{ fontSize: '11px', color: '#f59e0b', marginTop: '6px' }}>
              💡 Le téléchargement peut durer plusieurs minutes selon votre connexion.
              Le modèle sera mis en cache pour les prochaines utilisations.
            </div>
          )}

          {genResult && (
            <>
              <VideoResult localUrl={`${BACKEND}${genResult.file_url}`} />
              <div style={{ display: 'flex', gap: '14px', alignItems: 'center', marginTop: '8px',
                            fontSize: '11px', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                {genResult.duration != null && <span>⏱️ {genResult.duration}s</span>}
                {genResult.seed != null && (
                  <span>🎲 graine {genResult.seed}{' '}
                    <button onClick={() => setSeed(String(genResult.seed))}
                      title="Réutiliser cette graine pour reproduire/varier"
                      style={{ fontSize: '10px', color: '#a855f7', background: 'none',
                               border: '1px solid #a855f733', borderRadius: '5px', cursor: 'pointer', padding: '1px 6px' }}>
                      réutiliser
                    </button>
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}


// ── Tab: Texte animé (100% local, sans API ni GPU) ───────────────────────────

function TextAnimationTab() {
  const [text, setText]         = useState('');
  const [style, setStyle]       = useState('typewriter');
  const [duration, setDuration] = useState(5);
  const [fps, setFps]           = useState(24);
  const [format, setFormat]     = useState('gif');
  const [fontSize, setFontSize] = useState(40);
  const [width, setWidth]       = useState(854);
  const [height, setHeight]     = useState(480);
  const [generating, setGenerating] = useState(false);
  const [result, setResult]     = useState(null);
  const [err, setErr]           = useState('');
  const [galleryKey, setGalleryKey] = useState(0);

  const STYLES = [
    { value: 'typewriter', label: '⌨️ Machine à écrire', desc: 'Les caractères apparaissent un par un' },
    { value: 'fade',       label: '✨ Fondu',             desc: 'Le texte apparaît et disparaît en fondu' },
    { value: 'scroll',     label: '📜 Défilement',        desc: 'Le texte monte depuis le bas (générique)' },
    { value: 'title',      label: '🎬 Titre cinéma',      desc: 'Titre doré avec halo lumineux animé' },
  ];

  const generate = async () => {
    if (!text.trim() || generating) return;
    setGenerating(true);
    setErr('');
    setResult(null);
    try {
      const res = await fetch(`${BACKEND}/api/video/text-animation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text.trim(),
          style,
          duration: Number(duration),
          fps: Number(fps),
          output_format: format,
          font_size: Number(fontSize),
          width: Number(width),
          height: Number(height),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Erreur inconnue');
      setResult(data);
      setGalleryKey(k => k + 1);
    } catch (e) {
      setErr(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const resultUrl = result ? `${BACKEND}${result.url}` : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Info banner */}
      <div style={{
        padding: '10px 16px',
        background: 'rgba(34,197,94,0.08)',
        border: '1px solid rgba(34,197,94,0.2)',
        borderRadius: '8px',
        fontSize: '12px', color: '#4ade80',
        display: 'flex', alignItems: 'center', gap: '8px',
      }}>
        <span>✅</span>
        <span><strong>100% gratuit et local</strong> — Aucune clé API, aucun GPU requis. Génération instantanée sur CPU.</span>
      </div>

      <div style={card}>
        {/* Style selection */}
        <div style={{ marginBottom: '16px' }}>
          <span style={label}>Style d&apos;animation</span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
            {STYLES.map(s => (
              <div
                key={s.value}
                onClick={() => setStyle(s.value)}
                style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  border: `1px solid ${style === s.value ? 'rgba(79, 140, 255,0.6)' : 'rgba(228, 228, 231,0.12)'}`,
                  background: style === s.value ? 'rgba(79, 140, 255,0.08)' : '#0d0d0d',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                <div style={{ fontSize: '13px', fontWeight: 600, color: style === s.value ? '#4f8cff' : 'var(--text-primary)' }}>
                  {s.label}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '3px' }}>{s.desc}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Text input */}
        <div style={{ marginBottom: '16px' }}>
          <span style={label}>Texte à animer</span>
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) generate(); }}
            placeholder="Entrez votre texte ici…&#10;Plusieurs lignes supportées (Ctrl+Entrée pour générer)"
            rows={4}
            style={{ ...input, resize: 'vertical', lineHeight: '1.5' }}
          />
        </div>

        {/* Parameters */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '12px', marginBottom: '16px' }}>
          <div>
            <span style={label}>Format de sortie</span>
            <div style={{ display: 'flex', gap: '6px' }}>
              {['gif', 'mp4'].map(f => (
                <button key={f} onClick={() => setFormat(f)} style={{ ...btn(format === f), flex: 1, padding: '8px 0' }}>
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div>
            <span style={label}>Durée (s)</span>
            <input type="number" value={duration} onChange={e => setDuration(e.target.value)}
              min="2" max="30" step="0.5" style={input} />
          </div>
          <div>
            <span style={label}>FPS</span>
            <select value={fps} onChange={e => setFps(Number(e.target.value))} style={select}>
              {[8, 12, 15, 24, 30].map(f => <option key={f} value={f}>{f} fps</option>)}
            </select>
          </div>
          <div>
            <span style={label}>Taille police</span>
            <input type="number" value={fontSize} onChange={e => setFontSize(e.target.value)}
              min="16" max="80" step="2" style={input} />
          </div>
          <div>
            <span style={label}>Largeur (px)</span>
            <select value={width} onChange={e => setWidth(Number(e.target.value))} style={select}>
              {[640,854,1280,1920].map(w => <option key={w} value={w}>{w}</option>)}
            </select>
          </div>
          <div>
            <span style={label}>Hauteur (px)</span>
            <select value={height} onChange={e => setHeight(Number(e.target.value))} style={select}>
              {[360,480,720,1080].map(h => <option key={h} value={h}>{h}</option>)}
            </select>
          </div>
        </div>

        <button
          onClick={generate}
          disabled={!text.trim() || generating}
          style={{ ...primaryBtn(!text.trim() || generating), width: '100%' }}
        >
          {generating ? '⏳ Génération en cours…' : '🎬 Générer la vidéo'}
        </button>

        {err && (
          <div style={{ marginTop: '12px', padding: '10px', background: '#1a0808', border: '1px solid #ef444440', borderRadius: '6px', fontSize: '13px', color: '#ef4444' }}>
            ⚠️ {err}
          </div>
        )}
      </div>

      {/* Result preview */}
      {result && resultUrl && (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ fontSize: '13px', fontWeight: 600, color: '#22c55e' }}>
            ✅ Vidéo générée — {result.size_human}
          </div>
          {result.format === 'GIF' ? (
            <img src={resultUrl} alt="Animation" style={{ maxWidth: '100%', borderRadius: '6px', border: '1px solid rgba(228, 228, 231,0.1)' }} />
          ) : (
            <video src={resultUrl} controls loop style={{ maxWidth: '100%', borderRadius: '6px' }} />
          )}
          <a href={resultUrl} download={result.filename}
            style={{ ...primaryBtn(false), textDecoration: 'none', textAlign: 'center', display: 'block' }}>
            ⬇️ Télécharger ({result.format})
          </a>
        </div>
      )}
    </div>
  );
}


// ── Main page ─────────────────────────────────────────────────────────────────

export default function VideoPage() {
  const [activeTab, setActiveTab] = useState('anim');
  const [models, setModels] = useState({ text_to_video: {}, image_to_video: {} });
  const [galleryRefresh, setGalleryRefresh] = useState(0);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${BACKEND}/api/video/models`);
        if (!res.ok) throw new Error('Impossible de charger les modèles');
        const data = await res.json();
        setModels(data);
      } catch (e) {
        setModelsError(e.message);
      } finally {
        setModelsLoading(false);
      }
    })();
  }, []);

  const tabs = [
    { id: 'edit',      icon: '🛠️', label: 'Édition / Conversion' },
    { id: 'anim',      icon: '✨', label: 'Texte Animé'       },
    { id: 'slideshow', icon: '🎞️', label: 'Diaporama'         },
    { id: 'local',     icon: '💻', label: 'Local IA (GPU)'    },
    { id: 'text',      icon: '☁️', label: 'Cloud T→V'         },
    { id: 'image',     icon: '☁️', label: 'Cloud I→V'         },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0a0a0a', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding: '20px 28px 0',
        borderBottom: '1px solid rgba(228, 228, 231,0.06)',
        background: '#0d0d0d',
      }}>
        <h1 style={{ margin: '0 0 16px', fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          🎬 Génération Vidéo IA
        </h1>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: '2px' }}>
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              style={{
                padding: '10px 20px',
                border: 'none',
                borderBottom: activeTab === t.id ? '2px solid #4f8cff' : '2px solid transparent',
                background: 'transparent',
                color: activeTab === t.id ? '#4f8cff' : 'var(--text-muted)',
                fontSize: '13px',
                fontWeight: activeTab === t.id ? 600 : 400,
                cursor: 'pointer',
                transition: 'all 0.18s ease',
              }}
            >
              {t.icon} {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '24px 28px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
        {modelsLoading ? (
          <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '48px' }}>
            Chargement des modèles…
          </div>
        ) : modelsError ? (
          <div style={{ padding: '20px', background: '#1a0808', border: '1px solid #ef444440', borderRadius: '10px', color: '#ef4444', fontSize: '14px' }}>
            ⚠️ {modelsError}
            <div style={{ fontSize: '12px', marginTop: '6px', color: '#888' }}>
              Vérifiez que le backend est démarré sur le port 8005.
            </div>
          </div>
        ) : (
          <>
            {activeTab === 'edit'      && <EditTab onDone={() => setGalleryRefresh(n => n + 1)} />}
            {activeTab === 'anim'      && <TextAnimationTab />}
            {activeTab === 'local'     && <LocalVideoTab />}
            {activeTab === 'text'      && <TextToVideoTab  models={models.text_to_video}  />}
            {activeTab === 'image'     && <ImageToVideoTab models={models.image_to_video} />}
            {activeTab === 'slideshow' && <SlideshowTab />}

            {/* Notices */}
            {activeTab === 'local' && (
              <div style={{
                padding: '12px 16px', background: 'rgba(59,130,246,0.06)',
                border: '1px solid rgba(59,130,246,0.15)', borderRadius: '8px',
                fontSize: '12px', color: '#60a5fa',
              }}>
                💻 Génération <strong>100% locale, gratuite et privée</strong> — aucune clé API requise.
                <strong> AnimateLCM ⚡</strong> (recommandé) : téléchargement unique ~4 Go, puis ~2–4 min/vidéo,
                auto-optimisé pour votre GPU (bf16 + attention découpée, anti-écran-noir sur GTX 16xx).
                CogVideoX (~9–20 Go) offre une meilleure qualité mais est beaucoup plus lent sur petit GPU.
              </div>
            )}
            {(activeTab === 'text' || activeTab === 'image') && (
              <div style={{
                padding: '12px 16px', background: 'rgba(79, 140, 255,0.06)',
                border: '1px solid rgba(79, 140, 255,0.15)', borderRadius: '8px',
                fontSize: '12px', color: '#4f8cff',
              }}>
                ☁️ La génération cloud nécessite un token{' '}
                <a href="/settings" style={{ color: '#4f8cff', fontWeight: 600 }}>
                  Replicate (Paramètres → Connexions)
                </a>.
                Résultat en ~30–60s, coût ~$0.01–0.10 par vidéo. Sans token, utilisez <strong>Texte Animé</strong> (gratuit).
              </div>
            )}

            <VideoGallery refresh={galleryRefresh} />
          </>
        )}
      </div>
    </div>
  );
}
