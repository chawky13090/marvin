'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { LocalVideoTab, TextAnimationTab } from '@/components/video/LocalVideoTabs';
import {
  DropZone, GenerationProgress, VideoResult, btn, card, input, label, primaryBtn, select,
} from '@/components/video/VideoShared';

import { BACKEND_URL as BACKEND } from '@/lib/backend';

// ── Shared styles ─────────────────────────────────────────────────────────────

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
