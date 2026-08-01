'use client';
/* eslint-disable @next/next/no-img-element -- previews are user-provided data URLs, not optimizable remote assets */

import { useEffect, useMemo, useRef, useState } from 'react';
import { BACKEND_URL as BACKEND } from '@/lib/backend';
import styles from './LayerCanvas.module.css';

const blank = () => ({
  schema_version: 1, id: `design-${Date.now()}`, title: 'Nouveau document', width: 794, height: 1123,
  background: '#f5f4f0', layers: [
    { id: 'title', type: 'text', name: 'Titre', x: 70, y: 90, width: 650, height: 90, text: 'Votre titre', color: '#242628', fill: '#334155', fontSize: 52, fontWeight: 700, opacity: 1, rotation: 0 },
    { id: 'subtitle', type: 'text', name: 'Introduction', x: 74, y: 205, width: 580, height: 80, text: 'Construisez un document premium, calque par calque.', color: '#696b6d', fill: '#334155', fontSize: 22, fontWeight: 400, opacity: 1, rotation: 0 },
    { id: 'rule', type: 'line', name: 'Séparateur', x: 74, y: 310, width: 190, height: 3, text: '', color: '#242628', fill: '#8c8276', fontSize: 12, fontWeight: 400, opacity: 1, rotation: 0 },
  ],
});

const layerDefaults = (type, count) => ({ id: `${type}-${Date.now()}`, type, name: `${type} ${count + 1}`, x: 90, y: 340, width: type === 'line' ? 240 : 260, height: type === 'line' ? 4 : 100, text: type === 'text' ? 'Nouveau texte' : '', color: '#242628', fill: '#8c8276', fontSize: 28, fontWeight: type === 'text' ? 700 : 400, opacity: 1, rotation: 0 });

export default function LayerCanvas() {
  const [design, setDesign] = useState(blank);
  const [selected, setSelected] = useState('title');
  const [saved, setSaved] = useState([]);
  const [status, setStatus] = useState('Prêt');
  const [prompt, setPrompt] = useState('');
  const [history, setHistory] = useState([]);
  const fileRef = useRef(null);
  const active = useMemo(() => design.layers.find(layer => layer.id === selected), [design, selected]);

  useEffect(() => { fetch(`${BACKEND}/api/documents/canvas`).then(r => r.json()).then(r => setSaved(r.designs || [])).catch(() => {}); }, []);
  const remember = () => setHistory(items => [...items.slice(-19), structuredClone(design)]);
  const mutate = (fn, rememberFirst = true) => { if (rememberFirst) remember(); setDesign(current => fn(structuredClone(current))); };
  const update = (key, value) => mutate(next => { const layer = next.layers.find(item => item.id === selected); if (layer) layer[key] = value; return next; });

  function add(type, src = '') {
    const layer = layerDefaults(type, design.layers.length); if (src) layer.src = src;
    mutate(next => { next.layers.push(layer); return next; }); setSelected(layer.id);
  }
  function move(index, direction) { mutate(next => { const target = index + direction; if (target < 0 || target >= next.layers.length) return next; [next.layers[index], next.layers[target]] = [next.layers[target], next.layers[index]]; return next; }); }
  function remove() { mutate(next => { next.layers = next.layers.filter(item => item.id !== selected); return next; }); setSelected(''); }
  function duplicate() { if (!active) return; const copy = { ...active, id: `${active.type}-${Date.now()}`, name: `${active.name} copie`, x: active.x + 18, y: active.y + 18 }; mutate(next => { next.layers.push(copy); return next; }); setSelected(copy.id); }
  function undo() { const previous = history.at(-1); if (!previous) return; setDesign(previous); setHistory(items => items.slice(0, -1)); }

  async function save() {
    setStatus('Enregistrement…');
    const response = await fetch(`${BACKEND}/api/documents/canvas`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(design) });
    const body = await response.json(); if (!response.ok) throw new Error(body.detail || 'Échec');
    setDesign(body.manifest); setStatus('Enregistré');
    const list = await fetch(`${BACKEND}/api/documents/canvas`).then(r => r.json()); setSaved(list.designs || []);
  }
  async function load(id) { const body = await fetch(`${BACKEND}/api/documents/canvas/${id}`).then(r => r.json()); setDesign(body); setSelected(body.layers?.[0]?.id || ''); setHistory([]); }
  async function generateFromPrompt() {
    if (!prompt.trim()) return;
    setStatus('Création du manifeste…');
    const response = await fetch(`${BACKEND}/api/documents/canvas/from-prompt`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, title: design.title === 'Nouveau document' ? '' : design.title }) });
    const body = await response.json(); if (!response.ok) throw new Error(body.detail || 'Brief invalide');
    remember(); setDesign(body); setSelected(body.layers[1]?.id || body.layers[0]?.id); setStatus('Manifeste créé');
  }
  async function download(format) {
    setStatus(`Export ${format.toUpperCase()}…`);
    const response = await fetch(`${BACKEND}/api/documents/canvas/export/${format}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(design) });
    if (!response.ok) throw new Error((await response.json()).detail || 'Export impossible');
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${design.title}.${format}`; anchor.click(); URL.revokeObjectURL(url); setStatus('Export terminé');
  }
  async function downloadPng() {
    setStatus('Export PNG…');
    const esc = value => String(value || '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]);
    const content = design.layers.filter(layer => !layer.hidden).map(layer => {
      const common = `opacity="${layer.opacity}" transform="rotate(${layer.rotation} ${layer.x + layer.width / 2} ${layer.y + layer.height / 2})"`;
      if (layer.type === 'rect') return `<rect x="${layer.x}" y="${layer.y}" width="${layer.width}" height="${layer.height}" rx="8" fill="${layer.fill}" ${common}/>`;
      if (layer.type === 'line') return `<line x1="${layer.x}" y1="${layer.y}" x2="${layer.x + layer.width}" y2="${layer.y}" stroke="${layer.fill}" stroke-width="${Math.max(1, layer.height)}" ${common}/>`;
      if (layer.type === 'image' && layer.src) return `<image href="${esc(layer.src)}" x="${layer.x}" y="${layer.y}" width="${layer.width}" height="${layer.height}" preserveAspectRatio="xMidYMid slice" ${common}/>`;
      if (layer.type === 'text') return `<text x="${layer.x}" y="${layer.y + layer.fontSize}" fill="${layer.color}" font-family="Arial,sans-serif" font-size="${layer.fontSize}" font-weight="${layer.fontWeight}" ${common}>${esc(layer.text)}</text>`;
      return '';
    }).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${design.width}" height="${design.height}" viewBox="0 0 ${design.width} ${design.height}"><rect width="100%" height="100%" fill="${design.background}"/>${content}</svg>`;
    const blob = new Blob([svg], { type: 'image/svg+xml' }); const url = URL.createObjectURL(blob); const image = new Image();
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
    const canvas = document.createElement('canvas'); canvas.width = design.width * 2; canvas.height = design.height * 2;
    const context = canvas.getContext('2d'); context.scale(2, 2); context.drawImage(image, 0, 0); URL.revokeObjectURL(url);
    const png = await new Promise(resolve => canvas.toBlob(resolve, 'image/png')); const pngUrl = URL.createObjectURL(png); const anchor = document.createElement('a'); anchor.href = pngUrl; anchor.download = `${design.title}.png`; anchor.click(); URL.revokeObjectURL(pngUrl); setStatus('Export PNG terminé');
  }
  function imagePicked(file) { if (!file || file.size > 1_400_000) return setStatus('Image limitée à 1,4 Mo'); const reader = new FileReader(); reader.onload = () => add('image', reader.result); reader.readAsDataURL(file); }
  function pointerDown(event, layer) {
    if (layer.locked) return; event.preventDefault(); setSelected(layer.id); remember();
    const start = { x: event.clientX, y: event.clientY, left: layer.x, top: layer.y };
    const moveHandler = e => setDesign(current => ({ ...current, layers: current.layers.map(item => item.id === layer.id ? { ...item, x: Math.max(0, start.left + (e.clientX - start.x)), y: Math.max(0, start.top + (e.clientY - start.y)) } : item) }));
    const upHandler = () => { window.removeEventListener('pointermove', moveHandler); window.removeEventListener('pointerup', upHandler); };
    window.addEventListener('pointermove', moveHandler); window.addEventListener('pointerup', upHandler);
  }

  return <div className={styles.studio}>
    <header className={styles.toolbar}>
      <input aria-label="Titre du document" value={design.title} onChange={e => setDesign({ ...design, title: e.target.value })} className={styles.title} />
      <div className={styles.actions}>
        <button onClick={undo} disabled={!history.length}>Annuler</button><button onClick={() => add('text')}>Texte</button><button onClick={() => add('rect')}>Forme</button><button onClick={() => add('line')}>Ligne</button>
        <button onClick={() => fileRef.current?.click()}>Image</button><input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={e => imagePicked(e.target.files?.[0])} />
        <button className={styles.primary} onClick={() => save().catch(e => setStatus(e.message))}>Enregistrer</button>
      </div>
    </header>
    <div className={styles.promptbar}><input value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Décrivez le document : rapport exécutif premium, brochure nature, proposition technique…" /><button onClick={() => generateFromPrompt().catch(e => setStatus(e.message))}>Créer le manifeste</button></div>
    <div className={styles.body}>
      <aside className={styles.library}><h3>Documents</h3><button onClick={() => { setDesign(blank()); setSelected('title'); }}>Nouveau</button>{saved.map(item => <button key={item.id} onClick={() => load(item.id)}><strong>{item.title}</strong><small>{item.layers} calques</small></button>)}</aside>
      <main className={styles.workarea}>
        <div className={styles.page} style={{ aspectRatio: `${design.width}/${design.height}`, background: design.background }}>
          {design.layers.map(layer => !layer.hidden && <div key={layer.id} onPointerDown={e => pointerDown(e, layer)} className={`${styles.layer} ${selected === layer.id ? styles.selected : ''}`} style={{ left: `${layer.x / design.width * 100}%`, top: `${layer.y / design.height * 100}%`, width: `${layer.width / design.width * 100}%`, height: `${layer.height / design.height * 100}%`, opacity: layer.opacity, transform: `rotate(${layer.rotation}deg)`, color: layer.color, background: layer.type === 'rect' ? layer.fill : 'transparent', fontSize: `${Math.max(8, layer.fontSize * .55)}px`, fontWeight: layer.fontWeight, borderTop: layer.type === 'line' ? `3px solid ${layer.fill}` : undefined }}>
            {layer.type === 'text' && layer.text}{layer.type === 'image' && layer.src && <img src={layer.src} alt="Calque importé" />}
          </div>)}
        </div>
      </main>
      <aside className={styles.inspector}><h3>Calques</h3>{[...design.layers].reverse().map((layer, reverseIndex) => { const index = design.layers.length - 1 - reverseIndex; return <div key={layer.id} className={layer.id === selected ? styles.activeLayer : styles.layerRow} onClick={() => setSelected(layer.id)}><span>{layer.hidden ? 'Masqué' : layer.name}</span><span><button onClick={e => { e.stopPropagation(); move(index, 1); }}>↑</button><button onClick={e => { e.stopPropagation(); move(index, -1); }}>↓</button></span></div>; })}
        {active && <section className={styles.properties}><h3>Propriétés</h3>{active.type === 'text' && <textarea value={active.text} onChange={e => update('text', e.target.value)} />}{['x','y','width','height','rotation','opacity'].map(key => <label key={key}>{key}<input type="number" step={key === 'opacity' ? .1 : 1} value={active[key]} onChange={e => update(key, Number(e.target.value))} /></label>)}{active.type === 'text' && <><label>Taille<input type="number" value={active.fontSize} onChange={e => update('fontSize', Number(e.target.value))} /></label><label>Couleur<input type="color" value={active.color} onChange={e => update('color', e.target.value)} /></label></>}{active.type !== 'text' && <label>Couleur<input type="color" value={active.fill} onChange={e => update('fill', e.target.value)} /></label>}<div className={styles.danger}><button onClick={duplicate}>Dupliquer</button><button onClick={() => update('hidden', !active.hidden)}>{active.hidden ? 'Afficher' : 'Masquer'}</button><button onClick={() => update('locked', !active.locked)}>{active.locked ? 'Déverrouiller' : 'Verrouiller'}</button><button onClick={remove}>Supprimer</button></div></section>}
      </aside>
    </div>
    <footer className={styles.footer}><span>{status}</span><div><button onClick={() => downloadPng().catch(e => setStatus(e.message))}>PNG</button><button onClick={() => download('pdf').catch(e => setStatus(e.message))}>PDF</button><button onClick={() => download('docx').catch(e => setStatus(e.message))}>DOCX éditable</button><button onClick={() => download('pptx').catch(e => setStatus(e.message))}>PPTX éditable</button></div></footer>
  </div>;
}
