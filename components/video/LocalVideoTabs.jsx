'use client';

import { useEffect, useRef, useState } from 'react';
import { LoadingRow } from '@/components/ui/Spinner';
import { BACKEND_URL as BACKEND } from '@/lib/backend';
import {
  DropZone,
  VideoResult,
  btn,
  card,
  fmtDuration,
  input,
  label,
  primaryBtn,
  select,
} from './VideoShared';

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

export function LocalVideoTab() {
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

export function TextAnimationTab() {
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
